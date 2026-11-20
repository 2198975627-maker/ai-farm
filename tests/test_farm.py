"""Dry-run tests only — no network, no keys, no spend."""
import json
import subprocess
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
from ai_farm.mcp_relay import CoreBackend, FarmMCPRelay, MCP_ELIGIBLE_ACCESS, TOOLS
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


def test_big_task_split_batch_review_and_aggregate_dry_run():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "big_task_office.json")
        w1 = store.createagent({
            "name": "Worker Alpha", "vendor": "VendorA", "model": "m-a",
            "access_kind": "api", "paid": False, "key_env": "TEST_A_KEY",
            "base_url": "https://a.invalid/v1", "floor": "worker",
        })
        w2 = store.createagent({
            "name": "Worker Beta", "vendor": "VendorB", "model": "m-b",
            "access_kind": "cli", "paid": False, "executable": "codex", "floor": "worker",
        })
        w3 = store.createagent({
            "name": "Worker Gamma", "vendor": "VendorC", "model": "m-c",
            "access_kind": "web", "login_url": "https://example.com/", "floor": "worker",
        })

        # 1. Split one big task into 3 subtasks across distinct vendors (2 small + 1 code_change)
        created = store.createbigtask({
            "title": "重构登录校验并补齐文档",
            "goal": "先出验收清单，再修复空密码校验，最后汇总变更说明",
            "raw_steps": "1. 梳理登录接口验收清单\n2. [代码] 修复空密码校验并补 3 个单元测试\n3. 输出三档发布摘要",
        })
        parent = created["parent"]
        subs = created["subtasks"]
        assert parent["is_parent"] is True and len(subs) == 3
        assert len({s["assigned_vendor"] for s in subs}) == 3  # distinct-vendor round-robin
        code_sub = next(s for s in subs if s["requires_code_review"])
        assert code_sub["reviewer_id"] != code_sub["assigned_to"]

        # 2. Batch dry-run all subtasks (0 spend)
        batch = store.runbigtasksubtasks({"parent_task_id": parent["id"], "live": False})
        assert batch["mode"] == "dry_run" and batch["executed_count"] == 3

        # 3. Aggregation must be blocked before code_change subtask passes independent review
        try:
            store.aggregatebigtask({"parent_task_id": parent["id"]})
            raise AssertionError("Big task aggregation must block until code_change subtask passes review")
        except ValueError:
            pass

        # 4. Auto code review reads local git diff (0 tokens in dry-run) and passes review
        repo_root = str(Path(__file__).resolve().parents[1])
        rev_res = store.runautocodereview({
            "task_id": code_sub["id"],
            "workspace_dir": repo_root,
            "live": False,
        })
        assert rev_res["mode"] == "dry_run" and rev_res["review_status"] == "approved"

        # 5. Aggregate succeeds -> parent delivered -> owner accepts -> accepted_done
        delivered_parent = store.aggregatebigtask({"parent_task_id": parent["id"]})
        assert delivered_parent["status"] == "delivered"
        assert "大任务聚合总交付" in delivered_parent["final_delivery_text"]
        done = store.reviewfinalresult({"task_id": parent["id"], "decision": "verified"})
        assert done["status"] == "accepted_done"


class CountingAdapter:
    vendor = "Count"
    model_id = "count-1"
    access_kind = "api"

    def __init__(self):
        self.calls = 0

    def chat(self, prompt, max_tokens=1000):
        self.calls += 1
        return AgentReply(text="ok", model="count-1", usage={"total_tokens": 7})

    def check_quota(self):
        return Quota(kind="api", percent_remaining=50.0)


class ScriptedAdapter:
    """Returns a fixed reply (or raises) so mode runners can be tested deterministically."""
    vendor = "Scripted"
    model_id = "scripted-1"
    access_kind = "api"

    def __init__(self, text="ok", tokens=5, fail=False):
        self.text = text
        self.tokens = tokens
        self.fail = fail

    def chat(self, prompt, max_tokens=1000):
        if self.fail:
            raise RuntimeError("scripted failure: no usable model")
        return AgentReply(text=self.text, model="scripted-1", usage={"total_tokens": self.tokens})

    def check_quota(self):
        return Quota(kind="api", percent_remaining=50.0)


class PipelineAdapter:
    """Prompt-aware fake so the whole auto-orchestration loop runs deterministically."""
    vendor = "Pipe"
    model_id = "pipe-1"
    access_kind = "api"

    def __init__(self, fail=False):
        self.fail = fail

    def chat(self, prompt, max_tokens=1000):
        if self.fail:
            raise RuntimeError("no usable model")
        if "独立代码审查员" in prompt:
            text = "PASS"
        elif "你是总管，汇总" in prompt:
            text = "【结论】采纳 M1 的方案"
        elif "参加圆桌评审" in prompt:
            text = "【结论】支持方案A"
        elif "挑出最好的一份" in prompt:
            text = "【结论】采纳初稿1（更简洁）"
        elif "拆成可并行" in prompt:
            text = ('[{"title":"梳理","goal":"梳理清单","task_kind":"small","depends_on":[]},'
                    '{"title":"修复","goal":"修复校验","task_kind":"code_change","depends_on":[1]}]')
        else:
            text = "ok"
        return AgentReply(text=text, model="pipe-1", usage={"total_tokens": 5})

    def check_quota(self):
        return Quota(kind="api", percent_remaining=50.0)


def _seed_pipeline_team(store):
    store.createagent({"name": "M1", "vendor": "MV1", "model": "m1", "access_kind": "api", "paid": True,
                       "key_env": "M1_KEY", "base_url": "https://m1.invalid/v1", "floor": "manager"})
    store.createagent({"name": "M2", "vendor": "MV2", "model": "m2", "access_kind": "api", "paid": True,
                       "key_env": "M2_KEY", "base_url": "https://m2.invalid/v1", "floor": "manager"})
    for i in range(3):
        store.createagent({"name": f"W{i}", "vendor": f"SV{i}", "model": f"w{i}", "access_kind": "api",
                           "key_env": f"W{i}_KEY", "base_url": f"https://w{i}.invalid/v1", "floor": "worker"})


