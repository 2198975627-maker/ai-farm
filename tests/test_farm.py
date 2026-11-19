"""Dry-run tests only — no network, no keys, no spend."""
import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_farm.adapters.base import AgentReply, Quota
from ai_farm.adapters.cli_agent import CLIAdapter
from ai_farm.adapters.registry import get_adapter, register, registered_slugs
from ai_farm.cli import _append_agent_to_yaml, _build_adapter_for_agent, filter_live_executable_agents
from ai_farm.dispatcher import Task, dispatch
from ai_farm.office_server import create_server
from ai_farm.office_store import OfficeStore
from ai_farm.quota import quota_band, quota_label, quota_state
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

        # 7. Browser extension bridge action (gettaskprompt) & manifest check
        p_info = store.gettaskprompt({"task_id": task["id"], "mark_dispatched": True})
        assert p_info["task_id"] == task["id"]
        assert "不许自由发挥" in p_info["prompt"]
        p_latest = store.gettaskprompt({})
        assert p_latest["task_id"] == task["id"]
        ext_manifest = Path(__file__).resolve().parents[1] / "browser-extension" / "manifest.json"
        assert ext_manifest.exists()


def test_security_cors_and_workspace_guard():
    with tempfile.TemporaryDirectory() as tmp:
        srv = create_server("127.0.0.1", 0, state_path=Path(tmp) / "office.json")
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            # 1. Malicious external web origin must be blocked with 403
            evil_req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/action",
                data=json.dumps({"action": "listagents", "payload": {}}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "https://evil.example.com"},
                method="POST",
            )
            try:
                urllib.request.urlopen(evil_req, timeout=5)
                raise AssertionError("External origin must be rejected by CORS guard")
            except urllib.error.HTTPError as e:
                assert e.code == 403

            # 2. Chrome extension origin must be allowed
            ext_req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/action",
                data=json.dumps({"action": "listagents", "payload": {}}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "chrome-extension://abcdefghijklmnop"},
                method="POST",
            )
            with urllib.request.urlopen(ext_req, timeout=5) as resp:
                assert resp.status == 200
                assert resp.headers.get("Access-Control-Allow-Origin") == "chrome-extension://abcdefghijklmnop"
        finally:
            srv.shutdown()
            srv.server_close()

        # 3. System sensitive directory guard in exporttaskmd
        store = OfficeStore(state_path=Path(tmp) / "office2.json")
        task = store.seedexampletask()
        try:
            store.exporttaskmd({"task_id": task["id"], "workspace_dir": "C:\\Windows\\System32"})
            raise AssertionError("Should block writing into Windows system directory")
        except ValueError:
            pass


def test_office_live_fallback_chain_and_git_diff():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        w1 = store.createagent({
            "name": "Fail Worker 1", "vendor": "V1", "model": "m1",
            "access_kind": "cli", "executable": "missing_cli_1", "floor": "worker",
        })
        w2 = store.createagent({
            "name": "Fail Worker 2", "vendor": "V2", "model": "m2",
            "access_kind": "cli", "executable": "missing_cli_2", "floor": "worker",
        })
        mgr = store.createagent({
            "name": "Mock Manager", "vendor": "M1", "model": "mgr-m",
            "access_kind": "api", "paid": True, "key_env": "TEST_MGR_KEY",
            "base_url": "https://example.invalid/v1", "floor": "manager",
        })

        # Monkeypatch _build_adapter so mgr succeeds after 2 worker failures
        orig_build = store._build_adapter

        def patched_build(agent, workspace_dir="."):
            if agent["id"] == mgr["id"]:
                return FakeAdapter(fail=False)
            return orig_build(agent, workspace_dir=workspace_dir)

        store._build_adapter = patched_build  # type: ignore[method-assign]
        task = store.createtask({"title": "Fallback test", "assigned_to": w1["id"]})
        res = store.runadaptertask({"task_id": task["id"], "live": True})
        assert res["mode"] == "live"
        assert res["worker"] == mgr["name"]
        assert res["attempts"] == 3  # 2 worker failures -> escalated to manager

        # Verify collectgitdiff works on current repo
        repo_root = str(Path(__file__).resolve().parents[1])
        diff_res = store.collectgitdiff({"workspace_dir": repo_root})
        assert "summary" in diff_res


