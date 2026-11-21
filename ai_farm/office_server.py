"""Loopback office server with owner pairing and scoped member credentials."""
from __future__ import annotations

import json
import mimetypes
import secrets
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .office_auth import AccessDenied, OfficeAccess
from .office_store import OfficeStore

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
MAX_ACTION_BODY_BYTES = 1_048_576
MAX_UPLOAD_BODY_BYTES = 8 * 1024 * 1024


class OfficeHTTPHandler(BaseHTTPRequestHandler):
    store: OfficeStore
    access: OfficeAccess

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _origin(self):
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        if host not in hosts:
            raise AccessDenied("Forbidden Host")
        origin = self.headers.get("Origin")
        allowed = {f"http://{host}"}
        if origin and origin not in allowed:
            parsed = urlparse(origin)
            extension = parsed.scheme in ("chrome-extension", "moz-extension") and parsed.netloc and not parsed.path
            if not (extension and self.headers.get("Authorization", "").startswith("Bearer ")):
                raise AccessDenied("Forbidden Origin")
        return origin

    def _principal(self, mutate=False):
        authorization = self.headers.get("Authorization", "")
        if authorization:
            if not authorization.startswith("Bearer "):
                raise AccessDenied("Invalid authorization")
            principal = self.access.authenticate(authorization[7:])
            if principal["role"] == "owner":
                raise AccessDenied("主人只使用本机浏览器会话，不能向成员分发主人凭据。")
            return principal
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            raise AccessDenied("Invalid session") from None
        value = cookie.get("farm_session")
        principal = self.access.authenticate(value.value if value else "")
        if principal["role"] != "owner":
            raise AccessDenied("Invalid browser session")
        if mutate and not secrets.compare_digest(self.headers.get("X-Farm-CSRF", ""), principal["csrf"]):
            raise AccessDenied("CSRF check failed")
        return principal

    def _json(self, status, data, cookie=None):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        origin = self.headers.get("Origin")
        if origin and self.headers.get("Authorization", "").startswith("Bearer "):
            try:
                self._origin()
            except AccessDenied:
                pass
            else:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        try:
            self._origin()
        except AccessDenied:
            self._json(403, {"ok": False, "error": "Cross-origin browser requests are not permitted"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Farm-CSRF")
        self.end_headers()

    def _events(self, principal):
        self.access.require_owner(principal)
        with self.store._lock:
            if self.server.event_clients >= 8:
                self._json(429, {"ok": False, "error": "Too many open event streams"})
                return
            self.server.event_clients += 1
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.connection.settimeout(15)
            seen = -1
            while True:
                with self.access.lock:
                    self.access._revalidate(principal)
                    remaining = principal["expires"] - time.monotonic()
                with self.store._state_events:
                    if self.server.events_closed:
                        return
                    if seen == self.store._state_revision:
                        self.store._state_events.wait(min(30, max(0, remaining)))
                    if self.server.events_closed:
                        return
                    revision = self.store._state_revision
                with self.access.lock:
                    self.access._revalidate(principal)
                packet = (f"event: state\ndata: {revision}\n\n" if revision != seen else ": keep-alive\n\n")
                self.wfile.write(packet.encode("utf-8"))
                self.wfile.flush()
                seen = revision
        except (AccessDenied, OSError):
            return
        finally:
            with self.store._lock:
                self.server.event_clients -= 1

    def do_GET(self):
        try:
            self._origin()
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                principal = self._principal()
                if path == "/api/session":
                    self.access.require_owner(principal)
                    self._json(200, {"ok": True, "csrf": principal["csrf"]})
                elif path == "/api/connections":
                    self._json(200, {"ok": True, "connections": self.access.connections(principal)})
                elif path == "/api/state":
                    self._json(200, {"ok": True, **self.access.snapshot(principal)})
                elif path == "/api/events":
                    self._events(principal)
                else:
                    self._json(404, {"ok": False, "error": "Unknown endpoint"})
                return
            root = WEB_DIR.resolve()
            target = (root / ("index.html" if path == "/" else unquote(path).lstrip("/"))).resolve()
            if not target.is_relative_to(root):
                self._json(403, {"ok": False, "error": "Forbidden"})
                return
            if not target.is_file():
                self._json(404, {"ok": False, "error": "Not found"})
                return
            content = target.read_bytes()
            mime, _ = mimetypes.guess_type(str(target))
            self.send_response(200)
            self.send_header("Content-Type", f"{mime or 'application/octet-stream'}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(content)
        except AccessDenied as error:
            self._json(401 if str(error).startswith("请先") else 403, {"ok": False, "error": str(error)})

    def do_POST(self):
        try:
            self._origin()
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Transfer-Encoding is not supported")
            path = urlparse(self.path).path
            max_bytes = MAX_UPLOAD_BODY_BYTES if path == "/api/upload" else MAX_ACTION_BODY_BYTES
            length = int(self.headers.get("Content-Length", "0"))
            if length > max_bytes:
                self._json(413, {"ok": False, "error": "Request body too large"})
                return
            if length < 0 or self.headers.get_content_type() != "application/json":
                raise ValueError("Expected a JSON request")
            principal = None if path == "/api/pair" else self._principal(mutate=True)
            self.connection.settimeout(15)
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("Expected a JSON object")
            if path != "/api/pair":
                principal = self._principal(mutate=True)
            if path == "/api/pair":
                session = self.access.pair_owner(request.get("code"))
                self._json(200, {"ok": True, "csrf": session["csrf"]},
                           f"farm_session={session['token']}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800")
            elif path == "/api/connections":
                self._json(200, {"ok": True, **self.access.issue_member(principal, request)})
            elif path == "/api/revoke":
                self._json(200, {"ok": True, **self.access.revoke(principal, request.get("credential_id"))})
            elif path == "/api/logout":
                self.access.revoke(principal, principal["id"])
                self._json(200, {"ok": True}, "farm_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
            elif path == "/api/upload":
                self.access.require_owner(principal)
                self._json(200, {"ok": True, "attachment": self.store.uploadattachment(request)})
            elif path == "/api/action":
                action, payload = request.get("action"), request.get("payload", {})
                if not isinstance(action, str) or not isinstance(payload, dict):
                    raise ValueError("Invalid action or payload")
                action = action.strip().lower()
                result = self.access.action(principal, action, payload)
                response = {"ok": True, "action": action, "result": result}
                if principal["role"] == "owner":
                    response["snapshot"] = self.access.snapshot(principal)
                self._json(200, response)
            else:
                self._json(404, {"ok": False, "error": "Unknown endpoint"})
        except AccessDenied as error:
            self._json(401 if str(error).startswith("请先") else 403, {"ok": False, "error": str(error)})
        except (ValueError, KeyError, TypeError) as error:
            self._json(400, {"ok": False, "error": str(error)})
        except Exception:
            self._json(500, {"ok": False, "error": "操作未确认完成，请核查任务状态；不要盲目重试。"})


def create_server(host: str = "127.0.0.1", port: int = 8765, state_path: Path | None = None) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("办公室只能绑定本机 loopback 地址。")
    store = OfficeStore(state_path=state_path)

    class BoundHandler(OfficeHTTPHandler):
        pass

    BoundHandler.store = store
    BoundHandler.access = OfficeAccess(store)
    class OfficeServer(ThreadingHTTPServer):
        def server_close(self):
            # Revoke/wake waiters before ThreadingMixIn joins request threads.
            with store._state_events:
                self.events_closed = True
                store._state_events.notify_all()
            try:
                store.closeautomation()
            except AttributeError:
                pass
            try:
                BoundHandler.access.collaboration.close()
            finally:
                super().server_close()

    server = OfficeServer((host, port), BoundHandler)
    server.access = BoundHandler.access
    server.event_clients = 0
    server.events_closed = False
    return server


def run_office_server(host: str = "127.0.0.1", port: int = 8765, state_path: Path | None = None) -> None:
    server = create_server(host, port, state_path)
    print(f"AI 农场办公室已启动: http://{host}:{server.server_address[1]}")
    print(f"本机一次性配对码（10 分钟有效，不要分享）: {server.access.pair_code}")
    print("按 Ctrl+C 停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
