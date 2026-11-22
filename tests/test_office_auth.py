"""Office authorization integration tests: temporary state, localhost, no models."""
import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_farm.office_server import MAX_ACTION_BODY_BYTES, create_server


class OfficeAuthTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state_path = Path(temporary.name) / "office.json"
        self.server = create_server("127.0.0.1", 0, state_path=self.state_path)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True,
        )
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        self.origin = f"http://{self.host}"
        self.store = self.server.access.store
        adapter_patch = patch.object(
            self.store, "_build_adapter", side_effect=AssertionError("Models are forbidden in auth tests"),
        )
        self.adapter = adapter_patch.start()
        self.addCleanup(adapter_patch.stop)
        self.addCleanup(self.adapter.assert_not_called)
        self.worker = self.store.createagent({
            "name": "Fake API worker", "vendor": "AuthFakeAPI", "model": "fake-api",
            "access_kind": "api", "key_env": "FARM_AUTH_TEST_UNUSED_KEY",
            "base_url": "https://unused.invalid/v1", "floor": "worker",
        })
        self.other = self.store.createagent({
            "name": "Fake CLI worker", "vendor": "AuthFakeCLI", "model": "fake-cli",
            "access_kind": "cli", "executable": "farm-auth-test-never-execute", "floor": "worker",
        })
        self.web = self.store.createagent({
            "name": "Fake web worker", "vendor": "AuthFakeWeb", "model": "fake-web",
            "access_kind": "web", "login_url": "https://unused.invalid/", "floor": "worker",
        })
        self.task = self.make_task("Member task", self.worker)
        self.unscoped = self.make_task("Same worker but not authorized", self.worker)
        self.other_task = self.make_task("OTHER_TASK_PRIVATE_SENTINEL", self.other)
        self.web_task = self.make_task("Courier task", self.web)

    def make_task(self, title, worker, **extra):
        return self.store.createtask({
            "title": title, "goal": title, "assigned_to": worker["id"], "task_kind": "small", **extra,
        })

    def request(self, method, path, data=None, *, headers=None, raw=None, half_close=False):
        """Use raw headers so malformed lengths are not repaired by http.client."""
        body = raw if raw is not None else (json.dumps(data).encode("utf-8") if data is not None else b"")
        fields = {"Host": self.host}
        if method == "POST":
            fields.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        fields.update(headers or {})
        lines = [f"{method} {path} HTTP/1.1"]
        lines.extend(f"{name}: {value}" for name, value in fields.items() if value is not None)
        wire = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as connection:
            # Send headers/body together: early rejection must not race a second
            # body write against the server closing its connection on Windows.
            connection.sendall(wire)
            if half_close:
                connection.shutdown(socket.SHUT_WR)
            with http.client.HTTPResponse(connection) as response:
                response.begin()
                result = json.loads(response.read().decode("utf-8"))
                return response.status, dict(response.getheaders()), result

    def assert_ok(self, response):
        # Never include response bodies/headers in assertion output: issuance contains credentials.
        self.assertEqual(response[0], 200)
        self.assertIs(response[2].get("ok"), True)
        return response[2]

    def assert_denied(self, response):
        self.assertIn(response[0], (401, 403))
        self.assertIs(response[2].get("ok"), False)
        self.assertNotIn("snapshot", response[2])
        self.assertNotIn("result", response[2])

    def pair(self):
        response = self.request("POST", "/api/pair", {"code": self.server.access.pair_code})
        data = self.assert_ok(response)
        cookie = SimpleCookie()
        cookie.load(response[1].get("Set-Cookie", ""))
        self.assertIn("farm_session", cookie.keys())
        self.owner_headers = {
            "Cookie": f"farm_session={cookie['farm_session'].value}",
            "X-Farm-CSRF": data["csrf"], "Origin": self.origin,
        }
        return response, cookie

    def issue(self, agent=None, tasks=None, role="member"):
        if not hasattr(self, "owner_headers"):
            self.pair()
        response = self.request("POST", "/api/connections", {
            "agent_id": (agent or self.worker)["id"], "role": role,
            "task_ids": tasks if tasks is not None else [self.task["id"]],
        }, headers=self.owner_headers)
        data = self.assert_ok(response)
        self.assertEqual(data["role"], role)
        return {"Authorization": "Bearer " + data["token"]}, data["credential_id"]

    def action(self, name, payload=None, *, headers=None):
        return self.request("POST", "/api/action", {
            "action": name, "payload": payload or {},
        }, headers=headers)

    def roundtable(self, worker):
        seats = {}
        for seat in "abc":
            agent = self.store.createagent({"name": "Fixture " + seat, "vendor": "Fixture " + seat,
                "model": "fixture-" + seat, "access_kind": "desktop", "paid": True, "floor": "manager"})
            seats["seat_" + seat] = agent["id"]
        result = self.store.createbigtask({"title": "Scoped roundtable fixture", "mode": "roundtable", **seats,
            "subtasks": [{"title": "Collect", "assigned_to": worker["id"], "task_kind": "small"}]})
        return result["parent"], result["subtasks"][0]

    def test_roundtable_courier_can_read_until_single_send_claim(self):
        parent, child = self.roundtable(self.web)
        headers, _ = self.issue(self.web, [child["id"]], "courier")
        payload = {"task_id": child["id"]}
        first = self.assert_ok(self.action("gettaskprompt", payload, headers=headers))["result"]
        second = self.assert_ok(self.action("gettaskprompt", payload, headers=headers))["result"]
        self.assertEqual(first["prompt"], second["prompt"])
        self.assertTrue(second["dispatch_allowed"])
        self.assert_ok(self.action("courierclaim", payload, headers=headers))
        self.assert_denied(self.action("courierclaim", payload, headers=headers))
        blocked = self.assert_ok(self.action("gettaskprompt", payload, headers=headers))["result"]
        self.assertFalse(blocked["dispatch_allowed"])
        self.assertEqual(blocked["prompt"], "")
        self.assert_ok(self.action("postmessage", {**payload,
            "text": "【结论】Collected fixture【改动文件】none【测试结果】fixture checked"}, headers=headers))
        self.assert_ok(self.action("getroundtableprompt", {"task_id": parent["id"]}, headers=self.owner_headers))
        self.assertEqual(self.action("courierclaim", payload, headers=headers)[0], 400)

    def test_scoped_dry_report_cannot_become_roundtable_material(self):
        parent, child = self.roundtable(self.worker)
        headers, _ = self.issue(self.worker, [child["id"]])
        for marker in ({"dry_run": True}, {"usage": {"dry_run": True}}):
            response = self.action("postmessage", {"task_id": child["id"], "conclusion": "Fixture only",
                "test_result": "Not a real model", **marker}, headers=headers)
            self.assertIn(response[0], (400, 403))
        self.assertEqual(self.action("getroundtableprompt", {"task_id": parent["id"]}, headers=self.owner_headers)[0], 400)

    def test_scoped_review_and_conclusion_preserve_dry_boundary(self):
        self.task["reviewer_id"] = self.other["id"]
        review_headers, _ = self.issue(self.other, [self.task["id"]])
        with patch.object(self.store, "submitcodereview") as review:
            self.assertEqual(self.action("submitcodereview", {"task_id": self.task["id"], "passed": True,
                "dry_run": True}, headers=review_headers)[0], 400)
            review.assert_not_called()
        headers, _ = self.issue()
        with patch.object(self.store, "sendconclusion") as conclusion:
            self.assertEqual(self.action("sendconclusion", {"task_id": self.task["id"], "to_id": "owner",
                "conclusion": "Simulation", "usage": {"dry_run": True}}, headers=headers)[0], 400)
            conclusion.assert_not_called()

    def test_members_cannot_advance_or_choose_roundtable(self):
        parent, child = self.roundtable(self.worker)
        headers, _ = self.issue(self.worker, [child["id"]])
        for action in ("runroundtablestep", "getroundtableprompt", "submitroundtableresult", "chooseroundtable", "roundtablehandoff"):
            self.assert_denied(self.action(action, {"task_id": parent["id"], "decision": "C"}, headers=headers))

    def test_recipient_alias_cannot_escape_task_scope(self):
        headers, _ = self.issue()
        self.assert_denied(self.action("bussend", {"task_id": self.task["id"], "to_id": "",
            "recipient_id": self.other["id"], "text": "Attempted alias bypass"}, headers=headers))

    def test_stale_principal_cannot_mutate_after_revocation(self):
        headers, credential_id = self.issue()
        token = headers["Authorization"][7:]
        principal = self.server.access.authenticate(token)
        self.assert_ok(self.request("POST", "/api/revoke", {"credential_id": credential_id}, headers=self.owner_headers))
        with self.assertRaises(PermissionError):
            self.server.access.action(principal, "postmessage", {"task_id": self.task["id"], "text": "Late report"})

    def test_report_commit_failure_blocks_ambiguous_retry(self):
        headers, _ = self.issue()
        report = {"task_id": self.task["id"], "text": "Fixture report"}
        original = self.store.save
        writes = 0

        def fail_after_reservation():
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("fixture failure")
            original()

        with patch.object(self.store, "save", side_effect=fail_after_reservation):
            self.assertEqual(self.action("postmessage", report, headers=headers)[0], 500)
        self.assert_denied(self.action("postmessage", report, headers=headers))

    def test_courier_claim_and_report_are_not_repeated(self):
        headers, _ = self.issue(self.web, [self.web_task["id"]], "courier")
        payload = {"task_id": self.web_task["id"]}
        self.assert_ok(self.action("courierclaim", payload, headers=headers))
        self.assert_denied(self.action("courierclaim", payload, headers=headers))
        report = {**payload, "conclusion": "Fixture only", "changed_files": [], "test_result": "Fixture validation"}
        first = self.assert_ok(self.action("postmessage", report, headers=headers))["result"]
        second = self.assert_ok(self.action("postmessage", report, headers=headers))["result"]
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["report_meta"]["conclusion"], "Fixture only")
        self.assert_denied(self.action("courierclaim", payload, headers=headers))

    def test_anonymous_get_and_post_are_rejected_without_state_changes(self):
        before = self.state_path.read_bytes()
        for path in ("/api/state", "/api/session", "/api/connections"):
            with self.subTest(path=path):
                self.assert_denied(self.request("GET", path))
        for path, data in (
            ("/api/action", {"action": "createtask", "payload": {"title": "unauthorized"}}),
            ("/api/connections", {"agent_id": self.worker["id"], "task_ids": [self.task["id"]]}),
            ("/api/revoke", {"credential_id": "unknown"}), ("/api/logout", {}),
        ):
            with self.subTest(path=path):
                self.assert_denied(self.request("POST", path, data))
        self.assertEqual(before, self.state_path.read_bytes())

    def test_pairing_is_one_use_and_cookie_is_httponly_samesite(self):
        code = self.server.access.pair_code
        self.assert_denied(self.request("POST", "/api/pair", {"code": "wrong"}))
        response, cookie = self.pair()
        self.assertTrue(cookie["farm_session"]["httponly"])
        self.assertEqual(cookie["farm_session"]["samesite"].lower(), "strict")
        self.assertEqual(cookie["farm_session"]["path"], "/")
        self.assertNotIn("token", response[2])
        self.assertEqual(response[1]["Cache-Control"], "no-store")
        self.assert_denied(self.request("POST", "/api/pair", {"code": code}))
        self.assert_ok(self.request("GET", "/api/session", headers=self.owner_headers))

    def test_expired_pair_code_cannot_create_session(self):
        self.server.access.pair_deadline = time.monotonic() - 1
        self.assert_denied(self.request("POST", "/api/pair", {"code": self.server.access.pair_code}))

    def test_owner_cookie_requires_csrf_for_all_mutations(self):
        self.pair()
        for csrf in (None, "wrong"):
            for path, data in (
                ("/api/action", {"action": "toggleautoexecute", "payload": {"enabled": True}}),
                ("/api/connections", {"agent_id": self.worker["id"], "task_ids": [self.task["id"]]}),
                ("/api/revoke", {"credential_id": "unknown"}), ("/api/logout", {}),
            ):
                with self.subTest(csrf_missing=csrf is None, path=path):
                    self.assert_denied(self.request("POST", path, data, headers={
                        **self.owner_headers, "X-Farm-CSRF": csrf,
                    }))
        self.assertFalse(self.store.getsettings()["auto_execute_low_risk"])
        self.assert_ok(self.action("toggleautoexecute", {"enabled": True}, headers=self.owner_headers))
        self.assertTrue(self.store.getsettings()["auto_execute_low_risk"])

    def test_owner_can_act_and_read_full_snapshot(self):
        self.pair()
        data = self.assert_ok(self.action("createtask", {
            "title": "Owner-created task", "assigned_to": self.worker["id"], "task_kind": "small",
        }, headers=self.owner_headers))
        self.assertIn("snapshot", data)
        self.assertEqual(data["result"]["title"], "Owner-created task")
        state = self.assert_ok(self.request("GET", "/api/state", headers=self.owner_headers))
        self.assertIn("pending_approvals", state)
        self.assertIn(self.other_task["id"], {t["id"] for t in state["tasks"]["tasks"]})
        connections = self.assert_ok(self.request("GET", "/api/connections", headers=self.owner_headers))
        self.assertTrue(any(c["role"] == "owner" and c["current"] for c in connections["connections"]))
        self.assertTrue(all("token" not in c and "csrf" not in c for c in connections["connections"]))

    def test_owner_bearer_and_member_cookie_cannot_swap_auth_channels(self):
        _, cookie = self.pair()
        self.assert_denied(self.request("GET", "/api/state", headers={
            "Authorization": "Bearer " + cookie["farm_session"].value,
        }))
        member, _ = self.issue()
        self.assert_denied(self.request("GET", "/api/state", headers={
            "Cookie": "farm_session=" + member["Authorization"][7:],
        }))
        for authorization in ("Basic fake", "Bearer invalid", "Bearer "):
            with self.subTest(scheme=authorization.split()[0]):
                self.assert_denied(self.request("GET", "/api/state", headers={"Authorization": authorization}))

    def test_logout_revokes_owner_cookie(self):
        self.pair()
        response = self.request("POST", "/api/logout", {}, headers=self.owner_headers)
        self.assert_ok(response)
        self.assertIn("Max-Age=0", response[1].get("Set-Cookie", ""))
        self.assert_denied(self.request("GET", "/api/state", headers=self.owner_headers))

    def test_host_and_origin_must_match_exact_loopback_endpoint(self):
        self.pair()
        for host in (self.host, f"localhost:{self.port}"):
            with self.subTest(allowed_host=host):
                self.assert_ok(self.request("GET", "/api/state", headers={
                    **self.owner_headers, "Host": host, "Origin": "http://" + host,
                }))
        for host in (None, "evil.invalid", f"127.0.0.1.evil.invalid:{self.port}",
                     f"localhost.evil.invalid:{self.port}", f"127.0.0.1:{self.port + 1}",
                     f"evil.invalid@127.0.0.1:{self.port}"):
            with self.subTest(host=host):
                self.assert_denied(self.request("GET", "/api/state", headers={**self.owner_headers, "Host": host}))
        for origin in ("null", "https://evil.invalid", f"http://127.0.0.1.evil.invalid:{self.port}",
                       self.origin + ".evil.invalid", self.origin + "/", "https://" + self.host,
                       f"http://localhost:{self.port}", f"http://127.0.0.1:{self.port + 1}"):
            with self.subTest(origin=origin):
                headers = {**self.owner_headers, "Origin": origin}
                response = self.action("listagents", headers=headers)
                self.assert_denied(response)
                self.assertNotIn("Access-Control-Allow-Origin", response[1])

    def test_pairing_also_checks_host_and_origin(self):
        for headers in ({"Host": "evil.invalid"}, {"Origin": "https://evil.invalid"}):
            self.assert_denied(self.request("POST", "/api/pair", {
                "code": self.server.access.pair_code,
            }, headers=headers))
        self.pair()  # Hostile requests did not consume the one-use code.

    def test_extensions_need_scoped_bearer_not_anonymous_or_owner_cookie(self):
        self.pair()
        member, _ = self.issue()
        for origin in ("chrome-extension://fake-extension", "moz-extension://fake-extension"):
            with self.subTest(origin=origin):
                response = self.action("gettaskprompt", {"task_id": self.task["id"]}, headers={"Origin": origin})
                self.assert_denied(response)
                self.assertNotIn("Access-Control-Allow-Origin", response[1])
                self.assert_denied(self.action("listagents", headers={**self.owner_headers, "Origin": origin}))
                accepted = self.action("gettaskprompt", {"task_id": self.task["id"]}, headers={**member, "Origin": origin})
                self.assert_ok(accepted)
                self.assertEqual(accepted[1].get("Access-Control-Allow-Origin"), origin)
        self.assert_denied(self.action("gettaskprompt", {"task_id": self.task["id"]}, headers={
            **member, "Origin": "http://localhost.evil.invalid",
        }))

    def test_malformed_json_and_action_types_are_bad_requests(self):
        self.pair()
        for raw in (b"{", b"", b"\xff", b"[]", b"null", b'"string"', b"42",
                    b'{"action": 1}', b'{"action":"listagents","payload":[]}',
                    b'{"action":"listagents","payload":null}'):
            with self.subTest(raw=raw):
                response = self.request("POST", "/api/action", raw=raw, headers=self.owner_headers)
                self.assertEqual(response[0], 400)
                self.assertIs(response[2].get("ok"), False)
        self.assert_ok(self.action("listagents", headers=self.owner_headers))

    def test_invalid_length_type_transfer_encoding_and_oversize(self):
        self.pair()
        for override in ({"Content-Length": "not-a-number"}, {"Content-Length": "-1"},
                         {"Content-Length": None}, {"Content-Type": "text/plain"},
                         {"Content-Type": None}, {"Transfer-Encoding": "chunked"}):
            with self.subTest(headers=override):
                response = self.request("POST", "/api/action", raw=b"{}", headers={**self.owner_headers, **override})
                self.assertEqual(response[0], 400)
        response = self.request("POST", "/api/action", raw=b"", headers={
            **self.owner_headers, "Content-Length": str(MAX_ACTION_BODY_BYTES + 1),
        })
        self.assertEqual(response[0], 413)  # Must reject without waiting for the advertised body.
        self.assertEqual(self.request("POST", "/api/action", raw=b"{", half_close=True, headers={
            **self.owner_headers, "Content-Length": "100",
        })[0], 400)
        self.assert_ok(self.action("listagents", headers=self.owner_headers))

    def test_loopback_binding_only(self):
        for host in ("0.0.0.0", "::", "192.0.2.1", "example.invalid", "127.0.0.1.evil.invalid"):
            with self.subTest(host=host), patch("ai_farm.office_server.ThreadingHTTPServer") as constructor:
                with self.assertRaises(ValueError):
                    create_server(host, 0, state_path=self.state_path)
                constructor.assert_not_called()
        local = create_server("localhost", 0, state_path=self.state_path)
        try:
            self.assertEqual(local.server_address[0], "127.0.0.1")
        finally:
            local.server_close()

    def test_member_task_scope_and_server_bound_sender(self):
        member, _ = self.issue()
        prompt = self.assert_ok(self.action("gettaskprompt", {"task_id": self.task["id"]}, headers=member))
        self.assertEqual(prompt["result"]["task_id"], self.task["id"])
        self.assertNotIn("snapshot", prompt)
        claimed = self.assert_ok(self.action("claimtask", {"task_id": self.task["id"]}, headers=member))
        self.assertEqual(claimed["result"]["assigned_to"], self.worker["id"])
        report = self.assert_ok(self.action("postmessage", {
            "task_id": self.task["id"], "text": "Conclusion: fake work complete",
        }, headers=member))
        self.assertEqual(report["result"]["sender_id"], self.worker["id"])
        self.assertNotIn("snapshot", report)
        for task_id in (None, self.unscoped["id"], self.other_task["id"], "missing-task"):
            for name in ("gettaskprompt", "claimtask", "postmessage"):
                with self.subTest(task_id=task_id, action=name):
                    self.assert_denied(self.action(name, {"task_id": task_id, "text": "Unauthorized"}, headers=member))

    def test_member_sender_spoof_and_interrupt_are_rejected(self):
        member, _ = self.issue()
        for field in ("sender_id", "from_id", "worker_id", "reviewer_id", "requested_by", "agent_id"):
            for impostor in ("owner", "chief", self.other["id"]):
                with self.subTest(field=field, impostor=impostor):
                    self.assert_denied(self.action("postmessage", {
                        "task_id": self.task["id"], "text": "spoofed", field: impostor,
                    }, headers=member))
        self.assert_denied(self.action("bussend", {
            "task_id": self.task["id"], "to_id": "owner", "text": "fake", "interrupt": True,
        }, headers=member))
        self.assertFalse(self.task["worker_reported"])

    def test_member_cannot_manage_owner_actions_or_credentials(self):
        member, _ = self.issue()
        for name in ("listagents", "listtasks", "getsettings", "toggleautoexecute", "createagent",
                     "createtask", "runadaptertask", "resolveapproval", "executecriticalop",
                     "reviewfinalresult", "reset_to_seed", "deleteagent", "listmessages"):
            with self.subTest(action=name):
                # Even a regression must not execute owner-only operations during this test.
                with patch.object(self.store, "dispatch_action", side_effect=AssertionError("Owner dispatch forbidden")) as dispatch:
                    self.assert_denied(self.action(name, {"task_id": self.task["id"]}, headers=member))
                    dispatch.assert_not_called()
        for path in ("/api/session", "/api/connections"):
            self.assert_denied(self.request("GET", path, headers=member))
        for path, data in (("/api/connections", {"agent_id": self.worker["id"], "role": "owner", "task_ids": [self.task["id"]]}),
                           ("/api/revoke", {"credential_id": "unknown"})):
            self.assert_denied(self.request("POST", path, data, headers=member))

    def test_member_snapshot_has_no_unrelated_tasks_or_private_metadata(self):
        member, _ = self.issue()
        # Controlled metadata sentinels do not configure any executable integration.
        with self.store._lock:
            self.worker["login_detail"] = "PRIVATE_AGENT_SENTINEL"
            self.task["final_delivery_text"] = "PRIVATE_TASK_REPORT_SENTINEL"
            self.store.state["settings"]["auth_test_private"] = "PRIVATE_SETTINGS_SENTINEL"
        state = self.assert_ok(self.request("GET", "/api/state", headers=member))
        self.assertEqual({t["id"] for t in state["tasks"]["tasks"]}, {self.task["id"]})
        self.assertEqual({a["id"] for a in state["agents"]["agents"]}, {self.worker["id"]})
        self.assertEqual(state["settings"], {})
        for key in ("group_messages", "bus_messages", "discussions", "courier_log", "pending_approvals", "savings_ledger"):
            self.assertNotIn(key, state)
        serialized = json.dumps(state)
        for secret in ("PRIVATE_AGENT_SENTINEL", "PRIVATE_TASK_REPORT_SENTINEL", "PRIVATE_SETTINGS_SENTINEL",
                       "OTHER_TASK_PRIVATE_SENTINEL", "FARM_AUTH_TEST_UNUSED_KEY", "https://unused.invalid/v1"):
            self.assertNotIn(secret, serialized)

    def test_member_bus_recipient_and_inbox_are_task_scoped(self):
        member, _ = self.issue()
        for task, recipient, text in ((self.task, self.worker, "allowed"),
                                      (self.unscoped, self.worker, "outside scope"),
                                      (self.task, self.other, "different recipient")):
            self.store.bussend({"from_id": "chief", "to_id": recipient["id"], "task_id": task["id"], "text": text})
        inbox = self.assert_ok(self.action("businbox", headers=member))["result"]
        self.assertEqual([m["text"] for m in inbox], ["allowed"])
        sent = self.assert_ok(self.action("sendconclusion", {
            "task_id": self.task["id"], "to_id": "owner", "conclusion": "Fake conclusion",
        }, headers=member))
        self.assertEqual(sent["result"]["bus"]["from_id"], self.worker["id"])
        self.assertNotIn("snapshot", sent)
        self.assert_denied(self.action("bussend", {
            "task_id": self.task["id"], "to_id": self.other["id"], "text": "unauthorized recipient",
        }, headers=member))

    def test_reviewer_can_review_but_cannot_impersonate_executor(self):
        task = self.make_task("Independent review", self.worker, task_kind="code_change", reviewer_id=self.other["id"])
        self.store.postmessage({"task_id": task["id"], "sender_id": self.worker["id"], "text": "Fake patch ready"})
        reviewer, _ = self.issue(self.other, [task["id"]])
        reviewed = self.assert_ok(self.action("submitcodereview", {
            "task_id": task["id"], "passed": False, "issues": ["Fake review finding"],
        }, headers=reviewer))
        self.assertNotIn("snapshot", reviewed)
        self.assert_denied(self.action("postmessage", {"task_id": task["id"], "text": "Executor spoof"}, headers=reviewer))
        worker, _ = self.issue(self.worker, [task["id"]])
        self.assert_denied(self.action("submitcodereview", {"task_id": task["id"], "passed": True}, headers=worker))

    def test_member_credential_invalidated_by_access_downgrade(self):
        member, _ = self.issue()
        self.assert_ok(self.request("GET", "/api/state", headers=member))
        with self.store._lock:
            self.worker["access_kind"] = "web"
        self.assert_denied(self.request("GET", "/api/state", headers=member))
        self.assert_denied(self.action("gettaskprompt", {"task_id": self.task["id"]}, headers=member))

    def test_web_worker_cannot_get_mcp_member_or_owner_credentials(self):
        self.pair()
        for role in ("member", "owner"):
            with self.subTest(role=role):
                response = self.request("POST", "/api/connections", {
                    "agent_id": self.web["id"], "task_ids": [self.web_task["id"]], "role": role,
                }, headers=self.owner_headers)
                self.assertIn(response[0], (400, 403))
                self.assertNotIn("token", response[2])
        self.assert_denied(self.request("POST", "/api/connections", {
            "agent_id": self.worker["id"], "task_ids": [self.other_task["id"]], "role": "member",
        }, headers=self.owner_headers))

    def test_revocation_stops_member_and_courier_immediately(self):
        for agent, task, role in ((self.worker, self.task, "member"), (self.web, self.web_task, "courier")):
            with self.subTest(role=role):
                headers, credential_id = self.issue(agent, [task["id"]], role)
                self.assert_ok(self.action("gettaskprompt", {"task_id": task["id"]}, headers=headers))
                self.assert_ok(self.request("POST", "/api/revoke", {"credential_id": credential_id}, headers=self.owner_headers))
                self.assert_denied(self.action("gettaskprompt", {"task_id": task["id"]}, headers=headers))
                self.assert_denied(self.request("GET", "/api/state", headers=headers))

    def reassign(self):
        self.store.reassigntask({"task_id": self.task["id"], "to_worker_id": self.other["id"]})

    def test_reassigned_task_rejects_old_member_actions(self):
        member, _ = self.issue()
        self.reassign()
        for name in ("gettaskprompt", "claimtask", "postmessage", "requestapproval"):
            with self.subTest(action=name):
                self.assert_denied(self.action(name, {"task_id": self.task["id"], "text": "stale"}, headers=member))

    def test_reassigned_task_is_removed_from_old_member_snapshot(self):
        member, _ = self.issue()
        self.reassign()
        response = self.request("GET", "/api/state", headers=member)
        if response[0] in (401, 403):
            self.assert_denied(response)
        else:
            state = self.assert_ok(response)
            self.assertNotIn(self.task["id"], {t["id"] for t in state["tasks"]["tasks"]})
            self.assertNotIn(self.other["id"], {a["id"] for a in state["agents"]["agents"]})

    def test_reassigned_task_is_removed_from_old_member_inbox(self):
        member, _ = self.issue()
        self.reassign()
        self.store.bussend({"from_id": "chief", "to_id": self.worker["id"], "task_id": self.task["id"], "text": "After reassignment"})
        response = self.action("businbox", headers=member)
        if response[0] in (401, 403):
            self.assert_denied(response)
        else:
            self.assertEqual(self.assert_ok(response)["result"], [])

    def test_courier_can_only_read_prompt_and_report_bound_task(self):
        courier, _ = self.issue(self.web, [self.web_task["id"]], "courier")
        courier["Origin"] = "chrome-extension://fake-courier"
        prompt = self.assert_ok(self.action("gettaskprompt", {"task_id": self.web_task["id"]}, headers=courier))
        self.assertEqual(prompt["result"]["task_id"], self.web_task["id"])
        self.assertNotIn("snapshot", prompt)
        status = self.assert_ok(self.action("courierstatus", {
            "task_id": self.web_task["id"], "status": "selector_failed", "detail": "Fake selector failure",
            "url": "https://unused.invalid/private-session",
        }, headers=courier))
        self.assertNotIn("snapshot", status)
        self.assertEqual(self.web["courier_health"]["task_id"], self.web_task["id"])
        self.assertEqual(self.web["courier_health"]["url"], "")
        report = self.assert_ok(self.action("postmessage", {
            "task_id": self.web_task["id"], "text": "Conclusion: fake courier report",
        }, headers=courier))
        self.assertEqual(report["result"]["sender_id"], self.web["id"])
        self.assertNotIn("snapshot", report)
        self.assertTrue(self.web_task["worker_reported"])
        self.assertFalse(self.other_task["worker_reported"])

    def test_courier_cannot_read_snapshot_owner_data_or_other_tasks(self):
        courier, _ = self.issue(self.web, [self.web_task["id"]], "courier")
        second_web_task = self.make_task("Unauthorized same-web task", self.web)
        for path in ("/api/state", "/api/session", "/api/connections"):
            self.assert_denied(self.request("GET", path, headers=courier))
        for task_id in (None, self.task["id"], second_web_task["id"]):
            for name in ("gettaskprompt", "courierstatus", "postmessage"):
                with self.subTest(task_id=task_id, action=name):
                    self.assert_denied(self.action(name, {
                        "task_id": task_id, "status": "ok", "text": "Unauthorized",
                    }, headers=courier))
        for name in ("listagents", "listtasks", "getsettings", "claimtask", "sendconclusion", "bussend", "businbox",
                     "submitcodereview", "requestapproval", "runadaptertask", "resolveapproval", "reviewfinalresult"):
            with self.subTest(action=name):
                with patch.object(self.store, "dispatch_action", side_effect=AssertionError("Courier dispatch forbidden")) as dispatch:
                    self.assert_denied(self.action(name, {"task_id": self.web_task["id"]}, headers=courier))
                    dispatch.assert_not_called()
        self.assert_denied(self.request("POST", "/api/connections", {
            "agent_id": self.web["id"], "role": "member", "task_ids": [self.web_task["id"]],
        }, headers=courier))
        self.assert_denied(self.request("POST", "/api/revoke", {"credential_id": "unknown"}, headers=courier))
        self.assert_denied(self.action("postmessage", {
            "task_id": self.web_task["id"], "sender_id": "owner", "text": "Spoofed",
        }, headers=courier))

    def test_courier_issuance_requires_one_assigned_web_task(self):
        self.pair()
        second = self.make_task("Second courier task", self.web)
        for agent, tasks in ((self.web, []), (self.web, [self.web_task["id"], second["id"]]),
                             (self.worker, [self.task["id"]]), (self.web, [self.other_task["id"]])):
            with self.subTest(agent=agent["id"], tasks=tasks):
                response = self.request("POST", "/api/connections", {
                    "agent_id": agent["id"], "task_ids": tasks, "role": "courier",
                }, headers=self.owner_headers)
                self.assertIn(response[0], (400, 403))
                self.assertNotIn("token", response[2])

    def test_courier_cannot_report_after_task_reassignment(self):
        courier, _ = self.issue(self.web, [self.web_task["id"]], "courier")
        self.store.reassigntask({"task_id": self.web_task["id"], "to_worker_id": self.other["id"]})
        for name in ("gettaskprompt", "courierstatus", "postmessage"):
            with self.subTest(action=name):
                self.assert_denied(self.action(name, {
                    "task_id": self.web_task["id"], "status": "ok", "text": "Stale courier report",
                }, headers=courier))

    def _open_sse(self, headers=None, timeout=2.5):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        conn.request("GET", "/api/events", headers=headers or {})
        resp = conn.getresponse()
        return conn, resp

    def _read_sse_event(self, resp):
        lines = []
        while True:
            raw = resp.fp.readline()
            if not raw:
                return None
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                if lines:
                    return "\n".join(lines)
                continue
            lines.append(line)

    def test_events_owner_only_and_single_event_without_leak(self):
        self.pair()
        member, _ = self.issue(self.worker, [self.task["id"]], "member")
        courier, _ = self.issue(self.web, [self.web_task["id"]], "courier")
        for hdrs in ({}, member, courier):
            conn, resp = self._open_sse(hdrs)
            try:
                self.assertIn(resp.status, (401, 403))
            finally:
                conn.close()

        conn, resp = self._open_sse(self.owner_headers)
        try:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.getheader("Content-Type", ""))
            first = self._read_sse_event(resp)
            self.assertIsNotNone(first)
            self.assertTrue(first.startswith("event: state\ndata: "), first)
            rev0 = int(first.split("data: ", 1)[1])

            secret_title = "SSE_SECRET_BODY_DO_NOT_LEAK"
            self.make_task(secret_title, self.worker)
            second = self._read_sse_event(resp)
            self.assertEqual(second, f"event: state\ndata: {rev0 + 1}")
            self.assertNotIn(secret_title, second)
            self.assertNotIn("token", second.lower())
        finally:
            conn.close()

    def test_events_wakes_immediately_on_owner_logout(self):
        self.pair()
        conn, resp = self._open_sse(self.owner_headers, timeout=2.0)
        try:
            self.assertEqual(resp.status, 200)
            self._read_sse_event(resp)
            started = time.monotonic()
            status, _, _ = self.request("POST", "/api/logout", {}, headers=self.owner_headers)
            self.assertEqual(status, 200)
            eof = self._read_sse_event(resp)
            self.assertIsNone(eof)
            self.assertLess(time.monotonic() - started, 2.0)
        finally:
            conn.close()

    def test_events_wakes_immediately_on_owner_revoke(self):
        self.pair()
        conn, resp = self._open_sse(self.owner_headers, timeout=2.0)
        try:
            self.assertEqual(resp.status, 200)
            self._read_sse_event(resp)
            conns = self.request("GET", "/api/connections", headers=self.owner_headers)[2]["connections"]
            owner_id = next(c["id"] for c in conns if c["current"])
            started = time.monotonic()
            status, _, _ = self.request("POST", "/api/revoke", {"credential_id": owner_id}, headers=self.owner_headers)
            self.assertEqual(status, 200)
            self.assertIsNone(self._read_sse_event(resp))
            self.assertLess(time.monotonic() - started, 2.0)
        finally:
            conn.close()

    def test_events_wakes_on_server_close_and_enforces_cap(self):
        self.pair()
        streams = []
        try:
            for _ in range(8):
                conn, resp = self._open_sse(self.owner_headers, timeout=2.0)
                self.assertEqual(resp.status, 200)
                self._read_sse_event(resp)
                streams.append((conn, resp))
            conn9, resp9 = self._open_sse(self.owner_headers, timeout=2.0)
            try:
                self.assertEqual(resp9.status, 429)
            finally:
                conn9.close()

            started = time.monotonic()
            self.server.shutdown()
            self.server.server_close()
            for _, resp in streams:
                self.assertIsNone(self._read_sse_event(resp))
            self.assertLess(time.monotonic() - started, 2.0)
        finally:
            for conn, _ in streams:
                conn.close()
        # Wait briefly for handler finally blocks to decrement event_clients.
        deadline = time.monotonic() + 2.0
        while self.server.event_clients > 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(self.server.event_clients, 0)

    def test_roundtable_seat_member_scoped_prompt_and_submit_only_own_seat(self):
        self.pair()
        seat_a = self.store.createagent({
            "name": "Seat A Mgr", "vendor": "VendorA", "model": "m-a",
            "access_kind": "api", "key_env": "UNUSED_A", "base_url": "https://unused.invalid/v1", "floor": "manager",
        })
        seat_b = self.store.createagent({
            "name": "Seat B Mgr", "vendor": "VendorB", "model": "m-b",
            "access_kind": "desktop", "floor": "manager",
        })
        seat_c = self.store.createagent({
            "name": "Seat C Mgr", "vendor": "VendorC", "model": "m-c",
            "access_kind": "api", "key_env": "UNUSED_C", "base_url": "https://unused.invalid/v1", "floor": "manager",
        })
        big = self.store.createbigtask({
            "title": "RT auth test", "goal": "RT auth test", "mode": "roundtable",
            "seat_a": seat_a["id"], "seat_b": seat_b["id"], "seat_c": seat_c["id"],
            "subtasks": [{"title": "Collect", "goal": "Collect", "assigned_to": self.worker["id"]}],
        })
        parent = big["parent"]
        child = big["subtasks"][0]
        self.store.postmessage({
            "task_id": child["id"], "sender_id": self.worker["id"], "is_delivery": True,
            "conclusion": "done", "changed_files": ["a.py"], "test_result": "ok",
        })

        # Non-seat worker cannot be issued for roundtable parent.
        resp_bad = self.request("POST", "/api/connections", {
            "agent_id": self.worker["id"], "task_ids": [parent["id"]], "role": "member",
        }, headers=self.owner_headers)
        self.assertEqual(resp_bad[0], 403)

        # Courier cannot be issued for roundtable parent.
        resp_cour = self.request("POST", "/api/connections", {
            "agent_id": self.web["id"], "task_ids": [parent["id"]], "role": "courier",
        }, headers=self.owner_headers)
        self.assertEqual(resp_cour[0], 403)

        # Seat A completes stage A so stage B is active; Seat B member fetches & submits ONLY stage B.
        req_a = self.store.getroundtableprompt({"task_id": parent["id"], "stage_key": "A", "request_id": "req-a"})
        self.store.submitroundtableresult({
            "task_id": parent["id"], "stage_key": "A", "request_id": req_a["request_id"], "provenance": "manual",
            "result": {"prompt": "do B", "constraints": ["keep small"], "acceptance": ["passes"]},
        })

        hdr_b, _ = self.issue(seat_b, [parent["id"]], "member")
        # Seat B cannot access Seat A or Seat C.
        self.assert_denied(self.action("getroundtableprompt", {"task_id": parent["id"], "stage_key": "A", "request_id": "x"}, headers=hdr_b))
        self.assert_denied(self.action("submitroundtableresult", {
            "task_id": parent["id"], "stage_key": "C", "request_id": "x", "result": {},
        }, headers=hdr_b))

        # Seat B can get and submit Seat B.
        prompt_b = self.assert_ok(self.action("getroundtableprompt", {
            "task_id": parent["id"], "stage_key": "B", "request_id": "req-b",
        }, headers=hdr_b))["result"]
        self.assertEqual(prompt_b["stage_key"], "B")
        sub_b = self.assert_ok(self.action("submitroundtableresult", {
            "task_id": parent["id"], "stage_key": "B", "request_id": "req-b",
            "result": {"draft": "Draft from B"},
        }, headers=hdr_b))["result"]
        self.assertEqual(sub_b["status"], "completed")
        self.assertEqual(parent["roundtable_state"]["stage"], "C")

    def test_auto_pair_issues_single_use_cookie_on_loopback_get_and_blocks_cross_site(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        srv = create_server("127.0.0.1", 0, state_path=Path(tmp.name) / "auto.json", auto_pair=True)
        self.addCleanup(srv.server_close)
        t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        t.start()
        self.addCleanup(t.join, 5)
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]

        # Cross-site GET / must NOT auto-pair.
        conn_evil = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn_evil.request("GET", "/", headers={"Host": f"127.0.0.1:{port}", "Sec-Fetch-Site": "cross-site"})
            r_evil = conn_evil.getresponse()
            r_evil.read()
            self.assertEqual(r_evil.status, 200)
            self.assertIsNone(r_evil.getheader("Set-Cookie"))
        finally:
            conn_evil.close()

        # First same-origin / direct GET / auto-pairs once and sets HttpOnly farm_session cookie.
        conn1 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn1.request("GET", "/", headers={"Host": f"127.0.0.1:{port}", "Sec-Fetch-Site": "none"})
            r1 = conn1.getresponse()
            r1.read()
            self.assertEqual(r1.status, 200)
            sc = r1.getheader("Set-Cookie") or ""
            self.assertIn("farm_session=", sc)
            self.assertIn("HttpOnly", sc)
        finally:
            conn1.close()

        # Second unauthenticated GET / must NOT receive another Set-Cookie (single-use pair_code consumed).
        conn2 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn2.request("GET", "/", headers={"Host": f"127.0.0.1:{port}", "Sec-Fetch-Site": "none"})
            r2 = conn2.getresponse()
            r2.read()
            self.assertEqual(r2.status, 200)
            self.assertIsNone(r2.getheader("Set-Cookie"))
        finally:
            conn2.close()


if __name__ == "__main__":
    unittest.main()
