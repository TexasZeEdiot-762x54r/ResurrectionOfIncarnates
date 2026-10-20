"""Local stand-in for the retired Rise of Incarnates game server (gdragon.vs765.nbgi-amnet.jp).

    python server.py [--port 52710]

Logs every request to logs/server.log and answers from handlers in roi_server_data.py.
"""
import argparse
import json
from logging.handlers import RotatingFileHandler
import logging
import pathlib
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from network_defaults import LOOPBACK
LOG = HERE / "logs" / "server.log"
lock = threading.Lock()
logger = logging.getLogger("roi-profile")


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    logger.info(line)


def redact(value):
    if isinstance(value, dict):
        return {key: "<redacted>" if key.lower() in
                {"ticket", "sv_token", "oauth_token", "oauth_token_secret", "lobby_token"}
                else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    slots = threading.BoundedSemaphore(16)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, fmt, *args):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 <= n <= 1024 * 1024:
            raise ValueError("Request body exceeds limit")
        return self.rfile.read(n) if n else b""

    def _handle(self):
        from library_pages import respond as library_response
        local_page = library_response(self.command,self.path)
        if local_page is not None:
            if local_page[1].get('Content-Type','').startswith('text/html'):
                log('LIBRARY',self.command,self.path.split('?',1)[0],local_page[0],len(local_page[2]))
            if self.command not in ('GET','HEAD'):
                self.close_connection = True
            return self._reply(*local_page, quiet=True)
        body = self._body()
        try:
            shown = json.dumps(redact(json.loads(body)), separators=(",", ":")).encode()
        except (ValueError, UnicodeError):
            shown = b"<non-JSON request body omitted>"
        import re
        if b'"ticket"' in shown:  # do not keep the Steam session ticket in the log
            shown = re.sub(rb'"ticket":"[^"]*"', b'"ticket":"<redacted>"', shown)
        # the client also sends the Steam IDs of the user's friends; keep other people's IDs out of the log
        own = str(__import__("server_state").STATE.get("player_id", "")).encode()
        shown = re.sub(rb"7656119\d{10}", lambda m: m.group() if m.group() == own else b"<friend>", shown)
        if b'"call":"loadPlayer"' in shown and b"<friend>" in shown:
            return self._reply(*self._answer(body), quiet=True)
        log(f">>> {self.command} {self.path}")
        log(f">>> body[{len(body)}] {shown[:4000]!r}")
        self._reply(*self._answer(body))

    def _answer(self, body):
        try:
            import roi_server_data
            # Reloading this module clears CALLS while other request threads use it.
            # Import once; deploy handler changes with a local-server restart.
            status, headers, out = roi_server_data.respond(self.command, self.path, dict(self.headers), body)
        except Exception:
            log("handler error\n" + traceback.format_exc())
            status, headers, out = 500, {}, b"{}"
        if isinstance(out, (dict, list)):
            out = json.dumps(out, separators=(",", ":")).encode()
        elif isinstance(out, str):
            out = out.encode()
        return status, headers, out

    def _reply(self, status, headers, out, quiet=False):
        if not quiet:
            try:
                shown = json.dumps(redact(json.loads(out)), separators=(",", ":")).encode()
            except (ValueError, UnicodeError):
                shown = b"<non-JSON response body omitted>"
            log(f"<<< {status} body[{len(out)}] {shown[:3000]!r}")
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        if "Content-Type" not in headers:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(out)

    do_GET = do_POST = do_PUT = do_HEAD = _handle


def main():
    from server_state import STATE
    STATE['background_commendations'] = True
    STATE['circle_service'] = True
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=52710)
    a = ap.parse_args()
    LOG.parent.mkdir(exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.addHandler(RotatingFileHandler(LOG, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"))
    logger.addHandler(logging.StreamHandler(sys.stdout))
    srv = BoundedHTTPServer((LOOPBACK, a.port), Handler)
    log(f"listening on {LOOPBACK}:{a.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
