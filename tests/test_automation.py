"""Temporary fixtures and adapter doubles only; not real collaboration acceptance."""
import copy
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ai_farm.automation import AutomationMixin, AutomationRunner, _probe, recover_running
from ai_farm.office_store import OfficeStore


# Also works before the main integration adds the mixin to OfficeStore.
class Store(OfficeStore, AutomationMixin):
    pass


REPORT = "【结论】Collected facts\n【改动文件】none\n【测试结果】3 checks passed"
STAGES = {
    "A": {"prompt": "Build artifact", "constraints": ["No inventions"], "acceptance": ["Checks pass"]},
    "B": {"draft": "Complete draft"},
    "C": {"issues": [], "refined": "Refined draft"},
    "A-comparison": {"comments": ["C is clearer"], "recommendation": "C"},
    "B-comparison": {"comments": [], "recommendation": "B"},
}


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.json"
        self.store = Store(self.path)
        self.runner = self.store.automation_runner()
        self.notify_patch = patch.object(self.runner, "notify")
        self.notify = self.notify_patch.start()
        self.addCleanup(self.notify_patch.stop)
        self.addCleanup(self.store.closeautomation)
        for name, floor, channel, paid in [("worker", "worker", "api", False),
                                           ("other", "worker", "cli", False),
                                           ("web", "worker", "web", False),
                                           ("A", "manager", "api", True),
                                           ("B", "manager", "api", True),
                                           ("C", "manager", "api", True)]:
            self.store.state["agents"].append({"id": name, "name": name, "vendor": "vendor-" + name,
                                                "model": "model-" + name, "floor": floor,
                                                "access_kind": channel, "paid": paid, "status": "ready",
                                                "badge": channel, "tokens_used": 0, "session_count": 0,
                                                "skills": [], "quota_percent": None})
        self.calls = []
        self.callback = None
        self.store._build_adapter = Mock(side_effect=self.build)
        self.store.runroundtable = Mock(side_effect=AssertionError("no manager discussion"))
        self.store.reviewfinalresult = Mock(side_effect=AssertionError("no owner acceptance"))
        self.store.chooseroundtable = Mock(side_effect=AssertionError("no automatic choice"))

    def build(self, agent, workspace_dir):
        def chat(prompt, **kwargs):
            self.assertFalse(self.store._lock._is_owned())
            disk = json.loads(self.path.read_text(encoding="utf-8"))
            attempts = [a for t in disk["tasks"] for a in t.get("automation", {}).get("attempts", {}).values()]
            self.assertTrue(any(a["status"] == "running" and a["sent"] for a in attempts))
            self.calls.append((agent["id"], prompt))
            if self.callback:
                text = self.callback(agent, prompt)
            elif agent["floor"] == "manager":
                data = json.loads(prompt.split("\n")[-1])
                text = json.dumps(STAGES[data["stage_key"]])
            elif '"diff":' in prompt:
                text = '{"passed":true,"issues":[]}'
            else:
                text = REPORT
            return SimpleNamespace(text=text, usage={"total_tokens": 5})
        return SimpleNamespace(chat=chat)

    def create(self, mode="standard", specs=None):
        result = self.store.createbigtask({"title": "Automation fixture", "mode": mode,
                                          "seat_a": "A", "seat_b": "B", "seat_c": "C",
                                          "subtasks": specs or [{"title": "Collect", "assigned_to": "worker"}]})
        return result["parent"], result["subtasks"]

    def start(self, parent, **overrides):
        payload = {"task_id": parent["id"], "confirmed": True, "live": True,
                   "request_id": "start-1", "max_calls": 12, "workspace_dir": self.temp.name}
        payload.update(overrides)
        return self.store.startautomation(payload)

    def drain(self, parent):
        self.runner.run_until_blocked(parent["id"])
        return self.store.automationstatus({"task_id": parent["id"]})

    def manual_report(self, task, **overrides):
        payload = {"task_id": task["id"], "sender_id": task["assigned_to"], "text": REPORT, "is_delivery": True}
        payload.update(overrides)
        msg = self.store.postmessage(payload)
        self.store._automation_record_report(task, payload, msg)
        self.store.save()
        return msg

    def test_standard_delivers_without_discussion_or_acceptance(self):
        parent, children = self.create()
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual(status["status"], "awaiting_owner")
        self.assertEqual(status["calls_used"], 1)
        self.assertEqual(parent["status"], "delivered")
        self.assertTrue(children[0]["worker_reported"])
        self.store.runroundtable.assert_not_called()
        self.store.reviewfinalresult.assert_not_called()

    def test_roundtable_five_manager_calls_fixed_two_passes(self):
        parent, children = self.create("roundtable")
        self.manual_report(children[0])
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual(status["status"], "awaiting_owner")
        self.assertEqual(status["calls_used"], 5)
        self.assertEqual([a for a, _ in self.calls], ["A", "B", "C", "A", "B"])
        self.assertEqual(parent["roundtable_state"]["passes_used"], 2)
        self.assertEqual(parent["roundtable_state"]["calls_used"], 5)
        self.store.chooseroundtable.assert_not_called()

    def test_roundtable_worker_also_has_both_reservations(self):
        parent, children = self.create("roundtable")
        self.start(parent)
        self.assertEqual(self.drain(parent)["calls_used"], 6)
        dispatch = children[0]["roundtable_dispatch"]
        self.assertEqual(dispatch["receipts"][dispatch["current"]]["status"], "completed")

    def test_web_does_not_block_independent_child_and_report_resumes_dependency(self):
        parent, children = self.create(specs=[{"title": "Web", "assigned_to": "web"},
                                              {"title": "Dependent", "assigned_to": "worker", "depends_on": [1]},
                                              {"title": "Independent", "assigned_to": "other"}])
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "waiting_manual")
        self.assertEqual([a for a, _ in self.calls], ["other"])
        self.manual_report(children[0])
        self.assertEqual(self.drain(parent)["status"], "awaiting_owner")
        self.assertEqual([a for a, _ in self.calls], ["other", "worker"])
        self.assertIn("Collected facts", self.calls[-1][1])
        self.drain(parent)
        self.assertEqual(len(self.calls), 2)

    def test_budget_cannot_reset_or_increase(self):
        parent, _ = self.create(specs=[{"title": "One", "assigned_to": "worker"}, {"title": "Two", "assigned_to": "other"}])
        self.start(parent, max_calls=1)
        status = self.drain(parent)
        self.assertEqual((status["status"], status["reason"], status["calls_used"]), ("blocked", "budget_exhausted", 1))
        with self.assertRaises(ValueError):
            self.start(parent, request_id="increase", max_calls=2)
        self.start(parent, request_id="again", max_calls=1)
        self.drain(parent)
        self.assertEqual(len(self.calls), 1)

    def test_start_validation(self):
        parent, children = self.create()
        for overrides in ({"confirmed": False}, {"live": False}, {"max_calls": 0}, {"max_calls": 65},
                          {"max_calls": True}, {"request_id": ""}, {"task_id": children[0]["id"]}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.start(parent, **overrides)
        self.assertNotIn("automation", parent)
        self.notify.assert_not_called()

    def test_workspace_validation_before_authorization(self):
        parent, _ = self.create()
        with patch.object(self.store, "_validate_safe_workspace", side_effect=ValueError("unsafe")):
            with self.assertRaises(ValueError):
                self.start(parent)
        self.assertNotIn("automation", parent)

    def test_replay_and_conflicting_request_parameters(self):
        parent, _ = self.create()
        first = self.start(parent)
        self.assertEqual(self.start(parent), first)
        self.notify.assert_called_once()
        with self.assertRaises(ValueError):
            self.start(parent, max_calls=11)
        self.drain(parent)
        self.assertEqual(self.start(parent)["calls_used"], 1)
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_start_and_drains_do_not_duplicate_calls(self):
        parent, _ = self.create()
        barrier = threading.Barrier(5)
        errors = []
        def run():
            try:
                barrier.wait()
                self.start(parent)
                self.drain(parent)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(len(self.calls), 1)

    def test_identity_content_mode_and_reviewer_changes_pause(self):
        for change in ("identity", "content", "mode", "reviewer"):
            with self.subTest(change=change):
                parent, children = self.create(specs=[{"title": change, "assigned_to": "worker"}])
                self.start(parent, request_id=change)
                if change == "identity":
                    self.store._find_agent("worker")["model"] += "changed"
                elif change == "content":
                    children[0]["goal"] += "changed"
                elif change == "mode":
                    parent["mode"] = "split"
                else:
                    children[0]["reviewer_id"] = "other"
                self.assertEqual(self.drain(parent)["reason"], "authorization_changed")
        self.assertEqual(self.calls, [])

    def test_stop_during_request_rejects_late_result(self):
        parent, children = self.create()
        self.callback = lambda agent, prompt: (self.store.stopautomation({"task_id": parent["id"]}), REPORT)[1]
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual(status["status"], "stopped")
        self.assertEqual(next(iter(status["attempts"].values()))["status"], "unknown")
        self.assertFalse(self.store._find_task(children[0]["id"])["worker_reported"])
        with self.assertRaises(ValueError):
            self.start(parent, request_id="resume")

    def test_stop_during_roundtable_request_does_not_advance(self):
        parent, children = self.create("roundtable")
        self.manual_report(children[0])
        self.callback = lambda agent, prompt: (self.store.stopautomation({"task_id": parent["id"]}), json.dumps(STAGES["A"]))[1]
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "stopped")
        self.assertEqual(parent["roundtable_state"]["stage"], "A")
        self.assertIsNone(parent["roundtable_state"]["manager_a_prompt"])

    def test_exception_unknown_no_retry_or_vendor_fallback(self):
        parent, _ = self.create()
        def fail(agent, prompt):
            raise TimeoutError("possibly executed")
        self.callback = fail
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "unknown")
        self.drain(parent)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.start(parent)["status"], "unknown")

    def test_build_failure_blocked_without_external_call(self):
        parent, _ = self.create()
        self.store._build_adapter.side_effect = RuntimeError("missing adapter")
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(next(iter(status["attempts"].values()))["status"], "blocked")
        self.assertEqual(self.calls, [])

    def test_initial_save_failure_rolls_back_and_never_launches(self):
        parent, _ = self.create()
        before = copy.deepcopy(self.store.state)
        with patch.object(self.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.start(parent)
        self.assertEqual(self.store.state, before)
        self.notify.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_reservation_save_failure_rolls_back_without_call(self):
        parent, _ = self.create()
        self.start(parent)
        before = copy.deepcopy(self.store.state)
        with patch.object(self.store, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.drain(parent)
        self.assertEqual(self.store.state, before)
        self.assertEqual(self.calls, [])

    def test_result_save_failure_keeps_unknown_not_success(self):
        parent, children = self.create()
        real_save = self.store.save
        def fail_result():
            if self.store._find_task(children[0]["id"])["worker_reported"]:
                raise OSError("cannot persist result")
            real_save()
        self.start(parent)
        with patch.object(self.store, "save", side_effect=fail_result):
            self.assertEqual(self.drain(parent)["status"], "unknown")
        self.assertFalse(self.store._find_task(children[0]["id"])["worker_reported"])
        self.assertEqual(len(self.calls), 1)

    def test_restart_running_becomes_unknown(self):
        parent, _ = self.create()
        self.start(parent)
        self.assertTrue(recover_running(self.store.state))
        self.assertEqual(self.drain(parent)["status"], "unknown")
        self.assertFalse(recover_running(self.store.state))
        with self.assertRaises(ValueError):
            self.start(parent, request_id="restart")
        self.assertEqual(self.calls, [])

    def test_restart_waiting_needs_new_authorization_and_preserves_budget(self):
        parent, children = self.create(specs=[{"title": "Free", "assigned_to": "worker"},
                                              {"title": "Web", "assigned_to": "web"}])
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "waiting_manual")
        self.assertTrue(recover_running(self.store.state))
        self.manual_report(children[1])
        self.assertEqual(self.drain(parent)["status"], "stopped")
        self.assertEqual(self.start(parent)["status"], "stopped")
        self.start(parent, request_id="after-restart")
        self.assertEqual(self.drain(parent)["calls_used"], 1)
        self.assertEqual(len(self.calls), 1)

    def test_status_flags_alone_are_not_success(self):
        parent, children = self.create(specs=[{"title": "Manual", "assigned_to": "web"},
                                              {"title": "Dep", "assigned_to": "worker", "depends_on": [1]}])
        children[0].update(status="accepted_done", worker_reported=True)
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "waiting_manual")
        self.assertEqual(self.calls, [])

    def test_dry_report_rejected(self):
        parent, children = self.create()
        self.manual_report(children[0], dry_run=True)
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "blocked")
        self.assertEqual(self.calls, [])

    def test_adapter_dry_reply_rejected(self):
        parent, _ = self.create()
        self.callback = lambda a, p: REPORT.replace("Collected facts", "dry_run preview")
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "unknown")
        self.assertNotEqual(self.store._find_task(parent["id"])["status"], "delivered")

    def code_task(self):
        parent, children = self.create(specs=[{"title": "Code", "assigned_to": "worker", "task_kind": "code_change", "reviewer_id": "other"}])
        self.runner._read_diff = Mock(return_value="diff --git a/a.py b/a.py\n- x=1\n+ x=2")
        return parent, children[0]

    def test_strict_review_counts_budget_and_independent_free_worker(self):
        parent, child = self.code_task()
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual(status["status"], "awaiting_owner")
        self.assertEqual(status["calls_used"], 2)
        self.assertEqual([a for a, _ in self.calls], ["worker", "other"])
        self.assertTrue(child["automation_review"]["passed"])
        self.assertIn("diff --git", self.calls[-1][1])

    def test_review_plain_pass_is_not_json(self):
        parent, _ = self.code_task()
        self.callback = lambda agent, prompt: "PASS maybe not" if agent["id"] == "other" else REPORT
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "unknown")

    def test_review_rejection_blocks_without_repair_loop(self):
        parent, child = self.code_task()
        self.callback = lambda agent, prompt: '{"passed":false,"issues":["a.py:2 wrong"]}' if agent["id"] == "other" else REPORT
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual((status["status"], status["reason"]), ("blocked", "review_rejected"))
        self.assertEqual(child["review_status"], "changes_requested")
        self.assertEqual(len(self.calls), 2)

    def test_dry_review_does_not_release_dependency(self):
        parent, child = self.code_task()
        self.manual_report(child)
        payload = {"task_id": child["id"], "reviewer_id": "other", "passed": True, "dry_run": True}
        self.store.submitcodereview(payload)
        self.store._automation_record_review(child, payload, "other")
        self.start(parent)
        self.assertEqual(self.drain(parent)["reason"], "dry_review_rejected")
        self.assertEqual(self.calls, [])

    def test_paid_manager_cannot_be_collection_reviewer(self):
        parent, child = self.code_task()
        child["reviewer_id"] = "A"
        self.start(parent)
        self.assertEqual(self.drain(parent)["reason"], "collection_requires_free_worker")
        self.assertEqual([a for a, _ in self.calls], ["worker"])

    def test_manual_manager_wait_is_not_billed(self):
        self.store._find_agent("A")["access_kind"] = "web"
        parent, children = self.create("roundtable")
        self.manual_report(children[0])
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual((status["status"], status["calls_used"]), ("waiting_manual", 0))
        handoff = self.store.getroundtableprompt({"task_id": parent["id"], "workspace_dir": self.temp.name})
        self.store.submitroundtableresult({"task_id": parent["id"], "stage_key": "A", "request_id": handoff["request_id"],
                                          "provenance": "manual", "result": STAGES["A"]})
        self.assertEqual(self.drain(parent)["status"], "waiting_manual")  # A comparison is also manual.
        self.assertEqual([a for a, _ in self.calls], ["B", "C"])

    def test_managed_desktop_and_web_are_never_probed_as_automatic(self):
        for agent in ({"access_kind": "desktop"}, {"access_kind": "web"}, {"access_kind": "subscription"},
                      {"access_kind": "cli", "managedCodex": True}, {"access_kind": "cli", "adapter_slug": "codex-mcp"}):
            self.assertEqual(_probe(agent), "manual")

    def test_real_diff_reader_uses_patch_not_stat(self):
        workspace = Path(self.temp.name) / "repo"
        workspace.mkdir()
        subprocess.run(["git", "init", str(workspace)], capture_output=True, check=True)
        file = workspace / "a.py"
        file.write_text("x=1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=workspace, capture_output=True, check=True)
        diff = self.runner._read_diff(str(workspace))
        self.assertIn("+x=1", diff)
        (workspace / "untracked.py").write_text("x=2", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "tracked_diff"):
            self.runner._read_diff(str(workspace))

    def test_identity_change_in_flight_discards_reply(self):
        parent, children = self.create()
        def change(agent, prompt):
            self.store._find_agent("worker")["model"] = "replacement"
            return REPORT
        self.callback = change
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual(status["reason"], "authorization_changed")
        self.assertEqual(next(iter(status["attempts"].values()))["status"], "unknown")
        self.assertFalse(self.store._find_task(children[0]["id"])["worker_reported"])

    def test_stop_before_dispatch_consumes_no_budget(self):
        parent, _ = self.create()
        self.start(parent)
        self.store.stopautomation({"task_id": parent["id"]})
        self.assertEqual(self.drain(parent)["calls_used"], 0)
        self.assertEqual(self.calls, [])

    def test_restart_in_flight_receipt_is_unknown(self):
        parent, _ = self.create()
        self.start(parent)
        record = parent["automation"]
        record["attempts"]["interrupted"] = {"status": "running", "sent": True}
        record["calls_used"] = 1
        self.assertTrue(recover_running(self.store.state))
        self.assertEqual(record["attempts"]["interrupted"]["status"], "unknown")
        self.assertEqual(record["calls_used"], 1)
        self.drain(parent)
        self.assertEqual(self.calls, [])

    def test_roundtable_web_dependency_is_not_redispatched(self):
        parent, children = self.create("roundtable", specs=[{"title": "Web", "assigned_to": "web"},
                                                            {"title": "Dep", "assigned_to": "worker", "depends_on": [1]}])
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "waiting_manual")
        self.manual_report(children[0])
        self.assertEqual(self.drain(parent)["status"], "awaiting_owner")
        self.assertEqual([a for a, _ in self.calls], ["worker", "A", "B", "C", "A", "B"])
        self.assertIn("Collected facts", self.calls[0][1])

    def test_review_cannot_approve_a_newer_report(self):
        parent, child = self.code_task()
        def replace_report(agent, prompt):
            if agent["id"] == "other":
                self.manual_report(self.store._find_task(child["id"]), text=REPORT.replace("Collected facts", "Different code"))
                return '{"passed":true,"issues":[]}'
            return REPORT
        self.callback = replace_report
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual(status["status"], "unknown")
        self.assertEqual(status["reason"], "review_report_changed")
        self.assertNotEqual(self.store._find_task(child["id"])["review_status"], "approved")

    def test_chinese_dry_report_text_is_not_live_evidence(self):
        parent, children = self.create()
        self.manual_report(children[0], text=REPORT.replace("Collected facts", "干跑演练结果"))
        self.start(parent)
        self.assertEqual(self.drain(parent)["status"], "blocked")
        self.assertEqual(self.calls, [])

    def test_changed_diff_cannot_pass_review(self):
        parent, _ = self.code_task()
        self.runner._read_diff.side_effect = ["original patch", "different patch"]
        self.start(parent)
        status = self.drain(parent)
        self.assertEqual(status["status"], "unknown")
        self.assertEqual(status["reason"], "review_diff_changed_in_flight")

    def test_roundtable_budget_stops_before_extra_manager_call(self):
        parent, children = self.create("roundtable")
        self.manual_report(children[0])
        self.start(parent, max_calls=2)
        status = self.drain(parent)
        self.assertEqual(status["reason"], "budget_exhausted")
        self.assertEqual(parent["roundtable_state"]["stage"], "C")
        self.assertEqual([a for a, _ in self.calls], ["A", "B"])

    def test_event_queue_manual_parent_does_not_monopolize_thread(self):
        manual, _ = self.create(specs=[{"title": "Web only", "assigned_to": "web"}])
        automatic, _ = self.create(specs=[{"title": "Separate", "assigned_to": "worker"}])
        self.start(manual)
        self.start(automatic, request_id="separate-parent")
        done = threading.Event()
        visited = []
        real_drain = self.runner.run_until_blocked
        def drain(task_id):
            try:
                real_drain(task_id)
                visited.append(task_id)
            finally:
                if task_id == automatic["id"]:
                    done.set()
        with patch.object(self.runner, "run_until_blocked", side_effect=drain):
            AutomationRunner.notify(self.runner, manual["id"])
            AutomationRunner.notify(self.runner, automatic["id"])
            self.assertTrue(done.wait(5))
        self.assertEqual(visited, [manual["id"], automatic["id"]])
        self.assertEqual(self.store.automationstatus({"task_id": manual["id"]})["status"], "waiting_manual")
        self.assertEqual(self.store.automationstatus({"task_id": automatic["id"]})["status"], "awaiting_owner")
        self.runner.close()

    def test_event_runner_resumes_and_close_is_safe(self):
        parent, children = self.create(specs=[{"title": "Web", "assigned_to": "web"},
                                              {"title": "Dep", "assigned_to": "worker", "depends_on": [1]}])
        self.start(parent)
        self.drain(parent)
        self.manual_report(children[0])
        done = threading.Event()
        real_drain = self.runner.run_until_blocked
        def drain(task_id):
            try:
                real_drain(task_id)
            finally:
                done.set()
        with patch.object(self.runner, "run_until_blocked", side_effect=drain):
            AutomationRunner.notify(self.runner, children[0]["id"])
            self.assertTrue(done.wait(5))
        self.assertEqual(self.store.automationstatus({"task_id": parent["id"]})["status"], "awaiting_owner")
        self.assertIs(self.store.automation_runner(), self.runner)
        self.assertIs(AutomationRunner(self.store), self.runner)
        self.runner.close()
        self.assertFalse(self.runner._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
