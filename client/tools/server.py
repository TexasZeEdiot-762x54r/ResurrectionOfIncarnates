"""Local stand-in for the retired Rise of Incarnates game server (gdragon.vs765.nbgi-amnet.jp).

    python server.py [--port 52710]

Logs every request to logs/server.log and answers from handlers in roi_server_data.py.
"""
import argparse
import json
from logging.handlers import RotatingFileHandler
import logging
import pathlib
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from network_defaults import LOOPBACK
LOG = HERE / "logs" / "server.log"
lock = threading.Lock()
logger = logging.getLogger("roi-profile")
MAX_BODY = 1024 * 1024


class RequestTooLarge(ValueError):
    pass


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    logger.info(line)


def safe_log_path(path):
    """Omit query parameters and mask Steam IDs before logging a route."""
    route = path.split("?", 1)[0]
    route = re.sub(r"(?<!\d)7656119\d{10}(?!\d)", "<id>", route)
    route = re.sub(r"(?i)(/)(profile|commendations|circle)/\d{1,20}(?=/|$)",
                   r"\1\2/<id>", route)
    return route[:256]


def request_summary(body):
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        return "non-JSON omitted"
    if not isinstance(value, dict):
        return "JSON value omitted"
    call = value.get("call")
    if isinstance(call, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", call):
        return "call=" + call
    return "JSON object omitted"


def response_summary(body):
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        return "non-JSON omitted"
    result = value.get("result") if isinstance(value, dict) else None
    if isinstance(result, str) and result in {"OK", "NG", "ERROR"}:
        return "result=" + result
    return "JSON omitted"


def exception_summary(error):
    """Return bounded code location/type only; exception text may contain request data."""
    tb = error.__traceback__
    last = None
    for _ in range(32):
        if tb is None:
            break
        last = tb
        tb = tb.tb_next
    if last is None:
        location = "unknown"
    else:
        frame = last.tb_frame
        filename = pathlib.Path(frame.f_code.co_filename).name[:80]
        function = frame.f_code.co_name[:80]
        location = f"{filename}:{last.tb_lineno}:{function}"
    return f"{type(error).__name__[:80]} at {location}"[:256]


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
        if n > MAX_BODY:
            raise RequestTooLarge
        if n < 0:
            raise ValueError("Invalid request length")
        body = self.rfile.read(n) if n else b""
        if len(body) != n:
            raise ValueError("Truncated request body")
        return body

    def _handle(self):
        from library_pages import respond as library_response
        local_page = library_response(self.command,self.path)
        if local_page is not None:
            if local_page[1].get('Content-Type','').startswith('text/html'):
                log('LIBRARY', self.command[:16], safe_log_path(self.path), local_page[0], len(local_page[2]))
            if self.command not in ('GET','HEAD'):
                self.close_connection = True
            return self._reply(*local_page, quiet=True)
        try:
            body = self._body()
        except RequestTooLarge:
            self.close_connection = True
            return self._reply(413, {}, b'{"error":"Request body too large"}', quiet=True)
        except TimeoutError:
            self.close_connection = True
            return self._reply(408, {}, b'{"error":"Request body timed out"}', quiet=True)
        except ValueError:
            self.close_connection = True
            return self._reply(400, {}, b'{"error":"Invalid request body"}', quiet=True)
        summary = request_summary(body)
        if summary == "call=loadPlayer":
            return self._reply(*self._answer(body), quiet=True)
        log(f">>> {self.command[:16]} {safe_log_path(self.path)}")
        log(f">>> body[{len(body)}] {summary}")
        self._reply(*self._answer(body))

    def _answer(self, body):
        try:
            import roi_server_data
            # Reloading this module clears CALLS while other request threads use it.
            # Import once; deploy handler changes with a local-server restart.
            status, headers, out = roi_server_data.respond(self.command, self.path, dict(self.headers), body)
        except Exception as error:
            log("handler error", exception_summary(error))
            status, headers, out = 500, {}, b"{}"
        if isinstance(out, (dict, list)):
            out = json.dumps(out, separators=(",", ":")).encode()
        elif isinstance(out, str):
            out = out.encode()
        return status, headers, out

    def _reply(self, status, headers, out, quiet=False):
        if not quiet:
            try:
                summary = response_summary(out)
            except (ValueError, UnicodeError):
                summary = "non-JSON omitted"
            log(f"<<< {status} body[{len(out)}] {summary}")
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
