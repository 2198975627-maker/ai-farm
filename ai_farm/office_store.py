"""Office state engine implementing the AI Farm Office workbench.

Pure open-source framework:
- Ships with an empty workbench (only 1 generic Chief slot) so every user
  recruits their own managers, workers, CLI tools, or desktop agents.
- Supports all 4 recruitment channels:
  1) API (env var NAME only — never plaintext keys)
  2) Web / Subscription (one-time browser login on vendor's own site)
  3) CLI Agent (headless subprocess execution in workspace)
  4) Desktop GUI Agent (workspace file-mailbox + @task.md handoff)
- Enforces hard rules: one icon = one model/pool, cross-vendor only
  reassignment, private worker reports (🔒 notice in group), real quotas
  ("额度未填" when unknown, <=10% red alert).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import functools
import hashlib
import json
import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .adapters.registry import get_adapter, registered_slugs
from .adapters.web import session_dir
from .skills import SKILLS, analyze_skill_assignments


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _locked(fn):
    """Serialize state read-modify-write under the store's reentrant lock.

    Only fast (no network/subprocess I/O) mutating methods are decorated.
    Slow orchestration methods (runadaptertask / runbigtasksubtasks /
    runautocodereview / runroundtable / runswarm / checklivequota) deliberately
    stay unlocked across I/O so parallel subtasks never deadlock; their state
    writes go through locked sub-calls (postmessage / submitcodereview / save).
    """
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return wrapper


# Pass / chain circuit breakers (learned from Agent HUD: a message, not the
# conversation; bounded连续传递 so two models never burn quota arguing forever).
MAX_REVISION_ROUNDS = 3      # write -> review -> revise reject ceiling
MAX_DISCUSSION_ROUNDS = 3    # manager roundtable debate ceiling
MAX_CHAIN_PASS = 10          # cross-agent连续投递 ceiling (HUD default)
APPROVAL_TIMEOUT_SECONDS = 1800  # owner未批超时原样退回（不默认放行，学 HUD fail-open）


def _default_agents() -> list[dict[str, Any]]:
    """Open-source clean starter: only the generic Chief (总管) slot.
    Managers, workers, and rest-floor agents are recruited by the user.
    """
    return [
        {
            "id": "chief",
            "name": "总管 (Chief)",
            "brand": "Orchestrator",
            "vendor": "Chief",
            "model": "待绑定你的统筹模型",
            "verified_version": False,
            "access_kind": "chief",
            "paid": False,
            "floor": "manager",
            "role_label": "第1层 总管 · 唯一对接口",
            "badge": "总管·唯一入口",
            "badge_color": "blue",
            "status": "ready",
            "account_status": "工作台已就绪：请点击左下角「➕ 招募 AI Agent」接入你自己的模型或点击顶部「🎭 载入示例团队」体验。",
            "specialty": "听任务、拆单、派单、记账、质检、整合汇报",
            "quota_kind": "none",
            "quota_percent": None,
            "quota_note": "总管槽位，不绑死特定厂商",
            "usage_url": "",
            "login_url": "",
            "key_env": "",
            "base_url": "",
            "fallback_note": "由当前最高层级助手或你指定的统筹模型担任",
            "attached_tools": [],
            "skills": ["doc-drafting-frame"],
            "icon_kind": "chief",
            "tier": "总管插槽",
            "expires_at": "",
            "tokens_used": 0,
            "session_count": 0,
        }
    ]


CODE_REVIEW_SKILL_SLUGS = {"cheap-code-jobs", "code-review-checklist", "test-cases"}
CRITICAL_OPS = {"merge", "delete_code", "deploy"}
LOW_RISK_OPS = {"auto_dispatch", "low_risk_run"}


def format_conclusion_report(
    conclusion: str,
    changed_files: list[str] | str | None = None,
    test_result: str = "未运行测试",
    diff_summary: str = "",
) -> str:
    """Build a strict Conclusion-Only report ('A message, not the conversation')."""
    conc = (conclusion or "").strip()
    if not conc:
        raise ValueError("结论不能为空（只传结论，不传整段对话）。")
    if isinstance(changed_files, list):
        files_clean = [str(f).strip() for f in changed_files if str(f).strip()]
        files_str = ", ".join(files_clean) if files_clean else "无"
    else:
        files_str = (str(changed_files or "").strip()) or "无"
    tests_str = (test_result or "").strip() or "未运行测试"
    parts = [
        f"【结论】{conc}",
        f"【改动文件】{files_str}",
        f"【测试结果】{tests_str}",
    ]
    ds = (diff_summary or "").strip()
    if ds:
        parts.append(f"【Diff摘要】{ds[:360]}")
    return "\n".join(parts)


SAMPLE_DEMO_TEAM: list[dict[str, Any]] = [
    {
        "name": "示例经理 (API)",
        "vendor": "Vendor-Manager",
        "model": "manager-model-id",
        "access_kind": "api",
        "paid": True,
        "floor": "manager",
        "key_env": "SAMPLE_MANAGER_API_KEY",
        "base_url": "https://api.example.com/v1",
        "usage_url": "",
        "specialty": "架构规划、只审 diff / 摘要、最终整合",
        "tier": "付费·API",
    },
    {
        "name": "示例员工 A (免费 API)",
        "vendor": "Vendor-Alpha",
        "model": "alpha-flash",
        "access_kind": "api",
        "paid": False,
        "floor": "worker",
        "key_env": "SAMPLE_ALPHA_API_KEY",
        "base_url": "https://api.alpha.example.com/v1",
        "usage_url": "",
        "specialty": "批量翻译、单元测试生成、便宜代码小活",
        "tier": "免费·API",
    },
    {
        "name": "示例员工 B (免费网页)",
        "vendor": "Vendor-Beta",
        "model": "待核实具体版本",
        "access_kind": "web",
        "paid": False,
        "floor": "worker",
        "login_url": "https://example.com/",
        "usage_url": "",
        "specialty": "三档摘要、中文润色、名单整理成表格",
        "tier": "Free 免费版",
    },
    {
        "name": "示例桌面 Agent (桌面端)",
        "vendor": "Vendor-Desktop",
        "model": "客户端内置积分池",
        "access_kind": "desktop",
        "paid": False,
        "floor": "worker",
        "specialty": "本地文件夹整理、@工单.md 读写文件执行",
        "tier": "Free 免费积分",
        "sub_models": [
            "轻量免费子模型 (0.00x 优先)",
            "标准子模型 (0.30x)",
        ],
    },
]


GENERIC_EXAMPLE_TASKS: list[dict[str, Any]] = [
    {
        "title": "【通用示例 1/4】10 条日用品英文短句批量翻译成中英对照表",
        "manager_id": "chief",
        "assigned_to": "",
        "goal": "将 10 条通用日用品英文短句逐条翻译为中文，合成 1 次调用完成，省经理 Token。",
        "input_text": (
            "1. Insulated stainless steel water bottle keeps drinks cold for 24 hours.\n"
            "2. Compact folding umbrella with windproof fiberglass ribs.\n"
            "3. Ergonomic mesh office chair with adjustable lumbar support.\n"
            "4. USB-C fast charging cable braided with durable nylon.\n"
            "5. Non-slip silicone kitchen cutting board set of three.\n"
            "6. Portable LED desk lamp with three brightness levels.\n"
            "7. Quick-dry microfiber travel towel in a breathable pouch.\n"
            "8. Ceramic coffee mug with cork coaster base.\n"
            "9. Reusable grocery tote bag made from recycled canvas.\n"
            "10. Wireless optical mouse with silent click buttons."
        ),
        "output_format": "Markdown 三列表格：| 序号 | 英文原句 | 中文翻译 |，不增不减，不要开场白。",
        "acceptance": "10/10 条全齐、无漏译、无编造参数；经理只审表格，不重读原文。不许自由发挥。",
        "skill_slug": "batch-translate",
        "task_kind": "small",
    },
    {
        "title": "【通用示例 2/4】杂乱活动报名名单去重并整理成标准表格",
        "manager_id": "chief",
        "assigned_to": "",
        "goal": "把杂乱的报名文本去重、对齐列、标出缺失项，由免费员工完成。",
        "input_text": (
            "- 张三 / 班级A / 负责宣传海报\n"
            "- 李四，班级B，联系电话未填，负责场地签到\n"
            "- 张三 (重复提交) 班级A 负责宣传海报\n"
            "- 王五 | 班级C | 负责设备调试\n"
            "- 赵六 / 班级未写 / 负责摄影记录"
        ),
        "output_format": "Markdown 表格：| 姓名 | 班级 | 分工 | 备注(缺失项标[缺失]) |",
        "acceptance": "去重后共 4 人，缺失字段标 [缺失]，不编造电话或班级。不许自由发挥。",
        "skill_slug": "table-cleanup",
        "task_kind": "small",
    },
    {
        "title": "【通用示例 3/4】科普短文生成三档摘要（一句话 / 100字 / 要点清单）",
        "manager_id": "chief",
        "assigned_to": "",
        "goal": "对通用科普材料生成三档摘要，供经理 10 秒钟审阅完核心数字与结论。",
        "input_text": (
            "教学楼A栋于2026年3月15日完成照明与空调自控改造，共更换LED感应灯具420盏、"
            "加装温控模块36套。经过90天连续监测，日均耗电量由改造前的1,250千瓦时降至875千瓦时，"
            "节电率达30.0%，负责巡检的陈工与林工确认设备零故障运行。"
        ),
        "output_format": "严格分三块：1.【一句话结论】 2.【百字摘要】 3.【关键数字核对清单】",
        "acceptance": "日期、数字、人名与原文100%一致；字数按去空白后全部字符计。不许自由发挥。",
        "skill_slug": "three-tier-summary",
        "task_kind": "small",
    },
    {
        "title": "【通用示例 4/4】修复 calc_discount 负数折扣 Bug 并补边界测试（写-审-改闭环）",
        "manager_id": "chief",
        "assigned_to": "",
        "goal": "为纯函数 calc_discount(price, rate) 修复边界校验漏洞并编写 3 个单元测试（写完需独立审查 Agent 过问题清单）。",
        "input_text": "def calc_discount(price: float, rate: float) -> float: # rate in [0.0, 1.0], raises ValueError if invalid",
        "output_format": "只输出：【结论】+【改动文件】+【测试结果】+【Diff摘要】，不贴全文对话。",
        "acceptance": "包含正常折扣(100, 0.8 -> 80)、边界(100, 0 -> 0)、异常(ValueError)断言，且通过独立 Agent 审查清单。不许自由发挥。",
        "skill_slug": "test-cases",
        "task_kind": "code_change",
    },
]


class OfficeStore:
    """Persistent state store backing the office workbench + AgentAdapter execution."""

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or (Path.home() / ".ai-farm" / "office_state.json")
        self._lock = threading.RLock()
        self.state: dict[str, Any] = {
            "agents": [],
            "skills": [],
            "tasks": [],
            "group_messages": [],
            "task_messages": {},
            "hud_flights": [],
            "pending_approvals": [],
            "receipts": {},
            "bus_messages": [],
            "discussions": {},
            "savings_ledger": [],
            "settings": {"auto_execute_low_risk": False},
            "example_cursor": 0,
        }
        self._load_or_seed()

    def _ensure_runtime_keys(self) -> None:
        self.state.setdefault("hud_flights", [])
        self.state.setdefault("pending_approvals", [])
        self.state.setdefault("receipts", {})
        self.state.setdefault("bus_messages", [])
        self.state.setdefault("discussions", {})
        self.state.setdefault("savings_ledger", [])
        settings = self.state.setdefault("settings", {})
        settings.setdefault("auto_execute_low_risk", False)
        settings.setdefault("max_revision_rounds", MAX_REVISION_ROUNDS)
        settings.setdefault("max_discussion_rounds", MAX_DISCUSSION_ROUNDS)
        settings.setdefault("max_chain_pass", MAX_CHAIN_PASS)
        settings.setdefault("discussion_rounds", 1)
        settings.setdefault("approval_timeout_seconds", APPROVAL_TIMEOUT_SECONDS)
        for a in self.state.get("agents", []):
            a.setdefault("tokens_used", 0)
            a.setdefault("session_count", 0)
        for t in self.state.get("tasks", []):
            t.setdefault("task_kind", "small")
            t.setdefault("requires_code_review", t.get("task_kind") == "code_change")
            t.setdefault("reviewer_id", "")
            t.setdefault("reviewer_name", "")
            t.setdefault("review_status", "pending_review" if t.get("requires_code_review") else "not_needed")
            t.setdefault("review_issues", [])
            t.setdefault("revision_round", 0)
            t.setdefault("parent_task_id", "")
            t.setdefault("is_parent", False)
            t.setdefault("subtask_ids", [])
            t.setdefault("mode", "solo")
            t.setdefault("circuit_breaker", "")
            t.setdefault("depends_on", [])

    def _load_or_seed(self) -> None:
        if self.state_path.exists():
            try:
                loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("agents"):
                    self.state = loaded
                    self._ensure_runtime_keys()
                    return
            except Exception:  # noqa: BLE001
                pass
        self.reset_to_seed()

    def save(self) -> None:
        """Atomically persist state under the reentrant lock.

        Write to a temp file in the same directory then os.replace() so a
        concurrent reader (or a crash mid-write) never sees a torn JSON file.
        """
        with self._lock:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.state, ensure_ascii=False, indent=2)
            tmp_path = self.state_path.with_name(
                f".{self.state_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            try:
                tmp_path.write_text(payload, encoding="utf-8")
                os.replace(tmp_path, self.state_path)
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

    # ------------------------------------------------------------------
    # Idempotent request receipts (SHA-256 fingerprint + receipt record).
    # A double-click or a network retry must NOT dispatch the same work
    # order twice nor burn a free worker's quota twice.
    # ------------------------------------------------------------------
    def _request_fingerprint(self, action: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"action": action, "payload": payload},
            ensure_ascii=False, sort_keys=True, default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _find_receipt(self, fingerprint: str) -> dict[str, Any] | None:
        return self.state.get("receipts", {}).get(fingerprint)

    def _store_receipt(self, fingerprint: str, action: str, result_ref: dict[str, Any]) -> None:
        receipts = self.state.setdefault("receipts", {})
        receipts[fingerprint] = {
            "fingerprint": fingerprint,
            "action": action,
            "created_at": _now_iso(),
            **result_ref,
        }
        if len(receipts) > 300:
            for k in list(receipts.keys())[:len(receipts) - 300]:
                receipts.pop(k, None)

    @_locked
    def reset_to_seed(self) -> dict[str, Any]:
        self.state["agents"] = _default_agents()
        self.state["skills"] = [
            {
                "slug": s.slug,
                "name": s.name,
                "category": s.category,
                "description": s.description,
                "steps": s.steps,
                "best_for": s.best_for,
                "keywords": list(s.keywords),
                "savings_note": s.savings_note,
            }
            for s in SKILLS
        ]
        self.state["tasks"] = []
        self.state["task_messages"] = {}
        self.state["hud_flights"] = []
        self.state["pending_approvals"] = []
        self.state["receipts"] = {}
        self.state["bus_messages"] = []
        self.state["discussions"] = {}
        self.state["savings_ledger"] = []
        self.state["settings"] = {
            "auto_execute_low_risk": False,
            "max_revision_rounds": MAX_REVISION_ROUNDS,
            "max_discussion_rounds": MAX_DISCUSSION_ROUNDS,
            "max_chain_pass": MAX_CHAIN_PASS,
            "discussion_rounds": 1,
            "approval_timeout_seconds": APPROVAL_TIMEOUT_SECONDS,
        }
        self.state["example_cursor"] = 0
        self.state["group_messages"] = [
            {
                "id": "msg-welcome-1",
                "sender_id": "chief",
                "sender_name": "总管 (Chief)",
                "sender_role": "chief",
                "kind": "system_welcome",
                "text": (
                    "👋 欢迎来到 **AI Farm 开源多级协同工作台**！\n"
                    "• **纯框架、零预设绑定**：本工作台只提供规范接口与协作场地——你要用什么网页端 AI、接哪家 API、还是用 CLI / 桌面端 Agent，全部由你自己在左下角 **「➕ 招募新 AI Agent」** 按需接入。\n"
                    "• **四大标准接口**：支持 `🔌 API (环境变量)`、`🌐 网页/订阅 (登录一次)`、`⌨️ CLI 工具`、`🖥️ 桌面应用 (@工单.md)`。\n"
                    "• **快速体验**：可以先点顶部 **「🎭 载入示例团队」** 体验一次完整的「派单 → 员工认领 → 🔒私聊汇报 → 经理交付 → 验收」流程！"
                ),
                "created_at": _now_iso(),
            }
        ]
        self.save()
        return self.state

    def loadsampleteam(self) -> dict[str, Any]:
        """Populate anonymous placeholder agents so new OSS users can test the workflow."""
        added = []
        for item in SAMPLE_DEMO_TEAM:
            try:
                ag = self.createagent(dict(item))
                if item.get("sub_models"):
                    ag["sub_models"] = list(item["sub_models"])
                if item.get("tier"):
                    ag["tier"] = item["tier"]
                added.append(ag["name"])
            except ValueError:
                pass
        self.save()
        return {"added_count": len(added), "added": added}

    # ------------------------------------------------------------------
    # Action 1: listagents
    # ------------------------------------------------------------------
    def listagents(self) -> dict[str, Any]:
        if not self.state.get("agents"):
            self.state["agents"] = _default_agents()
            self.save()
        agents = self.state["agents"]
        grouped = {
            "manager": [a for a in agents if a["floor"] == "manager"],
            "worker": [a for a in agents if a["floor"] == "worker"],
            "rest": [a for a in agents if a["floor"] == "rest"],
        }
        low_quota = [
            a for a in agents
            if a.get("quota_percent") is not None and float(a["quota_percent"]) <= 10.0
        ]
        return {"agents": agents, "grouped": grouped, "low_quota_alerts": low_quota}

    # ------------------------------------------------------------------
    # Action 2: createagent (4 Channels: API / Web-Sub / CLI / Desktop)
    # ------------------------------------------------------------------
    def createagent(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = (payload.get("name") or "").strip()
        vendor = (payload.get("vendor") or payload.get("brand") or "").strip()
        model = (payload.get("model") or payload.get("model_id") or "待核实具体版本").strip()
        access_kind = (payload.get("access_kind") or "api").strip().lower()
        floor = (payload.get("floor") or "worker").strip().lower()
        paid = bool(payload.get("paid", False))
        specialty = (payload.get("specialty") or "通用边角任务执行").strip()

        if not name or not vendor:
            raise ValueError("招募失败：名字（name）和厂商（vendor）不能为空。")
        if access_kind not in ("api", "web", "subscription", "cli", "desktop"):
            raise ValueError("招募失败：接入方式只能是 api / web / subscription / cli / desktop。")
        if floor not in ("manager", "worker", "rest"):
            raise ValueError("招募失败：楼层只能是 manager / worker / rest。")

        # Rule 1 & Rule 2: one icon = one model + one access mode (no cloning same pool)
        for existing in self.state["agents"]:
            if (existing["vendor"].lower() == vendor.lower()
                    and existing["model"].lower() == model.lower()
                    and existing["access_kind"] == access_kind):
                raise ValueError(
                    f"违反「一个图标 = 一个模型 + 一种通道」及「一厂商一免费号」规则："
                    f"{vendor} / {model} ({access_kind}) 已在花名册中，禁止同款复制多开。"
                )

        key_env = (payload.get("key_env") or "").strip()
        base_url = (payload.get("base_url") or "").strip()
        login_url = (payload.get("login_url") or "").strip()
        usage_url = (payload.get("usage_url") or "").strip()
        executable = (payload.get("executable") or "").strip()
        fallback_note = (payload.get("fallback_note") or "").strip()

        if access_kind == "api":
            if not key_env:
                raise ValueError("API 招募必须填写环境变量名（如 MY_API_KEY），不能留空。")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key_env) or key_env.startswith("SK-"):
                raise ValueError(
                    "安全拦截：环境变量名必须是大写字母+下划线（如 DEEPSEEK_API_KEY）。"
                    "严禁在此处直接粘贴 API Key 明文！"
                )
            badge = f"{'付费' if paid else '免费'}·API"
            badge_color = "orange" if paid else "green"
            quota_kind = "api"
            account_status = f"✅ 已接入 API 接口（读取系统环境变量 ${key_env}，密钥不落盘）"
            adapter_slug = payload.get("adapter_slug") or "custom-api"
            if not fallback_note:
                fallback_note = "降级后：API余额归0或429真停（自动换其他免费员工）"
        elif access_kind == "cli":
            if not executable:
                raise ValueError("CLI 工具招募必须填写可执行命令名（如 codex / codebuddy）。")
            badge = f"{'付费' if paid else '免费'}·CLI"
            badge_color = "orange" if paid else "green"
            quota_kind = "unknown"
            account_status = f"⌨️ 本地 CLI Agent（命令：{executable}，通过 subprocess 读写工作区）"
            adapter_slug = payload.get("adapter_slug") or "cli-generic"
            if not fallback_note:
                fallback_note = "降级后：CLI 未安装或报错时自动换其他员工"
        elif access_kind == "desktop":
            badge = f"{'付费' if paid else '免费'}·桌面端"
            badge_color = "orange" if paid else "green"
            quota_kind = "subscription"
            account_status = "🖥️ 桌面端 Agent（走工作空间 @工单.md 半自动协同）"
            adapter_slug = ""
            if not fallback_note:
                fallback_note = "降级后：免费积分用完则回院子休息或切 0.00x 子模型"
        else:
            if not login_url:
                raise ValueError("网页 / 订阅制招募必须填写厂商登录页 URL（login_url）。")
            is_sub = access_kind == "subscription" or paid
            access_kind = "subscription" if is_sub else "web"
            paid = is_sub
            badge = "付费·订阅" if is_sub else "免费·网页"
            badge_color = "orange" if is_sub else "green"
            quota_kind = "subscription" if is_sub else "unknown"
            logged_in = bool(payload.get("logged_in", False))
            adapter_slug = payload.get("adapter_slug") or "custom-web"
            account_status = (
                "✅ 已在厂商页面点过「登录一次」（本地会话 ~/.ai-farm/sessions/）"
                if logged_in else "❓ 待点「登录一次」在厂商官网登录自己的账号"
            )
            if not fallback_note:
                fallback_note = (
                    "降级后：到周期限额自动降级为轻量模型，不真停"
                    if is_sub else "降级后：今日累了休息到明天，轮换给别家免费员工"
                )

        slug_id = re.sub(r"[^a-z0-9]+", "-", f"{vendor}-{model}-{access_kind}".lower()).strip("-")
        if not slug_id or any(a["id"] == slug_id for a in self.state["agents"]):
            slug_id = f"agent-{int(time.time() * 1000) % 1000000}"

        agent = {
            "id": slug_id,
            "name": name,
            "brand": vendor,
            "vendor": vendor,
            "model": model,
            "verified_version": model != "待核实具体版本",
            "access_kind": access_kind,
            "paid": paid,
            "floor": floor,
            "role_label": {"manager": "2楼 经理层", "worker": "1楼 员工层", "rest": "院子休息"}[floor],
            "badge": badge,
            "badge_color": badge_color,
            "status": payload.get("status") or "ready",
            "account_status": account_status,
            "specialty": specialty,
            "quota_kind": quota_kind,
            "quota_percent": None,  # Never invent a quota percentage on recruit
            "quota_note": payload.get("quota_note") or "额度未填（未实查前不编造百分比）",
            "usage_url": usage_url,
            "login_url": login_url,
            "key_env": key_env,
            "base_url": base_url,
            "executable": executable,
            "fallback_note": fallback_note,
            "attached_tools": [],
            "skills": [],
            "sub_models": list(payload.get("sub_models") or []),
            "tier": payload.get("tier") or badge,
            "expires_at": payload.get("expires_at") or "",
            "icon_kind": "text",
            "adapter_slug": adapter_slug,
            "tokens_used": 0,
            "session_count": 0,
        }
        if access_kind in ("web", "subscription") and payload.get("logged_in"):
            sdir = session_dir(slug_id)
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "session_meta.json").write_text(
                json.dumps({"id": slug_id, "vendor": vendor, "login_url": login_url, "logged_in_at": _now_iso()}, ensure_ascii=False),
                encoding="utf-8",
            )
        self.state["agents"].append(agent)
        chief = self._chief_agent()
        self._append_group_msg(
            sender_id=chief["id"],
            sender_name=chief["name"],
            kind="system_notice",
            text=f"🎉 新招募成员入驻：**{name}**（`{badge}` · 厂商：{vendor} · 模型：{model}），已安排至 **{agent['role_label']}**。",
        )
        self.save()
        return agent

    # ------------------------------------------------------------------
    # Action 3: updateagent
    # ------------------------------------------------------------------
    def updateagent(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self._find_agent(payload.get("id") or payload.get("agent_id"))
        for field in ("name", "brand", "vendor", "model", "specialty", "status",
                      "account_status", "usage_url", "login_url", "base_url",
                      "fallback_note", "tier", "expires_at", "executable"):
            if field in payload and payload[field] is not None:
                agent[field] = payload[field]
        if "key_env" in payload and payload["key_env"]:
            ke = str(payload["key_env"]).strip()
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", ke):
                raise ValueError("key_env 只能是环境变量名（大写字母+下划线），绝不能填 Key 明文。")
            agent["key_env"] = ke
        self.save()
        return agent

    # ------------------------------------------------------------------
    # Action 4: moveagent (Drag & Drop between manager / worker / rest)
    # ------------------------------------------------------------------
    def moveagent(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self._find_agent(payload.get("id") or payload.get("agent_id"))
        new_floor = (payload.get("floor") or "").strip().lower()
        if new_floor not in ("manager", "worker", "rest"):
            raise ValueError("目标楼层只能是 manager（2楼经理）、worker（1楼员工）或 rest（院子休息）。")
        old_floor = agent["floor"]
        agent["floor"] = new_floor
        floor_names = {"manager": "2楼 经理层", "worker": "1楼 员工层", "rest": "院子休息"}
        agent["role_label"] = floor_names[new_floor]
        if new_floor == "rest" and agent["status"] == "ready":
            agent["status"] = "tired"
        elif new_floor in ("manager", "worker") and agent["status"] == "tired":
            agent["status"] = "ready"
        if old_floor != new_floor:
            chief = self._chief_agent()
            self._append_group_msg(
                sender_id=chief["id"],
                sender_name=chief["name"],
                kind="system_notice",
                text=f"🔄 岗位调动：**{agent['name']}** 已从「{floor_names.get(old_floor, old_floor)}」移至「**{floor_names[new_floor]}**」。",
            )
        self.save()
        return agent

    # ------------------------------------------------------------------
    # Action 5: deleteagent
    # ------------------------------------------------------------------
    def deleteagent(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = payload.get("id") or payload.get("agent_id")
        if agent_id in ("chief", "muse"):
            raise ValueError("总管是唯一对接口，不能移除。")
        before = len(self.state["agents"])
        self.state["agents"] = [a for a in self.state["agents"] if a["id"] != agent_id]
        if len(self.state["agents"]) == before:
            raise KeyError(f"找不到 Agent: {agent_id}")
        self.save()
        return {"deleted": agent_id}

    # ------------------------------------------------------------------
    # Action 6: setagentquota
    # ------------------------------------------------------------------
    def setagentquota(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self._find_agent(payload.get("id") or payload.get("agent_id"))
        if "quota_kind" in payload and payload["quota_kind"]:
            agent["quota_kind"] = payload["quota_kind"]
        if "percent_remaining" in payload or "quota_percent" in payload:
            raw = payload.get("percent_remaining", payload.get("quota_percent"))
            if raw is None or raw == "" or str(raw).lower() == "null":
                agent["quota_percent"] = None
            else:
                val = max(0.0, min(100.0, float(raw)))
                agent["quota_percent"] = val
                if val == 0 and agent["access_kind"] == "api":
                    agent["status"] = "exhausted"
                    agent["badge"] = "已耗尽·API"
                    agent["badge_color"] = "red"
        if "note" in payload or "quota_note" in payload:
            agent["quota_note"] = payload.get("note") or payload.get("quota_note") or ""
        self.save()
        return agent

    # ------------------------------------------------------------------
    # Action 7 & 8: listgroupmessages & postgroupmessage
    # ------------------------------------------------------------------
    def listgroupmessages(self) -> list[dict[str, Any]]:
        return self.state["group_messages"]

    def postgroupmessage(self, payload: dict[str, Any]) -> dict[str, Any]:
        sender_id = payload.get("sender_id") or "owner"
        text = (payload.get("text") or "").strip()
        if not text:
            raise ValueError("群聊消息内容不能为空。")
        if sender_id in ("owner", "gao"):
            sender_name = "你 (董事长)"
            sender_role = "chairman"
        else:
            ag = self._find_agent(sender_id)
            sender_name = ag["name"]
            sender_role = ag["floor"]
        msg = self._append_group_msg(
            sender_id=sender_id,
            sender_name=sender_name,
            sender_role=sender_role,
            kind=payload.get("kind") or "chat",
            text=text,
            task_id=payload.get("task_id"),
        )
        self.save()
        return msg

    # ------------------------------------------------------------------
    # Action 9 & 10: listtasks & createtask
    # ------------------------------------------------------------------
    def listtasks(self) -> dict[str, Any]:
        tasks = list(reversed(self.state["tasks"]))
        total = len(tasks)
        claimed = sum(1 for t in tasks if t["status"] in ("accepted", "working", "in_review", "delivered", "accepted_done"))
        reported = sum(1 for t in tasks if t.get("worker_reported"))
        delivered = sum(1 for t in tasks if t["status"] in ("delivered", "accepted_done"))
        accepted = sum(1 for t in tasks if t["status"] == "accepted_done")
        return {
            "tasks": tasks,
            "summary": {
                "total": total,
                "claimed": claimed,
                "reported": reported,
                "delivered": delivered,
                "accepted": accepted,
            },
        }

    def _pick_reviewer(self, assigned_id: str, manager: dict[str, Any], requested_id: str = "") -> dict[str, Any]:
        """Choose a reviewer strictly distinct from the coding author."""
        if requested_id:
            if requested_id == assigned_id:
                raise ValueError("写—审—改闭环铁律：写代码的 Agent 与审查 Agent 必须分开，不能自己审自己。")
            cand = self._find_agent(requested_id)
            if cand["floor"] == "rest" or cand["status"] == "exhausted":
                raise ValueError(f"审查 Agent {cand['name']} 正在休息或额度已耗尽，请换一位在线成员。")
            return cand
        for a in self.state["agents"]:
            if a["id"] != assigned_id and a["floor"] in ("manager", "worker") and a["status"] == "ready":
                if a.get("access_kind") in ("api", "cli"):
                    return a
        for a in self.state["agents"]:
            if a["id"] != assigned_id and a["floor"] in ("manager", "worker") and a["status"] == "ready":
                return a
        return manager

    def createtask(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = (payload.get("title") or "").strip()
        if not title:
            raise ValueError("任务标题不能为空。")
        chief = self._chief_agent()
        manager_id = payload.get("manager_id") or chief["id"]
        try:
            manager = self._find_agent(manager_id)
        except KeyError:
            manager = chief
        assigned_to = payload.get("assigned_to") or ""
        assigned_agent = self._find_agent(assigned_to) if assigned_to else None

        if assigned_agent and assigned_agent["floor"] == "manager" and not payload.get("allow_manager_execution"):
            raise ValueError(
                f"违反「小任务不请经理」规则：{assigned_agent['name']} 是 2楼经理，只负责动脑规划与审阅 diff/摘要，"
                "请将具体执行任务派给 1楼免费员工（或留空让员工在群里认领）。"
            )

        base_id = f"TASK-{int(time.time() * 1000) % 1000000}"
        existing_ids = {t["id"] for t in self.state["tasks"]}
        task_id = base_id if base_id not in existing_ids else f"{base_id}-{len(self.state['tasks']) + 1}"
        goal = (payload.get("goal") or title).strip()
        input_text = (payload.get("input_text") or "见工单说明").strip()
        output_format = (payload.get("output_format") or "按验收标准输出结构化结果，不讲废话").strip()
        acceptance = (payload.get("acceptance") or "结果完整、不编造数据、符合格式要求").strip()
        skill_slug = payload.get("skill_slug") or ""

        raw_kind = (payload.get("task_kind") or "").strip().lower()
        if raw_kind in ("code_change", "small"):
            task_kind = raw_kind
        elif payload.get("requires_code_review") is True:
            task_kind = "code_change"
        elif payload.get("requires_code_review") is False:
            task_kind = "small"
        else:
            task_kind = "code_change" if skill_slug in CODE_REVIEW_SKILL_SLUGS else "small"
        requires_code_review = task_kind == "code_change"

        # Idempotent work-order receipt: identical dispatch content returns the
        # existing task instead of creating a duplicate (double-click / retry safe).
        parent_task_id = (payload.get("parent_task_id") or "").strip()
        fp = self._request_fingerprint("createtask", {
            "title": title, "goal": goal, "input_text": input_text,
            "output_format": output_format, "acceptance": acceptance,
            "manager_id": manager["id"],
            "assigned_to": assigned_agent["id"] if assigned_agent else "",
            "parent_task_id": parent_task_id, "task_kind": task_kind,
            "skill_slug": skill_slug,
            "idempotency_key": payload.get("idempotency_key") or "",
        })
        if not payload.get("force_new"):
            prior = self._find_receipt(fp)
            if prior and prior.get("task_id"):
                try:
                    return self._find_task(prior["task_id"])
                except KeyError:
                    pass

        reviewer_id = ""
        reviewer_name = ""
        if requires_code_review:
            rev = self._pick_reviewer(
                assigned_id=assigned_agent["id"] if assigned_agent else "",
                manager=manager,
                requested_id=(payload.get("reviewer_id") or "").strip(),
            )
            reviewer_id = rev["id"]
            reviewer_name = rev["name"]

        task = {
            "id": task_id,
            "title": title,
            "manager_id": manager["id"],
            "manager_name": manager["name"],
            "assigned_to": assigned_agent["id"] if assigned_agent else "",
            "assigned_name": assigned_agent["name"] if assigned_agent else "待1楼员工认领",
            "assigned_vendor": assigned_agent["vendor"] if assigned_agent else "",
            "goal": goal,
            "input_text": input_text,
            "output_format": output_format,
            "acceptance": acceptance,
            "rule_footer": "只传结论、改动文件、测试结果，不传整段对话。不许自由发挥，不确定写「未核实」。",
            "skill_slug": skill_slug,
            "task_kind": task_kind,
            "requires_code_review": requires_code_review,
            "reviewer_id": reviewer_id,
            "reviewer_name": reviewer_name,
            "review_status": "pending_review" if requires_code_review else "not_needed",
            "review_issues": [],
            "revision_round": 0,
            "parent_task_id": parent_task_id,
            "is_parent": bool(payload.get("is_parent", False)),
            "subtask_ids": list(payload.get("subtask_ids") or []),
            "mode": (payload.get("mode") or "solo").strip().lower(),
            "circuit_breaker": "",
            "depends_on": list(payload.get("depends_on") or []),
            "status": "assigned",
            "worker_reported": False,
            "latest_report_summary": "",
            "final_delivery_text": "",
            "usage_log": [],
            "created_at": _now_iso(),
        }
        self.state["tasks"].append(task)
        review_line = (
            f"\n• **写—审—改闭环**：开启（改代码任务，写完由 **{reviewer_name}** 独立审查问题清单）"
            if requires_code_review
            else "\n• **流程档位**：小活直通（免代码审查，省 Token）"
        )
        self.state["task_messages"][task_id] = [
            {
                "id": f"tmsg-{int(time.time() * 1000)}",
                "task_id": task_id,
                "sender_id": manager["id"],
                "sender_name": manager["name"],
                "kind": "template_dispatch",
                "text": (
                    f"📋 **模板化指令下发（只传结论 · 省 Token）**\n"
                    f"• **目标**：{goal}\n"
                    f"• **输入**：{input_text}\n"
                    f"• **强制输出格式**：{output_format}\n"
                    f"• **验收标准**：{acceptance}\n"
                    f"• **汇报模板**：【结论】+【改动文件】+【测试结果】（不贴整段对话）"
                    f"{review_line}"
                ),
                "created_at": _now_iso(),
            }
        ]
        mention = f"@{assigned_agent['name']} " if assigned_agent else "@全体1楼员工 "
        self._append_group_msg(
            sender_id=manager["id"],
            sender_name=manager["name"],
            sender_role="manager",
            kind="task_card",
            task_id=task_id,
            text=(
                f"📌 **派发新任务卡片** `{task_id}` · **{title}**"
                + (" `写-审-改闭环`" if requires_code_review else " `小活省Token`")
                + f"\n{mention}请按模板执行：\n"
                f"• **目标**：{goal}\n"
                f"• **强制格式**：{output_format}\n"
                f"• **验收标准**：{acceptance}（**只传结论不贴对话**）"
            ),
        )
        self._record_flight(
            from_id=manager["id"],
            from_name=manager["name"],
            to_id=assigned_agent["id"] if assigned_agent else "workers",
            to_name=assigned_agent["name"] if assigned_agent else "1楼空闲员工池",
            kind="dispatch",
            task_id=task_id,
            summary=f"派单: {title[:24]}",
            channel=self._channel_label(assigned_agent) if assigned_agent else "工作台广播",
        )
        self._store_receipt(fp, "createtask", {"task_id": task_id})
        self.save()
        return task

    def seedexampletask(self) -> dict[str, Any]:
        idx = int(self.state.get("example_cursor", 0)) % len(GENERIC_EXAMPLE_TASKS)
        tpl = dict(GENERIC_EXAMPLE_TASKS[idx])
        chief = self._chief_agent()
        tpl["manager_id"] = chief["id"]
        ready_workers = [a for a in self.state["agents"] if a["floor"] == "worker" and a["status"] == "ready"]
        if ready_workers:
            tpl["assigned_to"] = ready_workers[0]["id"]
        self.state["example_cursor"] = idx + 1
        return self.createtask(tpl)

    # ------------------------------------------------------------------
    # Action 11: claimtask
    # ------------------------------------------------------------------
    def claimtask(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        worker_id = payload.get("worker_id") or task.get("assigned_to")
        if not worker_id:
            ready_workers = [a for a in self.state["agents"] if a["floor"] == "worker" and a["status"] == "ready"]
            if not ready_workers:
                raise ValueError("当前没有 1楼 员工可认领任务，请先点击左下角「➕ 招募新 AI Agent」或顶部「🎭 载入示例团队」。")
            worker = ready_workers[0]
        else:
            worker = self._find_agent(worker_id)
        if worker["floor"] == "rest" or worker["status"] == "exhausted":
            raise ValueError(f"{worker['name']} 当前在院子休息或额度已耗尽，请换其他免费员工认领！")

        task["assigned_to"] = worker["id"]
        task["assigned_name"] = worker["name"]
        task["assigned_vendor"] = worker["vendor"]
        task["status"] = "working"
        if task.get("requires_code_review") and (not task.get("reviewer_id") or task.get("reviewer_id") == worker["id"]):
            mgr = self._find_agent(task["manager_id"]) if task.get("manager_id") else self._chief_agent()
            rev = self._pick_reviewer(assigned_id=worker["id"], manager=mgr)
            task["reviewer_id"] = rev["id"]
            task["reviewer_name"] = rev["name"]

        self._append_task_msg(
            task["id"],
            sender_id=worker["id"],
            sender_name=worker["name"],
            kind="system",
            text=f"✋ {worker['name']}（{worker['badge']}）已接单并开始执行，建立与经理 {task['manager_name']} 的独立私聊汇报线。",
        )
        self._append_group_msg(
            sender_id=worker["id"],
            sender_name=worker["name"],
            sender_role="worker",
            kind="claim_notice",
            task_id=task["id"],
            text=f"✋ **{worker['name']}**（`{worker['badge']}`）已领取任务 `{task['id']}`《{task['title']}》，正在执行中（只传结论汇报，不刷群）。",
        )
        self._record_flight(
            from_id=worker["id"],
            from_name=worker["name"],
            to_id=task["manager_id"],
            to_name=task["manager_name"],
            kind="claim",
            task_id=task["id"],
            summary="接单开工",
            channel=self._channel_label(worker),
        )
        self.save()
        return task

    # ------------------------------------------------------------------
    # Action 12 & 13: listmessages & postmessage (Conclusion-Only Report)
    # ------------------------------------------------------------------
    def listmessages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        task_id = payload.get("task_id") or payload.get("id")
        return self.state["task_messages"].get(task_id, [])

    def _reject_full_conversation_paste(self, text: str) -> None:
        """Prevent pasting raw multi-turn chat transcripts instead of conclusions."""
        turn_markers = len(re.findall(r"(?im)^(user|assistant|human|ai|老板|员工)\s*[:：]", text))
        if turn_markers >= 3 or (len(text) > 1600 and "【结论】" not in text):
            raise ValueError(
                "结论-only 拦截：禁止粘贴整段聊天记录或超长全文！请只填【结论】+【改动文件】+【测试结果】。"
            )

    def postmessage(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id"))
        chief = self._chief_agent()
        sender_id = payload.get("sender_id") or task.get("assigned_to") or chief["id"]
        if sender_id in ("owner", "gao"):
            sender: dict[str, Any] = {"id": "owner", "name": "你 (董事长)", "access_kind": "chief"}
        else:
            sender = self._find_agent(sender_id)

        is_delivery = bool(payload.get("is_delivery", True))
        conclusion = (payload.get("conclusion") or "").strip()
        changed_files = payload.get("changed_files")
        test_result = (payload.get("test_result") or "").strip()
        diff_summary = (payload.get("diff_summary") or "").strip()

        if conclusion:
            text = format_conclusion_report(
                conclusion=conclusion,
                changed_files=changed_files,
                test_result=test_result or "未运行测试",
                diff_summary=diff_summary,
            )
            report_meta = {
                "conclusion": conclusion,
                "changed_files": changed_files if isinstance(changed_files, list) else ([changed_files] if changed_files else []),
                "test_result": test_result or "未运行测试",
            }
        else:
            text = (payload.get("text") or "").strip()
            if not text:
                raise ValueError("私聊汇报内容不能为空。")
            if is_delivery:
                self._reject_full_conversation_paste(text)
            report_meta = None

        msg = self._append_task_msg(
            task["id"],
            sender_id=sender["id"],
            sender_name=sender["name"],
            kind="worker_report" if is_delivery else "private_chat",
            text=text,
            usage=payload.get("usage"),
        )
        if report_meta:
            msg["report_meta"] = report_meta

        if is_delivery:
            if sender["id"] not in ("owner", "gao"):
                sender["session_count"] = int(sender.get("session_count") or 0) + 1
            task["worker_reported"] = True
            task["latest_report_summary"] = text[:320] + ("..." if len(text) > 320 else "")
            if task.get("requires_code_review"):
                task["status"] = "in_review"
                task["review_status"] = "pending_review"
                if not task.get("reviewer_id") or task.get("reviewer_id") == sender["id"]:
                    mgr = self._find_agent(task["manager_id"]) if task.get("manager_id") else chief
                    rev = self._pick_reviewer(assigned_id=sender["id"], manager=mgr)
                    task["reviewer_id"] = rev["id"]
                    task["reviewer_name"] = rev["name"]
            elif task["status"] in ("assigned", "accepted"):
                task["status"] = "working"

            self._append_group_msg(
                sender_id=sender["id"],
                sender_name=sender["name"],
                sender_role="worker",
                kind="private_report_lock",
                task_id=task["id"],
                text=(
                    f"🔒 **{sender['name']}** 已向 **@{task['manager_name']}** 提交结论-only 汇报（`{task['id']}` · {len(text)} 字摘要已折叠，经理不重读对话）。"
                    + (f" 已自动飞书交给独立审查 **@{task['reviewer_name']}** 挑刺。" if task.get("requires_code_review") else "")
                ),
            )
            self._record_flight(
                from_id=sender["id"],
                from_name=sender["name"],
                to_id=task["reviewer_id"] if task.get("requires_code_review") else task["manager_id"],
                to_name=task["reviewer_name"] if task.get("requires_code_review") else task["manager_name"],
                kind="review_send" if task.get("requires_code_review") else "report",
                task_id=task["id"],
                summary=f"结论汇报 ({len(text)}字)" + (" → 等审查" if task.get("requires_code_review") else ""),
                channel=self._channel_label(sender),
            )
        self.save()
        return msg

    # ------------------------------------------------------------------
    # Action 13b: submitcodereview (Write -> Review -> Revise Loop)
    # ------------------------------------------------------------------
    def submitcodereview(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Independent reviewer submits ONLY an issue checklist (or pass) for code_change tasks."""
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        if not task.get("requires_code_review"):
            raise ValueError("该任务属于小活，未开启写—审—改闭环（避免空耗审查 Token）。")

        chief = self._chief_agent()
        reviewer_id = (payload.get("reviewer_id") or task.get("reviewer_id") or "").strip()
        if not reviewer_id:
            mgr = self._find_agent(task["manager_id"]) if task.get("manager_id") else chief
            reviewer = self._pick_reviewer(assigned_id=task.get("assigned_to") or "", manager=mgr)
        else:
            reviewer = self._pick_reviewer(assigned_id=task.get("assigned_to") or "", manager=chief, requested_id=reviewer_id)

        dry_run = bool(payload.get("dry_run", False))
        passed = bool(payload.get("passed", False))
        raw_issues = payload.get("issues") or []
        if isinstance(raw_issues, str):
            issues = [ln.strip(" -•\t") for ln in raw_issues.splitlines() if ln.strip()]
        elif isinstance(raw_issues, list):
            issues = [str(x).strip() for x in raw_issues if str(x).strip()]
        else:
            issues = []

        joined = "\n".join(issues)
        if len(joined) > 2500 or "```" in joined and len(joined) > 800:
            raise ValueError("审查红线：只回问题清单（文件/行号/原因），不要贴大段全文代码。")

        if dry_run and not issues and not payload.get("simulate_reject"):
            passed = True
        elif dry_run and payload.get("simulate_reject") and not issues:
            passed = False
            issues = ["[干跑演练问题1] calc_discount(100, -0.1) 未校验负数折扣率，请补 ValueError 断言与实现。"]

        if not passed and not issues:
            raise ValueError("审查不通过打回时，必须给出至少 1 条精简问题清单。")

        task["reviewer_id"] = reviewer["id"]
        task["reviewer_name"] = reviewer["name"]
        reviewer["session_count"] = int(reviewer.get("session_count") or 0) + 1

        if passed:
            task["review_status"] = "approved"
            task["review_issues"] = []
            task["circuit_breaker"] = ""
            task["status"] = "working"
            msg_text = (
                f"✅ **独立代码审查通过**（审查者：{reviewer['name']} · 写代码与审查已分开）\n"
                f"• 问题清单：无阻断问题（可由经理统筹交付）"
            )
            self._append_task_msg(task["id"], sender_id=reviewer["id"], sender_name=reviewer["name"], kind="code_review_pass", text=msg_text)
            self._append_group_msg(
                sender_id=reviewer["id"],
                sender_name=reviewer["name"],
                sender_role=reviewer.get("floor", "manager"),
                kind="review_notice",
                task_id=task["id"],
                text=f"✅ **审查通过** `{task['id']}`（{reviewer['name']} 只读摘要+diff 确认无阻断项，可交付）。",
            )
            self._record_flight(
                from_id=reviewer["id"],
                from_name=reviewer["name"],
                to_id=task["manager_id"],
                to_name=task["manager_name"],
                kind="review_pass",
                task_id=task["id"],
                summary="审查通过 (0阻断)",
                channel=self._channel_label(reviewer),
            )
        else:
            max_rounds = int(self.state.get("settings", {}).get("max_revision_rounds", MAX_REVISION_ROUNDS))
            current_round = int(task.get("revision_round") or 0)
            task["review_status"] = "changes_requested"
            task["review_issues"] = issues
            checklist_md = "\n".join(f"  {idx + 1}. {item}" for idx, item in enumerate(issues))
            if current_round >= max_rounds:
                # Pass circuit breaker: stop the write->review->revise ping-pong
                # so two models never burn quota arguing forever. Escalate to the
                # 2F manager / owner instead of looping again.
                task["circuit_breaker"] = "revision_limit"
                task["status"] = "rejected"
                esc_name = task.get("manager_name") or "总管"
                breaker_text = (
                    f"⛔ **写—审—改熔断（已达 {max_rounds} 轮打回上限）** `{task['id']}`\n"
                    f"• 审查者 {reviewer['name']} 第 {current_round + 1} 次打回被拦截，自动停下。\n"
                    f"• 升级给 **@{esc_name}** / 主人裁决，不再继续烧额度互改。\n"
                    f"• 遗留问题清单：\n{checklist_md}"
                )
                self._append_task_msg(task["id"], sender_id=reviewer["id"], sender_name=reviewer["name"], kind="circuit_breaker", text=breaker_text)
                self._append_group_msg(
                    sender_id=reviewer["id"], sender_name=reviewer["name"],
                    sender_role=reviewer.get("floor", "manager"), kind="circuit_breaker",
                    task_id=task["id"], text=breaker_text,
                )
                self._record_flight(
                    from_id=reviewer["id"], from_name=reviewer["name"],
                    to_id=task.get("manager_id") or "owner", to_name=esc_name,
                    kind="circuit_breaker", task_id=task["id"],
                    summary=f"打回超限熔断 ({max_rounds}轮)", channel=self._channel_label(reviewer),
                )
                self.save()
                return task
            task["revision_round"] = current_round + 1
            task["status"] = "rejected"
            msg_text = (
                f"↩ **独立审查打回重做（第 {task['revision_round']} 轮 · 只回问题清单，不回全文）**\n"
                f"• 审查者：{reviewer['name']} → 退回给：{task['assigned_name']}\n"
                f"• 问题清单：\n{checklist_md}"
            )
            self._append_task_msg(task["id"], sender_id=reviewer["id"], sender_name=reviewer["name"], kind="code_review_reject", text=msg_text)
            self._append_group_msg(
                sender_id=reviewer["id"],
                sender_name=reviewer["name"],
                sender_role=reviewer.get("floor", "manager"),
                kind="review_notice",
                task_id=task["id"],
                text=f"↩ **审查打回重做** `{task['id']}`：{reviewer['name']} 列出 {len(issues)} 条问题清单，飞回给 **@{task['assigned_name']}** 修改。",
            )
            self._record_flight(
                from_id=reviewer["id"],
                from_name=reviewer["name"],
                to_id=task.get("assigned_to") or "workers",
                to_name=task["assigned_name"],
                kind="review_reject",
                task_id=task["id"],
                summary=f"打回 ({len(issues)} 项问题)",
                channel=self._channel_label(reviewer),
            )
        self.save()
        return task

    # ------------------------------------------------------------------
    # Action 14: updatetaskstatus
    # ------------------------------------------------------------------
    def updatetaskstatus(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        new_status = payload.get("status")
        valid = ("assigned", "accepted", "working", "in_review", "delivered", "accepted_done", "rejected")
        if new_status not in valid:
            raise ValueError(f"状态必须是 {valid} 之一。")
        task["status"] = new_status
        chief = self._chief_agent()
        self._append_task_msg(
            task["id"],
            sender_id=chief["id"],
            sender_name=chief["name"],
            kind="system",
            text=f"📌 任务状态更新为：{new_status}",
        )
        self.save()
        return task

    # ------------------------------------------------------------------
    # Action 15: reassigntask (Enforce DIFFERENT VENDOR ONLY!)
    # ------------------------------------------------------------------
    def reassigntask(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        to_worker_id = payload.get("to_worker_id") or payload.get("worker_id")
        target = self._find_agent(to_worker_id)
        reason = (payload.get("reason") or "当前员工今日额度累了/限流，轮换给别家免费员工").strip()

        old_worker_id = task.get("assigned_to")
        old_vendor = (task.get("assigned_vendor") or "").strip()
        old_name = task.get("assigned_name") or "未指派"
        if old_worker_id:
            try:
                old_agent = self._find_agent(old_worker_id)
                old_vendor = old_agent["vendor"]
                old_name = old_agent["name"]
            except KeyError:
                pass

        if old_vendor and target["vendor"].strip().lower() == old_vendor.strip().lower():
            raise ValueError(
                f"违反「免费农场不同厂商轮换」规则：当前执行者 {old_name} 与目标 {target['name']} "
                f"同属厂商「{target['vendor']}」。转交只允许转给不同厂商的免费员工，禁止同厂商内倒手消耗同一套额度池！"
            )
        if target["floor"] == "rest" or target["status"] == "exhausted":
            raise ValueError(f"无法转交给 {target['name']}：该成员正在院子休息或额度为 0%。")

        task["assigned_to"] = target["id"]
        task["assigned_name"] = target["name"]
        task["assigned_vendor"] = target["vendor"]
        task["status"] = "working"

        chief = self._chief_agent()
        note = (
            f"↪ **跨厂商轮换转交**：由 **{old_name}**（{old_vendor or '原通道'}）转交给 "
            f"**@{target['name']}**（{target['vendor']} · `{target['badge']}`）。原因：{reason}"
        )
        self._append_task_msg(task["id"], sender_id=chief["id"], sender_name=chief["name"], kind="transfer", text=note)
        self._append_group_msg(
            sender_id=chief["id"],
            sender_name=chief["name"],
            sender_role="chief",
            kind="transfer_notice",
            task_id=task["id"],
            text=note,
        )
        self._record_flight(
            from_id=old_worker_id or chief["id"],
            from_name=old_name,
            to_id=target["id"],
            to_name=target["name"],
            kind="transfer",
            task_id=task["id"],
            summary=f"跨厂转交 ({target['vendor']})",
            channel=self._channel_label(target),
        )
        self.save()
        return task

    # ------------------------------------------------------------------
    # Action 16: deletetask
    # ------------------------------------------------------------------
    def deletetask(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = payload.get("task_id") or payload.get("id")
        self.state["tasks"] = [t for t in self.state["tasks"] if t["id"] != task_id]
        self.state["task_messages"].pop(task_id, None)
        self.save()
        return {"deleted": task_id}

    # ------------------------------------------------------------------
    # Action 17: deliverfinalresult
    # ------------------------------------------------------------------
    def deliverfinalresult(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        if task.get("requires_code_review") and task.get("review_status") != "approved":
            raise ValueError(
                f"写—审—改闭环拦截：改代码任务 `{task['id']}` 必须先经独立审查 Agent（{task.get('reviewer_name') or '待指定'}）审查通过，当前审查状态：{task.get('review_status')}。"
            )
        chief = self._chief_agent()
        manager_id = payload.get("manager_id") or task["manager_id"] or chief["id"]
        try:
            manager = self._find_agent(manager_id)
        except KeyError:
            manager = chief
        summary = (payload.get("final_text") or payload.get("summary") or "").strip()
        if not summary:
            report_preview = task.get("latest_report_summary") or "（员工已完成规定格式产出，质检通过）"
            summary = (
                f"经 **{manager['name']}** 抽查 diff/结论摘要核验通过（未重读对话全文，节省经理 Token）：\n"
                f"• 执行员工：**{task['assigned_name']}**\n"
                + (f"• 独立审查：**{task.get('reviewer_name')}**（✅ 问题清单清零）\n" if task.get("requires_code_review") else "")
                + f"• 成果摘要：\n{report_preview}"
            )
        task["final_delivery_text"] = summary
        task["status"] = "delivered"

        self._append_task_msg(
            task["id"],
            sender_id=manager["id"],
            sender_name=manager["name"],
            kind="final_delivery",
            text=f"🏁 经理已统筹交付总结果给董事长：\n{summary}",
        )
        self._append_group_msg(
            sender_id=manager["id"],
            sender_name=manager["name"],
            sender_role="manager",
            kind="final_delivery_card",
            task_id=task["id"],
            text=f"🏁 **最终交付 · 总结果 · 给 董事长 (You)**\n任务：`{task['id']}` 《{task['title']}》\n@你 (董事长) 请验收：\n\n{summary}",
        )
        self._record_flight(
            from_id=manager["id"],
            from_name=manager["name"],
            to_id="owner",
            to_name="你 (董事长)",
            kind="deliver",
            task_id=task["id"],
            summary="统筹交付待验收",
            channel="结论摘要",
        )
        self.save()
        return task

    # ------------------------------------------------------------------
    # Action 18: reviewfinalresult
    # ------------------------------------------------------------------
    def reviewfinalresult(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        decision = (payload.get("decision") or "verified").strip().lower()
        comment = (payload.get("comment") or "").strip()
        if decision in ("verified", "accepted", "pass", "accept"):
            if task.get("requires_code_review") and task.get("review_status") != "approved":
                raise ValueError("写—审—改闭环拦截：代码审查尚未通过，不能直接标记验收完成。")
            task["status"] = "accepted_done"
            text = f"✅ **你 (董事长) 已验收通过** 任务 `{task['id']}`《{task['title']}》！" + (f" 批注：{comment}" if comment else "")
            fl_summary = "董事长验收通过"
        else:
            task["status"] = "rejected"
            text = f"↩ **你 (董事长) 打回重做** 任务 `{task['id']}`《{task['title']}》！" + (f" 原因：{comment}" if comment else " 请按验收标准修正后重新汇报。")
            fl_summary = "董事长打回重做"

        self._append_task_msg(task["id"], sender_id="owner", sender_name="你 (董事长)", kind="review", text=text)
        self._append_group_msg(
            sender_id="owner",
            sender_name="你 (董事长)",
            sender_role="chairman",
            kind="review_notice",
            task_id=task["id"],
            text=text,
        )
        self._record_flight(
            from_id="owner",
            from_name="你 (董事长)",
            to_id=task["manager_id"],
            to_name=task["manager_name"],
            kind="review_pass" if task["status"] == "accepted_done" else "review_reject",
            task_id=task["id"],
            summary=fl_summary,
            channel="人工验收",
        )
        self.save()
        return task

    # ------------------------------------------------------------------
    # Action 19–25: Skill Center
    # ------------------------------------------------------------------
    def listskills(self) -> dict[str, Any]:
        skills = self.state["skills"]
        agents = self.state["agents"]
        equipped_map: dict[str, list[dict[str, str]]] = {s["slug"]: [] for s in skills}
        for ag in agents:
            for sk_slug in ag.get("skills", []):
                if sk_slug in equipped_map:
                    equipped_map[sk_slug].append({
                        "id": ag["id"],
                        "name": ag["name"],
                        "floor": ag["floor"],
                        "badge": ag["badge"],
                    })
        by_floor = {
            "manager": [
                {"id": a["id"], "name": a["name"], "badge": a["badge"], "skills": a.get("skills", [])}
                for a in agents if a["floor"] == "manager"
            ],
            "worker": [
                {"id": a["id"], "name": a["name"], "badge": a["badge"], "skills": a.get("skills", [])}
                for a in agents if a["floor"] == "worker"
            ],
            "rest": [
                {"id": a["id"], "name": a["name"], "badge": a["badge"], "skills": a.get("skills", [])}
                for a in agents if a["floor"] == "rest"
            ],
        }
        return {"skills": skills, "equipped_by": equipped_map, "by_floor": by_floor}

    def createskill(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("技能名称不能为空。")
        slug = (payload.get("slug") or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"))
        if not slug or any(s["slug"] == slug for s in self.state["skills"]):
            slug = f"skill-{int(time.time() * 1000) % 100000}"
        sk = {
            "slug": slug,
            "name": name,
            "category": (payload.get("category") or "自定义技能").strip(),
            "description": (payload.get("description") or "").strip(),
            "steps": (payload.get("steps") or "1. 按模板输入 2. 固定格式输出 3. 不许自由发挥").strip(),
            "best_for": (payload.get("best_for") or "1楼免费员工").strip(),
            "keywords": payload.get("keywords") or [name],
            "savings_note": (payload.get("savings_note") or "固定流程减少员工自由发挥，省额度").strip(),
        }
        self.state["skills"].append(sk)
        self.save()
        return sk

    def updateskill(self, payload: dict[str, Any]) -> dict[str, Any]:
        slug = payload.get("slug")
        for sk in self.state["skills"]:
            if sk["slug"] == slug:
                for k in ("name", "category", "description", "steps", "best_for", "keywords", "savings_note"):
                    if k in payload and payload[k] is not None:
                        sk[k] = payload[k]
                self.save()
                return sk
        raise KeyError(f"找不到技能: {slug}")

    def deleteskill(self, payload: dict[str, Any]) -> dict[str, Any]:
        slug = payload.get("slug")
        self.state["skills"] = [s for s in self.state["skills"] if s["slug"] != slug]
        for ag in self.state["agents"]:
            if slug in ag.get("skills", []):
                ag["skills"] = [x for x in ag["skills"] if x != slug]
        self.save()
        return {"deleted": slug}

    def setagentskill(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self._find_agent(payload.get("agent_id") or payload.get("id"))
        skill_slug = payload.get("skill_slug") or payload.get("slug")
        equip = bool(payload.get("equip", True))
        skills = list(agent.get("skills") or [])
        if equip and skill_slug not in skills:
            skills.append(skill_slug)
        elif not equip and skill_slug in skills:
            skills.remove(skill_slug)
        agent["skills"] = skills
        self.save()
        return agent

    def analyzeskillassignments(self, payload: dict[str, Any]) -> dict[str, Any]:
        chief = self._chief_agent()
        judge_id = payload.get("judge_id") or chief["id"]
        try:
            judge_name = self._find_agent(judge_id)["name"]
        except KeyError:
            judge_name = str(judge_id)
        recs = analyze_skill_assignments(self.state["agents"], self.state["skills"], judge=judge_name)
        return {"judge": judge_name, "recommendations": recs}

    def applyskillassignments(self, payload: dict[str, Any]) -> dict[str, Any]:
        chief = self._chief_agent()
        judge_name = payload.get("judge") or chief["name"]
        assignments = payload.get("assignments") or []
        applied = []
        for item in assignments:
            ag = self._find_agent(item["agent_id"])
            sk_slug = item["skill_slug"]
            if sk_slug not in ag.get("skills", []):
                ag.setdefault("skills", []).append(sk_slug)
                applied.append(f"{ag['name']} ➕ 装配「{item.get('skill_name', sk_slug)}」")
        if applied:
            self._append_group_msg(
                sender_id=chief["id"],
                sender_name=judge_name,
                sender_role="chief",
                kind="skill_judge_notice",
                text=(
                    f"🧠 **技能中心 · 高级模型裁判通知（裁判：{judge_name}，经你勾选批准）**\n"
                    f"已为团队成员装配以下固定流程 Skill（减少自由思考、提高准确度、省免费额度）：\n• "
                    + "\n• ".join(applied)
                ),
            )
        self.save()
        return {"applied_count": len(applied), "applied": applied}

    # ------------------------------------------------------------------
    # Extra: Bridge to Real AgentAdapter / Sync Profiles / Export Task MD
    # ------------------------------------------------------------------
    def runadaptertask(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id"))
        live = bool(payload.get("live", False))
        worker_id = payload.get("worker_id") or task.get("assigned_to")
        if not worker_id:
            ready_workers = [a for a in self.state["agents"] if a["floor"] == "worker" and a["status"] == "ready"]
            if not ready_workers:
                raise ValueError("当前没有 1楼 员工可执行，请先招募至少 1 名员工或载入示例团队。")
            worker = ready_workers[0]
        else:
            worker = self._find_agent(worker_id)

        prompt = (
            f"你是执行员工，只做下面这件事，不要做决定。\n"
            f"任务：{task['goal']}\n"
            f"输入：\n{task['input_text']}\n"
            f"输出格式：{task['output_format']}\n"
            f"验收标准：{task['acceptance']}\n"
            f"汇报规范：只回【结论】【改动文件】【测试结果】三项结论，不贴整段对话，不许自由发挥，不确定写「未核实」。"
        )
        if not live:
            dry_conclusion = f"[干跑演练 0消耗] 已模拟路由给 {worker['name']}（{worker['badge']}），降级链就绪。"
            dry_text = format_conclusion_report(
                conclusion=dry_conclusion,
                changed_files="无（干跑演练未改文件）",
                test_result="0 Token 干跑路由通过（未发起付费外部调用）",
                diff_summary=f"通道={worker['access_kind']} | 失败2次才升级给经理 {task['manager_name']}",
            )
            self.postmessage({
                "task_id": task["id"],
                "sender_id": worker["id"],
                "conclusion": dry_conclusion,
                "changed_files": ["无（干跑演练）"],
                "test_result": "0 Token 干跑通过",
                "diff_summary": f"通道={worker['access_kind']} | 降级链就绪",
                "is_delivery": True,
                "usage": {"dry_run": True, "prompt_tokens": 0, "completion_tokens": 0},
            })
            return {"mode": "dry_run", "worker": worker["name"], "text": dry_text}

        if worker.get("access_kind") in ("web", "subscription", "desktop"):
            raise RuntimeError(
                f"{worker['name']} 属于「{worker['badge']}」通道：网页端请点「🌐 打开网页 + 复制指令」，"
                "桌面应用端请点「📂 导出 .md + 复制 @触发句」。「🚀 真调执行」仅用于 API 直连与 CLI 命令行通道。"
            )
        workspace_dir = self._validate_safe_workspace(payload.get("workspace_dir") or worker.get("workspace") or ".")

        # Idempotent live execution: a retry / double-click of the SAME task at the
        # SAME revision round must not call the API (burn free quota) twice.
        live_fp = self._request_fingerprint("runadaptertask_live", {
            "task_id": task["id"],
            "worker_id": worker["id"],
            "workspace_dir": workspace_dir,
            "revision_round": int(task.get("revision_round") or 0),
            "idempotency_key": payload.get("idempotency_key") or "",
        })
        prior_live = self._find_receipt(live_fp)
        if prior_live and prior_live.get("mode") == "live":
            return {
                "mode": "live", "worker": prior_live.get("worker", worker["name"]),
                "reply": prior_live.get("reply", ""), "usage": prior_live.get("usage", {}),
                "attempts": prior_live.get("attempts", 1), "idempotent_replay": True,
            }

        # Build fallback chain: current worker -> other ready API/CLI workers -> ready API/CLI managers
        worker_candidates: list[dict[str, Any]] = [worker]
        seen_vendors = {(worker.get("vendor") or "").lower()}
        for a in self.state["agents"]:
            if a["id"] == worker["id"] or a.get("floor") != "worker" or a.get("status") != "ready":
                continue
            if a.get("access_kind") not in ("api", "cli"):
                continue
            v_low = (a.get("vendor") or "").lower()
            if v_low and v_low in seen_vendors:
                continue
            seen_vendors.add(v_low)
            worker_candidates.append(a)

        manager_candidates = [
            a for a in self.state["agents"]
            if a.get("floor") == "manager"
            and a.get("status") == "ready"
            and a.get("access_kind") in ("api", "cli")
        ]

        attempts_log: list[str] = []
        failures = 0
        last_err: Exception | None = None
        chosen_agent: dict[str, Any] | None = None
        reply = None

        for cand in worker_candidates:
            try:
                adapter = self._build_adapter(cand, workspace_dir=workspace_dir)
                reply = adapter.chat(prompt)
                chosen_agent = cand
                break
            except Exception as e:  # noqa: BLE001 - fall back to next worker
                failures += 1
                last_err = e
                attempts_log.append(f"❌ {cand['name']} 失败: {e}")
                if failures >= 2:
                    break

        if reply is None and failures >= 2:
            for mgr in manager_candidates:
                try:
                    adapter = self._build_adapter(mgr, workspace_dir=workspace_dir)
                    mgr_prompt = (
                        f"已有 {failures} 名免费员工连续失败（最近错误：{last_err}），按规矩升级由经理接手。\n"
                        + prompt
                    )
                    reply = adapter.chat(mgr_prompt)
                    chosen_agent = mgr
                    attempts_log.append(f"🆙 连续 {failures} 名员工失败，已升级经理 {mgr['name']} 接盘成功")
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    attempts_log.append(f"❌ 经理 {mgr['name']} 失败: {e}")

        if reply is None or chosen_agent is None:
            detail = "\n".join(attempts_log) if attempts_log else str(last_err)
            raise RuntimeError(f"员工降级与经理升级均未成功：\n{detail}")

        usage_info = {
            "live": True,
            "model": reply.model,
            "usage": reply.usage,
            "rate_limit_remaining": reply.rate_limit_remaining,
            "attempts": failures + 1,
        }
        # Accumulate real observed token count only (never fabricate when missing)
        tok_total = 0
        if isinstance(reply.usage, dict):
            tok_total = int(
                reply.usage.get("total_tokens")
                or (int(reply.usage.get("prompt_tokens") or 0) + int(reply.usage.get("completion_tokens") or 0))
            )
        fallback_trace = (" | ".join(attempts_log)) if attempts_log else "直调命中"
        conc_line = (reply.text or "").strip().splitlines()[0][:200] if (reply.text or "").strip() else "已完成"
        # Brief critical section: the network call above ran lock-free so parallel
        # subtasks stay concurrent; only the shared-state writes are serialized.
        with self._lock:
            if chosen_agent["id"] != worker["id"]:
                task["assigned_to"] = chosen_agent["id"]
                task["assigned_name"] = chosen_agent["name"]
                task["assigned_vendor"] = chosen_agent["vendor"]
            task.setdefault("usage_log", []).append(usage_info)
            chosen_agent["tokens_used"] = int(chosen_agent.get("tokens_used") or 0) + tok_total
            self._record_savings(chosen_agent, tok_total, task["id"], "execute")
            if reply.rate_limit_remaining:
                chosen_agent["quota_note"] = f"上次调用响应头剩余次数：{json.dumps(reply.rate_limit_remaining, ensure_ascii=False)}"
            self._store_receipt(live_fp, "runadaptertask_live", {
                "mode": "live", "worker": chosen_agent["name"], "task_id": task["id"],
                "reply": reply.text, "usage": usage_info, "attempts": failures + 1,
            })
            self.postmessage({
                "task_id": task["id"],
                "sender_id": chosen_agent["id"],
                "conclusion": f"[{chosen_agent['name']} ({reply.model})] {conc_line}",
                "changed_files": ["见本地工作区 git diff"],
                "test_result": f"Token={tok_total} | 调度={fallback_trace}",
                "diff_summary": (reply.text or "")[:300],
                "is_delivery": True,
                "usage": usage_info,
            })
        return {"mode": "live", "worker": chosen_agent["name"], "reply": reply.text, "usage": usage_info, "attempts": failures + 1}

    def checklivequota(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent = self._find_agent(payload.get("agent_id") or payload.get("id"))
        slug = agent.get("adapter_slug") or ""
        if slug in registered_slugs():
            if slug == "custom-api" and agent.get("base_url") and agent.get("key_env"):
                adapter = get_adapter(
                    "custom-api",
                    vendor=agent["vendor"],
                    model_id=agent["model"],
                    base_url=agent["base_url"],
                    key_env=agent["key_env"],
                    paid=agent["paid"],
                )
            elif slug == "cli-generic" and agent.get("executable"):
                adapter = get_adapter(
                    "cli-generic",
                    vendor=agent["vendor"],
                    model_id=agent["model"],
                    executable=agent["executable"],
                    paid=agent["paid"],
                )
            else:
                adapter = get_adapter(slug)
            q = adapter.check_quota()
            if q.percent_remaining is not None:
                agent["quota_percent"] = q.percent_remaining
            if q.note:
                agent["quota_note"] = q.note
            if getattr(q, "available_models", None):
                agent["available_models"] = q.available_models
            if getattr(q, "tier", None) and q.tier != "待核实" and not agent.get("tier"):
                agent["tier"] = q.tier
            if getattr(q, "expires_at", None) and not agent.get("expires_at"):
                agent["expires_at"] = q.expires_at
            agent["last_synced_at"] = _now_iso()
            self.save()
            return {
                "agent": agent,
                "checked": {
                    "kind": q.kind,
                    "percent_remaining": q.percent_remaining,
                    "note": q.note,
                    "tier": getattr(q, "tier", "待核实"),
                    "available_models": getattr(q, "available_models", []),
                },
            }
        agent["last_synced_at"] = _now_iso()
        self.save()
        return {
            "agent": agent,
            "checked": {
                "kind": "unknown",
                "percent_remaining": agent.get("quota_percent"),
                "note": agent.get("quota_note"),
                "tier": agent.get("tier", "待核实"),
                "available_models": agent.get("available_models", []),
            },
        }

    def syncprofiles(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        synced = []
        now = _now_iso()
        for agent in self.state["agents"]:
            slug = agent.get("adapter_slug") or ""
            if agent.get("access_kind") == "api" and slug in registered_slugs():
                key_env = agent.get("key_env") or ""
                if key_env and os.environ.get(key_env, "").strip():
                    res = self.checklivequota({"id": agent["id"]})
                    synced.append({"id": agent["id"], "mode": "api_live", "note": res["checked"]["note"]})
                else:
                    agent["last_synced_at"] = now
                    synced.append({"id": agent["id"], "mode": "api_no_key", "note": "环境变量未设"})
            else:
                sdir = session_dir(agent["id"])
                has_session = (sdir / "session_meta.json").exists()
                agent["local_session_ready"] = has_session
                agent["last_synced_at"] = now
                synced.append({"id": agent["id"], "mode": "web_or_desktop", "session": has_session})
        self.save()
        return {"synced_at": now, "count": len(synced), "details": synced}

    def exporttaskmd(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        custom_ws = (payload.get("workspace_dir") or "").strip()
        if custom_ws:
            safe_ws = self._validate_safe_workspace(custom_ws)
            base_dir = Path(safe_ws)
            out_dir = base_dir / "tasks" / "inbox"
            rel_path = f"tasks/inbox/{task['id']}.md"
        else:
            base_dir = Path(__file__).resolve().parents[1]
            out_dir = base_dir / "ai-team" / "tasks" / "inbox"
            rel_path = f"ai-team/tasks/inbox/{task['id']}.md"
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{task['id']}.md"

        sub_model_hint = ""
        worker_id = task.get("assigned_to") or ""
        if worker_id:
            try:
                w = self._find_agent(worker_id)
                subs = w.get("sub_models") or []
                if subs:
                    sub_model_hint = f"\n- **建议切换内置子模型**：{subs[0]}（优先使用最低倍率/限时免费档）"
            except KeyError:
                pass

        md_body = (
            f"# 工单 {task['id']} — {task['title']}\n\n"
            f"- **派单经理**：{task['manager_name']}\n"
            f"- **执行员工**：{task['assigned_name']}{sub_model_hint}\n"
            f"- **状态**：{task['status']}\n\n"
            f"## 1. 目标\n{task['goal']}\n\n"
            f"## 2. 输入\n{task['input_text']}\n\n"
            f"## 3. 强制输出格式\n{task['output_format']}\n\n"
            f"## 4. 验收标准\n{task['acceptance']}\n\n"
            f"## 5. 结论-only 汇报模板（不贴全文对话）\n"
            f"- 【结论】1-2句总结\n"
            f"- 【改动文件】路径列表或 无\n"
            f"- 【测试结果】通过/失败明细\n\n"
            f"## 6. 红线\n{task['rule_footer']}\n"
        )
        file_path.write_text(md_body, encoding="utf-8")
        trigger_text = f"@{rel_path} 严格按此工单要求执行（如有 0.00x 限时免费模型请优先切换），完成后只回【结论】【改动文件】【测试结果】。"
        return {"rel_path": rel_path, "file_path": str(file_path), "trigger_text": trigger_text}

    def gettaskprompt(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the formatted worker prompt for a task (used by browser-extension bridge)."""
        payload = payload or {}
        task_id = (payload.get("task_id") or "").strip()
        if not task_id:
            task_id = str(self.state.get("last_web_task_id") or "")
        task = None
        if task_id:
            for t in self.state["tasks"]:
                if t["id"] == task_id:
                    task = t
                    break
        if task is None and self.state["tasks"]:
            task = self.state["tasks"][-1]
        if task is None:
            raise ValueError("当前办公室还没有待执行的工单。")

        if payload.get("mark_dispatched"):
            self.state["last_web_task_id"] = task["id"]
            self.save()

        prompt = (
            f"你是执行员工，只做下面这件事，不要做决定。\n"
            f"任务目标：{task['goal']}\n"
            f"输入内容：\n{task['input_text']}\n"
            f"强制输出格式：{task['output_format']}\n"
            f"验收标准：{task['acceptance']}\n"
            f"汇报模板：只传【结论】【改动文件】【测试结果】，不要贴整段聊天记录。\n"
            f"红线：不确定的写“未核实”，不要猜。不许自由发挥。"
        )
        return {
            "task_id": task["id"],
            "title": task["title"],
            "assigned_to": task.get("assigned_to") or "",
            "assigned_name": task.get("assigned_name") or "网页员工",
            "status": task["status"],
            "prompt": prompt,
        }

    def collectgitdiff(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Collect concise git status + diff summary from workspace for manager QA (zero tokens)."""
        payload = payload or {}
        ws = self._validate_safe_workspace(payload.get("workspace_dir") or ".")
        status_proc = subprocess.run(
            ["git", "status", "-s"],
            cwd=ws,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        if status_proc.returncode != 0:
            raise RuntimeError(f"当前目录不是 Git 仓库或无法读取 git 状态：{ws}")
        stat_proc = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=ws,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        st = (status_proc.stdout or "").strip()
        df = (stat_proc.stdout or "").strip()
        changed_files = [
            line[3:].strip().split(" -> ")[-1]
            for line in st.splitlines()
            if line.strip() and len(line) > 3
        ]
        if not st and not df:
            summary = f"工作目录 `{ws}` 当前无未提交改动（工作区干净）。"
        else:
            summary = f"【本地工作区改动摘要 · `{ws}`】\n• git status:\n{st or '(无)'}\n• git diff --stat:\n{df or '(仅新增未跟踪文件)'}"
        return {"workspace_dir": ws, "summary": summary, "changed_files": changed_files, "diff_stat": df}

    # ------------------------------------------------------------------
    # Action 26–32: HUD Flights, Human Authorization Gate & MCP Conclusion Relay
    # ------------------------------------------------------------------
    def getsettings(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_runtime_keys()
        return dict(self.state["settings"])

    def toggleautoexecute(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_runtime_keys()
        payload = payload or {}
        curr = bool(self.state["settings"].get("auto_execute_low_risk", False))
        new_val = bool(payload["enabled"]) if "enabled" in payload else (not curr)
        self.state["settings"]["auto_execute_low_risk"] = new_val
        chief = self._chief_agent()
        self._append_group_msg(
            sender_id="owner",
            sender_name="你 (董事长)",
            sender_role="chairman",
            kind="system_notice",
            text=(
                f"🛡️ 授权策略切换：低风险任务自动执行已设为 **{'开启' if new_val else '关闭（安全默认）'}**。"
                " 合并、删代码、部署等关键操作**永远先弹窗请示你批准一次**，绝不私自放行。"
            ),
        )
        self._record_flight(
            from_id="owner",
            from_name="你 (董事长)",
            to_id=chief["id"],
            to_name=chief["name"],
            kind="approval",
            summary=f"低风险自动执行={'开' if new_val else '关'}",
            channel="安全门禁",
        )
        self.save()
        return dict(self.state["settings"])

    def listhudflights(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._ensure_runtime_keys()
        return list(self.state.get("hud_flights", []))

    def listapprovals(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._expire_approvals()
        return list(self.state.get("pending_approvals", []))

    def _expire_approvals(self) -> list[dict[str, Any]]:
        """Lazily return timed-out pending approvals to the owner (no polling).

        Learned from Agent HUD's fail-open gate: an approval the owner never
        answered must NOT silently auto-allow. On read we mark overdue pending
        requests ``expired`` and announce the return in the group; an expired
        request can never be consumed by executecriticalop. No background timer
        or polling loop is added (red line: 不要加定时轮询).
        """
        with self._lock:
            self._ensure_runtime_keys()
            timeout = int(self.state["settings"].get("approval_timeout_seconds", APPROVAL_TIMEOUT_SECONDS))
            if timeout <= 0:
                return []
            now_epoch = time.time()
            expired: list[dict[str, Any]] = []
            for item in self.state["pending_approvals"]:
                if item.get("status") != "pending":
                    continue
                exp = item.get("expires_at") or ""
                if not exp:
                    continue
                try:
                    exp_epoch = time.mktime(time.strptime(exp, "%Y-%m-%d %H:%M:%S"))
                except (ValueError, OverflowError):
                    continue
                if exp_epoch <= now_epoch:
                    item["status"] = "expired"
                    item["expired_at"] = _now_iso()
                    expired.append(item)
            for item in expired:
                self._append_group_msg(
                    sender_id="owner",
                    sender_name="门禁 (超时退回)",
                    sender_role="chairman",
                    kind="system_notice",
                    task_id=item.get("task_id") or None,
                    text=(
                        f"⏳ **授权超时，已原样退回（未执行）**：{item['title']}（`{item['op_type']}`）。"
                        f" 超过 {timeout} 秒未批复，按安全默认不放行；如仍需执行请重新发起授权。"
                    ),
                )
                self._record_flight(
                    from_id="owner",
                    from_name="门禁 (超时退回)",
                    to_id=item.get("requested_by") or "chief",
                    to_name=item.get("requested_by_name") or "总管",
                    kind="approval",
                    task_id=item.get("task_id") or "",
                    summary=f"超时退回: {item['op_type']}",
                    channel="审批超时(不默认放行)",
                )
            if expired:
                self.save()
            return expired

    def setapprovaltimeout(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Owner-configurable approval timeout (seconds). 0 disables expiry."""
        self._ensure_runtime_keys()
        raw = payload.get("seconds", payload.get("timeout_seconds", APPROVAL_TIMEOUT_SECONDS))
        try:
            seconds = int(raw)
        except (TypeError, ValueError):
            raise ValueError("审批超时秒数必须是整数。")
        if seconds < 0:
            raise ValueError("审批超时秒数不能为负数（0 表示永不超时）。")
        self.state["settings"]["approval_timeout_seconds"] = seconds
        self.save()
        return {"approval_timeout_seconds": seconds}

    def requestapproval(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Queue an explicit human authorization request (always asks for critical ops)."""
        self._ensure_runtime_keys()
        op_type = (payload.get("op_type") or "merge").strip().lower()
        target = (payload.get("target") or "main").strip()
        task_id = (payload.get("task_id") or "").strip()
        requested_by = (payload.get("requested_by") or "chief").strip()
        try:
            requester = self._find_agent(requested_by) if requested_by not in ("owner", "gao") else {"id": "owner", "name": "你 (董事长)"}
        except KeyError:
            requester = self._chief_agent()

        is_critical = op_type in CRITICAL_OPS or payload.get("risk_level") == "critical"
        risk_level = "critical" if is_critical else "low"
        op_labels = {
            "merge": "合并分支 (git merge)",
            "delete_code": "删除代码 / 清理文件",
            "deploy": "发布部署 (deploy)",
            "auto_dispatch": "低风险自动派发",
            "low_risk_run": "低风险自动执行",
        }
        title = (payload.get("title") or f"{op_labels.get(op_type, op_type)} → {target}").strip()

        auto_low = bool(self.state["settings"].get("auto_execute_low_risk", False))
        timeout = int(payload.get("timeout_seconds") or self.state["settings"].get("approval_timeout_seconds", APPROVAL_TIMEOUT_SECONDS))
        created_epoch = time.time()
        expires_at = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_epoch + timeout))
            if timeout > 0 else ""
        )
        apr_id = f"apr-{int(time.time() * 1000) % 1000000}-{len(self.state['pending_approvals']) + 1}"
        entry = {
            "id": apr_id,
            "op_type": op_type,
            "title": title,
            "target": target,
            "task_id": task_id,
            "requested_by": requester["id"],
            "requested_by_name": requester["name"],
            "risk_level": risk_level,
            "status": "auto_approved" if (not is_critical and auto_low) else "pending",
            "created_at": _now_iso(),
            "timeout_seconds": timeout,
            "expires_at": expires_at,
        }
        self.state["pending_approvals"].append(entry)
        if not is_critical and auto_low:
            self._record_flight(
                from_id=requester["id"],
                from_name=requester["name"],
                to_id="owner",
                to_name="自动门禁(低风险)",
                kind="approval",
                task_id=task_id,
                summary=f"低风险自动放行: {title[:22]}",
                channel="自动开关已开",
            )
            self.save()
            return entry

        self._append_group_msg(
            sender_id=requester["id"],
            sender_name=requester["name"],
            sender_role="chief",
            kind="approval_request",
            task_id=task_id or None,
            text=(
                f"🛡️ **{'关键操作等待人工授权' if is_critical else '低风险操作请求确认（自动开关已关）'}**\n"
                f"• 操作：`{op_type}` · {title}\n"
                f"• 目标：`{target}`\n"
                f"• 请在上方 HUD 授权条点击 **「✅ 允许一次」** 或 **「🚫 拒绝」**（不会私自执行）。"
            ),
        )
        self._record_flight(
            from_id=requester["id"],
            from_name=requester["name"],
            to_id="owner",
            to_name="你 (待授权)",
            kind="approval",
            task_id=task_id,
            summary=f"请求人工批准: {op_type}",
            channel="关键操作门禁",
        )
        self.save()
        return entry

    def resolveapproval(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._expire_approvals()
        apr_id = (payload.get("approval_id") or payload.get("id") or "").strip()
        decision = (payload.get("decision") or "allow_once").strip().lower()
        if decision not in ("allow_once", "always_allow", "deny"):
            raise ValueError("授权决策只能是 allow_once / always_allow / deny。")
        target_item = None
        for item in self.state["pending_approvals"]:
            if item["id"] == apr_id:
                target_item = item
                break
        if target_item is None:
            raise KeyError(f"找不到授权请求: {apr_id}")
        if target_item.get("status") == "expired":
            raise ValueError("该授权已超时原样退回（未执行），请重新发起授权后再批复。")

        if target_item["risk_level"] == "critical" and decision == "always_allow":
            raise ValueError("合并、删代码、部署属于关键操作，禁止设置「总是允许」，每次必须人工点「允许一次」或「拒绝」。")

        if decision == "deny":
            target_item["status"] = "denied"
            msg = f"🚫 **你 (董事长) 拒绝了操作**：{target_item['title']}（`{target_item['op_type']}`）"
        elif decision == "always_allow":
            target_item["status"] = "approved_once"
            self.state["settings"]["auto_execute_low_risk"] = True
            msg = f"⚡ **你 (董事长) 允许并开启低风险自动执行**：{target_item['title']}"
        else:
            target_item["status"] = "approved_once"
            msg = f"✅ **你 (董事长) 允许一次**：{target_item['title']}（执行后自动失效，下次重问）"

        target_item["resolved_at"] = _now_iso()
        self._append_group_msg(
            sender_id="owner",
            sender_name="你 (董事长)",
            sender_role="chairman",
            kind="system_notice",
            task_id=target_item.get("task_id") or None,
            text=msg,
        )
        self._record_flight(
            from_id="owner",
            from_name="你 (董事长)",
            to_id=target_item["requested_by"],
            to_name=target_item["requested_by_name"],
            kind="approval",
            task_id=target_item.get("task_id") or "",
            summary="允许一次" if decision == "allow_once" else ("总是允许低风险" if decision == "always_allow" else "已拒绝"),
            channel="人工批复",
        )
        self.save()
        return target_item

    def executecriticalop(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Gate merge / delete_code / deploy behind a single-use human approval.

        dry_run=True (default) is a zero-side-effect preview. dry_run=False runs
        a REAL controlled executor: it first creates a Git backup branch at HEAD
        so the owner can one-click rollback, then performs the operation. We
        label every outcome honestly (real / record-only / preview / safe-return)
        and never pretend an op ran when it did not. Subprocess I/O runs OUTSIDE
        the store lock; state writes use brief explicit locks + locked sub-calls.
        """
        self._expire_approvals()
        op_type = (payload.get("op_type") or "merge").strip().lower()
        target = (payload.get("target") or "main").strip()
        task_id = (payload.get("task_id") or "").strip()
        approval_id = (payload.get("approval_id") or "").strip()
        dry_run = bool(payload.get("dry_run", True))

        with self._lock:
            matched = None
            for item in reversed(self.state["pending_approvals"]):
                if approval_id and item["id"] != approval_id:
                    continue
                if item["op_type"] == op_type and item["target"] == target and item["status"] == "approved_once":
                    matched = item
                    break

        if matched is None:
            req = self.requestapproval({
                "op_type": op_type,
                "target": target,
                "task_id": task_id,
                "requested_by": payload.get("requested_by") or "chief",
                "title": payload.get("title"),
            })
            return {"executed": False, "requires_approval": True, "approval": req}

        # Consume the single-use approval immediately so the next run asks again.
        with self._lock:
            matched["status"] = "executed"
            matched["executed_at"] = _now_iso()

        if dry_run:
            result = self._preview_critical_op(op_type, target, payload)
        else:
            result = self._run_controlled_git_op(op_type, target, payload)

        chief_name = self._chief_agent()["name"]
        if result.get("real_executed"):
            note = (
                f"⚙️ **已凭人工单次授权真实执行** `{op_type}` → `{target}`。"
                f" 已自动创建 Git 备份 `{result.get('backup_ref')}`，可在授权抽屉一键回滚。该次授权已消耗。"
            )
            flight_summary = f"{op_type}:实操"
        elif result.get("record_only"):
            note = f"📝 **授权已记录，但未真实执行** `{op_type}` → `{target}`：{result.get('detail')}。该次授权已消耗。"
            flight_summary = f"{op_type}:仅记录"
        elif dry_run:
            note = (
                f"🧪 **干跑演练（零副作用）** `{op_type}` → `{target}`：{result.get('detail')}"
                f" 未触碰仓库；如需实操请取消干跑并重新授权。该次授权已消耗。"
            )
            flight_summary = f"{op_type}:干跑"
        else:
            note = (
                f"⛔ **执行未成功（已安全退回）** `{op_type}` → `{target}`：{result.get('error') or result.get('detail')}"
                f" 仓库未被破坏；如需重试请重新授权。该次授权已消耗。"
            )
            flight_summary = f"{op_type}:退回"
        with self._lock:
            self._append_group_msg(
                sender_id="chief", sender_name=chief_name, sender_role="chief",
                kind="system_notice", task_id=task_id or None, text=note,
            )
            self._record_flight(
                from_id="chief", from_name=chief_name, to_id="owner", to_name="你 (董事长)",
                kind="approval", task_id=task_id, summary=flight_summary, channel="受控执行器",
            )
        self.save()
        return {
            "executed": bool(result.get("executed")),
            "dry_run": dry_run,
            "real_executed": bool(result.get("real_executed")),
            "record_only": bool(result.get("record_only")),
            "op_type": op_type,
            "target": target,
            "approval_id": matched["id"],
            "backup_ref": result.get("backup_ref"),
            "rollback_available": bool(result.get("rollback_available")),
            "detail": result.get("detail", ""),
            "error": result.get("error", ""),
            "workspace_dir": result.get("workspace_dir", ""),
        }

    def _git_run(self, ws: str, args: list[str], timeout: int = 30):
        return subprocess.run(
            ["git", *args], cwd=ws, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )

    def _make_git_backup(self, ws: str, op_label: str) -> str | None:
        ref = f"backup/{op_label}-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000}"
        proc = self._git_run(ws, ["branch", ref, "HEAD"])
        return ref if proc.returncode == 0 else None

    def _delete_git_backup(self, ws: str, ref: str | None) -> None:
        if ref and ref.startswith("backup/"):
            self._git_run(ws, ["branch", "-D", ref])

    def _preview_critical_op(self, op_type: str, target: str, payload: dict[str, Any]) -> dict[str, Any]:
        ws = self._validate_safe_workspace(payload.get("workspace_dir") or ".")
        if op_type == "merge":
            detail = f"将在 `{ws}` 把 `{target}` 合并进当前分支（git merge --no-ff），执行前自动建备份分支。"
        elif op_type == "delete_code":
            files = payload.get("files") or []
            detail = f"将在 `{ws}` 删除 {len(files)} 个受版本控制的文件（git rm + commit），执行前自动建备份分支。"
        elif op_type == "deploy":
            cmd = payload.get("command") or self.state["settings"].get("deploy_command")
            detail = f"将运行已配置的部署命令：{cmd}" if cmd else "未配置部署命令：仅记录授权，不执行实际部署。"
        else:
            detail = f"操作 `{op_type}` 预览。"
        return {"executed": True, "real_executed": False, "record_only": False,
                "detail": detail, "workspace_dir": ws, "backup_ref": None, "rollback_available": False}

    def _run_controlled_git_op(self, op_type: str, target: str, payload: dict[str, Any]) -> dict[str, Any]:
        ws = self._validate_safe_workspace(payload.get("workspace_dir") or ".")

        if op_type == "deploy":
            cmd = payload.get("command") or self.state["settings"].get("deploy_command")
            if not cmd:
                return {"executed": True, "real_executed": False, "record_only": True,
                        "detail": "未配置部署命令（deploy_command）。仅记录授权，未执行实际部署。",
                        "workspace_dir": ws, "backup_ref": None, "rollback_available": False}
            args = list(cmd) if isinstance(cmd, (list, tuple)) else shlex.split(str(cmd))
            if not args:
                return {"executed": True, "real_executed": False, "record_only": True,
                        "detail": "部署命令为空，仅记录授权。", "workspace_dir": ws,
                        "backup_ref": None, "rollback_available": False}
            backup_ref = self._make_git_backup(ws, "deploy")
            try:
                proc = subprocess.run(
                    [str(a) for a in args], cwd=ws, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=120, check=False, shell=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {"executed": False, "real_executed": False,
                        "error": f"部署命令执行失败：{exc}", "workspace_dir": ws,
                        "backup_ref": backup_ref, "rollback_available": bool(backup_ref)}
            out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            if proc.returncode != 0:
                return {"executed": False, "real_executed": False,
                        "error": f"部署命令返回非零（{proc.returncode}）：{out[:400]}", "workspace_dir": ws,
                        "backup_ref": backup_ref, "rollback_available": bool(backup_ref)}
            return {"executed": True, "real_executed": True,
                    "detail": f"部署命令已执行：{' '.join(str(a) for a in args)}\n{out[:400]}",
                    "workspace_dir": ws, "backup_ref": backup_ref, "rollback_available": bool(backup_ref)}

        if op_type not in ("merge", "delete_code"):
            return {"executed": False, "real_executed": False,
                    "error": f"不支持的受控操作类型：{op_type}", "workspace_dir": ws}

        inside = self._git_run(ws, ["rev-parse", "--is-inside-work-tree"])
        if inside.returncode != 0 or (inside.stdout or "").strip() != "true":
            return {"executed": False, "real_executed": False,
                    "error": f"`{ws}` 不是 Git 仓库，无法安全执行 {op_type}（不伪造执行）。", "workspace_dir": ws}
        dirty = self._git_run(ws, ["status", "-s"])
        if (dirty.stdout or "").strip():
            return {"executed": False, "real_executed": False,
                    "error": "工作区有未提交改动。为避免丢失你的工作，受控执行器要求干净工作区；请先提交或清理后重试（不自动 stash）。",
                    "workspace_dir": ws}

        if op_type == "merge":
            verify = self._git_run(ws, ["rev-parse", "--verify", "--quiet", target + "^{commit}"])
            if verify.returncode != 0:
                return {"executed": False, "real_executed": False,
                        "error": f"找不到要合并的来源分支/引用：{target}", "workspace_dir": ws}
            backup_ref = self._make_git_backup(ws, "merge")
            if not backup_ref:
                return {"executed": False, "real_executed": False,
                        "error": "无法创建 Git 备份分支，已放弃执行（安全第一）。", "workspace_dir": ws}
            head_before = (self._git_run(ws, ["rev-parse", "HEAD"]).stdout or "").strip()
            merge = self._git_run(ws, ["merge", "--no-ff", target, "-m", f"ai-farm controlled merge: {target}"], timeout=60)
            if merge.returncode != 0:
                self._git_run(ws, ["merge", "--abort"])
                self._delete_git_backup(ws, backup_ref)
                return {"executed": False, "real_executed": False,
                        "error": f"合并失败/冲突，已自动 abort 并清理备份，仓库恢复原状：{((merge.stdout or '') + (merge.stderr or '')).strip()[:300]}",
                        "workspace_dir": ws, "backup_ref": None, "rollback_available": False}
            head_after = (self._git_run(ws, ["rev-parse", "HEAD"]).stdout or "").strip()
            return {"executed": True, "real_executed": True,
                    "detail": f"已把 `{target}` 合并进当前分支（--no-ff）。HEAD {head_before[:8]} → {head_after[:8]}。",
                    "workspace_dir": ws, "backup_ref": backup_ref, "rollback_available": True,
                    "head_before": head_before, "head_after": head_after}

        files = payload.get("files") or []
        if isinstance(files, str):
            files = [files]
        files = [str(f).strip() for f in files if str(f).strip()]
        if not files:
            return {"executed": False, "real_executed": False,
                    "error": "delete_code 需要 files 列表（要删除的受版本控制文件）。", "workspace_dir": ws}
        base = Path(ws).resolve()
        safe_files: list[str] = []
        for f in files:
            p = (base / f).resolve()
            if base != p and base not in p.parents:
                return {"executed": False, "real_executed": False,
                        "error": f"安全拦截：删除路径越界 `{f}`。", "workspace_dir": ws}
            safe_files.append(str(p.relative_to(base)).replace("\\", "/"))
        backup_ref = self._make_git_backup(ws, "delete")
        if not backup_ref:
            return {"executed": False, "real_executed": False,
                    "error": "无法创建 Git 备份分支，已放弃执行（安全第一）。", "workspace_dir": ws}
        rm = self._git_run(ws, ["rm", "-r", "--", *safe_files], timeout=60)
        if rm.returncode != 0:
            self._delete_git_backup(ws, backup_ref)
            return {"executed": False, "real_executed": False,
                    "error": f"git rm 失败（文件可能未被版本控制）：{((rm.stdout or '') + (rm.stderr or '')).strip()[:300]}",
                    "workspace_dir": ws, "backup_ref": None, "rollback_available": False}
        commit = self._git_run(ws, ["commit", "-m", f"ai-farm controlled delete: {', '.join(safe_files)[:120]}"], timeout=60)
        if commit.returncode != 0:
            self._git_run(ws, ["reset", "--hard", backup_ref])
            self._delete_git_backup(ws, backup_ref)
            return {"executed": False, "real_executed": False,
                    "error": f"删除提交失败，已回滚到备份：{((commit.stdout or '') + (commit.stderr or '')).strip()[:300]}",
                    "workspace_dir": ws, "backup_ref": None, "rollback_available": False}
        return {"executed": True, "real_executed": True,
                "detail": f"已删除并提交 {len(safe_files)} 个文件：{', '.join(safe_files)[:200]}。可凭备份分支一键恢复。",
                "workspace_dir": ws, "backup_ref": backup_ref, "rollback_available": True,
                "deleted_files": safe_files}

    def rollbackcriticalop(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Owner-triggered one-click rollback to a backup ref we created.

        Destructive (git reset --hard) but ONLY restores to a ``backup/...`` ref
        the controlled executor created, and ONLY on an explicit owner action
        with confirm=True. Never resets to arbitrary refs. Subprocess I/O runs
        outside the store lock; state writes use a brief explicit lock.
        """
        if not payload.get("confirm"):
            raise ValueError("回滚是破坏性操作，必须显式 confirm=True（主人一键确认）。")
        ref = (payload.get("backup_ref") or "").strip()
        if not ref.startswith("backup/"):
            raise ValueError("只允许回滚到受控执行器创建的 backup/ 备份分支，禁止重置到任意引用。")
        ws = self._validate_safe_workspace(payload.get("workspace_dir") or ".")
        inside = self._git_run(ws, ["rev-parse", "--is-inside-work-tree"])
        if inside.returncode != 0 or (inside.stdout or "").strip() != "true":
            raise RuntimeError(f"`{ws}` 不是 Git 仓库，无法回滚。")
        verify = self._git_run(ws, ["rev-parse", "--verify", "--quiet", ref + "^{commit}"])
        if verify.returncode != 0:
            raise ValueError(f"备份分支不存在或已被清理：{ref}")
        head_before = (self._git_run(ws, ["rev-parse", "HEAD"]).stdout or "").strip()
        reset = self._git_run(ws, ["reset", "--hard", ref], timeout=60)
        if reset.returncode != 0:
            raise RuntimeError(f"回滚失败：{((reset.stdout or '') + (reset.stderr or '')).strip()[:300]}")
        head_after = (self._git_run(ws, ["rev-parse", "HEAD"]).stdout or "").strip()
        with self._lock:
            self._append_group_msg(
                sender_id="owner", sender_name="你 (董事长)", sender_role="chairman",
                kind="system_notice", task_id=(payload.get("task_id") or None),
                text=f"↩️ **主人一键回滚**：仓库已恢复到备份 `{ref}`（HEAD {head_before[:8]} → {head_after[:8]}）。",
            )
            self._record_flight(
                from_id="owner", from_name="你 (董事长)", to_id="chief", to_name=self._chief_agent()["name"],
                kind="approval", task_id=payload.get("task_id") or "",
                summary=f"回滚到 {ref}", channel="受控执行器回滚",
            )
        self.save()
        return {"rolled_back": True, "backup_ref": ref, "workspace_dir": ws,
                "head_before": head_before, "head_after": head_after}

    # ------------------------------------------------------------------
    # Action 33–36: Big Task Split / Batch Subtasks / Aggregate / Auto Diff Review
    # ------------------------------------------------------------------
    def _distinct_vendor_workers(self) -> list[dict[str, Any]]:
        """Collect ready 1F workers across distinct vendors for balanced round-robin."""
        picked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for a in self.state["agents"]:
            if a.get("floor") != "worker" or a.get("status") != "ready":
                continue
            v = (a.get("vendor") or "").strip().lower()
            if v and v in seen:
                continue
            if v:
                seen.add(v)
            picked.append(a)
        return picked

    def createbigtask(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Split a large goal into child subtasks across distinct-vendor free workers."""
        title = (payload.get("title") or "").strip()
        if not title:
            raise ValueError("大任务标题不能为空。")
        goal = (payload.get("goal") or title).strip()
        chief = self._chief_agent()
        manager_id = payload.get("manager_id") or chief["id"]
        try:
            manager = self._find_agent(manager_id)
        except KeyError:
            manager = chief

        big_fp = self._request_fingerprint("createbigtask", {
            "title": title, "goal": goal,
            "raw_steps": (payload.get("raw_steps") or "").strip(),
            "subtasks": payload.get("subtasks") or [],
            "manager_id": manager["id"],
            "idempotency_key": payload.get("idempotency_key") or "",
        })
        if not payload.get("force_new"):
            prior_big = self._find_receipt(big_fp)
            if prior_big and prior_big.get("parent_id"):
                try:
                    par = self._find_task(prior_big["parent_id"])
                    subs = [self._find_task(sid) for sid in par.get("subtask_ids", [])
                            if any(t["id"] == sid for t in self.state["tasks"])]
                    return {"parent": par, "subtasks": subs, "idempotent_replay": True}
                except KeyError:
                    pass

        raw_subtasks = payload.get("subtasks")
        raw_steps = (payload.get("raw_steps") or "").strip()
        specs: list[dict[str, Any]] = []

        if isinstance(raw_subtasks, list) and raw_subtasks:
            for item in raw_subtasks:
                if isinstance(item, dict) and (item.get("title") or item.get("goal")):
                    specs.append(dict(item))
        elif raw_steps:
            for idx, ln in enumerate(raw_steps.splitlines(), start=1):
                clean = ln.strip().lstrip("-•*0123456789.、) ").strip()
                if not clean:
                    continue
                is_code = ("[代码]" in clean or "[code]" in clean.lower() or "改代码" in clean or "修复" in clean or "单测" in clean)
                clean_title = clean.replace("[代码]", "").replace("[code]", "").replace("[CODE]", "").strip()
                specs.append({
                    "title": f"子单 {idx}：{clean_title[:36]}",
                    "goal": clean_title,
                    "task_kind": "code_change" if is_code else "small",
                    "skill_slug": "cheap-code-jobs" if is_code else "",
                })

        if not specs:
            specs = [
                {
                    "title": f"子单 1：梳理骨架与验收清单 — {title[:18]}",
                    "goal": f"针对「{goal}」输出精简目录大纲与关键验收点（不超过300字）。",
                    "task_kind": "small",
                    "skill_slug": "doc-drafting-frame",
                },
                {
                    "title": f"子单 2：核心代码改动与测试 — {title[:18]}",
                    "goal": f"按大纲完成「{goal}」的核心实现与边界测试，提交结论+改动文件+测试结果。",
                    "task_kind": "code_change",
                    "skill_slug": "cheap-code-jobs",
                },
                {
                    "title": f"子单 3：结果核对与三档摘要 — {title[:18]}",
                    "goal": f"对照验收标准核对「{goal}」产出，生成一句话结论与要点清单。",
                    "task_kind": "small",
                    "skill_slug": "three-tier-summary",
                },
            ]

        base_id = f"EPIC-{int(time.time() * 1000) % 1000000}"
        existing_ids = {t["id"] for t in self.state["tasks"]}
        parent_id = base_id if base_id not in existing_ids else f"{base_id}-{len(self.state['tasks']) + 1}"

        parent_task: dict[str, Any] = {
            "id": parent_id,
            "title": f"🧩 [大任务] {title}",
            "manager_id": manager["id"],
            "manager_name": manager["name"],
            "assigned_to": "",
            "assigned_name": f"已拆 {len(specs)} 张子单",
            "assigned_vendor": "多厂商并行",
            "goal": goal,
            "input_text": f"共拆解为 {len(specs)} 张子单并行推进。",
            "output_format": "全部子单结论-only 汇总交付（未重读对话全文）",
            "acceptance": "全部子单完成汇报，且所有改代码子单通过独立审查后聚合交付。",
            "rule_footer": "大任务自动拆单：小活直通省额度，改代码子单必走写-审-改闭环。",
            "skill_slug": "",
            "task_kind": "small",
            "requires_code_review": False,
            "reviewer_id": "",
            "reviewer_name": "",
            "review_status": "not_needed",
            "review_issues": [],
            "revision_round": 0,
            "parent_task_id": "",
            "is_parent": True,
            "subtask_ids": [],
            "mode": (payload.get("mode") or "split").strip().lower(),
            "circuit_breaker": "",
            "depends_on": [],
            "status": "working",
            "worker_reported": False,
            "latest_report_summary": "",
            "final_delivery_text": "",
            "usage_log": [],
            "created_at": _now_iso(),
        }
        self.state["tasks"].append(parent_task)
        self.state["task_messages"][parent_id] = [
            {
                "id": f"tmsg-{int(time.time() * 1000)}-p",
                "task_id": parent_id,
                "sender_id": manager["id"],
                "sender_name": manager["name"],
                "kind": "template_dispatch",
                "text": f"🧩 **大任务拆解启动** `{parent_id}` · **{title}**\n• 目标：{goal}\n• 子单数量：{len(specs)} 张（按独立厂商轮换派发）",
                "created_at": _now_iso(),
            }
        ]

        workers = self._distinct_vendor_workers()
        created_subtasks: list[dict[str, Any]] = []
        for idx, spec in enumerate(specs):
            assigned_id = spec.get("assigned_to") or (workers[idx % len(workers)]["id"] if workers else "")
            sub = self.createtask({
                "title": spec.get("title") or f"子单 {idx + 1}",
                "manager_id": manager["id"],
                "assigned_to": assigned_id,
                "goal": spec.get("goal") or spec.get("title") or goal,
                "input_text": spec.get("input_text") or f"所属大任务 `{parent_id}`：{goal}",
                "output_format": spec.get("output_format") or "只输出【结论】+【改动文件】+【测试结果】，不贴全文对话。",
                "acceptance": spec.get("acceptance") or "结果完整、不编造数据、符合格式要求。",
                "skill_slug": spec.get("skill_slug") or "",
                "task_kind": spec.get("task_kind") or "small",
                "reviewer_id": spec.get("reviewer_id") or "",
                "parent_task_id": parent_id,
                "depends_on": spec.get("depends_on") or [],
            })
            parent_task["subtask_ids"].append(sub["id"])
            created_subtasks.append(sub)

        # Resolve DAG deps given as 1-based sibling indices (model planner output)
        # into concrete subtask ids; drop self/unknown references.
        for idx, sub in enumerate(created_subtasks):
            resolved: list[str] = []
            for dep in (sub.get("depends_on") or []):
                if isinstance(dep, int) or (isinstance(dep, str) and dep.isdigit()):
                    j = int(dep) - 1
                    if 0 <= j < len(created_subtasks) and j != idx:
                        resolved.append(created_subtasks[j]["id"])
                elif isinstance(dep, str) and dep != sub["id"] and any(s["id"] == dep for s in created_subtasks):
                    resolved.append(dep)
            sub["depends_on"] = list(dict.fromkeys(resolved))

        lines = "\n".join(
            f"  {i + 1}. `{s['id']}` {s['title']} → **{s['assigned_name']}**"
            + (" `[写-审-改]`" if s.get("requires_code_review") else " `[小活]`")
            for i, s in enumerate(created_subtasks)
        )
        self._append_group_msg(
            sender_id=manager["id"],
            sender_name=manager["name"],
            sender_role="manager",
            kind="big_task_card",
            task_id=parent_id,
            text=f"🧩 **大任务一键拆单完成** `{parent_id}` · **{title}**\n已拆成 **{len(created_subtasks)} 张子单** 并跨厂商分派：\n{lines}",
        )
        self._record_flight(
            from_id=manager["id"],
            from_name=manager["name"],
            to_id="workers",
            to_name=f"{len(created_subtasks)} 张子单并行池",
            kind="dispatch",
            task_id=parent_id,
            summary=f"大任务拆单 ({len(created_subtasks)}子单)",
            channel="父子编排",
        )
        self._store_receipt(big_fp, "createbigtask", {"parent_id": parent_id})
        self.save()
        return {"parent": parent_task, "subtasks": created_subtasks}

    def runbigtasksubtasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Batch-run all pending subtasks of a parent task, respecting the
        depends_on DAG: independent siblings run concurrently (API/CLI live),
        a subtask only starts once its upstream siblings have reported. Web /
        desktop siblings are handed to the courier extension / .md mailbox and
        their dependents wait honestly (no copy-paste, no fake success)."""
        parent = self._find_task(payload.get("parent_task_id") or payload.get("task_id") or payload.get("id"))
        if not parent.get("is_parent") or not parent.get("subtask_ids"):
            raise ValueError("该任务不是包含子单的大任务。")
        live = bool(payload.get("live", False))
        workspace_dir = (payload.get("workspace_dir") or "").strip()

        subtasks = [self._find_task(sid) for sid in parent["subtask_ids"] if any(t["id"] == sid for t in self.state["tasks"])]
        by_id = {s["id"]: s for s in subtasks}
        results: list[dict[str, Any]] = []
        done: set[str] = {s["id"] for s in subtasks if s["status"] in ("delivered", "accepted_done")}
        stalled: dict[str, str] = {}
        remaining = [s for s in subtasks if s["id"] not in done]

        def _exec_one(sub_task: dict[str, Any]) -> dict[str, Any]:
            try:
                res = self.runadaptertask({"task_id": sub_task["id"], "live": True, "workspace_dir": workspace_dir})
                return {"task_id": sub_task["id"], "mode": "live", "worker": res["worker"], "ok": True}
            except Exception as exc:  # noqa: BLE001
                return {"task_id": sub_task["id"], "mode": "live", "ok": False, "error": str(exc)}

        while remaining:
            wave: list[dict[str, Any]] = []
            blocked: list[dict[str, Any]] = []
            for s in remaining:
                deps = [d for d in (s.get("depends_on") or []) if d in by_id]
                if all(d in done for d in deps):
                    wave.append(s)
                elif any(d in stalled for d in deps):
                    blocked.append(s)
            for s in blocked:
                stalled[s["id"]] = "upstream"
                results.append({"task_id": s["id"], "skipped": True, "reason": "依赖未满足（上游子单未完成/被跳过）"})
            wave_ids = {s["id"] for s in wave}
            blocked_ids = {s["id"] for s in blocked}
            remaining = [s for s in remaining if s["id"] not in wave_ids and s["id"] not in blocked_ids]
            if not wave:
                for s in remaining:
                    results.append({"task_id": s["id"], "skipped": True, "reason": "依赖未满足，等待上游子单"})
                break

            if not live:
                for s in wave:
                    res = self.runadaptertask({"task_id": s["id"], "live": False, "workspace_dir": workspace_dir})
                    results.append({"task_id": s["id"], "mode": "dry_run", "worker": res["worker"]})
                    done.add(s["id"])
                continue

            auto_subs: list[dict[str, Any]] = []
            for s in wave:
                wid = s.get("assigned_to") or ""
                agent = self._find_agent(wid) if wid else None
                if agent and agent.get("access_kind") in ("web", "subscription", "desktop"):
                    stalled[s["id"]] = "channel"
                    results.append({
                        "task_id": s["id"], "skipped": True,
                        "reason": f"{agent['name']} 属于{agent['badge']}通道，等待传令兵扩展/信箱自动回执（不复制粘贴）",
                    })
                else:
                    auto_subs.append(s)
            if auto_subs:
                with ThreadPoolExecutor(max_workers=min(4, len(auto_subs))) as pool:
                    wave_results = list(pool.map(_exec_one, auto_subs))
                results.extend(wave_results)
                for r in wave_results:
                    if r.get("ok"):
                        done.add(r["task_id"])
                    else:
                        stalled[r["task_id"]] = "failed"

        executed = len([r for r in results if not r.get("skipped") and r.get("ok", True)])
        return {"parent_id": parent["id"], "mode": "live" if live else "dry_run",
                "executed_count": executed, "results": results}

    def runautocodereview(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Auto-collect local git diff (0 tokens) and run independent reviewer (dry-run or live API/CLI)."""
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        if not task.get("requires_code_review"):
            raise ValueError("该任务为小活，未开启写—审—改闭环。")
        chief = self._chief_agent()
        reviewer_id = (payload.get("reviewer_id") or task.get("reviewer_id") or "").strip()
        reviewer = self._pick_reviewer(
            assigned_id=task.get("assigned_to") or "",
            manager=chief,
            requested_id=reviewer_id,
        )
        live = bool(payload.get("live", False))
        workspace_dir = (payload.get("workspace_dir") or "").strip() or "."
        diff_info = self.collectgitdiff({"workspace_dir": workspace_dir})

        if not live:
            sim_reject = bool(payload.get("simulate_reject", False))
            files_preview = ", ".join(diff_info.get("changed_files") or ["(工作区无改动)"])[:120]
            issues = (
                [f"[自动读diff干跑] 请核对改动文件 ({files_preview}) 的边界条件与单测覆盖。"]
                if sim_reject else []
            )
            updated = self.submitcodereview({
                "task_id": task["id"],
                "reviewer_id": reviewer["id"],
                "passed": not sim_reject,
                "issues": issues,
                "dry_run": True,
            })
            return {
                "mode": "dry_run",
                "reviewer": reviewer["name"],
                "review_status": updated["review_status"],
                "changed_files": diff_info.get("changed_files", []),
            }

        if reviewer.get("access_kind") not in ("api", "cli"):
            alt = self._pick_reviewer(assigned_id=task.get("assigned_to") or "", manager=chief, requested_id="")
            if alt.get("access_kind") in ("api", "cli") and alt["id"] != (task.get("assigned_to") or ""):
                reviewer = alt
            else:
                raise RuntimeError(
                    f"独立审查者 {reviewer['name']}（{reviewer['badge']}）不是 API/CLI 通道，无法自动真调；"
                    "请切换 API/CLI 审查者，或用干跑/手动填入审查问题清单。"
                )
        safe_ws = self._validate_safe_workspace(workspace_dir)
        adapter = self._build_adapter(reviewer, workspace_dir=safe_ws)
        review_prompt = (
            "你是独立代码审查员，只看下方结论摘要和 git diff --stat，不要重写全文代码。\n"
            f"任务：{task['title']}\n"
            f"员工结论摘要：\n{task.get('latest_report_summary') or '(尚未提交结论)'}\n"
            f"本地改动摘要：\n{diff_info['summary']}\n"
            "如果无阻断问题，仅回复：PASS\n"
            "如果有问题，每行一条输出精简问题清单（格式：文件:行号 问题描述），绝不贴整文件代码。"
        )
        reply = adapter.chat(review_prompt, max_tokens=600)
        rev_tok = self._reply_tokens(reply)
        with self._lock:
            reviewer["tokens_used"] = int(reviewer.get("tokens_used") or 0) + rev_tok
            self._record_savings(reviewer, rev_tok, task["id"], "review")
        raw = (reply.text or "").strip()
        is_pass = raw.upper().startswith("PASS") or ("无阻断" in raw and len(raw) < 80)
        issues_list = [] if is_pass else [ln.strip(" -•\t") for ln in raw.splitlines() if ln.strip()][:12]
        updated = self.submitcodereview({
            "task_id": task["id"],
            "reviewer_id": reviewer["id"],
            "passed": is_pass,
            "issues": issues_list,
            "dry_run": False,
        })
        return {
            "mode": "live",
            "reviewer": reviewer["name"],
            "review_status": updated["review_status"],
            "issues": issues_list,
        }

    def aggregatebigtask(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Aggregate all completed & reviewed child subtasks into one parent executive delivery."""
        parent = self._find_task(payload.get("parent_task_id") or payload.get("task_id") or payload.get("id"))
        if not parent.get("is_parent") or not parent.get("subtask_ids"):
            raise ValueError("该任务不是大任务，请使用普通交付。")

        subtasks = [self._find_task(sid) for sid in parent["subtask_ids"] if any(t["id"] == sid for t in self.state["tasks"])]
        unreviewed = [
            f"{s['id']}({s['title']})"
            for s in subtasks
            if s.get("requires_code_review") and s.get("review_status") != "approved"
        ]
        if unreviewed:
            raise ValueError(
                f"写—审—改闭环拦截：以下改代码子单尚未通过独立审查，不能聚合总交付：{', '.join(unreviewed)}"
            )

        tripped = [f"{s['id']}({s.get('circuit_breaker')})" for s in subtasks if s.get("circuit_breaker")]
        if tripped and not payload.get("force"):
            raise ValueError(
                f"熔断拦截：以下子单已触发熔断（需主人/经理裁决），不能自动聚合：{', '.join(tripped)}"
            )

        force = bool(payload.get("force", False))
        unreported = [
            f"{s['id']}({s['title']})"
            for s in subtasks
            if not s.get("worker_reported") and s.get("status") not in ("delivered", "accepted_done")
        ]
        if unreported and not force:
            raise ValueError(f"仍有子单尚未提交结论汇报，无法汇总：{', '.join(unreported)}")

        bullet_lines = []
        for idx, sub in enumerate(subtasks, start=1):
            conc = (sub.get("latest_report_summary") or "已完成").splitlines()[0][:140]
            rev_tag = f" · 审查✅({sub.get('reviewer_name')})" if sub.get("requires_code_review") else ""
            bullet_lines.append(f"{idx}. `{sub['id']}` **{sub['title']}**（{sub['assigned_name']}{rev_tag}）：{conc}")
            if sub["status"] not in ("delivered", "accepted_done"):
                sub["status"] = "delivered"

        agg_summary = (
            f"🧩 **大任务聚合总交付**（共汇总 {len(subtasks)} 张子单结论，未重读任何对话全文）：\n"
            + "\n".join(bullet_lines)
        )
        parent["worker_reported"] = True
        parent["latest_report_summary"] = agg_summary[:320]
        return self.deliverfinalresult({"task_id": parent["id"], "summary": agg_summary})

    # ------------------------------------------------------------------
    # Octo modes (README §12). Solo / Critic / Pipeline / Split already have
    # prototypes and only need the mode label. Roundtable + Swarm are added
    # here. Both drive REAL model calls via _build_adapter; when no usable
    # model exists they STOP honestly and say so in the group — they never
    # fabricate a debate or a winner (red line §七: 不许伪造讨论).
    # Like runadaptertask, these are slow-I/O orchestrators: adapter.chat runs
    # lock-free, only the shared-state writes take the reentrant lock.
    # ------------------------------------------------------------------
    @staticmethod
    def _reply_tokens(reply: Any) -> int:
        usage = getattr(reply, "usage", None)
        if not isinstance(usage, dict):
            return 0
        return int(usage.get("total_tokens")
                   or (int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)))

    def _roundtable_debaters(self, requested: list[str], chief: dict[str, Any]) -> list[dict[str, Any]]:
        if requested:
            debaters: list[dict[str, Any]] = []
            for pid in requested:
                ag = self._resolve_bus_endpoint(pid)
                if not self._bus_eligible(ag):
                    raise ValueError(f"红线拦截：{ag.get('name', pid)} 是网页/订阅通道，不能进圆桌总线。")
                if ag.get("floor") not in ("manager", "chief", "chairman"):
                    raise ValueError(f"圆桌只接 2楼经理/总管，{ag.get('name')} 不是经理层。")
                if not any(d["id"] == ag["id"] for d in debaters):
                    debaters.append(ag)
            return debaters
        debaters = [a for a in self.state["agents"]
                    if a.get("floor") == "manager" and a.get("status") == "ready" and self._bus_eligible(a)]
        if len(debaters) < 2 and self._bus_eligible(chief) and not any(d["id"] == chief["id"] for d in debaters):
            debaters.append(chief)
        return debaters

    def runroundtable(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Roundtable: >=2 managers each give one conclusion-only opinion on the
        same proposal (real model calls), chief aggregates and adopts. Bounded
        rounds via the discussion bus. No usable model -> stop honestly."""
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        live = bool(payload.get("live", False))
        workspace_dir = (payload.get("workspace_dir") or "").strip()
        chief = self._chief_agent()
        requested = [str(p).strip() for p in (payload.get("participants") or []) if str(p).strip()]
        debaters = self._roundtable_debaters(requested, chief)
        with self._lock:
            if not payload.get("as_step"):
                task["mode"] = "roundtable"

        if len(debaters) < 2:
            self._append_group_msg(
                sender_id="chief", sender_name=chief["name"], sender_role="chief",
                kind="mode_stopped", task_id=task["id"],
                text=(f"⏸ **圆桌模式停下** `{task['id']}`：可用经理/总管不足 2 位（当前 {len(debaters)}），"
                      "无法开圆桌。请上线更多 API/CLI 经理后再跑，不伪造讨论。"),
            )
            self.save()
            return {"mode": "roundtable", "stopped": True, "reason": "insufficient_managers",
                    "debaters": [d["id"] for d in debaters]}

        disc = self.startdiscussion({
            "task_id": task["id"], "topic": (task.get("goal") or task["title"])[:60],
            "participants": [d["id"] for d in debaters],
        })
        disc_id = disc["id"]

        if not live:
            self._append_group_msg(
                sender_id="chief", sender_name=chief["name"], sender_role="chief",
                kind="mode_dry_run", task_id=task["id"],
                text=(f"🧪 **圆桌干跑（0 Token）** `{task['id']}`：已为 {len(debaters)} 位经理建好讨论串 `{disc_id}`，"
                      "但未调用真模型发言。点「真调」让经理各提一条结论意见、总管再汇总。"),
            )
            self._record_flight(
                from_id="chief", from_name=chief["name"], to_id="managers",
                to_name=f"{len(debaters)} 位经理圆桌", kind="roundtable", task_id=task["id"],
                summary=f"圆桌干跑 ({len(debaters)}经理)", channel="经理圆桌", status="ok",
            )
            self.save()
            return {"mode": "roundtable", "dry_run": True, "discussion_id": disc_id,
                    "debaters": [d["id"] for d in debaters], "opinions": 0, "tokens": 0}

        safe_ws = self._validate_safe_workspace(workspace_dir or ".")
        opinions: list[dict[str, Any]] = []
        tokens_total = 0
        for d in debaters:
            if d.get("access_kind") not in ("api", "cli", "chief"):
                continue
            prompt = (
                "你是 2 楼经理，参加圆桌评审。只就下面这个方案给一条结论性意见（支持/反对/修改建议），"
                "不超过 120 字，不贴整段对话、不重写全文代码，开头用【结论】。\n"
                f"方案目标：{task.get('goal') or task['title']}\n"
                f"验收标准：{task.get('acceptance') or '（未填）'}\n"
                f"当前产出摘要：{task.get('latest_report_summary') or '（尚无产出，请就目标本身评审）'}"
            )
            try:
                reply = self._build_adapter(d, workspace_dir=safe_ws).chat(prompt, max_tokens=300)
            except Exception as exc:  # noqa: BLE001 - skip honestly, never fabricate
                self._append_group_msg(
                    sender_id="chief", sender_name=chief["name"], sender_role="chief",
                    kind="mode_stopped", task_id=task["id"],
                    text=f"⏸ 圆桌：经理 {d['name']} 真调失败（{exc}），跳过其发言，不伪造意见。",
                )
                continue
            text = (reply.text or "").strip()
            if not text:
                continue
            tok = self._reply_tokens(reply)
            with self._lock:
                d["tokens_used"] = int(d.get("tokens_used") or 0) + tok
                self._record_savings(d, tok, task["id"], "discuss")
            tokens_total += tok
            stance = "oppose" if ("反对" in text or "不同意" in text) else ("revise" if ("修改" in text or "建议" in text) else "support")
            res = self.postdiscussionmessage({
                "discussion_id": disc_id, "from_id": d["id"], "text": text[:400],
                "stance": stance, "tokens": tok,
            })
            if res.get("blocked"):
                return {"mode": "roundtable", "stopped": True, "reason": "discussion_limit",
                        "discussion_id": disc_id, "opinions": len(opinions), "tokens": tokens_total}
            opinions.append({"from_id": d["id"], "from_name": d["name"], "text": text[:400], "stance": stance, "tokens": tok})

        if not opinions:
            self._append_group_msg(
                sender_id="chief", sender_name=chief["name"], sender_role="chief",
                kind="mode_stopped", task_id=task["id"],
                text=(f"⏸ **圆桌停下** `{task['id']}`：没有任何经理真调成功产出意见（无可用模型/额度）。"
                      "按红线不伪造讨论，已停下等主人处理。"),
            )
            self.save()
            return {"mode": "roundtable", "stopped": True, "reason": "no_real_model",
                    "discussion_id": disc_id, "opinions": 0, "tokens": 0}

        resolution, adopted = "", ""
        if chief.get("access_kind") in ("api", "cli"):
            try:
                opinions_block = "\n".join(f"- {o['from_name']}（{o['stance']}）：{o['text']}" for o in opinions)
                agg_prompt = (
                    "你是总管，汇总下面各位经理对同一方案的结论意见，给出最终裁决（采纳谁/综合方案），"
                    "不超过 150 字，开头用【结论】，不贴整段对话。\n" + opinions_block
                )
                reply = self._build_adapter(chief, workspace_dir=safe_ws).chat(agg_prompt, max_tokens=350)
                resolution = (reply.text or "").strip()[:400]
                tok = self._reply_tokens(reply)
                with self._lock:
                    chief["tokens_used"] = int(chief.get("tokens_used") or 0) + tok
                    self._record_savings(chief, tok, task["id"], "discuss_chief")
                tokens_total += tok
                adopted = next((o["from_name"] for o in opinions if o["from_name"] in resolution), opinions[0]["from_name"])
            except Exception:  # noqa: BLE001 - honest handoff to owner
                resolution, adopted = "", ""
        if not resolution:
            resolution = "（总管未真调汇总，请主人在讨论串里裁决采纳谁的意见）"
        closed = self.resolvediscussion({"discussion_id": disc_id, "resolution": resolution, "adopted": adopted})
        self._record_flight(
            from_id="chief", from_name=chief["name"], to_id="owner", to_name="你 (董事长)",
            kind="roundtable", task_id=task["id"], summary=f"圆桌汇总 ({len(opinions)}条意见)",
            channel="经理圆桌", status="ok",
        )
        self.save()
        return {"mode": "roundtable", "discussion_id": disc_id, "opinions": len(opinions),
                "tokens": tokens_total, "resolution": resolution, "adopted": adopted,
                "chief_aggregated": bool(adopted), "discussion": closed}

    def runswarm(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Swarm: two distinct-vendor free workers each draft the same task,
        chief picks the best (real model) and delivers to owner. No usable
        model -> stop honestly, never fabricate a winner."""
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        live = bool(payload.get("live", False))
        workspace_dir = (payload.get("workspace_dir") or "").strip()
        chief = self._chief_agent()
        workers = self._distinct_vendor_workers()
        free = [w for w in workers if not w.get("paid", False)]
        pool = free if len(free) >= 2 else workers
        with self._lock:
            task["mode"] = "swarm"
        if len(pool) < 2:
            self._append_group_msg(
                sender_id="chief", sender_name=chief["name"], sender_role="chief",
                kind="mode_stopped", task_id=task["id"],
                text=(f"⏸ **撒网竞选停下** `{task['id']}`：需要至少 2 名不同厂商的可用员工，当前 {len(pool)} 名。"
                      "请上线更多免费员工后再跑。"),
            )
            self.save()
            return {"mode": "swarm", "stopped": True, "reason": "insufficient_workers"}

        chosen = pool[:2]
        draft_ids: list[str] = []
        for i, w in enumerate(chosen, start=1):
            sub = self.createtask({
                "title": f"撒网初稿 {i}：{task['title'][:24]}",
                "manager_id": task.get("manager_id") or chief["id"],
                "assigned_to": w["id"],
                "goal": task.get("goal") or task["title"],
                "input_text": task.get("input_text") or "",
                "output_format": "只输出【结论】+【改动文件】+【测试结果】，不贴全文对话。",
                "acceptance": task.get("acceptance") or "结果完整、不编造数据、符合格式要求。",
                "task_kind": "small", "parent_task_id": task["id"], "force_new": True,
            })
            draft_ids.append(sub["id"])
        with self._lock:
            task["is_parent"] = True
            task["subtask_ids"] = list(dict.fromkeys(list(task.get("subtask_ids") or []) + draft_ids))
            task["assigned_to"] = ""
            task["assigned_name"] = f"撒网竞选 · {len(draft_ids)} 份初稿"
        self._append_group_msg(
            sender_id="chief", sender_name=chief["name"], sender_role="chief",
            kind="swarm_card", task_id=task["id"],
            text=(f"🐝 **撒网竞选启动** `{task['id']}`：{chosen[0]['name']} 与 {chosen[1]['name']} 各做一份初稿，"
                  "总管真调择优后交主人。"),
        )

        safe_ws = self._validate_safe_workspace(workspace_dir or ".")
        drafts: list[dict[str, Any]] = []
        for sid in draft_ids:
            sub = self._find_task(sid)
            if live:
                try:
                    res = self.runadaptertask({"task_id": sid, "live": True, "workspace_dir": safe_ws})
                    drafts.append({"task_id": sid, "worker": res["worker"], "summary": sub.get("latest_report_summary", ""), "ok": True})
                except Exception as exc:  # noqa: BLE001
                    drafts.append({"task_id": sid, "worker": sub.get("assigned_name", ""), "summary": "", "ok": False, "error": str(exc)})
            else:
                self.runadaptertask({"task_id": sid, "live": False, "workspace_dir": safe_ws})
                drafts.append({"task_id": sid, "worker": sub.get("assigned_name", ""), "summary": sub.get("latest_report_summary", ""), "ok": True, "dry_run": True})
        ok_drafts = [d for d in drafts if d["ok"] and d["summary"]]
        self._record_flight(
            from_id=chief["id"], from_name=chief["name"], to_id="workers",
            to_name=f"{len(draft_ids)} 份撒网初稿", kind="swarm", task_id=task["id"],
            summary=f"撒网 {len(ok_drafts)}/{len(draft_ids)} 份初稿", channel="撒网竞选", status="ok",
        )

        if not live:
            self._append_group_msg(
                sender_id="chief", sender_name=chief["name"], sender_role="chief",
                kind="mode_dry_run", task_id=task["id"],
                text=(f"🧪 **撒网干跑（0 Token）** `{task['id']}`：两份初稿已路由，未真调择优。"
                      "点「真调」让员工各做一份、总管挑最好的交主人。"),
            )
            self.save()
            return {"mode": "swarm", "dry_run": True, "drafts": drafts, "winner": "", "tokens": 0}

        worker_tokens = 0
        for sid in draft_ids:
            for u in self._find_task(sid).get("usage_log", []):
                worker_tokens += int((u.get("usage") or {}).get("total_tokens")
                                     or (int((u.get("usage") or {}).get("prompt_tokens") or 0)
                                         + int((u.get("usage") or {}).get("completion_tokens") or 0)))
        if not ok_drafts:
            self._append_group_msg(
                sender_id="chief", sender_name=chief["name"], sender_role="chief",
                kind="mode_stopped", task_id=task["id"],
                text=(f"⏸ **撒网停下** `{task['id']}`：两份初稿均未真调成功（无可用模型/额度）。"
                      "按红线不伪造，已停下等主人处理。"),
            )
            self.save()
            return {"mode": "swarm", "stopped": True, "reason": "no_real_model", "drafts": drafts, "tokens": worker_tokens}

        winner, winner_task, rationale = "", "", ""
        chief_tokens = 0
        if chief.get("access_kind") in ("api", "cli"):
            try:
                block = "\n".join(f"初稿{idx + 1}（{d['worker']}）：{d['summary'][:200]}" for idx, d in enumerate(ok_drafts))
                pick_prompt = (
                    "你是总管，下面是对同一任务的多份初稿结论。挑出最好的一份，只回一行："
                    "【结论】采纳初稿N（理由不超过60字）。不贴全文。\n" + block
                )
                reply = self._build_adapter(chief, workspace_dir=safe_ws).chat(pick_prompt, max_tokens=200)
                rationale = (reply.text or "").strip()[:300]
                chief_tokens = self._reply_tokens(reply)
                with self._lock:
                    chief["tokens_used"] = int(chief.get("tokens_used") or 0) + chief_tokens
                    self._record_savings(chief, chief_tokens, task["id"], "swarm_pick")
                m = re.search(r"初稿\s*(\d+)", rationale)
                if m:
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(ok_drafts):
                        winner = ok_drafts[idx]["worker"]
                        winner_task = ok_drafts[idx]["task_id"]
            except Exception:  # noqa: BLE001 - honest handoff
                winner, winner_task, rationale = "", "", ""
        tokens_total = worker_tokens + chief_tokens

        if not winner:
            for d in ok_drafts:
                self.deliverfinalresult({"task_id": d["task_id"]})
            self._append_group_msg(
                sender_id="chief", sender_name=chief["name"], sender_role="chief",
                kind="mode_stopped", task_id=task["id"],
                text=(f"⏸ **撒网：总管未真调择优** `{task['id']}`（无可用总管模型）。"
                      f"{len(ok_drafts)} 份初稿已分别交付，请主人手动挑选，不伪造赢家。"),
            )
            self.save()
            return {"mode": "swarm", "stopped": True, "reason": "chief_no_model",
                    "drafts": drafts, "winner": "", "tokens": tokens_total}

        win_sub = self._find_task(winner_task)
        summary = (
            f"🐝 **撒网竞选总交付**（总管真调择优）：\n"
            f"• 采纳：**{winner}** 的初稿 `{winner_task}`\n"
            f"• 裁决：{rationale}\n"
            f"• 成果摘要：\n{win_sub.get('latest_report_summary', '')}"
        )
        for d in ok_drafts:
            self.deliverfinalresult({"task_id": d["task_id"]})
        with self._lock:
            task["worker_reported"] = True
            task["latest_report_summary"] = summary[:320]
        delivered = self.deliverfinalresult({"task_id": task["id"], "summary": summary})
        self.save()
        return {"mode": "swarm", "drafts": drafts, "winner": winner, "winner_task": winner_task,
                "rationale": rationale, "tokens": tokens_total, "delivery": delivered}

    # ------------------------------------------------------------------
    # Action 37–46: In-office Message Bus (MCP Relay form) + Manager
    # Discussion Threads. Learned from Agent HUD: "a message, not the
    # conversation"; queue until the recipient is idle; bounded chain/pass
    # so two models never burn quota arguing forever. Web/subscription
    # workers are NOT bus members (red line) — they use the browser courier.
    # The relay only moves envelopes; all state/ledger math lives here in Core.
    # ------------------------------------------------------------------
    def _bus_eligible(self, agent: dict[str, Any]) -> bool:
        return (agent.get("access_kind") or "").lower() in ("api", "cli", "desktop", "chief")

    def _resolve_bus_endpoint(self, agent_id: str) -> dict[str, Any]:
        if agent_id in ("owner", "gao"):
            return {"id": "owner", "name": "你 (董事长)", "access_kind": "chief", "floor": "chairman"}
        return self._find_agent(agent_id)

    def _agent_busy(self, agent_id: str) -> bool:
        try:
            ag = self._find_agent(agent_id)
        except KeyError:
            return False
        if ag.get("status") in ("busy", "exhausted") or ag.get("floor") == "rest":
            return True
        for t in self.state["tasks"]:
            if t.get("assigned_to") == agent_id and t.get("status") in ("accepted", "working", "in_review"):
                return True
        return False

    def listbusmessages(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._ensure_runtime_keys()
        return list(self.state.get("bus_messages", []))

    def bussend(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Move ONE conclusion-only message between two bus-eligible agents.

        Queues when the recipient is busy (never interrupts a running task);
        blocks when the chain/pass ceiling is exceeded; rejects web workers.
        """
        self._ensure_runtime_keys()
        from_id = (payload.get("from_id") or payload.get("sender_id") or "").strip()
        to_id = (payload.get("to_id") or payload.get("recipient_id") or "").strip()
        if not from_id or not to_id:
            raise ValueError("总线消息必须指明 from_id 与 to_id。")
        text = (payload.get("text") or payload.get("conclusion") or "").strip()
        if not text:
            raise ValueError("总线消息内容不能为空（只传结论，不传整段对话）。")
        self._reject_full_conversation_paste(text)

        sender = self._resolve_bus_endpoint(from_id)
        recipient = self._resolve_bus_endpoint(to_id)
        if not self._bus_eligible(sender):
            raise ValueError(f"红线拦截：{sender.get('name', from_id)} 属于网页/订阅通道，不能作为总线发送方。")
        if not self._bus_eligible(recipient):
            raise ValueError(
                f"红线拦截：{recipient.get('name', to_id)} 属于网页/订阅通道，不进 MCP 总线。"
                "网页免费员工请走传令兵浏览器扩展自动填表+抓回，不许包装成总线客户端。"
            )

        kind = (payload.get("kind") or "conclusion").strip().lower()
        task_id = (payload.get("task_id") or "").strip()
        chain_id = (payload.get("chain_id") or task_id or f"chain-{int(time.time() * 1000)}").strip()
        prior = [m for m in self.state["bus_messages"] if m.get("chain_id") == chain_id]
        pass_no = len(prior) + 1
        max_pass = int(self.state["settings"].get("max_chain_pass", MAX_CHAIN_PASS))
        tokens = int(payload.get("tokens") or 0)

        env = {
            "id": f"bus-{int(time.time() * 1000)}-{len(self.state['bus_messages']) + 1}",
            "chain_id": chain_id, "pass": pass_no,
            "from_id": sender["id"], "from_name": sender["name"],
            "to_id": recipient["id"], "to_name": recipient["name"],
            "task_id": task_id, "kind": kind, "text": text,
            "tokens": tokens, "channel": self._channel_label(recipient),
            "status": "delivered", "block_reason": "",
            "created_at": _now_iso(), "delivered_at": "",
        }

        if pass_no > max_pass:
            env["status"] = "blocked"
            env["block_reason"] = "chain_pass_limit"
            self.state["bus_messages"].append(env)
            self._append_group_msg(
                sender_id=sender["id"], sender_name=sender["name"],
                sender_role=sender.get("floor", "chief"), kind="circuit_breaker",
                task_id=task_id or None,
                text=(f"⛔ **跨 agent 连续传递熔断**（chain `{chain_id}` 已达 {max_pass} 次上限）\n"
                      f"• {sender['name']} → {recipient['name']} 的第 {pass_no} 次投递被拦截。\n"
                      f"• 自动停下，等主人介入，不再继续烧额度互传。"),
            )
            self._record_flight(
                from_id=sender["id"], from_name=sender["name"],
                to_id=recipient["id"], to_name=recipient["name"],
                kind="circuit_breaker", task_id=task_id,
                summary=f"传递超限熔断 ({max_pass})", channel=env["channel"], status="blocked",
            )
            self.save()
            return env

        if self._agent_busy(recipient["id"]) and not payload.get("interrupt"):
            env["status"] = "queued"
        else:
            env["delivered_at"] = _now_iso()
        self.state["bus_messages"].append(env)
        if env["status"] == "delivered" and kind in ("conclusion", "handoff", "review"):
            self._append_group_msg(
                sender_id=sender["id"], sender_name=sender["name"],
                sender_role=sender.get("floor", "chief"), kind="bus_card",
                task_id=task_id or None,
                text=f"✉ **总线投递** {sender['name']} → @{recipient['name']}（{kind} · pass {pass_no}）\n{text[:300]}",
            )
        self._record_flight(
            from_id=sender["id"], from_name=sender["name"],
            to_id=recipient["id"], to_name=recipient["name"],
            kind="bus_" + kind, task_id=task_id,
            summary=f"{kind} pass{pass_no}" + (" (排队)" if env["status"] == "queued" else ""),
            channel=env["channel"], status="queued" if env["status"] == "queued" else "ok",
        )
        self.save()
        return env

    def businbox(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        self._ensure_runtime_keys()
        agent_id = (payload.get("agent_id") or payload.get("to_id") or "").strip()
        include_blocked = bool(payload.get("include_blocked", False))
        return [
            m for m in self.state["bus_messages"]
            if m.get("to_id") == agent_id and (include_blocked or m.get("status") != "blocked")
        ]

    def sendconclusion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Core-side conclusion delivery (the MCP relay forwards here; it never
        formats or parses chat itself). Format + bus delivery + optional report."""
        sender_id = (payload.get("sender_id") or payload.get("from_id") or "").strip()
        to_id = (payload.get("to_id") or "").strip()
        if sender_id and sender_id == to_id:
            raise ValueError("总线发送方与接收方不能是同一个 Agent。")
        conclusion = (payload.get("conclusion") or "").strip()
        text = format_conclusion_report(
            conclusion, payload.get("changed_files"),
            payload.get("test_result") or "未运行测试", payload.get("diff_summary") or "",
        )
        task_id = (payload.get("task_id") or "").strip()
        env = self.bussend({
            "from_id": sender_id, "to_id": to_id, "text": text,
            "kind": "conclusion", "task_id": task_id, "tokens": int(payload.get("tokens") or 0),
        })
        report = None
        if task_id:
            report = self.postmessage({
                "task_id": task_id, "sender_id": sender_id, "conclusion": conclusion,
                "changed_files": payload.get("changed_files"),
                "test_result": payload.get("test_result") or "未运行测试",
                "diff_summary": payload.get("diff_summary") or "", "is_delivery": True,
            })
        return {"bus": env, "report": report}

    def busflush(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Deliver queued messages to an agent once it goes idle (no interrupt)."""
        self._ensure_runtime_keys()
        agent_id = (payload.get("agent_id") or "").strip()
        if self._agent_busy(agent_id):
            return {"agent_id": agent_id, "delivered": 0, "still_busy": True}
        delivered = 0
        for m in self.state["bus_messages"]:
            if m.get("to_id") == agent_id and m.get("status") == "queued":
                m["status"] = "delivered"
                m["delivered_at"] = _now_iso()
                delivered += 1
        if delivered:
            self.save()
        return {"agent_id": agent_id, "delivered": delivered, "still_busy": False}

    def busledger(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Bus accounting computed in Core (the relay never re-parses chat)."""
        self._ensure_runtime_keys()
        msgs = self.state["bus_messages"]
        by_kind: dict[str, int] = {}
        by_agent: dict[str, dict[str, int]] = {}
        tokens = blocked = queued = 0
        for m in msgs:
            by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1
            tokens += int(m.get("tokens") or 0)
            blocked += 1 if m["status"] == "blocked" else 0
            queued += 1 if m["status"] == "queued" else 0
            s = by_agent.setdefault(m["from_id"], {"sent": 0, "received": 0, "tokens": 0})
            s["sent"] += 1
            s["tokens"] += int(m.get("tokens") or 0)
            by_agent.setdefault(m["to_id"], {"sent": 0, "received": 0, "tokens": 0})["received"] += 1
        return {
            "total_messages": len(msgs), "by_kind": by_kind, "tokens": tokens,
            "blocked": blocked, "queued": queued, "by_agent": by_agent,
        }

    # ------------------------------------------------------------------
    # Manager discussion threads (Roundtable surface). Conclusion-only,
    # pass-counted via the bus, bounded rounds -> deadlock escalates to owner.
    # ------------------------------------------------------------------
    def listdiscussions(self, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._ensure_runtime_keys()
        return list(self.state.get("discussions", {}).values())

    def listdiscussion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_runtime_keys()
        disc_id = (payload.get("discussion_id") or payload.get("task_id") or payload.get("id") or "").strip()
        disc = self.state["discussions"].get(disc_id)
        if disc is None:
            raise KeyError(f"找不到讨论串: {disc_id}")
        return disc

    def startdiscussion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_runtime_keys()
        task_id = (payload.get("task_id") or "").strip()
        topic = (payload.get("topic") or "经理圆桌讨论").strip()
        participants = []
        for pid in (payload.get("participants") or []):
            ag = self._resolve_bus_endpoint(pid)
            if not self._bus_eligible(ag):
                raise ValueError(f"红线拦截：{ag.get('name', pid)} 是网页/订阅通道，不能进经理讨论总线。")
            if ag.get("floor") not in ("manager", "chief", "chairman"):
                raise ValueError(f"经理讨论串只接 2楼经理/总管，{ag.get('name')} 不是经理层。")
            if not any(p["id"] == ag["id"] for p in participants):
                participants.append({"id": ag["id"], "name": ag["name"]})
        if len(participants) < 2:
            raise ValueError("圆桌讨论至少需要 2 位经理/总管参与。")
        disc_id = task_id or f"disc-{int(time.time() * 1000)}"
        disc = {
            "id": disc_id, "task_id": task_id, "topic": topic,
            "participants": participants, "messages": [],
            "round_limit": int(self.state["settings"].get("max_discussion_rounds", MAX_DISCUSSION_ROUNDS)),
            "status": "open", "resolution": "", "adopted": "",
            "circuit_breaker": "", "created_at": _now_iso(),
        }
        self.state["discussions"][disc_id] = disc
        names = "、".join(p["name"] for p in participants)
        self._append_group_msg(
            sender_id="chief", sender_name=self._chief_agent()["name"], sender_role="chief",
            kind="discussion_open", task_id=task_id or None,
            text=f"💬 **经理讨论串开启** `{disc_id}` · {topic}\n参与：{names}（只传结论/观点，计 pass，超 {disc['round_limit']} 轮自动熔断交主人）。",
        )
        self.save()
        return disc

    def postdiscussionmessage(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_runtime_keys()
        disc_id = (payload.get("discussion_id") or payload.get("task_id") or "").strip()
        disc = self.state["discussions"].get(disc_id)
        if disc is None:
            raise KeyError(f"找不到讨论串: {disc_id}")
        if disc["status"] != "open":
            raise ValueError(f"讨论串已 {disc['status']}，不能再发言（熔断或已裁决）。")
        ag = self._resolve_bus_endpoint((payload.get("from_id") or "").strip())
        if not any(p["id"] == ag["id"] for p in disc["participants"]):
            raise ValueError("只有本讨论串的参与经理才能发言。")
        text = (payload.get("text") or payload.get("conclusion") or "").strip()
        if not text:
            raise ValueError("讨论发言不能为空（只传结论/观点，不贴整段对话）。")
        self._reject_full_conversation_paste(text)
        stance = (payload.get("stance") or "comment").strip().lower()
        n = max(1, len(disc["participants"]))
        round_no = len(disc["messages"]) // n + 1
        if round_no > disc["round_limit"]:
            disc["status"] = "deadlock"
            disc["circuit_breaker"] = "discussion_limit"
            opposes = [m for m in disc["messages"] if m.get("stance") == "oppose"]
            disagreements = "\n".join(f"  • {m['from_name']}: {m['text'][:120]}" for m in opposes) or "  （无明确反对，但已达轮数上限）"
            breaker_text = (
                f"⛔ **经理讨论熔断（已达 {disc['round_limit']} 轮上限）** 讨论 `{disc_id}`\n"
                f"• 自动停下，分歧点汇总交主人裁决：\n{disagreements}"
            )
            self._append_group_msg(
                sender_id="chief", sender_name=self._chief_agent()["name"], sender_role="chief",
                kind="circuit_breaker", task_id=disc["task_id"] or None, text=breaker_text,
            )
            self._record_flight(
                from_id=ag["id"], from_name=ag["name"], to_id="owner", to_name="你 (董事长)",
                kind="circuit_breaker", task_id=disc["task_id"],
                summary=f"讨论超限熔断 ({disc['round_limit']}轮)", channel="经理圆桌", status="blocked",
            )
            self.save()
            return {"blocked": True, "circuit_breaker": "discussion_limit", "discussion": disc}
        msg = {
            "id": f"dmsg-{int(time.time() * 1000)}-{len(disc['messages']) + 1}",
            "from_id": ag["id"], "from_name": ag["name"],
            "text": text, "stance": stance, "round": round_no, "created_at": _now_iso(),
        }
        disc["messages"].append(msg)
        for p in disc["participants"]:
            if p["id"] != ag["id"]:
                self.bussend({
                    "from_id": ag["id"], "to_id": p["id"], "text": text,
                    "kind": "discussion", "task_id": disc["task_id"],
                    "chain_id": disc_id, "tokens": int(payload.get("tokens") or 0),
                })
        self.save()
        return msg

    def resolvediscussion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_runtime_keys()
        disc_id = (payload.get("discussion_id") or payload.get("task_id") or "").strip()
        disc = self.state["discussions"].get(disc_id)
        if disc is None:
            raise KeyError(f"找不到讨论串: {disc_id}")
        disc["resolution"] = (payload.get("resolution") or "").strip()
        disc["adopted"] = (payload.get("adopted") or "").strip()
        disc["status"] = "closed"
        self._append_group_msg(
            sender_id="chief", sender_name=self._chief_agent()["name"], sender_role="chief",
            kind="discussion_closed", task_id=disc["task_id"] or None,
            text=(f"✅ **经理讨论已裁决** `{disc_id}` · 采纳：**{disc['adopted'] or '综合意见'}**\n"
                  f"• 结论：{disc['resolution'] or '（见讨论串）'}"),
        )
        self.save()
        return disc

    # ------------------------------------------------------------------
    # P2: Auto-orchestration closed loop + savings ledger.
    # publish -> split -> dispatch -> execute -> report -> review -> discuss
    # -> aggregate -> deliver, pushed unattended by the office. Every
    # model-dependent step runs ONLY when a real model is available; otherwise
    # it stops honestly and records why (red line §七). The savings ledger
    # counts REAL recorded tokens only — dry-run contributes 0, never invented.
    # ------------------------------------------------------------------
    def _record_savings(self, agent: dict[str, Any], tokens: int, task_id: str, kind: str = "execute") -> None:
        with self._lock:
            ledger = self.state.setdefault("savings_ledger", [])
            ledger.append({
                "ts": _now_iso(), "date": _now_iso()[:10],
                "agent_id": agent.get("id", ""), "agent_name": agent.get("name", ""),
                "vendor": agent.get("vendor", ""), "floor": agent.get("floor", ""),
                "paid": bool(agent.get("paid", False)), "access_kind": agent.get("access_kind", ""),
                "tokens": int(tokens or 0), "task_id": task_id, "kind": kind,
            })
            if len(ledger) > 5000:
                self.state["savings_ledger"] = ledger[-5000:]

    def savingsledger(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """By-day / by-week accounting of 1F free workers substituting for 2F
        paid managers. Only real recorded tokens; rehearsal counts 0."""
        self._ensure_runtime_keys()
        events = self.state.get("savings_ledger", [])

        def is_free(e: dict[str, Any]) -> bool:
            return e.get("floor") == "worker" and not e.get("paid")

        free = [e for e in events if is_free(e)]
        paid = [e for e in events if not is_free(e)]
        by_day: dict[str, dict[str, int]] = {}
        by_week: dict[str, dict[str, int]] = {}
        for e in events:
            d = e.get("date", "")
            if not d:
                continue
            tok = int(e.get("tokens") or 0)
            fr = is_free(e)
            for key, bucket_map in ((d, by_day), (self._week_key(d), by_week)):
                b = bucket_map.setdefault(key, {"free_calls": 0, "free_tokens": 0, "paid_calls": 0, "paid_tokens": 0})
                if fr:
                    b["free_calls"] += 1
                    b["free_tokens"] += tok
                else:
                    b["paid_calls"] += 1
                    b["paid_tokens"] += tok
        return {
            "free_calls": len(free),
            "free_tokens": sum(int(e.get("tokens") or 0) for e in free),
            "paid_calls": len(paid),
            "paid_tokens": sum(int(e.get("tokens") or 0) for e in paid),
            "by_day": [{"date": k, **by_day[k]} for k in sorted(by_day)],
            "by_week": [{"week": k, **by_week[k]} for k in sorted(by_week)],
            "note": "只统计真实记录的 Token；干跑计 0。免费员工(1F)替付费经理(2F)执行的真实调用次数与 Token。",
        }

    @staticmethod
    def _week_key(day: str) -> str:
        try:
            iso = date.fromisoformat(day).isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        except ValueError:
            return day

    def _plan_with_manager(self, manager: dict[str, Any], goal: str, workspace_dir: str) -> list[dict[str, Any]] | None:
        """Ask a real 2F manager model for a structured subtask DAG. Returns
        None when no usable model / parse fails, so the caller falls back to
        rule split and labels it honestly."""
        if manager.get("access_kind") not in ("api", "cli"):
            return None
        try:
            safe_ws = self._validate_safe_workspace(workspace_dir or ".")
            prompt = (
                "你是 2 楼经理，负责把下面的需求拆成可并行/有依赖的子单 DAG。"
                "只输出一个 JSON 数组，不要解释、不要贴全文。每个元素形如 "
                '{"title":"短标题","goal":"具体目标","task_kind":"small 或 code_change","depends_on":[上游子单的1-based序号]}。'
                "改代码/修复/单测的子单 task_kind 用 code_change，其余用 small。子单数量 2-6 个。\n"
                f"需求：{goal}"
            )
            reply = self._build_adapter(manager, workspace_dir=safe_ws).chat(prompt, max_tokens=900)
            tok = self._reply_tokens(reply)
            with self._lock:
                manager["tokens_used"] = int(manager.get("tokens_used") or 0) + tok
            self._record_savings(manager, tok, "", "plan")
            raw = (reply.text or "").strip()
            start, end = raw.find("["), raw.rfind("]")
            if start < 0 or end <= start:
                return None
            parsed = json.loads(raw[start:end + 1])
            if not isinstance(parsed, list) or not parsed:
                return None
            specs: list[dict[str, Any]] = []
            for item in parsed[:6]:
                if not isinstance(item, dict):
                    continue
                g = (item.get("goal") or item.get("title") or "").strip()
                if not g:
                    continue
                kind = "code_change" if str(item.get("task_kind", "")).lower() == "code_change" else "small"
                specs.append({
                    "title": (item.get("title") or g)[:36],
                    "goal": g, "task_kind": kind,
                    "skill_slug": "cheap-code-jobs" if kind == "code_change" else "",
                    "depends_on": item.get("depends_on") or [],
                })
            return specs or None
        except Exception:  # noqa: BLE001 - honest fallback to rule split
            return None

    def autopublish(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One-click publish: split (real manager DAG if a model is available,
        else rule split + honest label) -> set mode -> dispatch to free workers
        (distinct-vendor round-robin, tired workers excluded). Optionally chains
        autorun so the whole loop runs unattended."""
        text = (payload.get("text") or payload.get("goal") or payload.get("title") or "").strip()
        if not text:
            raise ValueError("发布内容不能为空（一句话或一张工单）。")
        mode = (payload.get("mode") or "split").strip().lower()
        if mode not in ("solo", "roundtable", "critic", "pipeline", "split", "swarm"):
            mode = "split"
        workspace_dir = (payload.get("workspace_dir") or "").strip()
        chief = self._chief_agent()
        manager_id = payload.get("manager_id") or ""
        if manager_id:
            manager = self._find_agent(manager_id)
        else:
            ready_mgrs = [a for a in self.state["agents"]
                          if a.get("floor") == "manager" and a.get("status") == "ready"
                          and a.get("access_kind") in ("api", "cli")]
            manager = ready_mgrs[0] if ready_mgrs else chief
        if manager.get("floor") not in ("manager", "chief", "chairman"):
            manager = chief

        specs = None
        plan_source = "rule"
        if payload.get("live_plan") or payload.get("live"):
            specs = self._plan_with_manager(manager, text, workspace_dir)
            if specs:
                plan_source = "model"

        title = (payload.get("title") or text.splitlines()[0])[:40]
        if mode in ("swarm", "roundtable"):
            # These modes have their own structure (2 drafts / manager debate),
            # not a step split. Create one task; the mode runner builds the rest.
            parent = self.createtask({
                "title": title, "goal": text, "manager_id": manager["id"], "mode": mode,
                "task_kind": "small", "input_text": text,
                "output_format": "只输出【结论】+【改动文件】+【测试结果】，不贴全文对话。",
                "acceptance": payload.get("acceptance") or "结果完整、不编造数据、符合格式要求。",
                "idempotency_key": payload.get("idempotency_key") or "",
                "force_new": payload.get("force_new", False),
            })
            subs: list[dict[str, Any]] = []
            plan_source = "mode"
            label = "撒网竞选：两名免费员工各做初稿、总管择优" if mode == "swarm" else "圆桌讨论：多位经理各提意见、总管汇总"
            sub_line = "（本模式不拆步骤子单）"
            replay = False
        else:
            created = self.createbigtask({
                "title": title, "goal": text,
                "subtasks": specs if specs else None,
                "raw_steps": "" if specs else text,
                "mode": mode, "manager_id": manager["id"],
                "idempotency_key": payload.get("idempotency_key") or "",
                "force_new": payload.get("force_new", False),
            })
            parent = created["parent"]
            subs = created["subtasks"]
            replay = created.get("idempotent_replay", False)
            label = ("真模型经理规划 DAG" if plan_source == "model"
                     else "本次是规则拆单，未用真模型规划")
            sub_line = f"已拆 {len(subs)} 张子单，按免费员工跨厂商轮换派发。"
        with self._lock:
            parent["plan_source"] = plan_source
        self._append_group_msg(
            sender_id=manager["id"], sender_name=manager["name"], sender_role="manager",
            kind="publish_card", task_id=parent["id"],
            text=(f"🚀 **一键发布** `{parent['id']}` · 模式 **{mode}** · {label}\n"
                  f"• 需求：{text[:120]}\n• {sub_line}"),
        )
        self.save()
        result: dict[str, Any] = {
            "parent": parent, "subtasks": subs,
            "plan_source": plan_source, "mode": mode, "idempotent_replay": replay,
        }
        if payload.get("run"):
            result["autorun"] = self.autorun({
                "parent_task_id": parent["id"], "live": bool(payload.get("live", False)),
                "workspace_dir": workspace_dir, "discuss": payload.get("discuss", True),
            })
        return result

    def autorun(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Unattended pipeline driver. Pushes a published task through
        execute -> report -> review -> discuss -> aggregate -> deliver using the
        existing engines. Stops honestly at any step that lacks a real model or
        trips a breaker; never fabricates progress."""
        parent = self._find_task(payload.get("parent_task_id") or payload.get("task_id") or payload.get("id"))
        live = bool(payload.get("live", False))
        workspace_dir = (payload.get("workspace_dir") or "").strip()
        discuss = bool(payload.get("discuss", True))
        steps: list[dict[str, Any]] = []
        stopped_reason = ""

        def step(name: str, status: str, detail: str = "", **extra: Any) -> None:
            steps.append({"step": name, "status": status, "detail": detail, **extra})

        is_parent = bool(parent.get("is_parent") and parent.get("subtask_ids"))
        subtasks = ([self._find_task(sid) for sid in parent["subtask_ids"]
                     if any(t["id"] == sid for t in self.state["tasks"])] if is_parent else [parent])

        # Specialized single-task modes delegate to their own runners.
        mode = (parent.get("mode") or "split").strip().lower()
        if not is_parent and mode == "swarm":
            r = self.runswarm({"task_id": parent["id"], "live": live, "workspace_dir": workspace_dir})
            if r.get("dry_run"):
                step("execute", "dry_run", "撒网干跑：两份初稿已路由，未真调择优")
                return {"parent_id": parent["id"], "live": live, "delivered": False, "stopped_reason": "", "steps": steps}
            if r.get("stopped"):
                step("execute", "stopped", f"撒网停下：{r.get('reason')}")
                return {"parent_id": parent["id"], "live": live, "delivered": False, "stopped_reason": r.get("reason"), "steps": steps}
            step("execute", "ok", f"{len(r.get('drafts', []))} 份初稿，总管择优 {r.get('winner')}")
            step("deliver", "ok", "撒网总交付已发 @主人验收")
            return {"parent_id": parent["id"], "live": live, "delivered": True, "stopped_reason": "",
                    "steps": steps, "status": "delivered", "savings": self.savingsledger()}
        if not is_parent and mode == "roundtable":
            r = self.runroundtable({"task_id": parent["id"], "live": live, "workspace_dir": workspace_dir})
            if r.get("dry_run"):
                step("discuss", "dry_run", "圆桌干跑：已建讨论串，未真模型发言")
                return {"parent_id": parent["id"], "live": live, "delivered": False, "stopped_reason": "", "steps": steps}
            if r.get("stopped"):
                step("discuss", "stopped", f"圆桌停下：{r.get('reason')}")
                return {"parent_id": parent["id"], "live": live, "delivered": False, "stopped_reason": r.get("reason"), "steps": steps}
            step("discuss", "ok", f"{r.get('opinions')} 条真模型意见，采纳 {r.get('adopted') or '综合'}")
            delivered = self.deliverfinalresult({"task_id": parent["id"], "summary": f"💬 **圆桌裁决交付**：{r.get('resolution')}"})
            step("deliver", "ok", "圆桌裁决已发 @主人验收")
            return {"parent_id": parent["id"], "live": live, "delivered": True, "stopped_reason": "",
                    "steps": steps, "status": delivered.get("status"), "savings": self.savingsledger()}

        # 1) Execute (workers auto-report conclusions to private chat).
        if is_parent:
            batch = self.runbigtasksubtasks({"parent_task_id": parent["id"], "live": live, "workspace_dir": workspace_dir})
            failed = [r for r in batch["results"] if r.get("ok") is False]
            pending = [r for r in batch["results"] if r.get("skipped")]
            ex = batch["executed_count"]
            status = "ok" if ex and not failed and not pending else ("partial" if ex else "stopped")
            detail = f"执行 {ex} 张子单"
            if failed:
                detail += f"；{len(failed)} 张真调失败"
            if pending:
                detail += f"；{len(pending)} 张等待网页/桌面通道自动回执或上游依赖"
            step("execute", status, detail, executed=ex, failed=len(failed), pending=len(pending))
        else:
            try:
                res = self.runadaptertask({"task_id": parent["id"], "live": live, "workspace_dir": workspace_dir})
                step("execute", "ok", f"{res['worker']} 已汇报结论", worker=res["worker"])
            except Exception as exc:  # noqa: BLE001
                step("execute", "stopped", str(exc))
                return {"parent_id": parent["id"], "live": live, "delivered": False,
                        "stopped_reason": "execute_failed", "steps": steps}

        # 2) Write -> review -> revise loop for code subtasks (reviewer != author).
        max_rounds = int(self.state["settings"].get("max_revision_rounds", MAX_REVISION_ROUNDS))
        for sub in subtasks:
            if not sub.get("requires_code_review") or not sub.get("worker_reported"):
                continue
            if sub.get("review_status") == "approved":
                continue
            for _ in range(max_rounds + 1):
                try:
                    rev = self.runautocodereview({"task_id": sub["id"], "live": live, "workspace_dir": workspace_dir})
                except Exception as exc:  # noqa: BLE001 - honest stop, no fake review
                    step("review", "stopped", f"{sub['id']} 审查停下：{exc}", task_id=sub["id"])
                    stopped_reason = stopped_reason or "review_no_model"
                    break
                if rev.get("review_status") == "approved":
                    step("review", "ok", f"{sub['id']} 通过独立审查（{rev.get('reviewer')}）", task_id=sub["id"])
                    break
                if sub.get("circuit_breaker"):
                    step("review", "breaker", f"{sub['id']} 打回超限熔断，停下交主人", task_id=sub["id"])
                    stopped_reason = stopped_reason or "revision_limit"
                    break
                # rejected but under ceiling -> worker revises, then re-review
                try:
                    self.runadaptertask({"task_id": sub["id"], "live": live, "workspace_dir": workspace_dir})
                except Exception as exc:  # noqa: BLE001
                    step("review", "stopped", f"{sub['id']} 返工执行失败：{exc}", task_id=sub["id"])
                    stopped_reason = stopped_reason or "revise_failed"
                    break

        # 3) Manager discussion one round before aggregation (real models only).
        if discuss and is_parent:
            rt = self.runroundtable({"task_id": parent["id"], "live": live, "workspace_dir": workspace_dir, "as_step": True})
            if rt.get("dry_run"):
                step("discuss", "dry_run", "圆桌干跑：已建讨论串，未真模型发言")
            elif rt.get("stopped"):
                step("discuss", "stopped", f"经理讨论停下：{rt.get('reason')}（不伪造讨论）")
            else:
                step("discuss", "ok", f"{rt.get('opinions')} 条真模型意见，总管采纳 {rt.get('adopted') or '综合'}")

        # 4) Aggregate + 5) Deliver (chief summarizes conclusions, @owner accept).
        if is_parent:
            try:
                delivered = self.aggregatebigtask({"parent_task_id": parent["id"]})
                step("aggregate", "ok", f"汇总 {len(subtasks)} 张子单结论")
                step("deliver", "ok", "已发最终交付卡 @主人验收")
            except ValueError as exc:
                step("aggregate", "blocked", str(exc))
                return {"parent_id": parent["id"], "live": live, "delivered": False,
                        "stopped_reason": stopped_reason or "aggregate_blocked", "steps": steps}
        else:
            if parent.get("requires_code_review") and parent.get("review_status") != "approved":
                step("deliver", "blocked", "改代码任务未过审，不能交付")
                return {"parent_id": parent["id"], "live": live, "delivered": False,
                        "stopped_reason": stopped_reason or "review_pending", "steps": steps}
            delivered = self.deliverfinalresult({"task_id": parent["id"]})
            step("deliver", "ok", "已发最终交付卡 @主人验收")

        return {"parent_id": parent["id"], "live": live, "delivered": True,
                "stopped_reason": stopped_reason, "steps": steps,
                "status": delivered.get("status"), "savings": self.savingsledger()}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _validate_safe_workspace(self, raw_dir: str) -> str:
        ws = (raw_dir or ".").strip() or "."
        if ws == ".":
            return str(Path(__file__).resolve().parents[1])
        resolved = Path(ws).expanduser().resolve()
        low = str(resolved).lower()
        forbidden = (
            "c:\\windows", "c:\\program files", "c:\\program files (x86)",
            "/etc", "/usr", "/bin", "/sbin", "/system", "/library",
        )
        if any(low == f or low.startswith(f + "\\") or low.startswith(f + "/") for f in forbidden) or resolved == Path(resolved.anchor):
            raise ValueError(f"安全拦截：禁止将系统敏感目录作为工作空间：{resolved}")
        return str(resolved)

    def _build_adapter(self, agent: dict[str, Any], workspace_dir: str = "."):
        kind = agent.get("access_kind")
        slug = agent.get("adapter_slug") or ""
        if kind == "api":
            if agent.get("base_url") and agent.get("key_env"):
                return get_adapter(
                    "custom-api",
                    vendor=agent["vendor"],
                    model_id=agent["model"],
                    base_url=agent["base_url"],
                    key_env=agent["key_env"],
                    paid=bool(agent.get("paid", False)),
                )
            if slug in registered_slugs():
                return get_adapter(slug)
        if kind == "cli":
            return get_adapter(
                "cli-generic",
                vendor=agent["vendor"],
                model_id=agent["model"],
                executable=agent.get("executable") or "codex",
                workspace=workspace_dir,
                paid=bool(agent.get("paid", False)),
            )
        if slug in registered_slugs():
            return get_adapter(slug)
        raise RuntimeError(f"{agent['name']} 尚未绑定可执行的 Adapter。")
    def _chief_agent(self) -> dict[str, Any]:
        for a in self.state["agents"]:
            if a.get("access_kind") == "chief" or a["id"] in ("chief", "muse"):
                return a
        return self.state["agents"][0] if self.state["agents"] else {"id": "chief", "name": "总管 (Chief)"}

    def _find_agent(self, agent_id: str | None) -> dict[str, Any]:
        for a in self.state["agents"]:
            if a["id"] == agent_id:
                return a
        raise KeyError(f"找不到 Agent: {agent_id}")

    def _find_task(self, task_id: str | None) -> dict[str, Any]:
        for t in self.state["tasks"]:
            if t["id"] == task_id:
                return t
        raise KeyError(f"找不到任务: {task_id}")

    def _append_group_msg(self, sender_id: str, sender_name: str, kind: str, text: str,
                          sender_role: str = "chief", task_id: str | None = None) -> dict[str, Any]:
        msg = {
            "id": f"gmsg-{int(time.time() * 1000)}-{len(self.state['group_messages']) + 1}",
            "sender_id": sender_id,
            "sender_name": sender_name,
            "sender_role": sender_role,
            "kind": kind,
            "task_id": task_id,
            "text": text,
            "created_at": _now_iso(),
        }
        self.state["group_messages"].append(msg)
        return msg

    def _append_task_msg(self, task_id: str, sender_id: str, sender_name: str,
                         kind: str, text: str, usage: dict | None = None) -> dict[str, Any]:
        msgs = self.state["task_messages"].setdefault(task_id, [])
        msg = {
            "id": f"tmsg-{int(time.time() * 1000)}-{len(msgs) + 1}",
            "task_id": task_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "kind": kind,
            "text": text,
            "usage": usage or {},
            "created_at": _now_iso(),
        }
        msgs.append(msg)
        return msg

    def _channel_label(self, agent: dict[str, Any] | None) -> str:
        if not agent:
            return "工作台"
        ak = (agent.get("access_kind") or "").lower()
        if ak in ("web", "subscription"):
            return "浏览器传令兵/网页"
        if ak == "desktop":
            return ".md 文件信箱 (桌面端)"
        if ak == "cli":
            return "CLI 命令行"
        if ak == "api":
            return "API 结论通道"
        return "总管统筹"

    def _record_flight(
        self,
        from_id: str,
        from_name: str,
        to_id: str,
        to_name: str,
        kind: str,
        task_id: str = "",
        summary: str = "",
        channel: str = "",
        status: str = "ok",
    ) -> dict[str, Any]:
        flights = self.state.setdefault("hud_flights", [])
        entry = {
            "id": f"flt-{int(time.time() * 1000)}-{len(flights) + 1}",
            "from_id": from_id,
            "from_name": from_name,
            "to_id": to_id,
            "to_name": to_name,
            "kind": kind,
            "task_id": task_id,
            "summary": summary,
            "channel": channel,
            "status": status,
            "created_at": _now_iso(),
        }
        flights.append(entry)
        if len(flights) > 40:
            del flights[:-40]
        return entry

    def dispatch_action(self, action_name: str, payload: dict[str, Any] | None = None) -> Any:
        payload = payload or {}
        name = action_name.strip().lower()
        no_arg_actions = {
            "listagents", "listgroupmessages", "listtasks", "listskills",
            "seedexampletask", "reset_to_seed", "syncprofiles", "loadsampleteam",
            "getsettings", "listhudflights", "listapprovals",
            "listbusmessages", "busledger", "listdiscussions",
        }
        if not hasattr(self, name):
            raise ValueError(f"未知的办公室动作: {action_name}")
        fn = getattr(self, name)
        return fn() if name in no_arg_actions else fn(payload)


# ----------------------------------------------------------------------
# Concurrency guard: serialize every fast state-mutating action under the
# store's reentrant lock. Slow I/O actions (runadaptertask, runbigtasksubtasks,
# runautocodereview, runroundtable, runswarm, autopublish, autorun,
# checklivequota, syncprofiles, collectgitdiff, executecriticalop,
# rollbackcriticalop) are deliberately EXCLUDED so adapter.chat / the parallel
# subtask pool / controlled git subprocesses never deadlock holding the lock
# across a network/subprocess call; their state writes are protected by the
# locked sub-calls they make (postmessage / submitcodereview / createtask /
# deliverfinalresult / requestapproval / save) plus brief explicit
# `with self._lock:` around direct field mutations.
# ----------------------------------------------------------------------
_LOCKED_METHODS = (
    "loadsampleteam", "createagent", "updateagent", "moveagent", "deleteagent",
    "setagentquota", "postgroupmessage", "createtask", "seedexampletask",
    "claimtask", "postmessage", "submitcodereview", "updatetaskstatus",
    "reassigntask", "deletetask", "deliverfinalresult", "reviewfinalresult",
    "createskill", "updateskill", "deleteskill", "setagentskill",
    "applyskillassignments", "exporttaskmd", "gettaskprompt", "toggleautoexecute",
    "requestapproval", "resolveapproval", "listapprovals", "setapprovaltimeout",
    "createbigtask", "aggregatebigtask",
    "bussend", "busflush", "businbox", "busledger", "listbusmessages",
    "startdiscussion", "postdiscussionmessage", "resolvediscussion",
    "listdiscussion", "listdiscussions", "sendconclusion",
)
for _method_name in _LOCKED_METHODS:
    setattr(OfficeStore, _method_name, _locked(getattr(OfficeStore, _method_name)))
del _method_name
