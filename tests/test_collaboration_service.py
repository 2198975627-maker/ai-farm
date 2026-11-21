import concurrent.futures
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from ai_farm.adapters.codex_mcp import CodexMCPResult
from ai_farm.collaboration import CollaborationRuntime
from ai_farm.collaboration_service import ACTION_FIELDS
from ai_farm.mcp_relay import FarmMCPRelay, HTTPBackend, TOOLS
from ai_farm.office_auth import AccessDenied, OfficeAccess
from ai_farm.office_server import create_server
from ai_farm.office_store import OfficeStore


class FakeClient:
    """Protocol-independent test double, not evidence of live model acceptance."""
    def __init__(self, command, workspace):
        self.command = command
        self.workspace = workspace
        self.calls = []
        self.hook = None
        self.content = "Checked the task fixture"
        self.closed = threading.Event()

    def __enter__(self):
        return self

    def start(self, prompt, **kwargs):
        self.calls.append(("start", prompt, kwargs))
        if self.hook:
            self.hook()
        return CodexMCPResult("actual-fixture-thread", self.content)

    def reply(self, prompt, **kwargs):
        self.calls.append(("reply", prompt, kwargs))
        if self.hook:
            self.hook()
        return CodexMCPResult(kwargs["thread_id"], self.content)

    def close(self):
        self.closed.set()


class CollaborationServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="farm-service-test-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "office.json"
        self.store = OfficeStore(state_path=self.path)
        self.store.state["agents"] = [
            {"id": "worker", "name": "Codex fixture", "vendor": "OpenAI", "model": "fixture-codex", "access_kind": "cli"},
            {"id": "reviewer", "name": "Reviewer", "vendor": "Fixture", "model": "fixture-review", "access_kind": "desktop"},
            {"id": "outsider", "name": "Other", "vendor": "Fixture", "model": "fixture-other", "access_kind": "api"},
            {"id": "web", "name": "Web", "vendor": "Fixture", "model": "fixture-web", "access_kind": "web"},
        ]
        self.store.state["tasks"] = [
            {"id": "task", "assigned_to": "worker", "reviewer_id": "reviewer"},
            {"id": "other", "assigned_to": "outsider", "reviewer_id": "reviewer"},
            {"id": "webtask", "assigned_to": "web", "reviewer_id": "reviewer"},
        ]
        self.store.save()
        self.access = OfficeAccess(self.store)
        self.service = self.access.collaboration
        self.addCleanup(self.service.close)
        self.owner = self.access.authenticate(self.access.pair_owner(self.access.pair_code)["token"])
        self.reviewer = self.member("reviewer", ["task", "other", "webtask"])
        self.worker = None
        self.client = None

    def member(self, agent, tasks, role="member"):
        issued = self.access.issue_member(self.owner, {"agent_id": agent, "task_ids": tasks, "role": role})
        return self.access.authenticate(issued["token"])

    def act(self, who, action, **payload):
        return self.access.action(who, action, payload)

    def connect(self, managed=False):
        self.act(self.reviewer, "collabconnect")
        if managed:
            with patch("ai_farm.collaboration_service.CodexMCPClient", side_effect=FakeClient):
                result = self.act(self.owner, "collabconnectcodex", agent_id="worker", task_ids=["task"],
                                  executable=sys.executable, workspace_dir=self.tmp.name)
            self.assertTrue(result["connected"])
            self.worker = self.service._managed["worker"]["principal"]
            self.client = self.service._managed["worker"]["client"]
        else:
            self.worker = self.member("worker", ["task"])
            self.act(self.worker, "collabconnect")
        self.room = self.act(self.owner, "collabcreateroom", task_id="task", participants=["worker", "reviewer"],
                             supervisor_id="reviewer")["id"]

    def grant(self, request="grant", prompt="Inspect the task fixture"):
        return self.act(self.reviewer, "collabauthorize", room_id=self.room, target="worker", prompt=prompt, request_id=request)

    def test_lazy_initialization_and_tokens_are_private(self):
        self.assertIs(self.store._collaboration_service, self.service)
        self.assertIsNone(self.service._runtime)
        self.assertNotIn("collaboration", self.store.state)
        self.connect()
        output = self.act(self.worker, "collabsnapshot", room_id=self.room)
        saved = self.path.read_text(encoding="utf-8")
        for token in self.service._tokens.values():
            self.assertNotIn(token, saved)
            self.assertNotIn(token, json.dumps(output))
        status = self.act(self.worker, "collabconnect")
        self.assertEqual(status["connection_mode"], "active_member")
        self.assertFalse(status["automatic_wake"])

    def test_identity_scope_and_owner_boundaries(self):
        self.connect()
        for action, payload in [
            ("collabcreateroom", {"task_id": "task", "participants": ["worker", "reviewer"]}),
            ("collabclose", {"room_id": self.room, "accept": False, "summary": "Stop"}),
            ("collabauthorize", {"room_id": self.room, "target": "reviewer", "prompt": "Inspect", "request_id": "bad"}),
        ]:
            with self.assertRaises(AccessDenied):
                self.act(self.worker, action, **payload)
        with self.assertRaises(ValueError):
            self.act(self.worker, "collabpost", room_id=self.room, text="Message", request_id="spoof", agent_id="reviewer")
        forged = {**self.worker, "role": "owner"}
        with self.assertRaises(AccessDenied):
            self.act(forged, "collabsnapshot", room_id=self.room)
        self.store.state["tasks"][0]["assigned_to"] = "outsider"
        with self.assertRaises(AccessDenied):
            self.act(self.worker, "collabsnapshot", room_id=self.room)
        with self.assertRaises(AccessDenied):
            self.grant()

    def test_web_courier_and_foreign_room_denied(self):
        courier = self.member("web", ["webtask"], "courier")
        with self.assertRaises(AccessDenied):
            self.act(courier, "collabconnect")
        with self.assertRaises(AccessDenied):
            self.member("web", ["webtask"])
        self.connect()
        outsider = self.member("outsider", ["other"])
        self.act(outsider, "collabconnect")
        with self.assertRaises(AccessDenied):
            self.act(outsider, "collabsnapshot", room_id=self.room)
        with self.assertRaises(AccessDenied):
            self.act(self.owner, "collabcreateroom", task_id="task", participants=["worker", "outsider"])

    def test_manual_claim_complete_review_and_final_owner_accept(self):
        self.connect()
        grant = self.grant()
        self.assertEqual(grant, self.grant())
        with self.assertRaises(AccessDenied):
            self.act(self.reviewer, "collabclaim", grant_id=grant["id"])
        claim = self.act(self.worker, "collabclaim", grant_id=grant["id"])
        self.assertTrue(claim["claimed"])
        self.assertNotIn("binding_id", claim["execution"])
        self.assertFalse(self.act(self.worker, "collabclaim", grant_id=grant["id"])["claimed"])
        self.act(self.worker, "collabcomplete", grant_id=grant["id"], conclusion="Fixture inspected", test_result="Not run")
        with self.assertRaises(AccessDenied):
            self.act(self.worker, "collabreview", grant_id=grant["id"], accepted=True, evidence="Self")
        self.act(self.reviewer, "collabreview", grant_id=grant["id"], accepted=True, evidence="Independently inspected")
        self.assertEqual(self.act(self.owner, "collabclose", room_id=self.room, accept=True, summary="Accepted")["state"], "accepted")

    def wait_change(self, change, expected_error=False):
        entered = threading.Event()
        original = self.service.runtime._condition.wait
        def observed(timeout=None):
            entered.set()
            return original(timeout)
        with patch.object(self.service.runtime._condition, "wait", side_effect=observed) as waiting:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.act, self.worker, "collabwait", room_id=self.room, wait_id="wait", timeout_seconds=30)
                self.assertTrue(entered.wait(2), "wait never released auth/store locks")
                change()
                if expected_error:
                    with self.assertRaises(AccessDenied):
                        future.result(timeout=2)
                    result = None
                else:
                    result = future.result(timeout=2)
                self.assertEqual(waiting.call_count, 1)
                return result

    def test_wait_cancel_and_precancel_without_polling(self):
        self.connect()
        result = self.wait_change(lambda: self.act(self.worker, "collabcancelwait", wait_id="wait"))
        self.assertTrue(result["cancelled"])
        self.act(self.worker, "collabcancelwait", wait_id="early")
        result = self.act(self.worker, "collabwait", room_id=self.room, wait_id="early", timeout_seconds=30)
        self.assertTrue(result["cancelled"])

    def test_wait_revocation_wakes_without_auth_deadlock(self):
        self.connect()
        self.wait_change(lambda: self.access.revoke(self.owner, self.worker["id"]), expected_error=True)
        self.assertNotIn(self.worker["id"], self.service._tokens)

    def test_wait_response_revalidates_scope(self):
        self.connect()
        def change():
            with self.store._lock:
                self.store.state["tasks"][0]["assigned_to"] = "outsider"
            self.act(self.reviewer, "collabpost", room_id=self.room, text="Wake", request_id="wake")
        self.wait_change(change, expected_error=True)

    def test_wait_offer_ack_and_close_wakeup(self):
        self.connect()
        result = self.wait_change(lambda: self.act(self.reviewer, "collabpost", room_id=self.room, text="Evidence", request_id="msg"))
        self.act(self.worker, "collaback", room_id=self.room, sequence=result["offered_cursor"])
        self.assertEqual(self.act(self.worker, "collabinbox", room_id=self.room)["messages"], [])
        result = self.wait_change(lambda: self.act(self.owner, "collabclose", room_id=self.room, accept=False, summary="Stop"))
        self.assertEqual(result["room_state"], "stopped")

    def test_managed_explicit_grant_durable_claim_and_true_thread_reuse(self):
        self.connect(managed=True)
        self.assertEqual(self.client.command, [sys.executable, "mcp-server"])
        self.assertEqual(self.client.calls, [])
        self.assertTrue(self.service.supports("worker", "task"))
        self.assertFalse(self.service.supports("worker", "other"))
        with self.assertRaises(AccessDenied):
            self.service.execute_authorized("worker", "task", "Inspect", "missing")
        grant = self.grant()
        def check_saved():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertEqual(saved["collaboration"]["grants"][grant["id"]]["state"], "running")
        self.client.hook = check_saved
        first = self.act(self.owner, "collabexecute", grant_id=grant["id"])
        self.assertEqual(first["thread_id"], "actual-fixture-thread")
        self.assertEqual(first, self.act(self.owner, "collabexecute", grant_id=grant["id"]))
        self.assertEqual(len(self.client.calls), 1)
        record = self.store.state["collaboration"]["grants"][grant["id"]]
        self.assertEqual(record["result"]["test_result"], "未提供测试结果")
        self.assertIsNone(record["result"]["usage_tokens"])
        self.client.hook = None
        next_grant = self.grant("second")
        self.service.execute_authorized("worker", "task", next_grant["prompt"], "second")
        self.assertEqual(self.client.calls[1][0], "reply")
        self.assertEqual(self.client.calls[1][2]["thread_id"], first["thread_id"])
        self.assertEqual(self.client.calls[0][2]["model"], "fixture-codex")

    def test_failed_claim_save_never_calls_model(self):
        self.connect(managed=True)
        grant = self.grant()
        with patch.object(self.store, "save", side_effect=OSError("private fixture detail")):
            with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
                self.act(self.owner, "collabexecute", grant_id=grant["id"])
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.store.state["collaboration"]["grants"][grant["id"]]["state"], "pending")

    def test_unknown_is_sanitized_never_retried(self):
        self.connect(managed=True)
        grant = self.grant()
        def failure():
            raise RuntimeError("secret-key-and-private-location")
        self.client.hook = failure
        result = self.act(self.owner, "collabexecute", grant_id=grant["id"])
        self.assertEqual(result["state"], "unknown")
        self.assertNotIn("secret-key", json.dumps(result))
        self.assertNotIn("secret-key", self.path.read_text(encoding="utf-8"))
        self.assertFalse(self.service.supports("worker", "task"))
        with self.assertRaises(AccessDenied):
            self.act(self.owner, "collabexecute", grant_id=grant["id"])
        self.assertEqual(len(self.client.calls), 1)
        self.act(self.owner, "collabresolve", grant_id=grant["id"], evidence="Verified process stopped")

    def test_inflight_is_serial_and_revoke_discards_late_result(self):
        self.connect(managed=True)
        grant = self.grant()
        entered, release = threading.Event(), threading.Event()
        def hold():
            entered.set()
            self.assertTrue(release.wait(4))
        self.client.hook = hold
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.act, self.owner, "collabexecute", grant_id=grant["id"])
            self.assertTrue(entered.wait(2))
            try:
                second = self.grant("second")
                with self.assertRaises(ValueError):
                    self.act(self.owner, "collabexecute", grant_id=second["id"])
                self.access.revoke(self.owner, self.worker["id"])
                with self.assertRaises(ValueError):
                    self.act(self.owner, "collabresolve", grant_id=grant["id"], evidence="Too early")
            finally:
                release.set()
            self.assertEqual(future.result(timeout=2)["state"], "unknown")
        self.assertEqual(self.store.state["collaboration"]["grants"][grant["id"]]["state"], "unknown")
        self.assertEqual(len(self.client.calls), 1)

    def test_room_stop_and_supervisor_revoke_reject_late_completion(self):
        for stop_room in (True, False):
            with self.subTest(stop_room=stop_room):
                # Each subcase is a separate running manual grant.
                if self.worker is None:
                    self.connect()
                grant = self.grant("stop" if stop_room else "revoke")
                self.act(self.worker, "collabclaim", grant_id=grant["id"])
                if stop_room:
                    self.act(self.owner, "collabclose", room_id=self.room, accept=False, summary="Stop")
                else:
                    self.access.revoke(self.owner, self.reviewer["id"])
                with self.assertRaises((AccessDenied, ValueError)):
                    self.act(self.worker, "collabcomplete", grant_id=grant["id"], conclusion="Late", test_result="Not run")
                if stop_room:
                    self.act(self.owner, "collabresolve", grant_id=grant["id"], evidence="Confirmed stopped")
                    self.room = self.act(self.owner, "collabcreateroom", task_id="task", participants=["worker", "reviewer"], supervisor_id="reviewer")["id"]

    def test_frozen_model_and_managed_member_cannot_bypass_transport(self):
        self.connect(managed=True)
        grant = self.grant()
        with self.assertRaises(AccessDenied):
            self.act(self.worker, "collabclaim", grant_id=grant["id"])
        with self.assertRaises(AccessDenied):
            self.act(self.worker, "collabexecute", grant_id=grant["id"])
        self.store.state["agents"][0]["model"] = "changed-codex"
        self.assertFalse(self.service.supports("worker", "task"))
        with self.assertRaises(AccessDenied):
            self.act(self.owner, "collabexecute", grant_id=grant["id"])
        self.assertEqual(self.client.calls, [])

    def test_codex_identity_policy_and_handshake_failure_are_honest(self):
        base = {"agent_id": "worker", "task_ids": ["task"], "executable": sys.executable, "workspace_dir": self.tmp.name}
        for extra in ({"sandbox": "danger-full-access"}, {"approval_policy": "never"}, {"agent_id": "reviewer"}, {"task_ids": ["other"]}):
            with self.subTest(extra=extra), patch("ai_farm.collaboration_service.CodexMCPClient") as constructor:
                with self.assertRaises((AccessDenied, ValueError)):
                    self.act(self.owner, "collabconnectcodex", **{**base, **extra})
                constructor.assert_not_called()
        with patch("ai_farm.collaboration_service.CodexMCPClient") as constructor:
            constructor.return_value.__enter__.side_effect = RuntimeError("private executable path")
            with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
                self.act(self.owner, "collabconnectcodex", **base)
        self.assertFalse(self.service.supports("worker", "task"))
        self.assertNotIn("worker", self.service._managed)

    def test_structured_result_and_critical_operation_rejection(self):
        self.connect(managed=True)
        grant = self.grant()
        self.client.content = json.dumps({"conclusion": "Checked fixture", "test_result": "Fixture test passed", "changed_files": ["src/fixture.py"]})
        self.act(self.owner, "collabexecute", grant_id=grant["id"])
        self.assertEqual(self.store.state["collaboration"]["grants"][grant["id"]]["result"]["test_result"], "Fixture test passed")
        blocked = self.grant("critical", "Deploy production")
        with self.assertRaises(AccessDenied):
            self.act(self.owner, "collabexecute", grant_id=blocked["id"])
        self.assertEqual(len(self.client.calls), 1)

    def test_grant_match_is_exact_and_supervisor_scope_is_revalidated(self):
        self.connect(managed=True)
        grant = self.grant()
        for task_id, prompt, request_id in (("other", grant["prompt"], "grant"),
                                            ("task", "Different prompt", "grant"),
                                            ("task", grant["prompt"], "other-request")):
            with self.assertRaises(AccessDenied):
                self.service.execute_authorized("worker", task_id, prompt, request_id)
        self.store.state["tasks"][0]["reviewer_id"] = "outsider"
        with self.assertRaises(AccessDenied):
            self.act(self.owner, "collabexecute", grant_id=grant["id"])
        self.assertEqual(self.client.calls, [])

    def test_managed_new_room_starts_a_new_thread(self):
        self.connect(managed=True)
        first = self.grant()
        self.act(self.owner, "collabexecute", grant_id=first["id"])
        self.room = self.act(self.owner, "collabcreateroom", task_id="task", participants=["worker", "reviewer"], supervisor_id="reviewer")["id"]
        second = self.grant("new-room")
        self.act(self.owner, "collabexecute", grant_id=second["id"])
        self.assertEqual([call[0] for call in self.client.calls], ["start", "start"])

    def test_owner_logout_wakes_wait(self):
        self.connect()
        self.wait_change(lambda: self.access.revoke(self.owner, self.owner["id"]), expected_error=True)
        self.assertTrue(self.service._closed)
        self.assertEqual(self.service._tokens, {})

    def test_restart_marks_running_unknown(self):
        self.connect()
        grant = self.grant()
        self.act(self.worker, "collabclaim", grant_id=grant["id"])
        reopened = OfficeStore(state_path=self.path)
        recovered = CollaborationRuntime(reopened)
        try:
            self.assertEqual(recovered._data["grants"][grant["id"]]["state"], "unknown")
        finally:
            recovered.close()

    def test_real_stdio_transport_against_fake_protocol_process(self):
        # Actual CodexMCPClient handshake/start/reply, but subprocess is a tiny
        # protocol fixture, not a model or installed Codex invocation.
        program = '''import json, sys
for line in sys.stdin:
    req = json.loads(line)
    if "id" not in req: continue
    method = req["method"]
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": [{"name": "codex"}, {"name": "codex-reply"}]}
    else:
        args = req["params"]["arguments"]
        result = {"structuredContent": {"threadId": args.get("threadId", "protocol-thread"), "content": "Protocol fixture result"}}
    print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}), flush=True)
'''
        native_popen = subprocess.Popen
        commands = []
        def fixture_process(command, **kwargs):
            commands.append(command)
            self.assertFalse(kwargs["shell"])
            return native_popen([sys.executable, "-u", "-c", program], **kwargs)
        self.act(self.reviewer, "collabconnect")
        with patch("ai_farm.adapters.codex_mcp.subprocess.Popen", side_effect=fixture_process):
            result = self.act(self.owner, "collabconnectcodex", agent_id="worker", task_ids=["task"], executable=sys.executable, workspace_dir=self.tmp.name)
        self.assertTrue(result["connected"])
        self.assertEqual(commands, [[sys.executable, "mcp-server"]])
        connection = self.service._managed["worker"]
        self.addCleanup(connection["client"].close)
        self.room = self.act(self.owner, "collabcreateroom", task_id="task", participants=["worker", "reviewer"], supervisor_id="reviewer")["id"]
        for request in ("first", "reply"):
            grant = self.grant(request)
            result = self.act(self.owner, "collabexecute", grant_id=grant["id"])
            self.assertEqual(result["thread_id"], "protocol-thread")
            self.assertEqual(result["text"], "Protocol fixture result")

    def test_relay_tools_sanitize_and_receive_cancel_during_wait(self):
        self.connect()
        names = {tool["name"] for tool in TOOLS}
        self.assertTrue({"farm_" + name for name in ACTION_FIELDS}.issubset(names))
        entered, cancelled = threading.Event(), threading.Event()
        testcase = self
        class Backend:
            def action(self, name, payload):
                if name == "collabwait":
                    entered.set()
                    testcase.assertTrue(cancelled.wait(3))
                    return {"cancelled": True}
                if name == "collabcancelwait":
                    cancelled.set()
                    return {"cancelled": True}
                raise RuntimeError("secret-local-detail")
        relay = FarmMCPRelay(Backend())
        response = relay.handle_request({"id": 1, "method": "tools/call", "params": {"name": "farm_collabinbox", "arguments": {"room_id": self.room}}})
        self.assertNotIn("secret-local-detail", json.dumps(response))
        def input_lines():
            yield json.dumps({"id": 2, "method": "tools/call", "params": {"name": "farm_collabwait", "arguments": {"room_id": self.room, "wait_id": "stdio"}}})
            self.assertTrue(entered.wait(2))
            yield json.dumps({"method": "notifications/cancelled", "params": {"requestId": 2}})
            self.assertTrue(cancelled.wait(2))
        output = io.StringIO()
        relay.serve_stdio(input_lines(), output)
        self.assertTrue(cancelled.is_set())
        for line in output.getvalue().splitlines():
            self.assertEqual(json.loads(line)["jsonrpc"], "2.0")

    def test_http_wait_cancel_and_member_owner_boundary(self):
        # Exercise the production bearer HTTP path against an isolated OfficeServer.
        server_path = Path(self.tmp.name) / "http.json"
        server = create_server(port=0, state_path=server_path)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        access = server.access
        access.store.state["agents"] = copy.deepcopy(self.store.state["agents"])
        access.store.state["tasks"] = copy.deepcopy(self.store.state["tasks"])
        owner = access.authenticate(access.pair_owner(access.pair_code)["token"])
        issued = access.issue_member(owner, {"agent_id": "worker", "task_ids": ["task"]})
        review = access.issue_member(owner, {"agent_id": "reviewer", "task_ids": ["task"]})
        reviewer = access.authenticate(review["token"])
        access.action(reviewer, "collabconnect", {})
        with patch.dict(os.environ, {"AI_FARM_SERVICE_TEST_TOKEN": issued["token"]}):
            backend = HTTPBackend(f"http://127.0.0.1:{server.server_address[1]}", "AI_FARM_SERVICE_TEST_TOKEN")
        backend.action("collabconnect", {})
        room = access.action(owner, "collabcreateroom", {"task_id": "task", "participants": ["worker", "reviewer"]})["id"]
        with self.assertRaises(RuntimeError):
            backend.action("collabclose", {"room_id": room, "accept": False, "summary": "Unauthorized"})
        entered = threading.Event()
        original = access.collaboration.runtime._condition.wait
        def observed(timeout=None):
            entered.set()
            return original(timeout)
        with patch.object(access.collaboration.runtime._condition, "wait", side_effect=observed):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(backend.action, "collabwait", {"room_id": room, "wait_id": "http", "timeout_seconds": 30})
                self.assertTrue(entered.wait(2))
                backend.action("collabcancelwait", {"wait_id": "http"})
                self.assertTrue(future.result(timeout=3)["cancelled"])


if __name__ == "__main__":
    unittest.main()
