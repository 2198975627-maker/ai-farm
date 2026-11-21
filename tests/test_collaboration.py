import concurrent.futures
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_farm.collaboration import CollaborationConflict, CollaborationDenied, CollaborationRuntime
from ai_farm.office_store import OfficeStore


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="farm-collaboration-test-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state.json"
        self.store = OfficeStore(state_path=self.path)
        self.store.state["agents"] = [
            {"id": "chief", "access_kind": "desktop"},
            {"id": "worker", "access_kind": "cli"},
            {"id": "outsider", "access_kind": "api"},
            {"id": "web", "access_kind": "web"},
        ]
        self.store.state["tasks"] = [{"id": "task"}]
        self.runtime = CollaborationRuntime(self.store)
        self.addCleanup(lambda: self.runtime.close())
        self.owner = self.runtime.owner_token
        self.chief = self.runtime.pair(self.owner, "chief", "chief-session")
        self.worker = self.runtime.pair(self.owner, "worker", "worker-session")
        self.room = self.runtime.create_room(self.owner, "task", ["chief", "worker"], "chief")["id"]

    def grant(self, request="grant-1"):
        return self.runtime.authorize(self.chief, self.room, "worker", "Check the isolated fixture", request)

    def finish(self, grant):
        self.assertTrue(self.runtime.claim(self.worker, grant["id"])["claimed"])
        return self.runtime.complete(self.worker, grant["id"], "Fixture checked", "fixture test passed", ["src/example.py"])

    def test_connection_tokens_never_persist(self):
        saved = self.path.read_text(encoding="utf-8")
        for token in (self.owner, self.worker, self.chief):
            self.assertNotIn(token, saved)
        self.assertNotIn("_bindings", saved)

    def test_owner_only_pairing_and_no_web_members(self):
        with self.assertRaises(CollaborationDenied):
            self.runtime.pair(self.worker, "outsider", "new-session")
        for member in ("web", "owner", "gao", "missing"):
            with self.assertRaises(CollaborationDenied):
                self.runtime.pair(self.owner, member, "new-session")
        with self.assertRaises(CollaborationConflict):
            self.runtime.pair(self.owner, "worker", "another-session")

    def test_unpaired_and_foreign_room_access_denied(self):
        outsider = self.runtime.pair(self.owner, "outsider", "outsider-session")
        for token in ("owner", "worker", "", outsider):
            with self.assertRaises(CollaborationDenied):
                self.runtime.snapshot(token, self.room)

    def test_members_cannot_create_rooms_or_impersonate(self):
        with self.assertRaises(CollaborationDenied):
            self.runtime.create_room(self.worker, "task", ["worker", "chief"], "worker")
        message = self.runtime.post(self.worker, self.room, "A peer suggestion", "msg-1")
        self.assertEqual(message["author"], "worker")
        self.assertEqual(self.runtime.wait(self.chief, self.room, 0)["grants"], [])
        with self.assertRaises(CollaborationDenied):
            self.runtime.authorize(self.worker, self.room, "chief", "Wake now", "forged-grant")

    def test_designated_supervisor_is_room_scoped(self):
        room = self.runtime.create_room(self.owner, "task", ["worker", "chief"])["id"]
        with self.assertRaises(CollaborationDenied):
            self.runtime.authorize(self.chief, room, "worker", "Do work", "not-supervisor")
        self.assertEqual(self.grant()["authorized_by"], "chief")

    def test_messages_deduplicate_and_conflicting_ids_fail(self):
        first = self.runtime.post(self.worker, self.room, "One result", "same")
        self.assertEqual(first, self.runtime.post(self.worker, self.room, "One result", "same"))
        with self.assertRaises(CollaborationConflict):
            self.runtime.post(self.worker, self.room, "Different result", "same")
        reply = self.runtime.post(self.chief, self.room, "Evidence requested", "reply", first["id"])
        self.assertEqual(reply["reply_to"], first["id"])
        with self.assertRaises(ValueError):
            self.runtime.post(self.chief, self.room, "Invalid reference", "bad-ref", "unknown")

    def test_ack_requires_offer_and_is_not_execution(self):
        message = self.runtime.post(self.chief, self.room, "Please inspect", "msg")
        with self.assertRaises(CollaborationDenied):
            self.runtime.acknowledge(self.worker, self.room, message["sequence"])
        inbox = self.runtime.inbox(self.worker, self.room)
        self.assertEqual(inbox["acknowledged_cursor"], 0)
        self.runtime.acknowledge(self.worker, self.room, inbox["offered_cursor"])
        self.assertEqual(self.runtime.inbox(self.worker, self.room)["messages"], [])
        self.assertEqual(self.runtime.snapshot(self.worker, self.room)["executions"], [])

    def test_event_wait_wakes_on_post(self):
        entered = threading.Event()
        original = self.runtime._condition.wait

        def observed_wait(timeout=None):
            entered.set()
            return original(timeout)

        with patch.object(self.runtime._condition, "wait", side_effect=observed_wait):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.runtime.wait, self.worker, self.room, 5)
                self.assertTrue(entered.wait(2))
                message = self.runtime.post(self.chief, self.room, "New evidence", "event")
                self.assertEqual(future.result(timeout=2)["messages"][0]["id"], message["id"])

    def test_event_wait_wakes_on_execution_grant(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.runtime.wait, self.worker, self.room, 5)
            grant = self.grant()
            self.assertEqual(future.result(timeout=2)["grants"][0]["id"], grant["id"])

    def test_atomic_claim_and_durable_record(self):
        grant = self.grant()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.runtime.claim(self.worker, grant["id"]), range(8)))
        self.assertEqual(sum(r["claimed"] for r in results), 1)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        record = saved["collaboration"]["grants"][grant["id"]]
        self.assertEqual(record["state"], "running")
        self.assertEqual(record["client_session"], "worker-session")

    def test_failed_persistence_does_not_claim(self):
        grant = self.grant()
        with patch.object(self.store, "save", side_effect=OSError("fixture disk failure")):
            with self.assertRaises(OSError):
                self.runtime.claim(self.worker, grant["id"])
        self.assertEqual(self.runtime.snapshot(self.owner, self.room)["executions"][0]["state"], "pending")
        self.assertTrue(self.runtime.claim(self.worker, grant["id"])["claimed"])

    def test_execution_dedup_does_not_reset_budget(self):
        first = self.grant()
        self.assertEqual(first, self.grant())
        with self.assertRaises(CollaborationConflict):
            self.runtime.authorize(self.chief, self.room, "worker", "Different work", "grant-1")
        self.assertEqual(len(self.runtime.snapshot(self.owner, self.room)["executions"]), 1)

    def test_unknown_blocks_other_grants_in_all_rooms(self):
        first = self.grant()
        self.runtime.claim(self.worker, first["id"])
        self.runtime.fail(self.worker, first["id"], "Transport disconnected")
        room = self.runtime.create_room(self.owner, "task", ["worker", "chief"])["id"]
        second = self.runtime.authorize(self.owner, room, "worker", "Other work", "new")
        self.assertFalse(self.runtime.claim(self.worker, second["id"])["claimed"])
        self.assertEqual(self.runtime.wait(self.worker, room, 0)["grants"], [])
        with self.assertRaises(CollaborationDenied):
            self.runtime.resolve_unknown(self.chief, first["id"], "Not owner")
        self.runtime.resolve_unknown(self.owner, first["id"], "Confirmed owned process has stopped")
        self.assertTrue(self.runtime.claim(self.worker, second["id"])["claimed"])

    def test_restart_preserves_unknown_and_cancels_pending(self):
        first = self.grant()
        self.runtime.claim(self.worker, first["id"])
        self.grant("pending")
        reopened = OfficeStore(state_path=self.path)
        recovered = CollaborationRuntime(reopened)
        try:
            with self.assertRaises(CollaborationDenied):
                recovered.snapshot(self.worker, self.room)
            states = {g["request_id"]: g["state"] for g in recovered.snapshot(recovered.owner_token, self.room)["executions"]}
            self.assertEqual(states, {"grant-1": "unknown", "pending": "cancelled"})
            self.assertEqual(recovered.wait(recovered.owner_token, self.room, 0)["grants"], [])
        finally:
            recovered.close()

    def test_revoke_cancels_queued_marks_running_unknown(self):
        grant = self.grant()
        self.runtime.claim(self.worker, grant["id"])
        self.grant("queued")
        self.runtime.revoke(self.owner, "worker")
        with self.assertRaises(CollaborationDenied):
            self.runtime.complete(self.worker, grant["id"], "Done", "Tests passed")
        rebound = self.runtime.pair(self.owner, "worker", "replacement-session")
        with self.assertRaises(CollaborationDenied):
            self.runtime.complete(rebound, grant["id"], "Done", "Tests passed")
        states = [g["state"] for g in self.runtime.snapshot(self.owner, self.room)["executions"]]
        self.assertEqual(states, ["unknown", "cancelled"])

    def test_expiry_and_ineligible_member_rejected(self):
        key = next(k for k, b in self.runtime._bindings.items() if b["agent_id"] == "worker")
        self.runtime._bindings[key]["expires"] = time.monotonic() - 1
        with self.assertRaises(CollaborationDenied):
            self.runtime.inbox(self.worker, self.room)
        self.store.state["agents"][0]["access_kind"] = "web"
        with self.assertRaises(CollaborationDenied):
            self.runtime.inbox(self.chief, self.room)

    def test_only_claiming_member_reports_and_late_result_is_explicit(self):
        grant = self.grant()
        with self.assertRaises(CollaborationDenied):
            self.runtime.claim(self.chief, grant["id"])
        self.runtime.claim(self.worker, grant["id"])
        with self.assertRaises(CollaborationDenied):
            self.runtime.complete(self.chief, grant["id"], "Done", "Tests passed")
        self.runtime.fail(self.worker, grant["id"], "Result timed out")
        result = self.runtime.complete(self.worker, grant["id"], "Confirmed done", "Actual result arrived")
        self.assertEqual(result["state"], "succeeded")
        self.assertIsNone(result["result"]["usage_tokens"])

    def test_results_deduplicate_and_require_relative_paths(self):
        grant = self.grant()
        self.runtime.claim(self.worker, grant["id"])
        for path in ("C:/private/file", "C:private", "/private/file", "../outside", "..\\outside", "\\\\host\\share"):
            with self.assertRaises(ValueError):
                self.runtime.complete(self.worker, grant["id"], "Done", "Tests passed", [path])
        result = self.runtime.complete(self.worker, grant["id"], "Done", "Tests passed", ["src/file.py"])
        self.assertEqual(result, self.runtime.complete(self.worker, grant["id"], "Done", "Tests passed", ["src/file.py"]))
        with self.assertRaises(CollaborationConflict):
            self.runtime.complete(self.worker, grant["id"], "Different result", "Tests passed")

    def test_self_review_and_unreviewed_acceptance_denied(self):
        grant = self.grant()
        self.finish(grant)
        with self.assertRaises(CollaborationDenied):
            self.runtime.review(self.worker, grant["id"], True, "Trust my own work")
        with self.assertRaises(CollaborationConflict):
            self.runtime.close_room(self.owner, self.room, True, "Accept")
        self.runtime.review(self.chief, grant["id"], True, "Independently checked output and test evidence")
        with self.assertRaises(CollaborationDenied):
            self.runtime.close_room(self.chief, self.room, True, "Accept")
        self.assertEqual(self.runtime.close_room(self.owner, self.room, True, "Owner accepted")["state"], "accepted")

    def test_rejected_work_requires_bounded_explicit_revision(self):
        grant = self.grant()
        self.finish(grant)
        self.runtime.review(self.chief, grant["id"], False, "One acceptance criterion is missing")
        with self.assertRaises(CollaborationConflict):
            self.runtime.review(self.chief, grant["id"], True, "Change old verdict")
        revision = self.runtime.authorize(self.chief, self.room, "worker", "Address the missing criterion", "revision", grant["id"])
        self.finish(revision)
        self.runtime.review(self.chief, revision["id"], True, "Criterion verified")
        self.assertEqual(self.runtime.close_room(self.owner, self.room, True, "Revision accepted")["state"], "accepted")

    def test_unknown_cannot_be_superseded_automatically(self):
        grant = self.grant()
        self.runtime.claim(self.worker, grant["id"])
        self.runtime.fail(self.worker, grant["id"], "Disconnected")
        with self.assertRaises(CollaborationConflict):
            self.runtime.authorize(self.chief, self.room, "worker", "Repeat", "retry", grant["id"])

    def test_budgets_and_deadlines_enforced(self):
        room = self.runtime.create_room(self.owner, "task", ["worker", "chief"], max_calls=1, max_messages=1)["id"]
        self.runtime.post(self.worker, room, "Message", "first")
        with self.assertRaises(CollaborationConflict):
            self.runtime.post(self.worker, room, "Another", "second")
        self.runtime.authorize(self.owner, room, "worker", "Task", "one")
        with self.assertRaises(CollaborationConflict):
            self.runtime.authorize(self.owner, room, "worker", "Task", "two")
        self.store.state["collaboration"]["rooms"][room]["deadline"] = time.time() - 1
        self.assertTrue(self.runtime.wait(self.worker, room, 0)["expired"])
        with self.assertRaises(CollaborationConflict):
            self.runtime.post(self.worker, room, "Late message", "late")

    def test_stop_never_claims_external_execution_was_cancelled(self):
        grant = self.grant()
        self.runtime.claim(self.worker, grant["id"])
        self.grant("queued")
        self.runtime.close_room(self.owner, self.room, False, "Owner stopped orchestration")
        self.assertEqual([g["state"] for g in self.runtime.snapshot(self.owner, self.room)["executions"]], ["unknown", "cancelled"])
        self.assertEqual(self.runtime.wait(self.worker, self.room, 0)["grants"], [])

    def test_close_wakes_waiters_and_revokes_credentials(self):
        entered = threading.Event()
        original = self.runtime._condition.wait

        def observed_wait(timeout=None):
            entered.set()
            return original(timeout)

        with patch.object(self.runtime._condition, "wait", side_effect=observed_wait):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.runtime.wait, self.worker, self.room, 5)
                self.assertTrue(entered.wait(2))
                self.runtime.close()
                with self.assertRaises(CollaborationDenied):
                    future.result(timeout=2)

    def test_single_coordinator_per_store_and_defensive_snapshots(self):
        with self.assertRaises(CollaborationConflict):
            CollaborationRuntime(self.store)
        snapshot = self.runtime.snapshot(self.worker, self.room)
        snapshot["room"]["supervisor_id"] = "worker"
        self.assertEqual(self.runtime.snapshot(self.worker, self.room)["room"]["supervisor_id"], "chief")

    def test_revocation_save_failure_restores_binding_and_execution(self):
        grant = self.grant()
        self.runtime.claim(self.worker, grant["id"])
        with patch.object(self.store, "save", side_effect=OSError("fixture disk failure")):
            with self.assertRaises(OSError):
                self.runtime.revoke(self.owner, "worker")
        snapshot = self.runtime.snapshot(self.worker, self.room)
        self.assertEqual(snapshot["executions"][0]["state"], "running")
        self.runtime.complete(self.worker, grant["id"], "Done", "Tests passed")

    def test_cancelled_unclaimed_grant_can_be_explicitly_replaced(self):
        grant = self.grant()
        self.runtime.revoke(self.owner, "worker")
        self.worker = self.runtime.pair(self.owner, "worker", "replacement")
        replacement = self.runtime.authorize(self.chief, self.room, "worker", "New attempt", "replacement", grant["id"])
        self.finish(replacement)
        self.runtime.review(self.chief, replacement["id"], True, "Verified replacement result")
        self.assertEqual(self.runtime.close_room(self.owner, self.room, True, "Accepted")["state"], "accepted")

    def test_dedup_returns_receipts_after_room_stops_and_target_disconnects(self):
        message = self.runtime.post(self.chief, self.room, "Message", "receipt")
        grant = self.grant()
        self.runtime.revoke(self.owner, "worker")
        self.assertEqual(self.grant()["id"], grant["id"])
        self.runtime.close_room(self.owner, self.room, False, "Stopped")
        self.assertEqual(self.runtime.post(self.chief, self.room, "Message", "receipt"), message)
        self.assertEqual(self.grant()["id"], grant["id"])
        with self.assertRaises(CollaborationConflict):
            self.runtime.post(self.chief, self.room, "New message", "new")

    def test_legacy_deletion_and_reset_cannot_invalidate_live_identities(self):
        with self.assertRaises(ValueError):
            self.store.deleteagent({"id": "worker"})
        with self.assertRaises(ValueError):
            self.store.reset_to_seed()
        with self.assertRaises(ValueError):
            self.store.deletetask({"id": "task"})
        self.assertEqual(self.runtime.snapshot(self.worker, self.room)["room"]["task_id"], "task")
        self.runtime.close()
        with self.assertRaises(ValueError):
            self.store.reset_to_seed()
        self.assertEqual(self.store.deleteagent({"id": "worker"}), {"deleted": "worker"})

    def test_dispatch_rejects_internal_methods_and_new_runtime(self):
        for action in ("save", "dispatch_action", "_load_or_seed", "_collaboration_runtime", "__init__", "_ensure_runtime_keys"):
            with self.assertRaises(ValueError):
                self.store.dispatch_action(action, {})
        self.assertEqual(self.store.dispatch_action("getsettings"), self.store.getsettings())


if __name__ == "__main__":
    unittest.main()
