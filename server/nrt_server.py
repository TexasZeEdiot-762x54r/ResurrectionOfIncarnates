"""Bounded native lobby listener. External binds require provisioned credentials."""
import argparse
from collections import Counter
import ipaddress
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import socket
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nrt_logic
import nrt_rooms
import nrt_security as security
import paths

LOGGER = logging.getLogger("roi-lobby")
SLOTS = threading.BoundedSemaphore(security.MAX_CONNECTIONS)
PER_ADDRESS = Counter()
SLOT_LOCK = threading.Lock()
QUIET = os.environ.get("ROI_QUIET", "1") != "0"


def log(*parts):
    LOGGER.info(" ".join(map(str, parts)))


def configure_logging():
    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    LOGGER.addHandler(stream)
    try:
        (HERE / "logs").mkdir(exist_ok=True)
        handler = RotatingFileHandler(HERE / "logs/nrt.log", maxBytes=2 * 1024 * 1024,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)
    except OSError:
        pass


def serve(conn, addr, slot_acquired=False):
    session = {"addr": addr}
    buf = b""
    partial_since = None
    started = last_data = time.monotonic()
    next_tick = started + 3
    conn.settimeout(1)
    log("connect", addr)
    try:
        while True:
            now = time.monotonic()
            if not session.get("uid") and now - started > 10:
                raise security.ProtocolError("Login timed out")
            if now - last_data > security.IDLE_SECONDS:
                raise security.ProtocolError("Idle timed out")
            if partial_since is not None and now - partial_since > security.FRAME_SECONDS:
                raise security.ProtocolError("Incomplete frame timed out")
            for reply in nrt_logic.poll_quickchat(session):
                conn.sendall(reply)
            if now >= next_tick:
                next_tick = now + 3
                for reply in nrt_logic.tick(session):
                    conn.sendall(reply)
            try:
                data = conn.recv(8192)
            except socket.timeout:
                continue
            if not data:
                break
            last_data = time.monotonic()
            if not buf:
                partial_since = last_data
            buf += data
            replies, buf = nrt_logic.handle(session, buf)
            if len(buf) >= security.MAX_FRAME:
                raise security.ProtocolError("Receive buffer exceeded")
            if not buf:
                partial_since = None
            if not QUIET:
                log("traffic", addr, "received", len(data), "replies", len(replies))
            for reply in replies:
                conn.settimeout(5)
                conn.sendall(reply)
                conn.settimeout(1)
    except (OSError, security.ProtocolError) as error:
        log("connection ended", addr, type(error).__name__, str(error))
    except Exception as error:
        log("handler failed; connection closed", addr, type(error).__name__)
    finally:
        try:
            nrt_rooms.leave(session)
        finally:
            security.release(session)
            conn.close()
            if slot_acquired:
                with SLOT_LOCK:
                    PER_ADDRESS[addr[0]] -= 1
                    if not PER_ADDRESS[addr[0]]:
                        del PER_ADDRESS[addr[0]]
                SLOTS.release()
        log("disconnect", addr)


def main():
    global QUIET
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=paths.LOBBY_LISTEN)
    parser.add_argument("--port", type=int, default=52711)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    security.load_auth()
    if not ipaddress.ip_address(args.host).is_loopback and not security.AUTH_TOKENS:
        parser.error("External listener requires ROI_AUTH_FILE with per-player tokens")
    QUIET = QUIET or args.quiet
    configure_logging()
    import profile_relay
    relay = profile_relay.start_in_background(args.host, args.port + 2, log)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    nrt_rooms.LOG = log
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(16)
    log("listening on", f"{args.host}:{args.port}", "credentials required", bool(security.AUTH_TOKENS),
        "admission mode", security.AUTH_MODE)
    while True:
        conn, addr = listener.accept()
        acquired = SLOTS.acquire(blocking=False)
        with SLOT_LOCK:
            permitted = acquired and PER_ADDRESS[addr[0]] < security.MAX_PER_ADDRESS
            if permitted:
                PER_ADDRESS[addr[0]] += 1
        if not permitted:
            conn.close()
            if acquired:
                SLOTS.release()
            continue
        try:
            threading.Thread(target=serve, args=(conn, addr, True), daemon=True).start()
        except Exception:
            conn.close()
            with SLOT_LOCK:
                PER_ADDRESS[addr[0]] -= 1
                if not PER_ADDRESS[addr[0]]:
                    del PER_ADDRESS[addr[0]]
            SLOTS.release()
            raise


if __name__ == "__main__":
    main()
