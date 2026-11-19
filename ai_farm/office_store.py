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

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .adapters.registry import get_adapter, registered_slugs
from .adapters.web import session_dir
from .skills import SKILLS, analyze_skill_assignments


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


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
        self.state: dict[str, Any] = {
            "agents": [],
            "skills": [],
            "tasks": [],
            "group_messages": [],
            "task_messages": {},
            "hud_flights": [],
            "pending_approvals": [],
            "settings": {"auto_execute_low_risk": False},
            "example_cursor": 0,
        }
        self._load_or_seed()

    def _ensure_runtime_keys(self) -> None:
        self.state.setdefault("hud_flights", [])
        self.state.setdefault("pending_approvals", [])
        settings = self.state.setdefault("settings", {})
        settings.setdefault("auto_execute_low_risk", False)
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
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
        self.state["settings"] = {"auto_execute_low_risk": False}
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

        task_id = f"TASK-{int(time.time() * 1000) % 1000000}"
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
            task["review_status"] = "changes_requested"
            task["review_issues"] = issues
            task["revision_round"] = int(task.get("revision_round") or 0) + 1
            task["status"] = "rejected"
            checklist_md = "\n".join(f"  {idx + 1}. {item}" for idx, item in enumerate(issues))
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

        if chosen_agent["id"] != worker["id"]:
            task["assigned_to"] = chosen_agent["id"]
            task["assigned_name"] = chosen_agent["name"]
            task["assigned_vendor"] = chosen_agent["vendor"]

        usage_info = {
            "live": True,
            "model": reply.model,
            "usage": reply.usage,
            "rate_limit_remaining": reply.rate_limit_remaining,
            "attempts": failures + 1,
        }
        task.setdefault("usage_log", []).append(usage_info)
        # Accumulate real observed token count only (never fabricate when missing)
        tok_total = 0
        if isinstance(reply.usage, dict):
            tok_total = int(
                reply.usage.get("total_tokens")
                or (int(reply.usage.get("prompt_tokens") or 0) + int(reply.usage.get("completion_tokens") or 0))
            )
        chosen_agent["tokens_used"] = int(chosen_agent.get("tokens_used") or 0) + tok_total
        if reply.rate_limit_remaining:
            chosen_agent["quota_note"] = f"上次调用响应头剩余次数：{json.dumps(reply.rate_limit_remaining, ensure_ascii=False)}"
        fallback_trace = (" | ".join(attempts_log)) if attempts_log else "直调命中"
        conc_line = (reply.text or "").strip().splitlines()[0][:200] if (reply.text or "").strip() else "已完成"
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
        self._ensure_runtime_keys()
        return list(self.state.get("pending_approvals", []))

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
        self._ensure_runtime_keys()
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
        """Gate merge / delete_code / deploy behind a single-use human approval."""
        self._ensure_runtime_keys()
        op_type = (payload.get("op_type") or "merge").strip().lower()
        target = (payload.get("target") or "main").strip()
        task_id = (payload.get("task_id") or "").strip()
        approval_id = (payload.get("approval_id") or "").strip()
        dry_run = bool(payload.get("dry_run", True))

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

        # Consume one-time approval immediately so next run asks again
        matched["status"] = "executed"
        matched["executed_at"] = _now_iso()
        self._append_group_msg(
            sender_id="chief",
            sender_name=self._chief_agent()["name"],
            sender_role="chief",
            kind="system_notice",
            task_id=task_id or None,
            text=f"⚙️ 已凭人工单次授权执行 `{op_type}` → `{target}`（{'干跑演练' if dry_run else '实操'}完成，该次授权已消耗）。",
        )
        self.save()
        return {"executed": True, "dry_run": dry_run, "op_type": op_type, "target": target, "approval_id": matched["id"]}

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
            "created_at": _now_iso(),
        }
        flights.append(entry)
        if len(flights) > 30:
            del flights[:-30]
        return entry

    def dispatch_action(self, action_name: str, payload: dict[str, Any] | None = None) -> Any:
        payload = payload or {}
        name = action_name.strip().lower()
        no_arg_actions = {
            "listagents", "listgroupmessages", "listtasks", "listskills",
            "seedexampletask", "reset_to_seed", "syncprofiles", "loadsampleteam",
            "getsettings", "listhudflights", "listapprovals",
        }
        if not hasattr(self, name):
            raise ValueError(f"未知的办公室动作: {action_name}")
        fn = getattr(self, name)
        return fn() if name in no_arg_actions else fn(payload)
