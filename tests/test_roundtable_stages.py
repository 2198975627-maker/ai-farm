"""Isolated stdlib tests: temporary state and fake adapters, never live credentials."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ai_farm.office_auth import AccessDenied, OfficeAccess
from ai_farm.office_store import OfficeStore
from ai_farm.roundtable import STAGES, validate_result


RESULTS = {
    "A": {"prompt": "Build the requested artifact", "constraints": ["No invented data"], "acceptance": ["Tests pass"]},
    "B": {"draft": "  Exact B artifact\n"},
    "C": {"issues": [{"severity": "P1", "detail": "Boundary case omitted"}], "refined": "  Exact C artifact\n"},
    "A-comparison": {"comments": ["C fixes the boundary"], "recommendation": "C"},
    "B-comparison": {"comments": ["Keep the B structure"], "recommendation": "B"},
}
REPORT = "【结论】Actual collected facts\n【改动文件】none\n【测试结果】3 checks passed"


class RoundtableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.json"
        self.store = OfficeStore(self.path)
        self.store._build_adapter = Mock(side_effect=AssertionError("No real model allowed"))
        self.store.collectgitdiff = Mock(return_value={"diff_stat": " src.py | 2 +-", "changed_files": ["src.py"], "summary": "stat"})
        for label in "ABC":
            self.agent(label, "manager", "api", True)
        for label, kind in (("worker", "api"), ("web", "web"), ("desktop", "desktop"), ("other", "cli")):
            self.agent(label, "worker", kind, False)

    def agent(self, label, floor, kind, paid):
        # Deliberately no provider URLs, env keys, sessions, executable config or personal state.
        agent = {"id": label, "name": label, "vendor": "vendor-" + label, "model": "model-" + label,
                 "floor": floor, "access_kind": kind, "paid": paid, "status": "ready", "badge": kind,
                 "tokens_used": 0, "session_count": 0, "skills": [], "quota_percent": None}
        self.store.state["agents"].append(agent)
        return agent

    def create(self, **overrides):
        payload = {"title": "Roundtable", "goal": "A high quality artifact", "mode": "roundtable",
                   "seat_a": "A", "seat_b": "B", "seat_c": "C",
                   "subtasks": [{"title": "Collect facts", "assigned_to": "worker", "task_kind": "small"}]}
        payload.update(overrides)
        result = self.store.createbigtask(payload)
        return result["parent"], result["subtasks"]

    def report(self, child, text=REPORT, **extra):
        return self.store.postmessage({"task_id": child["id"], "sender_id": child["assigned_to"],
                                       "text": text, "is_delivery": True, **extra})

    def ready(self, **kwargs):
        parent, children = self.create(**kwargs)
        for child in children:
            self.report(child)
            if child["requires_code_review"]:
                self.store.submitcodereview({"task_id": child["id"], "reviewer_id": "A", "passed": True})
        return parent, children

    def fake_models(self, callback=None):
        calls = []

        def build(agent, workspace_dir):
            def chat(prompt, **kwargs):
                self.assertFalse(self.store._lock._is_owned(), "adapter must run outside store lock")
                data = json.loads(prompt.split("\n")[-1])
                stage = data["stage_key"]
                disk = json.loads(self.path.read_text(encoding="utf-8"))
                task = next(t for t in disk["tasks"] if t["id"] == data.get("task_id", self.parent_id))
                attempt = next(a for a in task["roundtable_state"]["attempts"].values() if a["stage_key"] == stage)
                self.assertEqual(attempt["status"], "running", "reservation must be durable before invocation")
                calls.append((agent["id"], data, prompt))
                text = callback(stage) if callback else json.dumps(RESULTS[stage])
                return SimpleNamespace(text=text, usage={"total_tokens": 7}, model=agent["model"], rate_limit_remaining={})
            return SimpleNamespace(chat=chat)
        self.store._build_adapter = Mock(side_effect=build)
        return calls

    def run_all(self, parent):
        self.parent_id = parent["id"]
        calls = self.fake_models()
        receipts = []
        for index, stage in enumerate(STAGES):
            receipts.append(self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": f"req-{index}"}))
            self.assertEqual(receipts[-1]["stage_key"], stage)
        return calls, receipts

    def test_seats_validated_before_any_creation(self):
        cases = [{"seat_c": "worker"}, {"seat_c": "web"}, {"seat_c": "A"}, {"seat_c": "missing"}]
        for case in cases:
            before = copy.deepcopy(self.store.state)
            with self.assertRaises((ValueError, KeyError)):
                self.create(**case)
            self.assertEqual(before, self.store.state)
        c = self.store._find_agent("C")
        for field in ("vendor", "model"):
            saved = c[field]
            c[field] = self.store._find_agent("A")[field].upper()
            before = copy.deepcopy(self.store.state)
            with self.assertRaises(ValueError):
                self.create()
            self.assertEqual(before, self.store.state)
            c[field] = saved

    def test_mode_and_seats_are_in_creation_fingerprint(self):
        standard, _ = self.create(mode="standard")
        roundtable, _ = self.create()
        same, _ = self.create()
        swapped, _ = self.create(seat_a="B", seat_b="A")
        split, _ = self.create(mode="split")
        self.assertEqual(same["id"], roundtable["id"])
        self.assertEqual(len({standard["id"], roundtable["id"], swapped["id"], split["id"]}), 4)
        self.assertNotIn("roundtable_state", standard)
        self.assertEqual(roundtable["title"], "Roundtable")
        self.assertEqual(standard["title"], "\U0001f9e9 [大任务] Roundtable")
        self.assertEqual(split["title"], standard["title"])
        default = self.store.createbigtask({"title": "Default", "raw_steps": "Gather data"})["parent"]
        self.assertEqual(default["mode"], "standard")
        self.assertEqual(default["title"], "\U0001f9e9 [大任务] Default")

    def test_dry_run_is_read_only_five_stage_plan(self):
        parent, children = self.create()
        before = copy.deepcopy(self.store.state)
        on_disk = self.path.read_bytes()
        plan = self.store.runroundtablestep({"task_id": parent["id"], "live": False})
        self.store.runadaptertask({"task_id": children[0]["id"], "live": False})
        self.assertEqual(len(plan["plan"]), 5)
        self.assertEqual(plan["plan"][4]["stage_keys"], ["A-comparison", "B-comparison"])
        self.assertFalse(plan["reply_hint"])
        self.assertEqual(before, self.store.state)
        self.assertEqual(on_disk, self.path.read_bytes())
        self.store._build_adapter.assert_not_called()

    def test_requires_all_real_structured_reports(self):
        parent, children = self.create(subtasks=[{"title": "One", "assigned_to": "worker"}, {"title": "Two", "assigned_to": "web"}])
        first, second = children
        first.update(worker_reported=True, status="accepted_done", latest_report_summary="fake legacy summary")
        with self.assertRaises(ValueError):
            self.store.getroundtableprompt({"task_id": parent["id"]})
        with self.assertRaises(ValueError):
            self.report(first, usage={"dry_run": True})
        with self.assertRaises(ValueError):
            self.report(first, text="unstructured whole output")
        with self.assertRaises(ValueError):
            self.report(first, text="【结论】" + "x" * 8000 + "【改动文件】none【测试结果】pass")
        self.report(first)
        with self.assertRaises(ValueError):
            self.store.getroundtableprompt({"task_id": parent["id"]})
        self.report(second)
        self.store.postmessage({"task_id": first["id"], "text": "PRIVATE_HISTORY_SECRET", "is_delivery": False})
        prompt = self.store.getroundtableprompt({"task_id": parent["id"]})
        self.assertNotIn("PRIVATE_HISTORY_SECRET", prompt["prompt"])
        self.assertNotIn("fake legacy summary", prompt["prompt"])
        self.assertIn("Actual collected facts", prompt["prompt"])
        self.assertEqual(len(parent["roundtable_state"]["basket"]), 2)

    def test_code_children_need_independent_non_dry_review(self):
        parent, (child,) = self.create(subtasks=[{"title": "Code", "assigned_to": "worker", "task_kind": "code_change"}])
        self.report(child)
        with self.assertRaises(ValueError):
            self.store.submitcodereview({"task_id": child["id"], "reviewer_id": "worker", "passed": True})
        self.store.submitcodereview({"task_id": child["id"], "reviewer_id": "A", "passed": True, "dry_run": True})
        with self.assertRaises(ValueError):
            self.store.getroundtableprompt({"task_id": parent["id"]})
        self.store.submitcodereview({"task_id": child["id"], "reviewer_id": "A", "passed": True})
        self.run_all(parent)
        c_prompt = self.store._build_adapter.call_count
        self.assertEqual(c_prompt, 5)
        self.store.collectgitdiff.assert_called_once()

    def test_five_live_calls_separate_comparison_and_owner_choice(self):
        parent, children = self.ready()
        calls, receipts = self.run_all(parent)
        state = parent["roundtable_state"]
        self.assertEqual([c[0] for c in calls], ["A", "B", "C", "A", "B"])
        self.assertTrue(all(c[1]["reply_hint"] is False for c in calls))
        self.assertNotIn("ab_opinions", calls[-1][1])
        self.assertEqual(state["stage"], "awaiting_owner")
        self.assertEqual(parent["final_delivery_text"], "")
        self.assertEqual(state["calls_used"], 5)
        self.assertEqual(state["passes_used"], 2)
        self.assertEqual(state["max_passes"], 2)
        for index in range(5):
            replay = self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": f"req-{index}"})
            self.assertEqual(replay, receipts[index])
        self.assertEqual(len(calls), 5)
        with self.assertRaises(ValueError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "sixth"})
        result = self.store.chooseroundtable({"task_id": parent["id"], "decision": "C", "comment": "Ship this"})
        self.assertEqual(result["final_delivery_text"], RESULTS["C"]["refined"])
        self.assertEqual(result["status"], "accepted_done")
        self.assertEqual(len(state["attempts"]), 5)
        with self.assertRaises(ValueError):
            self.report(children[0])

    def test_select_b_preserves_exact_artifact(self):
        parent, _ = self.ready()
        self.run_all(parent)
        self.store.chooseroundtable({"task_id": parent["id"], "decision": "B"})
        self.assertEqual(parent["final_delivery_text"], RESULTS["B"]["draft"])

    def test_revise_is_terminal_no_budget_reset(self):
        parent, _ = self.ready()
        self.run_all(parent)
        self.store.chooseroundtable({"task_id": parent["id"], "decision": "revise", "comment": "New task required"})
        self.assertEqual(parent["status"], "rejected")
        self.assertEqual(parent["roundtable_state"]["calls_used"], 5)
        with self.assertRaises(ValueError):
            self.store.getroundtableprompt({"task_id": parent["id"]})
        with self.assertRaises(ValueError):
            self.store.chooseroundtable({"task_id": parent["id"], "decision": "C"})
        fresh, _ = self.create(force_new=True)
        self.assertNotEqual(fresh["id"], parent["id"])
        self.assertEqual(fresh["roundtable_state"]["calls_used"], 0)

    def test_manual_paid_web_and_desktop_seats_no_fake_adapter(self):
        self.store._find_agent("A")["access_kind"] = "subscription"
        self.store._find_agent("B")["access_kind"] = "desktop"
        parent, _ = self.ready()
        with self.assertRaises(ValueError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True})
        for stage in STAGES:
            pending = self.store.getroundtableprompt({"task_id": parent["id"]})
            self.assertEqual(pending, self.store.getroundtableprompt({"task_id": parent["id"]}))
            self.assertEqual(pending["stage_key"], stage)
            payload = {"task_id": parent["id"], "stage_key": stage, "request_id": pending["request_id"], "result": RESULTS[stage]}
            with self.assertRaises(ValueError):
                self.store.submitroundtableresult(payload)
            payload["provenance"] = "manual"
            done = self.store.submitroundtableresult(payload)
            self.assertEqual(done, self.store.submitroundtableresult(payload))
            self.assertEqual(done["provenance"], "manual")
        self.assertEqual(parent["roundtable_state"]["calls_used"], 0)
        self.assertEqual(parent["status"], "awaiting_owner")
        self.store._build_adapter.assert_not_called()

    def test_manual_requires_matching_pending_and_valid_json(self):
        parent, _ = self.ready()
        payload = {"task_id": parent["id"], "stage_key": "A", "request_id": "manual", "provenance": "manual", "result": RESULTS["A"]}
        with self.assertRaises(ValueError):
            self.store.submitroundtableresult(payload)
        self.store.getroundtableprompt({"task_id": parent["id"], "request_id": "manual"})
        for change in ({"stage_key": "B"}, {"request_id": "wrong"}, {"result": {"prompt": "missing fields"}}):
            with self.assertRaises(ValueError):
                self.store.submitroundtableresult({**payload, **change})
        self.assertEqual(parent["roundtable_state"]["stage"], "A")
        self.store.submitroundtableresult(payload)
        with self.assertRaises(ValueError):
            self.store.submitroundtableresult({**payload, "result": {**RESULTS["A"], "prompt": "Overwrite"}})
        with self.assertRaises(ValueError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "manual"})

    def test_invalid_model_output_is_terminal_no_advance_or_retry(self):
        parent, _ = self.ready()
        self.parent_id = parent["id"]
        calls = self.fake_models(lambda stage: '{"draft":"wrong stage"}')
        with self.assertRaises(ValueError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "bad"})
        state = parent["roundtable_state"]
        self.assertEqual(state["stage"], "A")
        self.assertIsNone(state["manager_a_prompt"])
        self.assertEqual(next(iter(state["attempts"].values()))["status"], "invalid")
        for request in ("bad", "new-id"):
            with self.assertRaises(ValueError):
                self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": request})
        with self.assertRaises(ValueError):
            self.store.getroundtableprompt({"task_id": parent["id"]})
        self.assertEqual(len(calls), 1)

    def test_shape_bounds_and_no_full_comparison_rewrite(self):
        for stage in STAGES:
            self.assertEqual(validate_result(stage, json.dumps(RESULTS[stage])), RESULTS[stage])
        invalid = [("A", {**RESULTS["A"], "prompt": "x" * 4001}),
                   ("B", {"draft": "x" * 16001}),
                   ("C", {**RESULTS["C"], "issues": [{"severity": "P2", "detail": "not allowed"}]}),
                   ("A-comparison", {"comments": ["x"] * 4, "recommendation": "C"}),
                   ("B-comparison", {"comments": ["x" * 241], "recommendation": "C"}),
                   ("B-comparison", {**RESULTS["B-comparison"], "draft": "full rewrite"}),
                   ("B-comparison", {"comments": [], "recommendation": "revise"})]
        for stage, value in invalid:
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                validate_result(stage, value)

    def test_unknown_after_invocation_no_fallback_and_restart_recovery(self):
        parent, _ = self.ready()
        chat = Mock(side_effect=TimeoutError("response lost"))
        self.store._build_adapter = Mock(return_value=SimpleNamespace(chat=chat))
        with self.assertRaises(RuntimeError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "lost"})
        attempt = next(iter(parent["roundtable_state"]["attempts"].values()))
        self.assertEqual(attempt["status"], "unknown")
        immutable_fp = attempt["fingerprint"]
        for request in ("lost", "fallback"):
            with self.assertRaises(ValueError):
                self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": request})
        chat.assert_called_once()
        attempt["status"] = "running"  # Simulate a process dying before writing its terminal receipt.
        self.store.save()
        recovered = OfficeStore(self.path)
        saved = next(iter(recovered._find_task(parent["id"])["roundtable_state"]["attempts"].values()))
        self.assertEqual(saved["status"], "unknown")
        self.assertEqual(saved["fingerprint"], immutable_fp)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["tasks"][0]["roundtable_state"]["calls_used"], 1)

    def test_concurrent_manager_invocation_reserves_once(self):
        parent, _ = self.ready()
        entered, finish = threading.Event(), threading.Event()
        failures = []

        def chat(prompt, **kwargs):
            entered.set()
            self.assertTrue(finish.wait(5))
            return SimpleNamespace(text=json.dumps(RESULTS["A"]), usage={})

        self.store._build_adapter = Mock(return_value=SimpleNamespace(chat=Mock(side_effect=chat)))
        def execute():
            try:
                self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "concurrent"})
            except Exception as exc:
                failures.append(exc)
        thread = threading.Thread(target=execute)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            for request in ("concurrent", "second"):
                with self.assertRaises(ValueError):
                    self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": request})
            with self.assertRaises(ValueError):
                self.store.getroundtableprompt({"task_id": parent["id"]})
        finally:
            finish.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures)
        self.store._build_adapter.assert_called_once()

    def test_child_single_dispatch_completed_receipt_replay(self):
        parent, (child,) = self.create()
        def chat(prompt):
            self.assertFalse(self.store._lock._is_owned())
            disk = json.loads(self.path.read_text(encoding="utf-8"))
            saved = next(t for t in disk["tasks"] if t["id"] == child["id"])["roundtable_dispatch"]
            self.assertEqual(saved["receipts"][saved["current"]]["status"], "running")
            with self.assertRaises(ValueError):
                self.store.runadaptertask({"task_id": child["id"], "live": True})
            self.assertFalse(self.store.gettaskprompt({"task_id": child["id"]})["dispatch_allowed"])
            return SimpleNamespace(text=REPORT, usage={}, model="worker", rate_limit_remaining={})
        self.store._build_adapter = Mock(return_value=SimpleNamespace(chat=chat))
        result = self.store.runadaptertask({"task_id": child["id"], "live": True})
        self.assertIn("Actual collected facts", result["reply"])
        replay = self.store.runadaptertask({"task_id": child["id"], "live": True, "idempotency_key": "changing-key"})
        self.assertEqual(result, replay)
        self.assertFalse(self.store.gettaskprompt({"task_id": child["id"]})["dispatch_allowed"])
        self.store._build_adapter.assert_called_once()
        self.store.getroundtableprompt({"task_id": parent["id"]})

    def test_child_unknown_no_retry_and_explicit_cross_vendor_handoff(self):
        parent, (child,) = self.create()
        self.store._build_adapter = Mock(return_value=SimpleNamespace(chat=Mock(side_effect=TimeoutError("lost"))))
        with self.assertRaises(RuntimeError):
            self.store.runadaptertask({"task_id": child["id"], "live": True})
        dispatch = child["roundtable_dispatch"]
        prior = copy.deepcopy(dispatch["receipts"])
        with self.assertRaises(ValueError):
            self.store.runadaptertask({"task_id": child["id"], "live": True, "worker_id": "other"})
        self.assertEqual(self.store.gettaskprompt({"task_id": child["id"]})["prompt"], "")
        with self.assertRaises(ValueError):
            self.report(child)
        for payload in ({}, {"confirmed_not_running": True, "to_worker_id": "worker"},
                        {"confirmed_not_running": True, "to_worker_id": "A"}):
            with self.assertRaises(ValueError):
                self.store.roundtablehandoff({"task_id": child["id"], "to_worker_id": "other", **payload})
        self.store.roundtablehandoff({"task_id": child["id"], "to_worker_id": "other", "confirmed_not_running": True})
        self.assertEqual(prior, dispatch["receipts"])
        self.assertEqual(dispatch["current"], "")
        with self.assertRaises(ValueError):
            self.store.postmessage({"task_id": child["id"], "sender_id": "worker", "text": REPORT})
        with self.assertRaises(ValueError):
            self.store.postmessage({"task_id": child["id"], "text": REPORT})
        self.report(child)
        self.assertEqual(len(dispatch["receipts"]), 2)
        self.assertEqual(len(dispatch["handoffs"]), 1)
        self.store.getroundtableprompt({"task_id": parent["id"]})
        self.store._build_adapter.assert_called_once()

    def test_web_child_pending_manual_single_feed_and_blocked_handoff(self):
        _, (child,) = self.create(subtasks=[{"title": "Web", "assigned_to": "web"}])
        first = self.store.gettaskprompt({"task_id": child["id"]})
        self.assertTrue(first["dispatch_allowed"])
        self.assertFalse(self.store.gettaskprompt({"task_id": child["id"], "mark_dispatched": True})["dispatch_allowed"])
        with self.assertRaises(ValueError):
            self.store.roundtablehandoff({"task_id": child["id"], "to_worker_id": "other", "confirmed_not_running": True})
        self.store.courierstatus({"task_id": child["id"], "agent_id": "web", "status": "captcha"})
        self.store.roundtablehandoff({"task_id": child["id"], "to_worker_id": "other", "confirmed_not_running": True})
        self.assertTrue(self.store.gettaskprompt({"task_id": child["id"]})["dispatch_allowed"])
        self.store._build_adapter.assert_not_called()

    def test_child_report_replay_is_immutable(self):
        _, (child,) = self.create()
        first = self.report(child)
        count = len(self.store.state["task_messages"][child["id"]])
        self.assertEqual(first, self.report(child))
        self.assertEqual(len(self.store.state["task_messages"][child["id"]]), count)
        with self.assertRaises(ValueError):
            self.report(child, REPORT.replace("Actual", "Changed"))

    def test_child_restart_running_becomes_unknown(self):
        _, (child,) = self.create()
        self.store.gettaskprompt({"task_id": child["id"]})
        dispatch = child["roundtable_dispatch"]
        dispatch["receipts"][dispatch["current"]]["status"] = "running"
        self.store.save()
        recovered = OfficeStore(self.path)
        response = recovered.gettaskprompt({"task_id": child["id"]})
        self.assertEqual(response["status"], "unknown")
        self.assertFalse(response["dispatch_allowed"])

    def test_legacy_bypass_guards_and_standard_unchanged(self):
        parent, (child,) = self.ready()
        actions = ["updatetaskstatus", "deliverfinalresult", "reviewfinalresult", "aggregatebigtask",
                   "autorun", "runroundtable", "runswarm", "runadaptertask", "gettaskprompt", "exporttaskmd", "claimtask"]
        for action in actions:
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.store.dispatch_action(action, {"task_id": parent["id"], "status": "accepted_done", "force": True, "live": True})
        for action in ("reassigntask", "runswarm", "runroundtable", "autorun", "exporttaskmd", "checkdesktopreceipt"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.store.dispatch_action(action, {"task_id": child["id"], "to_worker_id": "other", "live": True})
        with self.assertRaises(ValueError):
            self.store.chooseroundtable({"task_id": parent["id"], "decision": "C"})
        standard, _ = self.create(mode="standard")
        self.store.deliverfinalresult({"task_id": standard["id"], "final_text": "Legacy"})
        self.store.reviewfinalresult({"task_id": standard["id"], "decision": "accept"})
        self.assertEqual(standard["status"], "accepted_done")
        self.store._build_adapter.assert_not_called()

    def test_new_actions_explicit_allowlist_and_owner_only(self):
        parent, (child,) = self.create()
        access = OfficeAccess(self.store)
        owner = access.authenticate(access.pair_owner(access.pair_code)["token"])
        names = ("runroundtablestep", "getroundtableprompt", "submitroundtableresult", "chooseroundtable", "roundtablehandoff")
        for role in ("member", "courier"):
            agent_id = "worker" if role == "member" else "web"
            if role == "courier":
                _, (child,) = self.create(title="Web auth", subtasks=[{"title": "Web", "assigned_to": "web"}])
            credential = access.issue_member(owner, {"role": role, "agent_id": agent_id, "task_ids": [child["id"]]})
            principal = access.authenticate(credential["token"])
            for name in names:
                with self.subTest(role=role, name=name), self.assertRaises(AccessDenied):
                    access.action(principal, name, {"task_id": parent["id"]})
        for name in names:
            method = getattr(self.store, name)
            setattr(self.store, name, Mock(return_value={"registered": name}))
            self.assertEqual(access.action(owner, name, {}), {"registered": name})
            setattr(self.store, name, method)
        with self.assertRaises(ValueError):
            self.store.dispatch_action("_rt_complete", {})

    def test_reservation_save_failure_rolls_back_before_prompt_or_model(self):
        for manual in (True, False):
            with self.subTest(manual=manual):
                parent, _ = self.ready(force_new=True)
                before = copy.deepcopy(self.store.state)
                disk = self.path.read_bytes()
                real_save = self.store.save
                self.store.save = Mock(side_effect=OSError("disk full"))
                action = self.store.getroundtableprompt if manual else self.store.runroundtablestep
                payload = {"task_id": parent["id"], "live": True, "request_id": "disk"}
                for _ in range(2):
                    with self.assertRaises(OSError):
                        action(payload)
                    self.assertEqual(self.store.state, before)
                    self.assertEqual(self.path.read_bytes(), disk)
                self.assertEqual(self.store.save.call_count, 2)
                self.store._build_adapter.assert_not_called()
                self.store.save = real_save
                if manual:
                    result = action(payload)
                    self.assertEqual(result["status"], "pending_manual")
                    recovered = OfficeStore(self.path)
                    self.assertEqual(result, recovered.getroundtableprompt(payload))
                else:
                    self.parent_id = parent["id"]
                    self.fake_models()
                    self.assertEqual(action(payload)["status"], "completed")
                    self.store._build_adapter.assert_called_once()
                    self.store._build_adapter = Mock(side_effect=AssertionError("No real model allowed"))

    def test_completion_save_failure_cannot_advance_or_retry(self):
        parent, _ = self.ready()
        self.parent_id = parent["id"]
        calls = self.fake_models()
        real_save = self.store.save
        saves = []
        def save():
            saves.append(1)
            if len(saves) == 2:
                raise OSError("completion write failed")
            real_save()
        self.store.save = save
        with self.assertRaises(RuntimeError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "disk"})
        state = parent["roundtable_state"]
        self.assertEqual(state["stage"], "A")
        self.assertIsNone(state["manager_a_prompt"])
        self.assertEqual(next(iter(state["attempts"].values()))["status"], "unknown")
        with self.assertRaises(ValueError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "retry"})
        self.assertEqual(len(calls), 1)

    def test_sendconclusion_rejects_explicit_simulation_before_bus_or_report(self):
        parent, (child,) = self.create()
        payload = {"task_id": child["id"], "sender_id": "worker", "to_id": "A",
                   "conclusion": "Actual collected facts", "changed_files": [], "test_result": "checks passed"}
        before = copy.deepcopy(self.store.state)
        disk = self.path.read_bytes()
        real_save = self.store.save
        self.store.save = Mock(wraps=real_save)
        for extra in ({"dry_run": True}, {"usage": {"dry_run": True}},
                      {"dry_run": False, "usage": {"dry_run": True, "live": True}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.store.sendconclusion({**payload, **extra})
            self.assertEqual(self.store.state, before)
            self.assertEqual(self.path.read_bytes(), disk)
        self.store.save.assert_not_called()
        with self.assertRaises(ValueError):
            self.store.getroundtableprompt({"task_id": parent["id"]})
        result = self.store.sendconclusion({**payload, "dry_run": False, "usage": {"dry_run": False}})
        self.assertTrue(result["report"]["report_meta"]["live_eligible"])
        self.assertEqual(result["report"]["usage"], {"dry_run": False})
        self.store._build_adapter.assert_not_called()

    def test_child_reservation_save_failure_rolls_back_manual_and_automatic(self):
        for manual in (True, False):
            for handed_off in (False, True):
                with self.subTest(manual=manual, handed_off=handed_off):
                    _, (child,) = self.create(force_new=True)
                    if handed_off:
                        self.store.gettaskprompt({"task_id": child["id"]})
                        self.store.roundtablehandoff({"task_id": child["id"], "to_worker_id": "other",
                                                     "confirmed_not_running": True, "blocked": True})
                    before = copy.deepcopy(self.store.state)
                    disk = self.path.read_bytes()
                    real_save = self.store.save
                    self.store.save = Mock(side_effect=OSError("disk full"))
                    action = self.store.gettaskprompt if manual else self.store.runadaptertask
                    payload = {"task_id": child["id"], "live": True}
                    for _ in range(2):
                        with self.assertRaises(OSError):
                            action(payload)
                        self.assertEqual(self.store.state, before)
                        self.assertEqual(self.path.read_bytes(), disk)
                    self.assertEqual(self.store.save.call_count, 2)
                    self.store._build_adapter.assert_not_called()
                    self.store.save = real_save
                    if manual:
                        result = action(payload)
                        self.assertTrue(result["dispatch_allowed"])
                        self.assertTrue(result["prompt"])
                        self.assertFalse(action(payload)["dispatch_allowed"])
                    else:
                        chat = Mock(return_value=SimpleNamespace(text=REPORT, usage={}))
                        self.store._build_adapter = Mock(return_value=SimpleNamespace(chat=chat))
                        self.assertEqual(action(payload)["mode"], "live")
                        chat.assert_called_once()
                        self.store._build_adapter = Mock(side_effect=AssertionError("No real model allowed"))

    def test_manual_child_report_save_failure_never_replays_phantom_completion(self):
        for reserved in (False, True):
            with self.subTest(reserved=reserved):
                parent, (child,) = self.create(force_new=True)
                if reserved:
                    self.store.gettaskprompt({"task_id": child["id"]})
                real_save = self.store.save
                reserved_states = []

                def save():
                    current = self.store._find_task(child["id"])
                    dispatch = current["roundtable_dispatch"]
                    if dispatch["receipts"][dispatch["current"]]["status"] == "completed":
                        raise OSError("report write failed")
                    real_save()
                    reserved_states.append(copy.deepcopy(self.store.state))

                expected = copy.deepcopy(self.store.state) if reserved else None
                self.store.save = Mock(side_effect=save)
                for _ in range(2):
                    with self.assertRaises(OSError):
                        self.report(child)
                    expected = expected or reserved_states[0]
                    self.assertEqual(self.store.state, expected)
                    self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), expected)
                    with self.assertRaises(ValueError):
                        self.store.getroundtableprompt({"task_id": parent["id"]})
                    recovered = OfficeStore(self.path)
                    with self.assertRaises(ValueError):
                        recovered.getroundtableprompt({"task_id": parent["id"]})
                self.assertEqual(self.store.save.call_count, 2 if reserved else 3)
                self.store.save = real_save
                report = self.report(child)
                self.assertEqual(report, self.report(child))
                saved = OfficeStore(self.path)
                self.assertEqual(saved._rt_basket(saved._find_task(parent["id"]))[0]["report_id"], report["id"])
                self.store._build_adapter.assert_not_called()

    def test_automatic_child_report_save_failure_is_unknown_not_replayable(self):
        for fail_unknown in (False, True):
            with self.subTest(fail_unknown=fail_unknown):
                parent, (child,) = self.create(force_new=True)
                real_save = self.store.save
                chat = Mock(return_value=SimpleNamespace(text=REPORT, usage={}))
                self.store._build_adapter = Mock(return_value=SimpleNamespace(chat=chat))

                def save():
                    dispatch = self.store._find_task(child["id"])["roundtable_dispatch"]
                    status = dispatch["receipts"][dispatch["current"]]["status"]
                    if status == "completed" or (fail_unknown and status == "unknown"):
                        raise OSError("report write failed")
                    real_save()

                self.store.save = Mock(side_effect=save)
                payload = {"task_id": child["id"], "live": True}
                with self.assertRaises((RuntimeError, OSError)):
                    self.store.runadaptertask(payload)
                current = self.store._find_task(child["id"])
                dispatch = current["roundtable_dispatch"]
                receipt = dispatch["receipts"][dispatch["current"]]
                self.assertEqual(receipt["status"], "unknown")
                self.assertNotIn("message_id", receipt)
                self.assertNotIn("result", receipt)
                self.assertFalse(current.get("worker_reported"))
                self.assertFalse(any(m.get("report_meta") for m in self.store.state["task_messages"].get(child["id"], [])))
                with self.assertRaises(ValueError):
                    self.store.runadaptertask(payload)
                with self.assertRaises(ValueError):
                    self.store.getroundtableprompt({"task_id": parent["id"]})
                recovered = OfficeStore(self.path)
                with self.assertRaises(ValueError):
                    recovered.runadaptertask(payload)
                with self.assertRaises(ValueError):
                    recovered.getroundtableprompt({"task_id": parent["id"]})
                chat.assert_called_once()
                self.store.save = real_save

    def test_code_review_save_failure_rolls_back_all_outcomes(self):
        for outcome in ("approved", "changes_requested", "revision_limit"):
            with self.subTest(outcome=outcome):
                parent, (child,) = self.create(force_new=True, subtasks=[
                    {"title": "Code", "assigned_to": "worker", "task_kind": "code_change"}])
                self.report(child)
                if outcome == "revision_limit":
                    child["revision_round"] = self.store.state["settings"]["max_revision_rounds"]
                    self.store.save()
                payload = {"task_id": child["id"], "reviewer_id": "A", "passed": outcome == "approved",
                           "issues": [] if outcome == "approved" else ["src.py:1: Missing boundary check"]}
                before = copy.deepcopy(self.store.state)
                disk = self.path.read_bytes()
                with patch.object(self.store, "save", side_effect=OSError("review write failed")) as save:
                    for _ in range(2):
                        with self.assertRaises(OSError):
                            self.store.submitcodereview(payload)
                        self.assertEqual(self.store.state, before)
                        self.assertEqual(self.path.read_bytes(), disk)
                        current = self.store._find_task(child["id"])
                        self.assertEqual(current["review_status"], "pending_review")
                        self.assertNotIn("roundtable_review", current)
                    self.assertEqual(save.call_count, 2)
                for store in (self.store, OfficeStore(self.path)):
                    with self.assertRaises(ValueError):
                        store._rt_basket(store._find_task(parent["id"]))
                    with self.assertRaises(ValueError):
                        store.getroundtableprompt({"task_id": parent["id"]})
                self.assertEqual(self.store.state, before)
                self.assertEqual(self.path.read_bytes(), disk)
                reviewed = self.store.submitcodereview(payload)
                self.assertEqual(reviewed["review_status"], "approved" if outcome == "approved" else "changes_requested")
                self.assertEqual(reviewed["circuit_breaker"], "revision_limit" if outcome == "revision_limit" else "")
                self.assertEqual(OfficeStore(self.path)._find_task(child["id"]), reviewed)
                if outcome == "approved":
                    self.assertEqual(self.store.getroundtableprompt({"task_id": parent["id"]})["stage_key"], "A")
        self.store._build_adapter.assert_not_called()

    def test_handoff_save_failure_rolls_back_assignment_and_generation(self):
        for status in ("pending_manual", "unknown", "blocked"):
            with self.subTest(status=status):
                _, (child,) = self.create(force_new=True)
                self.store.gettaskprompt({"task_id": child["id"]})
                dispatch = child["roundtable_dispatch"]
                dispatch["receipts"][dispatch["current"]]["status"] = status
                self.store.save()
                payload = {"task_id": child["id"], "to_worker_id": "other",
                           "confirmed_not_running": True, "blocked": True}
                before = copy.deepcopy(self.store.state)
                disk = self.path.read_bytes()
                with patch.object(self.store, "save", side_effect=OSError("handoff write failed")) as save:
                    for _ in range(2):
                        with self.assertRaises(OSError):
                            self.store.roundtablehandoff(payload)
                        self.assertEqual(self.store.state, before)
                        self.assertEqual(self.path.read_bytes(), disk)
                        current = self.store._find_task(child["id"])
                        self.assertEqual(current["assigned_to"], "worker")
                        self.assertEqual(current["roundtable_dispatch"]["generation"], 0)
                        self.assertEqual(current["roundtable_dispatch"]["handoffs"], [])
                    self.assertEqual(save.call_count, 2)
                self.assertEqual(OfficeStore(self.path)._find_task(child["id"]), current)
                self.assertFalse(self.store.gettaskprompt({"task_id": child["id"]})["dispatch_allowed"])
                handed_off = self.store.roundtablehandoff(payload)
                self.assertEqual(handed_off["assigned_to"], "other")
                self.assertEqual(handed_off["roundtable_dispatch"]["generation"], 1)
                self.assertEqual(len(handed_off["roundtable_dispatch"]["handoffs"]), 1)
                self.assertEqual(OfficeStore(self.path)._find_task(child["id"]), handed_off)
        self.store._build_adapter.assert_not_called()

    def test_owner_choice_save_failure_rolls_back_every_decision(self):
        parent, _ = self.ready()
        self.run_all(parent)
        before = copy.deepcopy(self.store.state)
        disk = self.path.read_bytes()
        real_save = self.store.save
        self.store.save = Mock(side_effect=OSError("choice write failed"))
        for decision in ("B", "C", "revise"):
            for _ in range(2):
                with self.subTest(decision=decision), self.assertRaises(OSError):
                    self.store.chooseroundtable({"task_id": parent["id"], "decision": decision, "comment": "Choose"})
                self.assertEqual(self.store.state, before)
                self.assertEqual(self.path.read_bytes(), disk)
        self.assertEqual(self.store.save.call_count, 6)
        self.store.save = real_save
        chosen = self.store.chooseroundtable({"task_id": parent["id"], "decision": "C"})
        self.assertEqual(chosen["final_delivery_text"], RESULTS["C"]["refined"])
        self.assertEqual(OfficeStore(self.path)._find_task(parent["id"]), chosen)

    def test_automatic_errors_never_persist_credentials_or_absolute_paths(self):
        secret = "sk-private-credential C:/Users/fixture-user/private/provider.json"
        for target in ("manager", "child"):
            for phase in ("build", "chat", "completion"):
                with self.subTest(target=target, phase=phase):
                    parent, (child,) = self.ready(force_new=True) if target == "manager" else self.create(force_new=True)
                    error = OSError(secret)
                    text = json.dumps(RESULTS["A"]) if target == "manager" else REPORT
                    chat = Mock(side_effect=error) if phase == "chat" else Mock(return_value=SimpleNamespace(text=text, usage={}))
                    self.store._build_adapter = (Mock(side_effect=error) if phase == "build"
                                                 else Mock(return_value=SimpleNamespace(chat=chat)))
                    real_save = self.store.save
                    count = 0

                    def save():
                        nonlocal count
                        count += 1
                        if phase == "completion" and count == 2:
                            raise error
                        real_save()

                    self.store.save = Mock(side_effect=save)
                    task_id = parent["id"] if target == "manager" else child["id"]
                    action = self.store.runroundtablestep if target == "manager" else self.store.runadaptertask
                    with self.assertRaises(RuntimeError) as caught:
                        action({"task_id": task_id, "live": True, "request_id": "secret"})
                    self.assertIs(caught.exception.__cause__, error)
                    current = self.store._find_task(task_id)
                    attempts = (current["roundtable_state"]["attempts"] if target == "manager"
                                else current["roundtable_dispatch"]["receipts"])
                    receipt = next(iter(attempts.values()))
                    self.assertEqual(receipt["status"], "unknown")
                    self.assertTrue(receipt["error"])
                    for value in (json.dumps(self.store.state), self.path.read_text(encoding="utf-8"), str(caught.exception)):
                        self.assertNotIn("sk-private-credential", value)
                        self.assertNotIn("C:/Users/fixture-user/private", value)
                    self.store.save = real_save

    def test_invalid_reply_error_is_stored_as_safe_category(self):
        parent, _ = self.ready()
        error = ValueError("sk-private-credential C:/Users/fixture-user/private/provider.json")

        class InvalidReply:
            @property
            def text(self):
                raise error

        chat = Mock(return_value=InvalidReply())
        self.store._build_adapter = Mock(return_value=SimpleNamespace(chat=chat))
        real_save = self.store.save
        self.store.save = Mock(wraps=real_save)
        with self.assertRaises(ValueError) as caught:
            self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "invalid"})
        self.assertIs(caught.exception.__cause__, error)
        receipt = next(iter(parent["roundtable_state"]["attempts"].values()))
        self.assertEqual(receipt["status"], "invalid")
        self.assertTrue(receipt["error"])
        for value in (json.dumps(self.store.state), self.path.read_text(encoding="utf-8"), str(caught.exception)):
            self.assertNotIn("sk-private-credential", value)
            self.assertNotIn("C:/Users/fixture-user/private", value)
        with self.assertRaises(ValueError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "invalid"})
        self.assertEqual(self.store.save.call_count, 2)
        chat.assert_called_once()

    def test_state_snapshot_replacement_during_invocation(self):
        parent, _ = self.ready()
        self.parent_id = parent["id"]
        def reply(stage):
            self.store.state = copy.deepcopy(self.store.state)
            return json.dumps(RESULTS[stage])
        self.fake_models(reply)
        self.store.runroundtablestep({"task_id": parent["id"], "live": True, "request_id": "snapshot"})
        canonical = self.store._find_task(parent["id"])
        self.assertEqual(canonical["roundtable_state"]["stage"], "B")
        self.assertEqual(next(iter(canonical["roundtable_state"]["attempts"].values()))["status"], "completed")
        saved = OfficeStore(self.path)._find_task(parent["id"])
        self.assertEqual(saved["roundtable_state"], canonical["roundtable_state"])

    def test_manual_child_report_unblocks_dag_without_legacy_status(self):
        parent, children = self.create(subtasks=[{"title": "Web input", "assigned_to": "web"},
                                                {"title": "Compute", "assigned_to": "worker", "depends_on": [1]}])
        self.report(children[0])
        self.assertEqual(children[0]["status"], "working")
        chat = Mock(return_value=SimpleNamespace(text=REPORT, usage={}))
        self.store._build_adapter = Mock(return_value=SimpleNamespace(chat=chat))
        batch = self.store.runbigtasksubtasks({"task_id": parent["id"], "live": True})
        self.assertEqual(batch["executed_count"], 1)
        self.assertEqual(batch["results"][0]["task_id"], children[1]["id"])
        chat.assert_called_once()
        self.store.getroundtableprompt({"task_id": parent["id"]})

    def test_manual_pending_survives_restart_and_cannot_call_automatically(self):
        parent, _ = self.ready()
        prompt = self.store.getroundtableprompt({"task_id": parent["id"], "request_id": "pending"})
        self.store = OfficeStore(self.path)
        self.store._build_adapter = Mock(side_effect=AssertionError("No model allowed"))
        self.assertEqual(prompt, self.store.getroundtableprompt({"task_id": parent["id"]}))
        with self.assertRaises(ValueError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True})
        self.store.submitroundtableresult({"task_id": parent["id"], "stage_key": "A", "request_id": "pending",
                                           "provenance": "manual", "result": RESULTS["A"]})
        self.store._build_adapter.assert_not_called()

    def test_live_desktop_cannot_pretend_connected(self):
        self.store._find_agent("A")["access_kind"] = "desktop"
        parent, _ = self.ready()
        with self.assertRaises(ValueError):
            self.store.runroundtablestep({"task_id": parent["id"], "live": True})
        self.store._build_adapter.assert_not_called()
        self.assertEqual(parent["roundtable_state"]["attempts"], {})
        self.assertEqual(self.store.getroundtableprompt({"task_id": parent["id"]})["provenance"], "manual")

    def test_active_child_cannot_handoff_even_with_confirmation(self):
        _, (child,) = self.create()
        def chat(prompt):
            with self.assertRaises(ValueError):
                self.store.roundtablehandoff({"task_id": child["id"], "to_worker_id": "other", "confirmed_not_running": True})
            return SimpleNamespace(text=REPORT, usage={})
        self.store._build_adapter = Mock(return_value=SimpleNamespace(chat=chat))
        self.store.runadaptertask({"task_id": child["id"], "live": True})
        self.assertEqual(child["assigned_to"], "worker")
        self.assertEqual(child["roundtable_dispatch"]["handoffs"], [])

    def test_seat_identity_cannot_change_between_stages(self):
        parent, _ = self.ready()
        self.store._find_agent("A")["model"] = "different"
        with self.assertRaises(ValueError):
            self.store.getroundtableprompt({"task_id": parent["id"]})
        self.assertEqual(parent["roundtable_state"]["stage"], "collecting")


if __name__ == "__main__":
    unittest.main()
