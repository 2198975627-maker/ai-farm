"""HTTP server for the AI Farm Office ("AI 农场办公室").

Uses Python's standard library only (http.server + json), serving:
  - GET /               -> web/index.html
  - GET /<static>       -> web/<static>
  - POST /api/action    -> {"action": "<name>", "payload": {...}}
  - GET /api/state      -> full office state snapshot
"""
from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .office_store import OfficeStore


WEB_DIR = Path(__file__).resolve().parents[1] / "web"
EXT_DIR = Path(__file__).resolve().parents[1] / "browser-extension"


class OfficeHTTPHandler(BaseHTTPRequestHandler):
    store: OfficeStore

    def log_message(self, fmt: str, *args: Any) -> None:
        # Quiet clean logs
        pass

    def _is_allowed_origin(self, origin: str | None) -> bool:
        if not origin:
            return True
        low = origin.strip().lower()
        return (
            low.startswith("http://127.0.0.1:")
            or low == "http://127.0.0.1"
            or low.startswith("http://localhost:")
            or low == "http://localhost"
            or low.startswith("chrome-extension://")
            or low.startswith("moz-extension://")
        )

    def _send_json(self, status: int, data: Any, origin: str | None = None) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if origin and self._is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        origin = self.headers.get("Origin")
        if origin and not self._is_allowed_origin(origin):
            self._send_json(403, {"ok": False, "error": "Forbidden cross-origin request"})
            return
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/state":
            origin = self.headers.get("Origin")
            if origin and not self._is_allowed_origin(origin):
                self._send_json(403, {"ok": False, "error": "Forbidden Origin"})
                return
            self._send_json(200, {
                "ok": True,
                "agents": self.store.listagents(),
                "tasks": self.store.listtasks(),
                "group_messages": self.store.listgroupmessages(),
                "skills": self.store.listskills(),
            }, origin=origin)
            return

        if path == "/bridge.js":
            target = EXT_DIR / "content.js"
            if target.exists():
                content = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
                return

        if path in ("/", "/index.html"):
            target = WEB_DIR / "index.html"
        else:
            rel = path.lstrip("/")
            target = (WEB_DIR / rel).resolve()
            if not str(target).startswith(str(WEB_DIR.resolve())):
                self._send_json(403, {"ok": False, "error": "Forbidden"})
                return

        if not target.exists() or not target.is_file():
            self._send_json(404, {"ok": False, "error": f"Not found: {path}"})
            return

        mime, _ = mimetypes.guess_type(str(target))
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime or 'text/plain'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        origin = self.headers.get("Origin")
        if origin and not self._is_allowed_origin(origin):
            self._send_json(403, {"ok": False, "error": f"Forbidden Origin: {origin}"})
            return

        parsed = urlparse(self.path)
        if parsed.path != "/api/action":
            self._send_json(404, {"ok": False, "error": "Unknown endpoint"}, origin=origin)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            req = json.loads(body) if body else {}
            action = req.get("action", "")
            payload = req.get("payload") or {}
            result = self.store.dispatch_action(action, payload)
            self._send_json(200, {
                "ok": True,
                "action": action,
                "result": result,
                "snapshot": {
                    "agents": self.store.listagents(),
                    "tasks": self.store.listtasks(),
                    "group_messages": self.store.listgroupmessages(),
                    "skills": self.store.listskills(),
                },
            }, origin=origin)
        except Exception as e:  # noqa: BLE001
            self._send_json(400, {"ok": False, "error": str(e)}, origin=origin)


def create_server(host: str = "127.0.0.1", port: int = 8765,
                  state_path: Path | None = None) -> ThreadingHTTPServer:
    store = OfficeStore(state_path=state_path)

    class BoundHandler(OfficeHTTPHandler):
        pass

    BoundHandler.store = store
    return ThreadingHTTPServer((host, port), BoundHandler)


def run_office_server(host: str = "127.0.0.1", port: int = 8765,
                      state_path: Path | None = None) -> None:
    srv = create_server(host=host, port=port, state_path=state_path)
    print(f"🏡 AI 农场办公室已启动: http://{host}:{port}")
    print("按 Ctrl+C 停止服务。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止办公室服务。")
    finally:
        srv.server_close()