def test_cli_recruit_persists_yaml_and_skips_web_on_live():
    with tempfile.TemporaryDirectory() as tmp:
        yaml_path = Path(tmp) / "agents.yaml"
        ag_api = Agent(
            name="Custom Qwen", slug="custom-api", role="worker", vendor="Qwen",
            model_id="qwen-plus", access_kind="api", paid=True,
            key_env="MY_QWEN_KEY", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        ag_web = Agent(
            name="Web Chat", slug="custom-web", role="worker", vendor="WebV",
            model_id="web-m", access_kind="web", login_url="https://example.com/",
        )
        _append_agent_to_yaml(str(yaml_path), ag_api)
        _append_agent_to_yaml(str(yaml_path), ag_web)

        loaded = load_roster(str(yaml_path))
        assert len(loaded.agents) == 2
        adapter = _build_adapter_for_agent(loaded.agents[0])
        assert adapter.model_id == "qwen-plus"
        assert adapter.key_env == "MY_QWEN_KEY"

        live_w, skipped_w = filter_live_executable_agents(loaded.workers())
        assert [a.name for a in live_w] == ["Custom Qwen"]
        assert [a.name for a in skipped_w] == ["Web Chat"]


def test_agent_hud_4_features_and_red_lines_dry_run():
    assert quota_band(None) == "unknown"
    assert quota_band(80.0) == "green"
    assert quota_band(25.0) == "yellow"
    assert quota_band(10.0) == "red"
    assert quota_state(Quota(kind="api", percent_remaining=20.0)) == "warn"

    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "hud_office.json")
        assert store.getsettings()["auto_execute_low_risk"] is False

        coder = store.createagent({
            "name": "API Coder", "vendor": "V-Coder", "model": "coder-lite",
            "access_kind": "api", "paid": False, "key_env": "TEST_CODER_KEY",
            "base_url": "https://coder.invalid/v1", "floor": "worker",
        })
        reviewer = store.createagent({
            "name": "CLI Reviewer", "vendor": "V-Rev", "model": "rev-m",
            "access_kind": "cli", "paid": False, "executable": "codex", "floor": "worker",
        })
        web_worker = store.createagent({
            "name": "Free Web Chat", "vendor": "KimiWeb", "model": "web-free",
            "access_kind": "web", "login_url": "https://kimi.moonshot.cn/", "floor": "worker",
        })

        # 1. Small task skips code review to save tokens; conclusion-only blocks chat dumps
        small_task = store.createtask({"title": "Small batch translate", "assigned_to": coder["id"], "task_kind": "small"})
        assert small_task["requires_code_review"] is False
        try:
            store.postmessage({
                "task_id": small_task["id"],
                "sender_id": coder["id"],
                "text": "User: hi\nAssistant: ok\nUser: step 2\nAssistant: full chat dump",
                "is_delivery": True,
            })
            raise AssertionError("Multi-turn chat dump must be rejected by Conclusion-Only guard")
        except ValueError:
            pass
        dry_res = store.runadaptertask({"task_id": small_task["id"], "live": False})
        assert dry_res["mode"] == "dry_run" and "【结论】" in dry_res["text"]

        # 2. Code change task enforces Write -> Review -> Revise with separate agents
        try:
            store.createtask({
                "title": "Fix bug same reviewer", "assigned_to": coder["id"],
                "task_kind": "code_change", "reviewer_id": coder["id"],
            })
            raise AssertionError("Reviewer cannot be the same agent as coder")
        except ValueError:
            pass

        code_task = store.createtask({
            "title": "Fix login bug", "assigned_to": coder["id"],
            "task_kind": "code_change", "reviewer_id": reviewer["id"],
        })
        assert code_task["requires_code_review"] is True
        store.postmessage({
            "task_id": code_task["id"],
            "sender_id": coder["id"],
            "conclusion": "已修复空密码登录越界校验",
            "changed_files": ["auth.py"],
            "test_result": "dry-run 3/3 PASS",
            "is_delivery": True,
        })
        # Delivery blocked before independent review passes
        try:
            store.deliverfinalresult({"task_id": code_task["id"]})
            raise AssertionError("Cannot deliver code_change task before code review approval")
        except ValueError:
            pass

        # Reject once -> revision_round = 1 -> revise -> approve -> deliver -> accept
        rejected = store.submitcodereview({
            "task_id": code_task["id"],
            "reviewer_id": reviewer["id"],
            "passed": False,
            "issues": ["auth.py:42 缺少空字符串 strip() 检查"],
        })
        assert rejected["status"] == "rejected" and rejected["revision_round"] == 1
        approved = store.submitcodereview({
            "task_id": code_task["id"],
            "reviewer_id": reviewer["id"],
            "passed": True,
            "dry_run": True,
        })
        assert approved["review_status"] == "approved"
        store.deliverfinalresult({"task_id": code_task["id"]})
        done = store.reviewfinalresult({"task_id": code_task["id"], "decision": "verified"})
        assert done["status"] == "accepted_done"

        # 3. HUD flights recorded across workflow
        flights = store.listhudflights()
        assert any(f["kind"] == "review_reject" for f in flights)
        assert any(f["kind"] == "review_pass" for f in flights)

        # 4. Human authorization switch & critical op gating
        low_req = store.requestapproval({"op_type": "low_risk_run", "target": "demo", "requested_by": "chief"})
        assert low_req["status"] == "pending"  # default OFF
        store.toggleautoexecute({"enabled": True})
        low_auto = store.requestapproval({"op_type": "low_risk_run", "target": "demo", "requested_by": "chief"})
        assert low_auto["status"] == "auto_approved"

        # Critical ops ALWAYS require human allow_once even when low-risk auto-execute is ON
        blocked_merge = store.executecriticalop({"op_type": "merge", "target": "main", "task_id": code_task["id"], "dry_run": True})
        assert blocked_merge["executed"] is False and blocked_merge["requires_approval"] is True
        apr_id = blocked_merge["approval"]["id"]
        try:
            store.resolveapproval({"approval_id": apr_id, "decision": "always_allow"})
            raise AssertionError("Critical ops must forbid always_allow")
        except ValueError:
            pass
        store.resolveapproval({"approval_id": apr_id, "decision": "allow_once"})
        exec_ok = store.executecriticalop({"op_type": "merge", "target": "main", "task_id": code_task["id"], "dry_run": True})
        assert exec_ok["executed"] is True and exec_ok["dry_run"] is True
        # Consumed single-use approval -> second run asks again
        re_asked = store.executecriticalop({"op_type": "merge", "target": "main", "task_id": code_task["id"], "dry_run": True})
        assert re_asked["executed"] is False and re_asked["requires_approval"] is True


if __name__ == "__main__":
    for name in sorted(dir()):
        if name.startswith("test_"):
            globals()[name]()
            print(f"PASS: {name}")
