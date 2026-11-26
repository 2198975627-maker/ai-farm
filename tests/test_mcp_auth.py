"""MCP auth tests: stdlib only, local fixtures, no providers or credentials."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_farm import mcp_relay
from ai_farm.mcp_relay import FarmMCPRelay, HTTPBackend, TOOLS
from ai_farm.office_server import create_server

TOKEN = "test-member-secret-not-for-output"
URL = "http://127.0.0.1:8765"


@contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


class MCPAuthTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"AI_FARM_MEMBER_TOKEN": TOKEN}))

    def test_url_restrictions(self):
        for url in [
            "https://127.0.0.1:8765", "http://example.com:8765", "http://127.0.0.2:8765",
            "http://[::1]:8765", "http://localhost", "http://127.0.0.1:0",
            "http://localhost:65536", "http://localhost:-1", "http://localhost:abc",
            "http://user:secret@localhost:8765", "http://localhost:8765/",
            "http://localhost:8765/api", "http://localhost:8765?", "http://localhost:8765#",
            "http://localhost:8765?q=secret", "http://localhost:8765#secret",
            " http://localhost:8765", "http://localhost:8765\n", "http://local\thost:8765",
            "http://localhost.:8765", "http://2130706433:8765", "http://127.1:8765",
            "http://localhost:8765\\@example.com", "http://%6cocalhost:8765",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError) as error:
                HTTPBackend(url)
            self.assertEqual(str(error.exception),
                             "Office URL must be http://localhost:PORT or http://127.0.0.1:PORT")
            self.assertNotIn(TOKEN, str(error.exception))

    def test_allowed_loopback_urls(self):
        for url in (URL, "http://localhost:1", "http://localhost:65535"):
            with self.subTest(url=url):
                self.assertEqual(HTTPBackend(url).office_url, url)

    def test_invalid_token_env_name(self):
        for name in ("", "1TOKEN", "TOKEN=secret", "TOKEN-NAME", "TOKEN\n", "秘密"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "environment variable name"):
                HTTPBackend(URL, member_token_env=name)

    def test_missing_or_invalid_auth_fails_before_transport(self):
        opener = self.enterContext(patch.object(mcp_relay.urllib.request, "build_opener"))
        for token in (None, "", " ", "secret\r\nInjected: yes", "secret value", "秘密"):
            os.environ.pop("AI_FARM_MEMBER_TOKEN", None)
            if token is not None:
                os.environ["AI_FARM_MEMBER_TOKEN"] = token
            with self.subTest(token=token), self.assertRaises(ValueError):
                HTTPBackend(URL)
        opener.assert_not_called()

    def test_custom_token_env(self):
        os.environ.pop("AI_FARM_MEMBER_TOKEN")
        os.environ["SCOPED_MEMBER_TOKEN"] = TOKEN
        backend = HTTPBackend(URL, member_token_env="SCOPED_MEMBER_TOKEN")
        self.assertNotIn(TOKEN, repr(backend))

    def test_redirects_never_forward_credentials(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            status = 302
            location = "/credential-leak"

            def log_message(self, *args):
                pass

            def do_GET(self):
                received.append((self.path, self.headers.get("Authorization")))
                self.send_response(self.status)
                self.send_header("Location", self.location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_POST = do_GET

        with running(ThreadingHTTPServer(("127.0.0.1", 0), Handler)) as url:
            backend = HTTPBackend(url)
            for location in ("/credential-leak", url.replace("127.0.0.1", "localhost") + "/credential-leak"):
                Handler.location = location
                for status in (301, 302, 303, 307, 308):
                    Handler.status = status
                    for method in ("GET", "POST"):
                        received.clear()
                        with self.subTest(location=location, status=status, method=method):
                            with self.assertRaises(RuntimeError) as error:
                                backend.snapshot() if method == "GET" else backend.action("businbox", {})
                            path = "/api/state" if method == "GET" else "/api/action"
                            self.assertEqual(received, [(path, f"Bearer {TOKEN}")])
                            self.assertNotIn(TOKEN, str(error.exception))

    def test_response_errors_are_sanitized(self):
        class Handler(BaseHTTPRequestHandler):
            status = 403
            body = {"ok": False, "error": TOKEN}

            def log_message(self, *args):
                pass

            def do_GET(self):
                raw = json.dumps(self.body).encode()
                self.send_response(self.status, TOKEN)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        with running(ThreadingHTTPServer(("127.0.0.1", 0), Handler)) as url:
            relay = FarmMCPRelay(HTTPBackend(url))
            for status, body in ((403, {"ok": False, "error": TOKEN}),
                                 (200, {"ok": False, "error": TOKEN}), (200, TOKEN)):
                Handler.status, Handler.body = status, body
                with self.subTest(status=status, body=body):
                    result = relay.handle_request({"id": 1, "method": "tools/call",
                                                   "params": {"name": "farm_list_tasks"}})
                    self.assertIn("error", result)
                    self.assertNotIn(TOKEN, json.dumps(result))

    def test_transport_errors_are_sanitized(self):
        backend = HTTPBackend(URL)
        backend._opener = Mock()
        backend._opener.open.side_effect = OSError(TOKEN)
        with self.assertRaises(RuntimeError) as error:
            backend.snapshot()
        self.assertNotIn(TOKEN, str(error.exception))

    def test_get_post_headers_ignore_proxy_and_global_cookies(self):
        os.environ["http_proxy"] = "http://untrusted.invalid:1"
        os.environ["no_proxy"] = ""
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                received.append((self.command, self.headers.get("Authorization"), self.headers.get("Cookie")))
                body = b'{"ok":true,"result":[],"tasks":{"tasks":[]}}'
                self.send_response(200)
                self.send_header("Set-Cookie", "farm_session=owner-secret")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET

        global_opener = self.enterContext(patch.object(mcp_relay.urllib.request, "urlopen"))
        with running(ThreadingHTTPServer(("127.0.0.1", 0), Handler)) as url:
            backend = HTTPBackend(url)
            backend.snapshot()
            backend.action("businbox", {})
        self.assertEqual(received, [("GET", f"Bearer {TOKEN}", None), ("POST", f"Bearer {TOKEN}", None)])
        global_opener.assert_not_called()

    def test_real_office_member_scope_and_no_owner_bearer(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = create_server(port=0, state_path=Path(tmp) / "office.json")
            with running(server) as url:
                access = server.access
                store = access.store
                agent = store.createagent({"name": "MCP fixture", "vendor": "fixture", "model": "fixture",
                                           "access_kind": "cli", "executable": "unused", "floor": "worker"})
                task = store.createtask({"title": "Allowed", "assigned_to": agent["id"], "task_kind": "small"})
                other = store.createtask({"title": "Private", "task_kind": "small"})
                owner_token = access.pair_owner(access.pair_code)["token"]
                owner = access.authenticate(owner_token)
                member = access.issue_member(owner, {"agent_id": agent["id"], "task_ids": [task["id"]]})
                os.environ["AI_FARM_MEMBER_TOKEN"] = member["token"]
                backend = HTTPBackend(url)
                self.assertEqual([t["id"] for t in backend.snapshot()["tasks"]["tasks"]], [task["id"]])
                self.assertEqual(backend.action("businbox", {"agent_id": agent["id"]}), [])
                for action, payload in [
                    ("claimtask", {"task_id": other["id"]}),
                    ("claimtask", {"task_id": task["id"], "worker_id": "chief"}),
                    ("bussend", {"task_id": task["id"], "interrupt": True}),
                    ("runroundtable", {"task_id": task["id"]}),
                    ("runautodispatch", {"task_id": task["id"]}),
                ]:
                    with self.subTest(action=action), self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                        backend.action(action, payload)
                for token in (owner_token, "invalid-member-token"):
                    os.environ["AI_FARM_MEMBER_TOKEN"] = token
                    denied = HTTPBackend(url)
                    with self.assertRaises(RuntimeError):
                        denied.snapshot()
                    with self.assertRaises(RuntimeError):
                        denied.action("businbox", {})
                access.revoke(owner, member["credential_id"])
                with self.assertRaises(RuntimeError):
                    backend.snapshot()

    def test_production_never_falls_back_to_personal_store(self):
        os.environ.pop("AI_FARM_MEMBER_TOKEN")
        store = self.enterContext(patch.object(mcp_relay, "OfficeStore"))
        self.enterContext(patch.object(sys, "stdin", io.StringIO("")))
        self.enterContext(patch.object(sys, "stdout", io.StringIO()))
        self.enterContext(patch.object(sys, "stderr", io.StringIO()))
        for argv in ([], ["--state-path", "personal.json"], ["--office-url", URL],
                     ["--dry-run", "--office-url", URL]):
            with self.subTest(argv=argv), patch.object(sys, "argv", ["mcp_relay", *argv]):
                with self.assertRaises(SystemExit) as error:
                    mcp_relay.main()
                self.assertEqual(error.exception.code, 2)
        store.assert_not_called()

    def test_explicit_dry_run_uses_cleaned_temporary_fixture(self):
        self.enterContext(patch.object(sys, "argv", ["mcp_relay", "--dry-run"]))
        self.enterContext(patch.object(sys, "stdin", io.StringIO("")))
        self.enterContext(patch.object(sys, "stdout", io.StringIO()))
        store = self.enterContext(patch.object(mcp_relay, "OfficeStore"))
        self.assertEqual(mcp_relay.main(), 0)
        path = store.call_args.kwargs["state_path"]
        self.assertEqual(path.name, "office.json")
        self.assertFalse(path.parent.exists())
        self.assertNotEqual(path, Path.home() / ".ai-farm" / "office_state.json")

    def test_unknown_methods_and_tools_do_not_dispatch(self):
        backend = Mock()
        relay = FarmMCPRelay(backend)
        for method in ("runroundtable", "execute", "dispatch_action"):
            self.assertEqual(relay.handle_request({"id": 1, "method": method})["error"]["code"], -32601)
            self.assertIn("error", relay.handle_request({"id": 1, "method": "tools/call",
                                                        "params": {"name": method}}))
        self.assertEqual(backend.mock_calls, [])
        for tool in TOOLS:
            self.assertIn("bound task scope", tool["description"])
            for field in ("sender_id", "from_id", "worker_id", "reviewer_id", "requested_by", "agent_id"):
                prop = tool["inputSchema"]["properties"].get(field)
                if prop:
                    self.assertIn("cannot impersonate", prop["description"])

    def test_http_mcp_endpoint_requires_bearer_and_allows_tunnel_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = create_server("127.0.0.1", 0, Path(tmp) / "office.json")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                access = server.access
                owner = access.authenticate(access.pair_owner(access.pair_code)["token"])
                agent = access.store.createagent({"name": "MCP Worker", "vendor": "OpenAI", "model": "gpt-4o-mini", "access_kind": "api", "floor": "worker", "key_env": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1"})
                task = access.store.createtask({"title": "remote mcp", "goal": "check", "assigned_to": agent["id"]})
                member = access.issue_member(owner, {"agent_id": agent["id"], "kind": "mcp", "task_ids": [task["id"]]})

                import http.client
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    # Valid member Bearer on /mcp works even with external tunnel Host.
                    conn.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
                                 headers={"Host": "demo.trycloudflare.com", "Content-Type": "application/json",
                                          "Authorization": f"Bearer {member['token']}"})
                    r_ok = conn.getresponse()
                    data = json.loads(r_ok.read().decode("utf-8"))
                    self.assertEqual(r_ok.status, 200)
                    self.assertEqual(data["result"]["serverInfo"]["name"], "ai-farm-mcp-relay")

                    # Tunnel Host without Bearer on /mcp is rejected.
                    conn.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"}),
                                 headers={"Host": "demo.trycloudflare.com", "Content-Type": "application/json"})
                    r_no_auth = conn.getresponse()
                    r_no_auth.read()
                    self.assertEqual(r_no_auth.status, 403)

                    # Tunnel Host on /api/state is still blocked even with Bearer.
                    conn.request("GET", "/api/state",
                                 headers={"Host": "demo.trycloudflare.com", "Authorization": f"Bearer {member['token']}"})
                    r_api = conn.getresponse()
                    r_api.read()
                    self.assertEqual(r_api.status, 403)
                finally:
                    conn.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