def test_p0_concurrent_writes_no_lost_updates_and_atomic_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "office.json"
        store = OfficeStore(state_path=path)
        errors = []

        def recruit(i):
            try:
                store.createagent({
                    "name": f"W{i}", "vendor": f"Vendor{i}", "model": f"m{i}",
                    "access_kind": "api", "key_env": f"K{i}_KEY",
                    "base_url": f"https://v{i}.invalid/v1", "floor": "worker",
                })
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=recruit, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        assert len(store.listagents()["agents"]) == 13  # chief + 12, no lost updates
        json.loads(path.read_text(encoding="utf-8"))  # never a torn file
        reloaded = OfficeStore(state_path=path)
        assert len(reloaded.listagents()["agents"]) == 13


def test_p0_parallel_big_task_subtasks_no_deadlock():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "office.json"
        store = OfficeStore(state_path=path)
        for i in range(3):
            store.createagent({
                "name": f"API W{i}", "vendor": f"ParVendor{i}", "model": f"pm{i}",
                "access_kind": "api", "key_env": f"PAR{i}_KEY",
                "base_url": f"https://par{i}.invalid/v1", "floor": "worker",
            })
        store._build_adapter = lambda agent, workspace_dir=".": FakeAdapter()
        created = store.createbigtask({
            "title": "并行压测", "goal": "三个小活并行",
            "raw_steps": "1. 翻译短句\n2. 整理名单\n3. 生成摘要",
        })
        parent = created["parent"]
        res = store.runbigtasksubtasks({"parent_task_id": parent["id"], "live": True})
        assert res["mode"] == "live" and res["executed_count"] == 3
        assert all(r.get("ok") for r in res["results"] if not r.get("skipped"))
        subs = [store._find_task(sid) for sid in parent["subtask_ids"]]
        assert all(s["worker_reported"] for s in subs)
        json.loads(path.read_text(encoding="utf-8"))


def test_p0_idempotent_work_order_receipts():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        w = store.createagent({
            "name": "Idem W", "vendor": "IdemV", "model": "im",
            "access_kind": "api", "key_env": "IDEM_KEY",
            "base_url": "https://idem.invalid/v1", "floor": "worker",
        })
        payload = {"title": "重复点击工单", "goal": "只派一遍", "assigned_to": w["id"], "task_kind": "small"}
        t1 = store.createtask(payload)
        t2 = store.createtask(dict(payload))
        assert t1["id"] == t2["id"]
        assert len([t for t in store.listtasks()["tasks"] if t["title"] == "重复点击工单"]) == 1
        assert any(len(fp) == 64 for fp in store.state["receipts"])  # SHA-256 hex

        b1 = store.createbigtask({"title": "重复大任务", "raw_steps": "1. 甲\n2. 乙"})
        b2 = store.createbigtask({"title": "重复大任务", "raw_steps": "1. 甲\n2. 乙"})
        assert b1["parent"]["id"] == b2["parent"]["id"]

        counter = CountingAdapter()
        store._build_adapter = lambda agent, workspace_dir=".": counter
        task = store.createtask({"title": "真调一次", "assigned_to": w["id"], "task_kind": "small", "force_new": True})
        store.runadaptertask({"task_id": task["id"], "live": True})
        r2 = store.runadaptertask({"task_id": task["id"], "live": True})
        assert counter.calls == 1  # quota burned once, not twice
        assert r2.get("idempotent_replay") is True
        assert w["tokens_used"] == 7  # real tokens counted exactly once


def test_p0_revision_circuit_breaker():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        coder = store.createagent({
            "name": "CB Coder", "vendor": "CBV1", "model": "cb1",
            "access_kind": "api", "key_env": "CB1_KEY",
            "base_url": "https://cb1.invalid/v1", "floor": "worker",
        })
        reviewer = store.createagent({
            "name": "CB Reviewer", "vendor": "CBV2", "model": "cb2",
            "access_kind": "cli", "executable": "codex", "floor": "worker",
        })
        store.state["settings"]["max_revision_rounds"] = 1
        task = store.createtask({
            "title": "熔断测试", "assigned_to": coder["id"],
            "task_kind": "code_change", "reviewer_id": reviewer["id"],
        })
        store.postmessage({"task_id": task["id"], "sender_id": coder["id"],
                           "conclusion": "初版", "changed_files": ["x.py"], "is_delivery": True})
        r1 = store.submitcodereview({"task_id": task["id"], "reviewer_id": reviewer["id"],
                                     "passed": False, "issues": ["x.py:1 问题A"]})
        assert r1["revision_round"] == 1 and r1["circuit_breaker"] == ""
        r2 = store.submitcodereview({"task_id": task["id"], "reviewer_id": reviewer["id"],
                                     "passed": False, "issues": ["x.py:2 问题B"]})
        assert r2["circuit_breaker"] == "revision_limit"
        assert r2["revision_round"] == 1  # stopped at ceiling, no further increment
        assert any(m["kind"] == "circuit_breaker" for m in store.listgroupmessages())
        try:
            store.deliverfinalresult({"task_id": task["id"]})
            raise AssertionError("breaker-tripped task must still block delivery")
        except ValueError:
            pass


