"""Dry-run tests only — no network, no keys, no spend."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_farm.adapters.base import AgentReply, Quota
from ai_farm.adapters.cli_agent import CLIAdapter
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
    assert "codex-cli" in registered_slugs()
    assert "cli-generic" in registered_slugs()


def test_cli_adapter_missing_executable_triggers_fallback():
    cli = CLIAdapter(
        vendor="TestCLI",
        model_id="test-m",
        executable="nonexistent_cli_tool_xyz_999",
    )
    assert not cli.is_installed()
    try:
        cli.chat("hello")
        raise AssertionError("Missing CLI executable must raise so dispatcher falls back")
    except RuntimeError:
        pass
    q = cli.check_quota()
    assert "未安装" in q.note


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


def test_office_clean_starter_and_4_channels():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        # 1. Clean OSS starter: only 1 generic Chief slot (no hardcoded personal accounts)
        ag_res = store.listagents()
        assert len(ag_res["agents"]) == 1
        assert ag_res["agents"][0]["access_kind"] == "chief"

        # 2. Optional anonymous sample team loader works cleanly
        sample_res = store.loadsampleteam()
        assert sample_res["added_count"] == 4
        assert len(store.listagents()["agents"]) == 5

        # 3. API recruit validation: reject raw secret key, accept ENV VAR NAME
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
            "name": "My Free API Worker",
            "vendor": "VendorX",
            "model": "x-flash",
            "access_kind": "api",
            "paid": False,
            "key_env": "VENDOR_X_API_KEY",
            "base_url": "https://api.vendorx.example/v1",
        })
        assert new_api["badge"] == "免费·API"
        assert new_api["quota_percent"] is None

        # CLI & Desktop channels recruit cleanly
        new_cli = store.createagent({
            "name": "My CLI Tool",
            "vendor": "CLI-Vendor",
            "model": "cli-model",
            "access_kind": "cli",
            "executable": "my-cli",
        })
        assert new_cli["badge"] == "免费·CLI"

        new_desktop = store.createagent({
            "name": "My Desktop App",
            "vendor": "Desktop-Vendor",
            "model": "app-pool",
            "access_kind": "desktop",
            "sub_models": ["free-fast (0.00x)"],
        })
        assert new_desktop["badge"] == "免费·桌面端"

        # 4. Group chat task -> claim -> private report (no body leak in group!) -> cross-vendor transfer -> final delivery -> accept
        task = store.seedexampletask()
        store.claimtask({"task_id": task["id"], "worker_id": new_api["id"]})

        secret_report_body = "PRIVATE_WORKER_TABLE_ROW_999"
        store.postmessage({
            "task_id": task["id"],
            "sender_id": new_api["id"],
            "text": secret_report_body,
            "is_delivery": True,
        })
        group_texts = [m["text"] for m in store.listgroupmessages()]
        assert any("🔒" in t for t in group_texts), "Group chat must receive 🔒 lock notice"
        assert not any(secret_report_body in t for t in group_texts), "Report body must NOT appear in group chat"

        # Same-vendor reassignment must be blocked; different-vendor allowed
        try:
            store.reassigntask({"task_id": task["id"], "to_worker_id": new_api["id"]})
            raise AssertionError("Same-vendor reassignment must be blocked")
        except ValueError:
            pass

        store.reassigntask({"task_id": task["id"], "to_worker_id": new_cli["id"]})
        store.deliverfinalresult({"task_id": task["id"]})
        assert any("🏁" in m["text"] and "最终交付" in m["text"] for m in store.listgroupmessages())

        reviewed = store.reviewfinalresult({"task_id": task["id"], "decision": "verified"})
        assert reviewed["status"] == "accepted_done"

        # 5. Senior model skill judgment & apply
        judged = store.analyzeskillassignments({"judge_id": "chief"})
        assert len(judged["recommendations"]) >= 1
        applied = store.applyskillassignments({
            "judge": judged["judge"],
            "assignments": judged["recommendations"][:2],
        })
        assert applied["applied_count"] >= 1

        # 6. Custom workspace_dir export for desktop GUI agents + live guard on web/desktop
        custom_ws = Path(tmp) / "my_desktop_workspace"
        exported = store.exporttaskmd({"task_id": task["id"], "workspace_dir": str(custom_ws)})
        assert Path(exported["file_path"]).exists()
        assert exported["rel_path"] == f"tasks/inbox/{task['id']}.md"

        try:
            store.runadaptertask({"task_id": task["id"], "worker_id": new_desktop["id"], "live": True})
            raise AssertionError("Live adapter call on desktop GUI channel must guide user to @task.md button")
        except RuntimeError as e:
            assert "导出 .md" in str(e)


if __name__ == "__main__":
    for name in sorted(dir()):
        if name.startswith("test_"):
            globals()[name]()
            print(f"PASS: {name}")
