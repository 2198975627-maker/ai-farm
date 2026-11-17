"""Dry-run tests only — no network, no keys, no spend."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_farm.adapters.base import AgentReply, Quota
from ai_farm.adapters.registry import get_adapter, register, registered_slugs
from ai_farm.dispatcher import Task, dispatch
from ai_farm.office_store import OfficeStore
from ai_farm.quota import quota_label, quota_state
from ai_farm.roster import Agent, Roster, load_roster
from ai_farm.skills import SKILLS, get_skill


class FakeAdapter:
    vendor = "Fake"
    model_id = "fake-1"
    access_kind = "api"

    def __init__(self, fail=False):
        self.fail = fail

    def chat(self, prompt, max_tokens=1000):
        if self.fail:
            raise RuntimeError("fake failure")
        return AgentReply(text="ok", model="fake-1")

    def check_quota(self):
        return Quota(kind="api", percent_remaining=50.0)


def test_one_icon_one_model():
    r = Roster([Agent(name="A", slug="a", role="worker", vendor="V",
                      model_id="m1", access_kind="api", key_env="K1"),
                Agent(name="B", slug="b", role="worker", vendor="V",
                      model_id="m1", access_kind="api", key_env="K1")])
    assert r.validate(), "duplicate vendor+model+access must be rejected"


def test_api_agent_needs_key_env_name_not_key():
    a = Agent(name="A", slug="a", role="worker", vendor="V",
              model_id="m1", access_kind="api")
    assert a.validate(), "API agent without key_env must be rejected"
    bad_key = Agent(name="A", slug="a", role="worker", vendor="V",
                    model_id="m1", access_kind="api", key_env="sk-real-secret-123")
    assert bad_key.validate(), "API agent with actual key instead of env var name must be rejected"


def test_quota_unknown_is_not_invented():
    assert quota_label(Quota(kind="unknown")) == "额度未填"
    assert quota_state(Quota(kind="subscription", percent_remaining=5.0)) == "downgraded"
    assert quota_state(Quota(kind="api", percent_remaining=0.0)) == "exhausted"


def test_dispatcher_falls_back_then_escalates():
    task = Task("t", "g", "in", "out", "acc")
    d = dispatch(task, [("w1", FakeAdapter(fail=True)), ("w2", FakeAdapter())],
                 [("m", FakeAdapter())], dry_run=False)
    assert d.worker_name == "w2" and d.text == "ok"
    d2 = dispatch(task, [("w1", FakeAdapter(fail=True)), ("w2", FakeAdapter(fail=True))],
                  [("m", FakeAdapter())], dry_run=False)
    assert d2.worker_name == "manager:m"


def test_dry_run_spends_nothing():
    task = Task("t", "g", "in", "out", "acc")
    d = dispatch(task, [("w1", FakeAdapter(fail=True))], [], dry_run=True)
    assert "DRY RUN" in d.text


def test_builtin_adapters_registered():
    assert "deepseek-flash" in registered_slugs()
    assert "kexaone" in registered_slugs()
    assert "deepseek-pro" in registered_slugs()
    assert "gemini-web" in registered_slugs()
    assert "dola-web" in registered_slugs()
    assert "qwen-intl-web" in registered_slugs()


def test_load_example_roster_and_12_seed_skills():
    example_yaml = Path(__file__).resolve().parents[1] / "examples" / "agents.example.yaml"
    roster = load_roster(str(example_yaml))
    assert len(roster.agents) >= 4
    assert len(SKILLS) == 12
    assert get_skill("batch-translate").name == "批量翻译"
    assert get_skill("doc-drafting-frame").name == "文档起草框架"


def test_recruit_new_vendor_in_under_30_lines():
    slug = "unit-test-vendor"
    if slug not in registered_slugs():
        register(slug, lambda: FakeAdapter())
    adapter = get_adapter(slug)
    assert adapter.chat("ping").text == "ok"


def test_office_26_actions_and_hard_rules():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        # 1. Verify 17 model icons + real quotas (Gemini 82%, GLM 0%, others None)
        ag_res = store.listagents()
        assert len(ag_res["agents"]) == 17
        gemini = next(a for a in ag_res["agents"] if a["id"] == "gemini-4-argon")
        glm = next(a for a in ag_res["agents"] if a["id"] == "glm-5-3-flash")
        kex = next(a for a in ag_res["agents"] if a["id"] == "k-exaone-2-5")
        assert gemini["quota_percent"] == 82.0
        assert glm["quota_percent"] == 0.0
        assert kex["quota_percent"] is None

        # 2. Two-path recruit validation: reject raw secret key, accept ENV VAR NAME
        try:
            store.createagent({
                "name": "Bad Key Agent",
                "vendor": "TestV",
                "model": "m1",
                "access_kind": "api",
                "key_env": "sk-123456secret",
            })
            raise AssertionError("Should have rejected raw API key")
        except ValueError:
            pass

        new_api = store.createagent({
            "name": "SiliconFlow Free",
            "vendor": "SiliconFlow",
            "model": "待核实具体版本",
            "access_kind": "api",
            "paid": False,
            "key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
        })
        assert new_api["badge"] == "免费·API"
        assert new_api["quota_percent"] is None

        # 3. Group chat task -> claim -> private report (no body leak in group!) -> cross-vendor transfer -> final delivery -> Gao accept
        task = store.seedexampletask()
        store.claimtask({"task_id": task["id"], "worker_id": "deepseek-v4-flash"})

        secret_report_body = "PRIVATE_WORKER_TABLE_ROW_999"
        store.postmessage({
            "task_id": task["id"],
            "sender_id": "deepseek-v4-flash",
            "text": secret_report_body,
            "is_delivery": True,
        })
        group_texts = [m["text"] for m in store.listgroupmessages()]
        assert any("🔒" in t for t in group_texts), "Group chat must receive 🔒 lock notice"
        assert not any(secret_report_body in t for t in group_texts), "Report body must NOT appear in group chat"

        # Same-vendor reassignment must be blocked; different-vendor allowed
        try:
            store.reassigntask({"task_id": task["id"], "to_worker_id": "deepseek-v4-flash"})
            raise AssertionError("Same-vendor reassignment must be blocked")
        except ValueError:
            pass

        store.reassigntask({"task_id": task["id"], "to_worker_id": "k-exaone-2-5"})
        store.deliverfinalresult({"task_id": task["id"]})
        assert any("🏁" in m["text"] and "给 Gao" in m["text"] for m in store.listgroupmessages())

        reviewed = store.reviewfinalresult({"task_id": task["id"], "decision": "verified"})
        assert reviewed["status"] == "accepted_done"

        # 4. Senior model skill judgment & apply
        judged = store.analyzeskillassignments({"judge_id": "muse"})
        assert judged["judge"] == "Muse（总管）"
        if judged["recommendations"]:
            applied = store.applyskillassignments({
                "judge": judged["judge"],
                "assignments": judged["recommendations"][:2],
            })
            assert applied["applied_count"] >= 1


if __name__ == "__main__":
    for name in sorted(dir()):
        if name.startswith("test_"):
            globals()[name]()
            print(f"PASS: {name}")