def test_p1_bus_conclusion_only_queue_web_exclusion_and_chain_breaker():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        a = store.createagent({"name": "Bus A", "vendor": "BusVA", "model": "ba",
                               "access_kind": "api", "key_env": "BA_KEY",
                               "base_url": "https://ba.invalid/v1", "floor": "worker"})
        b = store.createagent({"name": "Bus B", "vendor": "BusVB", "model": "bb",
                               "access_kind": "cli", "executable": "codex", "floor": "worker"})
        web = store.createagent({"name": "Bus Web", "vendor": "BusVW", "model": "bw",
                                 "access_kind": "web", "login_url": "https://example.com/", "floor": "worker"})

        e1 = store.bussend({"from_id": "chief", "to_id": a["id"], "text": "【结论】已完成翻译", "kind": "conclusion"})
        assert e1["status"] == "delivered" and e1["pass"] == 1
        try:
            store.bussend({"from_id": "chief", "to_id": a["id"],
                           "text": "User: hi\nAssistant: ok\nUser: again\nAssistant: dump"})
            raise AssertionError("bus must reject full conversation dump")
        except ValueError:
            pass
        try:
            store.bussend({"from_id": "chief", "to_id": web["id"], "text": "【结论】x"})
            raise AssertionError("web worker must not be a bus recipient (red line)")
        except ValueError:
            pass

        t = store.createtask({"title": "占用A", "assigned_to": a["id"], "task_kind": "small"})
        store.claimtask({"task_id": t["id"], "worker_id": a["id"]})
        e2 = store.bussend({"from_id": "chief", "to_id": a["id"], "text": "【结论】排队消息", "kind": "conclusion"})
        assert e2["status"] == "queued"
        assert store.busflush({"agent_id": a["id"]})["still_busy"] is True
        store.deliverfinalresult({"task_id": t["id"]})
        flush = store.busflush({"agent_id": a["id"]})
        assert flush["delivered"] >= 1 and flush["still_busy"] is False

        store.state["settings"]["max_chain_pass"] = 2
        store.bussend({"from_id": "chief", "to_id": b["id"], "text": "【结论】1", "chain_id": "cX"})
        store.bussend({"from_id": "chief", "to_id": b["id"], "text": "【结论】2", "chain_id": "cX"})
        e_blocked = store.bussend({"from_id": "chief", "to_id": b["id"], "text": "【结论】3", "chain_id": "cX"})
        assert e_blocked["status"] == "blocked" and e_blocked["block_reason"] == "chain_pass_limit"
        assert any(m["kind"] == "circuit_breaker" for m in store.listgroupmessages())
        led = store.busledger()
        assert led["total_messages"] >= 5 and led["blocked"] >= 1


def test_p1_discussion_rounds_breaker_and_resolve():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        m1 = store.createagent({"name": "Mgr One", "vendor": "MV1", "model": "m1",
                                "access_kind": "api", "paid": True, "key_env": "M1_KEY",
                                "base_url": "https://m1.invalid/v1", "floor": "manager"})
        m2 = store.createagent({"name": "Mgr Two", "vendor": "MV2", "model": "m2",
                                "access_kind": "cli", "paid": True, "executable": "codex", "floor": "manager"})
        web = store.createagent({"name": "Web Mgr", "vendor": "MVW", "model": "mw",
                                 "access_kind": "web", "login_url": "https://example.com/", "floor": "manager"})
        try:
            store.startdiscussion({"topic": "x", "participants": [m1["id"], web["id"]]})
            raise AssertionError("web manager must be excluded from discussion bus")
        except ValueError:
            pass

        store.state["settings"]["max_discussion_rounds"] = 1
        disc = store.startdiscussion({"task_id": "T-disc", "topic": "方案评审", "participants": [m1["id"], m2["id"]]})
        assert disc["status"] == "open" and len(disc["participants"]) == 2
        store.postdiscussionmessage({"discussion_id": "T-disc", "from_id": m1["id"], "text": "【结论】建议采用方案A", "stance": "support"})
        store.postdiscussionmessage({"discussion_id": "T-disc", "from_id": m2["id"], "text": "【结论】反对：方案A有并发风险", "stance": "oppose"})
        blocked = store.postdiscussionmessage({"discussion_id": "T-disc", "from_id": m1["id"], "text": "【结论】再议", "stance": "revise"})
        assert blocked.get("blocked") is True and blocked["circuit_breaker"] == "discussion_limit"
        d = store.listdiscussion({"discussion_id": "T-disc"})
        assert d["status"] == "deadlock" and len(d["messages"]) == 2
        assert any(m["kind"] == "circuit_breaker" for m in store.listgroupmessages())
        assert any(m["kind"] == "discussion" and m["chain_id"] == "T-disc" for m in store.listbusmessages())
        try:
            store.postdiscussionmessage({"discussion_id": "T-disc", "from_id": m2["id"], "text": "【结论】x"})
            raise AssertionError("deadlocked discussion must reject further speech")
        except ValueError:
            pass

        store.state["settings"]["max_discussion_rounds"] = 3
        store.startdiscussion({"task_id": "T-disc2", "topic": "二轮", "participants": [m1["id"], m2["id"]]})
        store.postdiscussionmessage({"discussion_id": "T-disc2", "from_id": m1["id"], "text": "【结论】方案B", "stance": "support"})
        closed = store.resolvediscussion({"discussion_id": "T-disc2", "resolution": "采用方案B", "adopted": m1["name"]})
        assert closed["status"] == "closed" and closed["adopted"] == m1["name"]


