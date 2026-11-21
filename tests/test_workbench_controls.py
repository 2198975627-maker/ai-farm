import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_farm.office_store import OfficeStore


class WorkbenchControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = OfficeStore(Path(self.temp.name) / "state.json")
        for name, floor, paid in (("first", "worker", False), ("next", "rest", False),
                                   ("A", "manager", True), ("B", "manager", True),
                                   ("C", "manager", True), ("D", "manager", True)):
            self.store.state["agents"].append({
                "id": name, "name": name, "vendor": "vendor-" + name,
                "model": "model-" + name, "floor": floor, "paid": paid,
                "status": "tired" if floor == "rest" else "ready",
                "access_kind": "api", "badge": "api", "skills": [],
                "tokens_used": 0, "session_count": 0, "quota_percent": None,
            })

    def task(self):
        return self.store.createtask({"title": "fixture task", "assigned_to": "first", "manager_id": "A"})

    def test_manager_move_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            self.store.moveagent({"id": "D", "floor": "worker"})
        self.assertEqual(self.store._find_agent("D")["floor"], "manager")
        self.store.moveagent({"id": "D", "floor": "worker", "confirm_manager": True})
        self.assertEqual(self.store._find_agent("D")["floor"], "worker")

    def test_active_member_cannot_be_moved_out_of_task(self):
        self.task()
        with self.assertRaises(ValueError):
            self.store.moveagent({"id": "first", "floor": "rest"})

    def test_idle_free_worker_can_replace_pending_worker(self):
        task = self.task()
        result = self.store.dispatch_action("replaceagent", {
            "task_id": task["id"], "from_id": "first", "to_id": "next"})
        self.assertEqual(result["assigned_to"], "next")
        self.assertEqual(self.store._find_agent("next")["status"], "ready")
        self.assertEqual(self.store._find_agent("next")["floor"], "worker")

    def test_manager_replacement_confirmation_and_save_rollback(self):
        task = self.task()
        payload = {"task_id": task["id"], "from_id": "A", "to_id": "D"}
        with self.assertRaises(ValueError):
            self.store.replaceagent(payload)
        before = copy.deepcopy(self.store.state)
        with patch.object(self.store, "save", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.store.replaceagent({**payload, "confirm_manager": True})
        self.assertEqual(self.store.state, before)
        result = self.store.replaceagent({**payload, "confirm_manager": True})
        self.assertEqual(result["manager_id"], "D")

    def test_same_vendor_and_reported_tasks_are_not_replaceable(self):
        task = self.task()
        payload = {"task_id": task["id"], "from_id": "first", "to_id": "next"}
        target = self.store._find_agent("next")
        target["vendor"] = "VENDOR-first"
        with self.assertRaises(ValueError):
            self.store.replaceagent(payload)
        target["vendor"] = "vendor-next"
        task["worker_reported"] = True
        with self.assertRaises(ValueError):
            self.store.replaceagent(payload)

    def test_pending_collaboration_grant_prevents_replacement(self):
        task = self.task()
        self.store.state["collaboration"] = {"grants": {"x": {"target": "first", "state": "pending"}}}
        with self.assertRaises(ValueError):
            self.store.replaceagent({"task_id": task["id"], "from_id": "first", "to_id": "next"})

    def test_standard_mode_never_runs_manager_discussion(self):
        parent = self.store.createbigtask({"title": "fixture standard", "mode": "standard",
            "subtasks": [{"title": "collect", "assigned_to": "first"}]})["parent"]
        with patch.object(self.store, "runbigtasksubtasks", return_value={"results": [], "executed_count": 0}), \
             patch.object(self.store, "runroundtable") as discussion, \
             patch.object(self.store, "aggregatebigtask", return_value={"status": "delivered"}):
            self.store.autorun({"task_id": parent["id"], "live": False, "discuss": True})
        discussion.assert_not_called()

    def test_standard_mode_rejects_paid_worker_before_task_creation(self):
        self.store._find_agent("first")["paid"] = True
        before = copy.deepcopy(self.store.state)
        with self.assertRaises(ValueError):
            self.store.createbigtask({"title": "fixture paid", "mode": "standard",
                "subtasks": [{"title": "collect", "assigned_to": "first"}]})
        self.assertEqual(self.store.state, before)

    def test_roundtable_seat_replacement_only_before_execution(self):
        parent = self.store.createbigtask({"title": "fixture roundtable", "mode": "roundtable",
            "seat_a": "A", "seat_b": "B", "seat_c": "C",
            "subtasks": [{"title": "collect", "assigned_to": "first"}]})["parent"]
        payload = {"task_id": parent["id"], "from_id": "A", "to_id": "D"}
        with self.assertRaises(ValueError):
            self.store.replaceagent(payload)
        updated = self.store.replaceagent({**payload, "confirm_manager": True})
        self.assertEqual(updated["roundtable_state"]["seats"]["A"]["id"], "D")
        parent["roundtable_state"]["stage"] = "B"
        with self.assertRaises(ValueError):
            self.store.replaceagent({"task_id": parent["id"], "from_id": "D", "to_id": "A", "confirm_manager": True})


if __name__ == "__main__":
    unittest.main()