def test_p1_mcp_relay_protocol_compatible_and_core_delegated():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        a1 = store.createagent({"name": "API Worker", "vendor": "AV1", "model": "a1",
                                "access_kind": "api", "key_env": "A1_KEY",
                                "base_url": "https://a1.invalid/v1", "floor": "worker"})
        a2 = store.createagent({"name": "CLI Worker", "vendor": "AV2", "model": "a2",
                                "access_kind": "cli", "executable": "codex", "floor": "worker"})
        web = store.createagent({"name": "Web Worker", "vendor": "AVW", "model": "aw",
                                 "access_kind": "web", "login_url": "https://example.com/", "floor": "worker"})
        m1 = store.createagent({"name": "Mgr One", "vendor": "MV1", "model": "m1",
                                "access_kind": "api", "paid": True, "key_env": "M1_KEY",
                                "base_url": "https://m1.invalid/v1", "floor": "manager"})
        m2 = store.createagent({"name": "Mgr Two", "vendor": "MV2", "model": "m2",
                                "access_kind": "cli", "paid": True, "executable": "codex", "floor": "manager"})
        relay = FarmMCPRelay(CoreBackend(store))

        def call(name, args=None, rid=1):
            return relay.handle_request({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                                         "params": {"name": name, "arguments": args or {}}})

        def payload(resp):
            assert "result" in resp, resp
            assert resp["result"]["isError"] is False
            return json.loads(resp["result"]["content"][0]["text"])

        init = relay.handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        assert init["result"]["protocolVersion"] == "2024-11-05"
        assert init["result"]["serverInfo"]["name"] == "ai-farm-mcp-relay"
        assert relay.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

        listed = relay.handle_request({"jsonrpc": "2.0", "id": 0, "method": "tools/list", "params": {}})
        names = {t["name"] for t in listed["result"]["tools"]}
        # the original 6 private-bridge tools stay name/behavior compatible
        assert {"farm_list_agents", "farm_list_tasks", "farm_claim_task", "farm_send_conclusion",
                "farm_submit_code_review", "farm_request_approval"} <= names
        assert {"farm_bus_send", "farm_bus_inbox", "farm_bus_ledger", "farm_start_discussion",
                "farm_post_discussion", "farm_resolve_discussion"} <= names
        assert len(TOOLS) == 12

        agents = payload(call("farm_list_agents"))["agents"]
        by_id = {a["id"]: a for a in agents}
        assert by_id[web["id"]]["mcp_eligible"] is False
        assert by_id[a1["id"]]["mcp_eligible"] is True
        assert MCP_ELIGIBLE_ACCESS == {"api", "cli", "desktop", "chief"}

        # relay forwards conclusion formatting to Core (it must NOT format itself)
        sent = payload(call("farm_send_conclusion", {"sender_id": a1["id"], "to_id": a2["id"],
                                                     "conclusion": "完成登录模块", "changed_files": ["auth.py"],
                                                     "test_result": "3 passed", "tokens": 11}))
        assert sent["bus"]["status"] == "delivered"
        assert "【结论】完成登录模块" in sent["bus"]["text"]
        assert "【改动文件】auth.py" in sent["bus"]["text"]
        inbox = payload(call("farm_bus_inbox", {"agent_id": a2["id"]}))
        assert any("【结论】" in m["text"] for m in inbox)

        # red line: web worker is not a bus member — Core rejects, relay surfaces error
        bad = call("farm_send_conclusion", {"sender_id": a1["id"], "to_id": web["id"], "conclusion": "x"})
        assert "error" in bad and bad["error"]["code"] == -32000

        led = payload(call("farm_bus_ledger"))
        assert led["total_messages"] >= 1 and led["tokens"] >= 11
        assert led["by_agent"][a1["id"]]["sent"] >= 1

        # discussion tools ride the same Core bus
        disc = payload(call("farm_start_discussion", {"task_id": "T-relay", "topic": "评审",
                                                      "participants": [m1["id"], m2["id"]]}))
        assert disc["status"] == "open"
        payload(call("farm_post_discussion", {"discussion_id": "T-relay", "from_id": m1["id"],
                                              "text": "【结论】方案A", "stance": "support"}))
        closed = payload(call("farm_resolve_discussion", {"discussion_id": "T-relay",
                                                          "resolution": "采用A", "adopted": m1["name"]}))
        assert closed["status"] == "closed" and closed["adopted"] == m1["name"]

        unknown = call("farm_does_not_exist")
        assert "error" in unknown
        bad_method = relay.handle_request({"jsonrpc": "2.0", "id": 9, "method": "nope"})
        assert bad_method["error"]["code"] == -32601


def test_p1_roundtable_mode_real_opinions_and_honest_stop():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        m1 = store.createagent({"name": "M1", "vendor": "MV1", "model": "m1", "access_kind": "api",
                                "paid": True, "key_env": "M1_KEY", "base_url": "https://m1.invalid/v1", "floor": "manager"})
        m2 = store.createagent({"name": "M2", "vendor": "MV2", "model": "m2", "access_kind": "api",
                                "paid": True, "key_env": "M2_KEY", "base_url": "https://m2.invalid/v1", "floor": "manager"})
        chief = store._find_agent("chief")
        chief["access_kind"] = "api"; chief["base_url"] = "https://c.invalid/v1"; chief["key_env"] = "C_KEY"

        # too few debaters -> honest stop, no fabricated debate
        t0 = store.createtask({"title": "圆桌缺人", "goal": "x", "task_kind": "small"})
        r0 = store.runroundtable({"task_id": t0["id"], "live": True, "participants": [m1["id"]]})
        assert r0["stopped"] is True and r0["reason"] == "insufficient_managers"

        task = store.createtask({"title": "圆桌方案", "goal": "设计登录模块", "task_kind": "small", "mode": "roundtable"})

        def picker(agent, workspace_dir="."):
            if agent["id"] == "chief":
                return ScriptedAdapter("【结论】采纳 M1 的方案，注意并发", tokens=5)
            return ScriptedAdapter("【结论】支持方案A", tokens=5)
        store._build_adapter = picker
        r = store.runroundtable({"task_id": task["id"], "live": True, "participants": [m1["id"], m2["id"]]})
        assert r["mode"] == "roundtable" and r["opinions"] == 2 and r["tokens"] == 15
        assert r["adopted"] == "M1" and r["chief_aggregated"] is True
        assert r["discussion"]["status"] == "closed"
        assert store._find_task(task["id"])["mode"] == "roundtable"
        assert any(m["kind"] == "discussion" and m["chain_id"] == task["id"] for m in store.listbusmessages())
        assert any(m["kind"] == "discussion_open" for m in store.listgroupmessages())
        assert any(m["kind"] == "discussion_closed" for m in store.listgroupmessages())

        # dry-run builds the thread but never fabricates opinions
        t2 = store.createtask({"title": "圆桌干跑", "goal": "x", "task_kind": "small", "force_new": True})
        r2 = store.runroundtable({"task_id": t2["id"], "live": False, "participants": [m1["id"], m2["id"]]})
        assert r2["dry_run"] is True and r2["opinions"] == 0
        assert store.listdiscussion({"discussion_id": t2["id"]})["messages"] == []

        # live but no usable model -> stop honestly, zero fabricated opinions
        store._build_adapter = lambda agent, workspace_dir=".": ScriptedAdapter(fail=True)
        t3 = store.createtask({"title": "圆桌无模型", "goal": "x", "task_kind": "small", "force_new": True})
        r3 = store.runroundtable({"task_id": t3["id"], "live": True, "participants": [m1["id"], m2["id"]]})
        assert r3["stopped"] is True and r3["reason"] == "no_real_model" and r3["opinions"] == 0
        assert any(m["kind"] == "mode_stopped" for m in store.listgroupmessages())


def test_p1_swarm_mode_two_drafts_chief_picks_and_honest_stop():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        w1 = store.createagent({"name": "W1", "vendor": "SV1", "model": "s1", "access_kind": "api",
                                "key_env": "W1_KEY", "base_url": "https://w1.invalid/v1", "floor": "worker"})
        # only one free worker -> honest stop
        t0 = store.createtask({"title": "撒网缺人", "goal": "x", "task_kind": "small"})
        r0 = store.runswarm({"task_id": t0["id"], "live": True})
        assert r0["stopped"] is True and r0["reason"] == "insufficient_workers"

        w2 = store.createagent({"name": "W2", "vendor": "SV2", "model": "s2", "access_kind": "api",
                                "key_env": "W2_KEY", "base_url": "https://w2.invalid/v1", "floor": "worker"})
        chief = store._find_agent("chief")
        chief["access_kind"] = "api"; chief["base_url"] = "https://c.invalid/v1"; chief["key_env"] = "C_KEY"
        task = store.createtask({"title": "撒网任务", "goal": "写一段排序", "task_kind": "small", "mode": "swarm"})

        def picker(agent, workspace_dir="."):
            if agent["id"] == "chief":
                return ScriptedAdapter("【结论】采纳初稿1（更简洁）", tokens=5)
            return ScriptedAdapter("ok", tokens=5)
        store._build_adapter = picker
        r = store.runswarm({"task_id": task["id"], "live": True})
        assert r["mode"] == "swarm" and r["winner"] == "W1" and r["tokens"] == 15
        parent = store._find_task(task["id"])
        assert parent["is_parent"] is True and len(parent["subtask_ids"]) == 2
        assert parent["status"] == "delivered" and r["winner_task"] == parent["subtask_ids"][0]
        assert any(m["kind"] == "swarm_card" for m in store.listgroupmessages())

        # dry-run routes two drafts but never fabricates a winner
        t2 = store.createtask({"title": "撒网干跑", "goal": "x", "task_kind": "small", "force_new": True})
        r2 = store.runswarm({"task_id": t2["id"], "live": False})
        assert r2["dry_run"] is True and r2["winner"] == "" and len(r2["drafts"]) == 2

        # workers succeed but chief has no model -> hand both drafts to owner, no fake winner
        chief["access_kind"] = "chief"
        store._build_adapter = lambda agent, workspace_dir=".": ScriptedAdapter("ok", tokens=5)
        t3 = store.createtask({"title": "撒网总管无模型", "goal": "x", "task_kind": "small", "force_new": True})
        r3 = store.runswarm({"task_id": t3["id"], "live": True})
        assert r3["stopped"] is True and r3["reason"] == "chief_no_model" and r3["winner"] == ""
        assert all(store._find_task(d["task_id"])["status"] == "delivered" for d in r3["drafts"] if d["ok"])

        # no usable model at all -> honest stop
        store._build_adapter = lambda agent, workspace_dir=".": ScriptedAdapter(fail=True)
        t4 = store.createtask({"title": "撒网全无模型", "goal": "x", "task_kind": "small", "force_new": True})
        r4 = store.runswarm({"task_id": t4["id"], "live": True})
        assert r4["stopped"] is True and r4["reason"] == "no_real_model"


def test_p2_autopublish_dry_pipeline_rule_label_and_zero_savings():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        _seed_pipeline_team(store)
        r = store.autopublish({"text": "1. 梳理清单\n2. [代码] 修复校验\n3. 输出摘要",
                               "mode": "split", "run": True, "live": False})
        assert r["plan_source"] == "rule" and len(r["subtasks"]) == 3
        ar = r["autorun"]
        assert ar["delivered"] is True and ar["stopped_reason"] == ""
        statuses = {s["step"]: s["status"] for s in ar["steps"]}
        assert statuses["execute"] == "ok" and statuses["review"] == "ok"
        assert statuses["discuss"] == "dry_run" and statuses["aggregate"] == "ok" and statuses["deliver"] == "ok"
        # discussion sub-step must NOT overwrite the split dispatch mode
        assert store._find_task(r["parent"]["id"])["mode"] == "split"
        assert store._find_task(r["parent"]["id"])["status"] == "delivered"
        # dry-run spends nothing: savings ledger counts 0
        assert ar["savings"]["free_calls"] == 0 and ar["savings"]["free_tokens"] == 0
        assert any(m["kind"] == "publish_card" for m in store.listgroupmessages())
        assert any("规则拆单" in m["text"] for m in store.listgroupmessages())


def test_p2_autopublish_model_dag_live_pipeline_and_real_savings():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        _seed_pipeline_team(store)
        store._build_adapter = lambda agent, workspace_dir=".": PipelineAdapter()
        r = store.autopublish({"text": "重构登录模块并补文档", "mode": "split",
                               "run": True, "live": True, "live_plan": True})
        assert r["plan_source"] == "model" and len(r["subtasks"]) == 2
        deps = [store._find_task(t["id"])["depends_on"] for t in r["subtasks"]]
        assert deps[0] == [] and deps[1] == [r["subtasks"][0]["id"]]  # DAG resolved to sibling id
        ar = r["autorun"]
        assert ar["delivered"] is True
        statuses = {s["step"]: s["status"] for s in ar["steps"]}
        assert statuses["review"] == "ok" and statuses["discuss"] == "ok" and statuses["deliver"] == "ok"
        led = store.savingsledger()
        assert led["free_calls"] >= 2 and led["free_tokens"] >= 10   # real worker tokens
        assert led["paid_calls"] >= 3 and led["paid_tokens"] >= 15   # plan + debate + chief
        assert led["by_day"] and led["by_week"]
        done = store.reviewfinalresult({"task_id": r["parent"]["id"], "decision": "verified"})
        assert done["status"] == "accepted_done"


def test_p2_autorun_stops_honestly_without_model():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        _seed_pipeline_team(store)
        store._build_adapter = lambda agent, workspace_dir=".": PipelineAdapter(fail=True)
        r = store.autopublish({"text": "1. 甲\n2. [代码] 乙", "mode": "split", "run": True, "live": True})
        ar = r["autorun"]
        assert ar["delivered"] is False and ar["stopped_reason"]
        assert store._find_task(r["parent"]["id"])["status"] != "delivered"
        assert store.savingsledger()["free_calls"] == 0  # nothing real succeeded
        assert any(s["status"] in ("stopped", "blocked", "partial") for s in ar["steps"])


def test_p2_big_task_dag_dependency_waves():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        for i in range(2):
            store.createagent({"name": f"DW{i}", "vendor": f"DV{i}", "model": f"d{i}", "access_kind": "api",
                               "key_env": f"DW{i}_KEY", "base_url": f"https://dw{i}.invalid/v1", "floor": "worker"})
        created = store.createbigtask({"title": "DAG", "subtasks": [
            {"title": "上游A", "goal": "上游A目标", "task_kind": "small", "depends_on": []},
            {"title": "下游B", "goal": "下游B目标", "task_kind": "small", "depends_on": [1]},
        ]})
        parent = created["parent"]
        a, b = created["subtasks"]
        assert b["depends_on"] == [a["id"]]
        # dry-run: both waves complete
        batch = store.runbigtasksubtasks({"parent_task_id": parent["id"], "live": False})
        assert batch["executed_count"] == 2
        # live: upstream fails -> downstream waits honestly (no fake success)
        store._build_adapter = lambda agent, workspace_dir=".": ScriptedAdapter(fail=True)
        b2 = store.createbigtask({"title": "DAG2", "subtasks": [
            {"title": "上游A", "goal": "上游A目标", "task_kind": "small", "depends_on": []},
            {"title": "下游B", "goal": "下游B目标", "task_kind": "small", "depends_on": [1]},
        ], "force_new": True})
        res = store.runbigtasksubtasks({"parent_task_id": b2["parent"]["id"], "live": True})
        by_id = {r["task_id"]: r for r in res["results"]}
        subs2 = b2["subtasks"]
        assert by_id[subs2[0]["id"]].get("ok") is False
        assert by_id[subs2[1]["id"]].get("skipped") is True
        assert res["executed_count"] == 0


def test_p2_swarm_and_roundtable_autopublish_modes():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        _seed_pipeline_team(store)
        chief = store._find_agent("chief")
        chief["access_kind"] = "api"; chief["base_url"] = "https://c.invalid/v1"; chief["key_env"] = "C_KEY"
        store._build_adapter = lambda agent, workspace_dir=".": PipelineAdapter()
        rs = store.autopublish({"text": "写一段排序", "mode": "swarm", "run": True, "live": True})
        assert rs["mode"] == "swarm" and rs["subtasks"] == []
        assert rs["autorun"]["delivered"] is True
        assert store._find_task(rs["parent"]["id"])["is_parent"] is True  # swarm built 2 drafts
        rr = store.autopublish({"text": "评审登录方案", "mode": "roundtable", "run": True, "live": True, "force_new": True})
        assert rr["mode"] == "roundtable" and rr["autorun"]["delivered"] is True
        assert any(m["kind"] == "discussion_closed" for m in store.listgroupmessages())


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=str(cwd),
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )


def _init_temp_repo(path):
    """A throwaway git repo — NEVER the real ai-farm repo. Destructive rollback
    logic is exercised only here."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "farm@test.local")
    _git(path, "config", "user.name", "Farm Test")
    _git(path, "checkout", "-q", "-b", "main")
    (path / "file.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "file.txt")
    _git(path, "commit", "-q", "-m", "base commit")
    return path


def test_p4_controlled_merge_backup_and_one_click_rollback():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_temp_repo(Path(tmp) / "repo")
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        # feature branch ahead of main
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "file.txt").write_text("feature change\n", encoding="utf-8")
        _git(repo, "add", "file.txt")
        _git(repo, "commit", "-q", "-m", "feature work")
        _git(repo, "checkout", "-q", "main")

        # dry-run preview must be zero-side-effect (no backup branch, HEAD unchanged)
        head0 = _git(repo, "rev-parse", "HEAD").stdout.strip()
        store.executecriticalop({"op_type": "merge", "target": "feature", "dry_run": True, "workspace_dir": str(repo)})
        apr = store.listapprovals()[-1]
        store.resolveapproval({"approval_id": apr["id"], "decision": "allow_once"})
        prev = store.executecriticalop({"op_type": "merge", "target": "feature", "dry_run": True, "workspace_dir": str(repo)})
        assert prev["executed"] is True and prev["real_executed"] is False and prev["backup_ref"] is None
        assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head0
        assert "backup/" not in _git(repo, "branch").stdout

        # real merge: fresh approval, backup branch created, content merged
        store.executecriticalop({"op_type": "merge", "target": "feature", "dry_run": True, "workspace_dir": str(repo)})
        apr2 = store.listapprovals()[-1]
        store.resolveapproval({"approval_id": apr2["id"], "decision": "allow_once"})
        real = store.executecriticalop({"op_type": "merge", "target": "feature", "dry_run": False, "workspace_dir": str(repo)})
        assert real["real_executed"] is True and real["rollback_available"] is True
        assert real["backup_ref"].startswith("backup/merge-")
        assert (repo / "file.txt").read_text(encoding="utf-8") == "feature change\n"

        # one-click owner rollback restores pre-merge state
        rb = store.rollbackcriticalop({"confirm": True, "backup_ref": real["backup_ref"], "workspace_dir": str(repo)})
        assert rb["rolled_back"] is True and rb["head_after"] == head0
        assert (repo / "file.txt").read_text(encoding="utf-8") == "base\n"


def test_p4_controlled_delete_code_backup_and_rollback():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_temp_repo(Path(tmp) / "repo")
        (repo / "del.txt").write_text("to remove\n", encoding="utf-8")
        _git(repo, "add", "del.txt")
        _git(repo, "commit", "-q", "-m", "add del.txt")
        store = OfficeStore(state_path=Path(tmp) / "office.json")

        store.executecriticalop({"op_type": "delete_code", "target": "cleanup", "dry_run": True, "workspace_dir": str(repo)})
        apr = store.listapprovals()[-1]
        store.resolveapproval({"approval_id": apr["id"], "decision": "allow_once"})
        real = store.executecriticalop({"op_type": "delete_code", "target": "cleanup", "dry_run": False,
                                        "files": ["del.txt"], "workspace_dir": str(repo)})
        assert real["real_executed"] is True and real["backup_ref"].startswith("backup/delete-")
        assert not (repo / "del.txt").exists()

        rb = store.rollbackcriticalop({"confirm": True, "backup_ref": real["backup_ref"], "workspace_dir": str(repo)})
        assert rb["rolled_back"] is True and (repo / "del.txt").exists()

        # path escape is blocked
        store.executecriticalop({"op_type": "delete_code", "target": "escape", "dry_run": True, "workspace_dir": str(repo)})
        apr2 = store.listapprovals()[-1]
        store.resolveapproval({"approval_id": apr2["id"], "decision": "allow_once"})
        bad = store.executecriticalop({"op_type": "delete_code", "target": "escape", "dry_run": False,
                                       "files": ["../outside.txt"], "workspace_dir": str(repo)})
        assert bad["real_executed"] is False and "越界" in bad["error"]


def test_p4_deploy_record_only_unless_command_configured():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_temp_repo(Path(tmp) / "repo")
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        # no deploy command -> honest record-only, never pretends to deploy
        store.executecriticalop({"op_type": "deploy", "target": "prod", "dry_run": True, "workspace_dir": str(repo)})
        apr = store.listapprovals()[-1]
        store.resolveapproval({"approval_id": apr["id"], "decision": "allow_once"})
        rec = store.executecriticalop({"op_type": "deploy", "target": "prod", "dry_run": False, "workspace_dir": str(repo)})
        assert rec["record_only"] is True and rec["real_executed"] is False and rec["executed"] is True

        # explicit owner-configured command -> real execution
        store.executecriticalop({"op_type": "deploy", "target": "prod2", "dry_run": True, "workspace_dir": str(repo)})
        apr2 = store.listapprovals()[-1]
        store.resolveapproval({"approval_id": apr2["id"], "decision": "allow_once"})
        real = store.executecriticalop({"op_type": "deploy", "target": "prod2", "dry_run": False,
                                        "command": [sys.executable, "-c", "print('deployed-ok')"], "workspace_dir": str(repo)})
        assert real["real_executed"] is True and "deployed-ok" in real["detail"]


def test_p4_executor_safe_return_on_non_git_and_dirty_tree():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        non_git = Path(tmp) / "plain"
        non_git.mkdir()
        store.executecriticalop({"op_type": "merge", "target": "feature", "dry_run": True, "workspace_dir": str(non_git)})
        apr = store.listapprovals()[-1]
        store.resolveapproval({"approval_id": apr["id"], "decision": "allow_once"})
        res = store.executecriticalop({"op_type": "merge", "target": "feature", "dry_run": False, "workspace_dir": str(non_git)})
        assert res["executed"] is False and res["real_executed"] is False and "不是 Git 仓库" in res["error"]

        repo = _init_temp_repo(Path(tmp) / "repo")
        (repo / "file.txt").write_text("uncommitted\n", encoding="utf-8")  # dirty tree
        store.executecriticalop({"op_type": "merge", "target": "feature", "dry_run": True, "workspace_dir": str(repo)})
        apr2 = store.listapprovals()[-1]
        store.resolveapproval({"approval_id": apr2["id"], "decision": "allow_once"})
        dirty = store.executecriticalop({"op_type": "merge", "target": "feature", "dry_run": False, "workspace_dir": str(repo)})
        assert dirty["real_executed"] is False and "未提交改动" in dirty["error"]


def test_p4_rollback_requires_confirm_and_backup_namespace():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_temp_repo(Path(tmp) / "repo")
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        try:
            store.rollbackcriticalop({"backup_ref": "backup/merge-x", "workspace_dir": str(repo)})
            raise AssertionError("rollback must require explicit confirm=True")
        except ValueError:
            pass
        try:
            store.rollbackcriticalop({"confirm": True, "backup_ref": "main", "workspace_dir": str(repo)})
            raise AssertionError("rollback must refuse non-backup refs")
        except ValueError:
            pass


def test_p4_approval_timeout_returns_not_auto_allow():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        store.setapprovaltimeout({"seconds": 1800})
        req = store.requestapproval({"op_type": "merge", "target": "main", "requested_by": "chief"})
        assert req["status"] == "pending" and req["expires_at"]
        # simulate the owner never answering: force expiry into the past (no polling/sleep)
        req["expires_at"] = "2000-01-01 00:00:00"
        store.save()
        listed = store.listapprovals()
        target = next(a for a in listed if a["id"] == req["id"])
        assert target["status"] == "expired"  # returned, NOT auto-approved
        # an expired approval can never be consumed by the executor
        res = store.executecriticalop({"op_type": "merge", "target": "main", "dry_run": True})
        assert res["executed"] is False and res["requires_approval"] is True
        # resolving an expired request is rejected
        try:
            store.resolveapproval({"approval_id": req["id"], "decision": "allow_once"})
            raise AssertionError("expired approval must not be resolvable")
        except ValueError:
            pass
        # timeout=0 disables expiry
        store.setapprovaltimeout({"seconds": 0})
        req2 = store.requestapproval({"op_type": "deploy", "target": "p", "requested_by": "chief"})
        assert req2["expires_at"] == ""


def test_p3_courier_self_check_reports_blockers_and_login_state():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        w = store.createagent({"name": "Kimi 网页", "vendor": "Kimi", "model": "kimi-web",
                               "access_kind": "web", "floor": "worker", "login_url": "https://kimi.com/",
                               "adapter_slug": "kimi-web"})
        t = store.createtask({"title": "网页活", "goal": "x", "task_kind": "small", "assigned_to": w["id"]})

        r1 = store.courierstatus({"task_id": t["id"], "status": "selector_failed", "detail": "找不到输入框"})
        assert r1["blocked"] is True and r1["agent_id"] == w["id"]
        assert store._find_agent(w["id"])["courier_health"]["status"] == "selector_failed"
        assert any(m["kind"] == "courier_alert" and "卡住了" in m["text"] for m in store.listgroupmessages())

        store.courierstatus({"task_id": t["id"], "status": "captcha", "detail": "人机验证"})
        assert any("验证码" in m["text"] for m in store.listgroupmessages() if m["kind"] == "courier_alert")

        store.courierstatus({"task_id": t["id"], "status": "login_expired", "detail": "会话失效"})
        assert store._find_agent(w["id"])["login_state"] == "会话过期"

        ok = store.courierstatus({"task_id": t["id"], "status": "login_ok", "detail": "自检通过"})
        assert ok["blocked"] is False and store._find_agent(w["id"])["login_state"] == "已登录"

        d = store.courierstatus({"task_id": t["id"], "status": "delivered", "detail": "已交回"})
        assert d["blocked"] is False
        assert len(store.state["courier_log"]) == 5

        try:
            store.courierstatus({"status": "bogus"})
            raise AssertionError("unknown courier status must be rejected")
        except ValueError:
            pass


def test_p3_desktop_receipt_auto_detect_and_conclusion_only():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        ws = Path(tmp) / "ws"
        w = store.createagent({"name": "豆包桌面", "vendor": "豆包PC", "model": "doubao-desktop",
                               "access_kind": "desktop", "floor": "worker"})
        t = store.createtask({"title": "桌面活", "goal": "整理清单", "task_kind": "small", "assigned_to": w["id"]})
        exp = store.exporttaskmd({"task_id": t["id"], "workspace_dir": str(ws)})
        assert (ws / "tasks" / "inbox" / f"{t['id']}.md").exists()
        assert exp["outbox_rel"] == f"tasks/outbox/{t['id']}.md"

        # no receipt yet -> wait honestly
        miss = store.checkdesktopreceipt({"task_id": t["id"], "workspace_dir": str(ws)})
        assert miss["found"] is False and miss["waiting"] is True

        outbox = ws / "tasks" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        receipt = outbox / f"{t['id']}.md"
        receipt.write_text("", encoding="utf-8")
        empty = store.checkdesktopreceipt({"task_id": t["id"], "workspace_dir": str(ws)})
        assert empty["found"] is True and empty["empty"] is True and empty["waiting"] is True

        receipt.write_text("【结论】清单已整理完成\n【改动文件】无\n【测试结果】通过", encoding="utf-8")
        got = store.checkdesktopreceipt({"task_id": t["id"], "workspace_dir": str(ws)})
        assert got["found"] is True and got["delivered"] is True
        assert store._find_task(t["id"])["worker_reported"] is True

        # a full-conversation paste in the receipt is rejected, never faked
        t2 = store.createtask({"title": "桌面活2", "goal": "y", "task_kind": "small", "assigned_to": w["id"], "force_new": True})
        store.exporttaskmd({"task_id": t2["id"], "workspace_dir": str(ws)})
        (outbox / f"{t2['id']}.md").write_text("user: 你好\nassistant: 你好\nuser: 帮我\nassistant: 好的", encoding="utf-8")
        bad = store.checkdesktopreceipt({"task_id": t2["id"], "workspace_dir": str(ws)})
        assert bad["found"] is True and bad["delivered"] is False and "结论-only" in bad["error"]


def test_p3_syncprofiles_login_state_visible():
    import os
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        unset = store.createagent({"name": "未配置API", "vendor": "VUnset", "model": "m1", "access_kind": "api",
                                   "floor": "worker", "key_env": "FARM_TEST_UNSET_KEY", "base_url": "https://u.invalid/v1",
                                   "adapter_slug": "test-not-registered"})
        os.environ.pop("FARM_TEST_UNSET_KEY", None)
        os.environ["FARM_TEST_SET_KEY"] = "dummy-value-not-a-real-key"
        try:
            setagent = store.createagent({"name": "已配置API", "vendor": "VSet", "model": "m2", "access_kind": "api",
                                          "floor": "worker", "key_env": "FARM_TEST_SET_KEY", "base_url": "https://s.invalid/v1",
                                          "adapter_slug": "test-not-registered"})
            web = store.createagent({"name": "未登录网页", "vendor": "VWeb", "model": "m3", "access_kind": "web",
                                     "floor": "worker", "login_url": "https://example.com/", "adapter_slug": "test-web"})
            cli = store.createagent({"name": "未安装CLI", "vendor": "VCli", "model": "m4", "access_kind": "cli",
                                     "floor": "worker", "executable": "definitely-not-installed-xyz"})
            store.syncprofiles()
            assert store._find_agent(unset["id"])["login_state"] == "未登录"
            assert store._find_agent(setagent["id"])["login_state"] == "已登录"
            assert store._find_agent(web["id"])["login_state"] == "未登录"
            assert store._find_agent(cli["id"])["login_state"] == "未登录"
            # detail must never leak a plaintext key — only the env-var name
            assert "FARM_TEST_SET_KEY" in store._find_agent(setagent["id"])["login_detail"]
            assert "dummy-value" not in store._find_agent(setagent["id"])["login_detail"]
        finally:
            os.environ.pop("FARM_TEST_SET_KEY", None)


def test_p3_autorun_auto_collects_desktop_receipt():
    with tempfile.TemporaryDirectory() as tmp:
        store = OfficeStore(state_path=Path(tmp) / "office.json")
        ws = Path(tmp) / "ws"
        w = store.createagent({"name": "桌面员工", "vendor": "WorkBuddy", "model": "wb-1",
                               "access_kind": "desktop", "floor": "worker"})
        store._build_adapter = lambda agent, workspace_dir=".": ScriptedAdapter("ok", tokens=5)
        big = store.createbigtask({"title": "桌面大任务", "subtasks": [
            {"title": "桌面子单", "goal": "整理", "task_kind": "small", "assigned_to": w["id"]},
        ]})
        sub = big["subtasks"][0]
        store.exporttaskmd({"task_id": sub["id"], "workspace_dir": str(ws)})
        outbox = ws / "tasks" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / f"{sub['id']}.md").write_text("【结论】整理完成\n【改动文件】无\n【测试结果】通过", encoding="utf-8")

        ar = store.autorun({"parent_task_id": big["parent"]["id"], "live": True, "workspace_dir": str(ws)})
        ex_step = next(s for s in ar["steps"] if s["step"] == "execute")
        assert ex_step["collected"] == 1 and ex_step["pending"] == 0 and ex_step["status"] == "ok"
        assert store._find_task(sub["id"])["worker_reported"] is True
        assert ar["delivered"] is True


if __name__ == "__main__":
    for name in sorted(dir()):
        if name.startswith("test_"):
            globals()[name]()
            print(f"PASS: {name}")
