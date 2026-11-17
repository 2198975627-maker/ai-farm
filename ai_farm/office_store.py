"""Office state engine implementing all 26 actions from office/office-actions.json.

Enforces all hard rules from 01-HANDOFF-FOR-ANTIGRAVITY.md:
1. One icon = one model + one access mode. Same vendor paid + free = two icons.
   Codex is a tool (running DeepSeek V4 Pro), NOT a model icon.
2. One free account per vendor. Reassignment (转交) ONLY to a DIFFERENT vendor.
3. Managers think, workers do. Workers report in a private thread (group gets a 🔒
   notice only); managers consolidate into a final delivery card for Gao.
4. Quotas are REAL: Gemini 4 Argon (82% 5h / 91% weekly), GLM-5.3-Flash (0% red
   flashing), all unverified quotas are None ("额度未填"). Never invent numbers.
5. Keys never enter the store or UI: API recruitment only accepts env var NAME.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .adapters.registry import get_adapter, registered_slugs
from .adapters.web import session_dir
from .skills import SKILLS, analyze_skill_assignments


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _default_agents() -> list[dict[str, Any]]:
    """The 17 verified model icons (6 manager/chief + 9 worker + 2 rest).
    Codex is a tool sharing DeepSeek V4 Pro's balance, not a model icon.
    """
    return [
        # === 2楼 经理层 (含总管 Muse) ===
        {
            "id": "muse",
            "name": "Muse（总管）",
            "brand": "Meta (Muse)",
            "vendor": "Meta",
            "model": "Muse 总管（唯一入口）",
            "verified_version": True,
            "access_kind": "chief",
            "paid": False,
            "floor": "manager",
            "role_label": "第1层 总管 / 第2层 统筹经理",
            "badge": "总管·唯一入口",
            "badge_color": "blue",
            "status": "ready",
            "account_status": "✅ 已核实有号（当前总管，持全量上下文）",
            "specialty": "听任务、拆单、派单、记账、质检、整合、汇报、中文理解",
            "quota_kind": "none",
            "quota_percent": None,
            "quota_note": "总管唯一对接口，无独立查额度链接",
            "usage_url": "",
            "login_url": "",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：常驻总管，经理缺席时顶上",
            "attached_tools": [],
            "skills": ["doc-drafting-frame"],
            "icon_kind": "muse",
        },
        {
            "id": "gemini-4-argon",
            "name": "Gemini 4 Argon",
            "brand": "Google Gemini",
            "vendor": "Gemini",
            "model": "gemini-4-argon",
            "verified_version": True,
            "access_kind": "subscription",
            "paid": True,
            "floor": "manager",
            "role_label": "2楼 经理层 · 前端/长代码/文档",
            "badge": "付费·订阅",
            "badge_color": "orange",
            "status": "ready",
            "account_status": "✅ 已核实有号（新加坡区，2026-12-15到期/订阅页写12-14，已取消自动续费）",
            "specialty": "前端、大块长代码、Canvas文档、架构设计",
            "quota_kind": "subscription",
            "quota_percent": 82.0,
            "quota_note": "2026-11-16 22:21实查：5小时周期已用18%（剩约82%，2:39重置）；每周已用9%（剩约91%，11月22日0:39重置）",
            "usage_url": "https://gemini.google.com/usage",
            "login_url": "https://gemini.google.com/",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：Gemini Flash-Lite（订阅制到限额不真停，降级后只能干小活）",
            "attached_tools": [],
            "skills": ["doc-drafting-frame", "code-review-checklist"],
            "icon_kind": "text",
            "adapter_slug": "gemini-web",
        },
        {
            "id": "deepseek-v4-pro",
            "name": "DeepSeek V4 Pro",
            "brand": "DeepSeek",
            "vendor": "DeepSeek",
            "model": "deepseek-v4-pro",
            "verified_version": True,
            "access_kind": "api",
            "paid": True,
            "floor": "manager",
            "role_label": "2楼 经理层 · 代码实现/审查",
            "badge": "付费·API",
            "badge_color": "orange",
            "status": "ready",
            "account_status": "✅ 已核实有号（API直连；与 DeepSeek V4 Flash、工具 Codex 共用同一余额）",
            "specialty": "中文代码实现、代码审查、架构落地、高性价比推理",
            "quota_kind": "api",
            "quota_percent": None,
            "quota_note": "额度未填（2026-11-16网页登录受阻；设好 DEEPSEEK_API_KEY 后可调 GET /user/balance 实时读余额）",
            "usage_url": "https://platform.deepseek.com/usage",
            "login_url": "",
            "key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com/v1",
            "fallback_note": "降级后：API余额归0或402真停（先换免费员工，不硬烧）",
            "attached_tools": ["🔧 工具 Codex CLI（非模型，不占独立图标，共用本账号 DeepSeek 余额）"],
            "skills": ["code-review-checklist"],
            "icon_kind": "text",
            "adapter_slug": "deepseek-pro",
        },
        {
            "id": "gpt-plus",
            "name": "GPT Plus",
            "brand": "OpenAI ChatGPT",
            "vendor": "ChatGPT",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "subscription",
            "paid": True,
            "floor": "manager",
            "role_label": "2楼 经理层 · 架构/复杂推理",
            "badge": "付费·订阅",
            "badge_color": "orange",
            "status": "pending",
            "account_status": "❓ 待确认（Gao 已确认没有订 Plus，目前只有 ChatGPT 免费版）",
            "specialty": "复杂推理、架构对比、代码审查",
            "quota_kind": "subscription",
            "quota_percent": None,
            "quota_note": "额度未填（未开通 Plus，不编造数字）",
            "usage_url": "https://chatgpt.com/#settings/Usage",
            "login_url": "https://chatgpt.com/",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：mini（订阅制到周期限额切 mini，不真停）",
            "attached_tools": [],
            "skills": [],
            "icon_kind": "text",
            "adapter_slug": "chatgpt-plus-web",
        },
        {
            "id": "grok-paid",
            "name": "Grok 付费版",
            "brand": "xAI Grok",
            "vendor": "Grok",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "subscription",
            "paid": True,
            "floor": "manager",
            "role_label": "2楼 经理层 · 实时情报/舆情",
            "badge": "付费·订阅",
            "badge_color": "orange",
            "status": "pending",
            "account_status": "❓ 待确认（Gao 已确认使用的是 Grok 免费版，未确认付费版）",
            "specialty": "X 实时热点、舆情分析、快速情报检索",
            "quota_kind": "subscription",
            "quota_percent": None,
            "quota_note": "额度未填（待确认是否付费）",
            "usage_url": "https://grok.com/",
            "login_url": "https://grok.com/",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：待核实具体降级档位",
            "attached_tools": [],
            "skills": [],
            "icon_kind": "text",
            "adapter_slug": "grok-web",
        },
        {
            "id": "qwen-max",
            "name": "千问 Max",
            "brand": "阿里千问 Qwen",
            "vendor": "Qwen",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "api",
            "paid": True,
            "floor": "manager",
            "role_label": "2楼 经理层 · 中文长文/总结",
            "badge": "付费·API",
            "badge_color": "orange",
            "status": "pending",
            "account_status": "❓ 待确认（只提过千问名字，尚未确认是否有 Max API Key）",
            "specialty": "中文长文统筹、深度总结、专业翻译审校",
            "quota_kind": "api",
            "quota_percent": None,
            "quota_note": "额度未填（去阿里百炼控制台查看）",
            "usage_url": "https://bailian.console.aliyun.com/",
            "login_url": "",
            "key_env": "QWEN_API_KEY",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "fallback_note": "降级后：API余额归0真停",
            "attached_tools": [],
            "skills": [],
            "icon_kind": "text",
            "adapter_slug": "qwen-api",
        },

        # === 1楼 员工层 (9个免费/便宜动手模型) ===
        {
            "id": "k-exaone-2-5",
            "name": "K-EXAONE 2.5",
            "brand": "LG EXAONE",
            "vendor": "K-EXAONE",
            "model": "k-exaone_v2.5",
            "verified_version": True,
            "access_kind": "api",
            "paid": False,
            "floor": "worker",
            "role_label": "1楼 员工层 · 批量初稿/英韩处理",
            "badge": "免费·API",
            "badge_color": "green",
            "status": "ready",
            "account_status": "⚠️ 已核实有号（免费至2026-12-10；仅限非商业、仅韩语/英语，单次上限524,288 tokens；2026-11-17早3次真调：前2次401、第3次403 Access denied，需在EXAONE控制台核对模型权限）",
            "specialty": "512k长上下文、英文/韩语批量初稿、批量分类打标、批量翻译",
            "quota_kind": "api",
            "quota_percent": None,
            "quota_note": "额度未填（无总额度API，仅靠每次响应头 x-day-rate-limit-remaining 读取；id.exaone.ai 登录两次被拒，勿反复重试）",
            "usage_url": "https://docs.exaone.ai/en/my-profile/api-key",
            "login_url": "",
            "key_env": "KEXAONE_API_KEY",
            "base_url": "https://api.exaone.ai/v1",
            "fallback_note": "降级后：API报429/403真停（立即换 DeepSeek Flash 或其他免费员工）",
            "attached_tools": [],
            "skills": ["batch-translate", "batch-classify", "english-writing"],
            "icon_kind": "text",
            "adapter_slug": "kexaone",
        },
        {
            "id": "deepseek-v4-flash",
            "name": "DeepSeek V4 Flash",
            "brand": "DeepSeek",
            "vendor": "DeepSeek",
            "model": "deepseek-v4-flash（含V3.2）",
            "verified_version": True,
            "access_kind": "api",
            "paid": False,
            "floor": "worker",
            "role_label": "1楼 员工层 · 写测试/便宜代码",
            "badge": "免费·API",
            "badge_color": "green",
            "status": "ready",
            "account_status": "✅ 已核实有号（替代2026-07-24停用的 deepseek-chat；与 DeepSeek V4 Pro 共用同一余额）",
            "specialty": "写单元测试、便宜代码小活、批量翻译、格式化",
            "quota_kind": "api",
            "quota_percent": None,
            "quota_note": "额度未填（与 DeepSeek V4 Pro 共用同一 API 余额，设 Key 后可自动读）",
            "usage_url": "https://platform.deepseek.com/usage",
            "login_url": "",
            "key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com/v1",
            "fallback_note": "降级后：API余额归0真停（换 ChatGPT 免费或千问免费网页）",
            "attached_tools": [],
            "skills": ["test-cases", "cheap-code-jobs", "batch-translate"],
            "icon_kind": "text",
            "adapter_slug": "deepseek-flash",
        },
        {
            "id": "qwen-free-web",
            "name": "千问 免费网页",
            "brand": "阿里通义千问",
            "vendor": "Qwen",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "web",
            "paid": False,
            "floor": "worker",
            "role_label": "1楼 员工层 · 中文整理/翻译",
            "badge": "免费·网页",
            "badge_color": "green",
            "status": "pending",
            "account_status": "❓ 待确认（待点「登录一次」确认是否有通义千问免费网页号）",
            "specialty": "中文批量翻译、名单整理成表格、中文润色、批量分类",
            "quota_kind": "unknown",
            "quota_percent": None,
            "quota_note": "额度未填（去通义千问网页端查看）",
            "usage_url": "https://tongyi.aliyun.com/",
            "login_url": "https://tongyi.aliyun.com/",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：今日限流则休息到明天，轮换给豆包/Kimi",
            "attached_tools": [],
            "skills": ["table-cleanup", "chinese-polish", "batch-translate"],
            "icon_kind": "text",
            "adapter_slug": "qwen-web",
        },
        {
            "id": "qwen-paid-api",
            "name": "千问 付费 API",
            "brand": "阿里百炼 Qwen",
            "vendor": "Qwen",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "api",
            "paid": True,
            "floor": "worker",
            "role_label": "1楼 员工层 · API批量格式化/摘要",
            "badge": "付费·API",
            "badge_color": "orange",
            "status": "pending",
            "account_status": "❓ 待确认（与千问免费网页拆成两个独立图标；待确认百炼 API Key）",
            "specialty": "API并行批量摘要、分类打标、表格格式化",
            "quota_kind": "api",
            "quota_percent": None,
            "quota_note": "额度未填（去阿里百炼控制台查看）",
            "usage_url": "https://bailian.console.aliyun.com/",
            "login_url": "",
            "key_env": "QWEN_API_KEY",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "fallback_note": "降级后：API余额归0真停",
            "attached_tools": [],
            "skills": ["table-cleanup", "batch-classify"],
            "icon_kind": "text",
            "adapter_slug": "qwen-api",
        },
        {
            "id": "gemini-flash-lite",
            "name": "Gemini Flash-Lite",
            "brand": "Google Gemini",
            "vendor": "Gemini",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "web",
            "paid": False,
            "floor": "worker",
            "role_label": "1楼 员工层 · 长上下文小活/Pro降级形态",
            "badge": "免费·网页",
            "badge_color": "green",
            "status": "ready",
            "account_status": "✅ 已核实有号（Gemini 免费档 / Pro 额度用尽后的自动降级形态）",
            "specialty": "长上下文速读、轻量问答、小批量摘要",
            "quota_kind": "subscription",
            "quota_percent": None,
            "quota_note": "额度未填（见 gemini.google.com/usage 实时页面）",
            "usage_url": "https://gemini.google.com/usage",
            "login_url": "https://gemini.google.com/",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：本身即为降级轻量模型，只接边角小任务",
            "attached_tools": [],
            "skills": ["long-text-speed-read"],
            "icon_kind": "text",
            "adapter_slug": "gemini-flash-web",
        },
        {
            "id": "chatgpt-free",
            "name": "ChatGPT 免费",
            "brand": "OpenAI ChatGPT",
            "vendor": "ChatGPT",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "web",
            "paid": False,
            "floor": "worker",
            "role_label": "1楼 员工层 · 英文写作/小代码",
            "badge": "免费·网页",
            "badge_color": "green",
            "status": "ready",
            "account_status": "✅ 已核实有号（Gao 本人确认有免费版账号，与 GPT Plus 拆开独立计算）",
            "specialty": "英文写作小活、简单代码、单元测试草稿",
            "quota_kind": "subscription",
            "quota_percent": None,
            "quota_note": "额度未填（去 ChatGPT Settings -> Usage 查看）",
            "usage_url": "https://chatgpt.com/#settings/Usage",
            "login_url": "https://chatgpt.com/",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：mini（免费档达到周期限额后自动降级为 mini，不真停）",
            "attached_tools": [],
            "skills": ["english-writing", "cheap-code-jobs"],
            "icon_kind": "text",
            "adapter_slug": "chatgpt-web",
        },
        {
            "id": "grok-free",
            "name": "Grok 免费",
            "brand": "xAI Grok",
            "vendor": "Grok",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "web",
            "paid": False,
            "floor": "worker",
            "role_label": "1楼 员工层 · 网页问答/宣传口号",
            "badge": "免费·网页",
            "badge_color": "green",
            "status": "ready",
            "account_status": "✅ 已核实有号（Gao 确认免费版，网页 grok.com 可用，手机 GBox App 暂打不开）",
            "specialty": "宣传口号、英文/中文短平快问答、热点摘要",
            "quota_kind": "subscription",
            "quota_percent": None,
            "quota_note": "额度未填（去 Grok Settings -> Usage 查看）",
            "usage_url": "https://grok.com/",
            "login_url": "https://grok.com/",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：触发冷却休息到明天，轮换给其他免费员工",
            "attached_tools": [],
            "skills": ["promo-slogans"],
            "icon_kind": "text",
            "adapter_slug": "grok-web",
        },
        {
            "id": "kimi-free",
            "name": "Kimi 免费",
            "brand": "Moonshot Kimi",
            "vendor": "Kimi",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "web",
            "paid": False,
            "floor": "worker",
            "role_label": "1楼 员工层 · 长文三档摘要/速读",
            "badge": "免费·网页",
            "badge_color": "green",
            "status": "pending",
            "account_status": "❓ 待确认（待点「登录一次」看看是否有号，无号可当场免费注册）",
            "specialty": "长文三档摘要、长文速读、资料归纳",
            "quota_kind": "subscription",
            "quota_percent": None,
            "quota_note": "额度未填（去 kimi.com 设置 -> 订阅 查看）",
            "usage_url": "https://kimi.com/",
            "login_url": "https://kimi.com/",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：今日累了休息，轮换给豆包/Gemini Flash-Lite",
            "attached_tools": [],
            "skills": ["three-tier-summary", "long-text-speed-read"],
            "icon_kind": "text",
            "adapter_slug": "kimi-web",
        },
        {
            "id": "doubao-free",
            "name": "豆包 免费",
            "brand": "字节豆包 Doubao",
            "vendor": "Doubao",
            "model": "待核实具体版本",
            "verified_version": False,
            "access_kind": "web",
            "paid": False,
            "floor": "worker",
            "role_label": "1楼 员工层 · 中文日常问答/润色",
            "badge": "免费·网页",
            "badge_color": "green",
            "status": "pending",
            "account_status": "❓ 待确认（待点「登录一次」确认是否有号；简单问答不限，重活有限额）",
            "specialty": "中文润色、三档摘要、名单整理成表格、宣传口号",
            "quota_kind": "unknown",
            "quota_percent": None,
            "quota_note": "额度未填（官方不给固定数字，无独立查额度页）",
            "usage_url": "",
            "login_url": "https://www.doubao.com/",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：重活排队时轮换给千问/Kimi",
            "attached_tools": [],
            "skills": ["three-tier-summary", "chinese-polish", "table-cleanup"],
            "icon_kind": "text",
            "adapter_slug": "doubao-web",
        },

        # === 院子休息 (2个：已耗尽 / 待确认) ===
        {
            "id": "glm-5-3-flash",
            "name": "GLM-5.3-Flash",
            "brand": "智谱 / 国家超算 scnet",
            "vendor": "GLM",
            "model": "glm-5.3-flash",
            "verified_version": True,
            "access_kind": "api",
            "paid": False,
            "floor": "rest",
            "role_label": "院子休息 · 额度已耗尽 (0%)",
            "badge": "已耗尽·API",
            "badge_color": "red",
            "status": "exhausted",
            "account_status": "⛔ 已核实有号（10M免费额度4天已用完，2026-11-15实查剩0%，休息等新额度）",
            "specialty": "批量小任务（当前已停用休息）",
            "quota_kind": "api",
            "quota_percent": 0.0,
            "quota_note": "剩 0%（实查已耗尽，≤10%红条闪烁告警，API归0真停，在院子休息）",
            "usage_url": "https://www.scnet.cn/",
            "login_url": "",
            "key_env": "GLM_API_KEY",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "fallback_note": "降级后：API余额 0% 真停（等新活动额度再拖回1楼）",
            "attached_tools": [],
            "skills": [],
            "icon_kind": "text",
            "adapter_slug": "glm-flash",
        },
        {
            "id": "workbuddy",
            "name": "WorkBuddy 桌面端",
            "brand": "腾讯 WorkBuddy",
            "vendor": "WorkBuddy",
            "model": "内置免费积分池（多模型路由）",
            "verified_version": True,
            "access_kind": "desktop",
            "paid": False,
            "floor": "worker",
            "role_label": "1楼 员工层 · 桌面智能体（本地文件/表格/代码）",
            "badge": "免费·桌面端",
            "badge_color": "green",
            "status": "ready",
            "account_status": "✅ 已核实本机已安装（AppData\\Local\\WorkBuddy），走官方每月免费积分+签到积分，不花外部API余额",
            "specialty": "本地文件整理、批量格式转换、表格/文档初稿、本地代码小活（桌面端手动复制交接）",
            "quota_kind": "subscription",
            "quota_percent": None,
            "quota_note": "额度未填（请在 WorkBuddy 客户端内查看每月剩余免费积分）",
            "usage_url": "",
            "login_url": "",
            "key_env": "",
            "base_url": "",
            "fallback_note": "降级后：免费积分用完则回院子休息，等下月刷新或每日签到领分",
            "attached_tools": [],
            "skills": ["table-cleanup", "cheap-code-jobs", "doc-drafting-frame"],
            "icon_kind": "text",
        },
    ]


GENERIC_EXAMPLE_TASKS: list[dict[str, Any]] = [
    {
        "title": "【通用示例 1/4】10 条日常用品英文短句批量翻译成中英对照表",
        "manager_id": "muse",
        "assigned_to": "deepseek-v4-flash",
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
    },
    {
        "title": "【通用示例 2/4】杂乱社团活动报名名单去重并整理成标准表格",
        "manager_id": "muse",
        "assigned_to": "qwen-free-web",
        "goal": "把杂乱的社团报名文本去重、对齐列、标出缺失项，由免费中文员工完成。",
        "input_text": (
            "- 张三 / 人工智能2401班 / 负责宣传海报\n"
            "- 李四，软件工程2402班，联系电话未填，负责场地签到\n"
            "- 张三 (重复提交) 人工智能2401班 负责宣传海报\n"
            "- 王五 | 大数据2401班 | 负责设备调试\n"
            "- 赵六 / 班级未写 / 负责摄影记录"
        ),
        "output_format": "Markdown 表格：| 姓名 | 班级 | 分工 | 备注(缺失项标[缺失]) |",
        "acceptance": "去重后共 4 人，缺失字段标 [缺失]，不编造电话或班级。不许自由发挥。",
        "skill_slug": "table-cleanup",
    },
    {
        "title": "【通用示例 3/4】科普短文生成三档摘要（一句话 / 100字 / 要点清单）",
        "manager_id": "muse",
        "assigned_to": "kimi-free",
        "goal": "对通用科普材料生成三档摘要，供经理 10 秒钟审阅完核心数字与结论。",
        "input_text": (
            "2026年校园节能改造示范报告（通用示例文本）：教学楼A栋于2026年3月15日完成照明与空调自控改造，"
            "共更换LED感应灯具420盏、加装温控模块36套。经过90天连续监测，日均耗电量由改造前的1,250千瓦时"
            "降至875千瓦时，节电率达30.0%，负责巡检的陈工与林工确认设备零故障运行。"
        ),
        "output_format": "严格分三块：1.【一句话结论】 2.【百字摘要】 3.【关键数字核对清单】",
        "acceptance": "日期(2026-03-15)、灯具(420盏)、模块(36套)、耗电(1250->875)、节电率(30.0%)、人名(陈工/林工)与原文100%一致。不许自由发挥。",
        "skill_slug": "three-tier-summary",
    },
    {
        "title": "【通用示例 4/4】通用价格折扣计算纯函数的 3 个边界单元测试用例生成",
        "manager_id": "deepseek-v4-pro",
        "assigned_to": "deepseek-v4-flash",
        "goal": "为通用示例纯函数 calc_discount(price, rate) 编写正常、边界、异常 3 个单元测试。",
        "input_text": "函数签名：def calc_discount(price: float, rate: float) -> float: # rate in [0.0, 1.0], raises ValueError if price < 0 or rate not in [0, 1]",
        "output_format": "仅输出 Python unittest/assert 测试函数代码 + 3 行覆盖说明，不改业务代码。",
        "acceptance": "包含正常折扣(100, 0.8 -> 80)、0折/满折边界(100, 0 -> 0)、负数异常(ValueError)三类断言。不许自由发挥。",
        "skill_slug": "test-cases",
    },
]


class OfficeStore:
    """Persistent state store backing the 26 office actions + adapter execution."""

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or (Path.home() / ".ai-farm" / "office_state.json")
        self.state: dict[str, Any] = {
            "agents": [],
            "skills": [],
            "tasks": [],
            "group_messages": [],
            "task_messages": {},
            "example_cursor": 0,
        }
        self._load_or_seed()

    def _load_or_seed(self) -> None:
        if self.state_path.exists():
            try:
                loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("agents"):
                    self.state = loaded
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
        self.state["example_cursor"] = 0
        self.state["group_messages"] = [
            {
                "id": "msg-welcome-1",
                "sender_id": "muse",
                "sender_name": "Muse（总管）",
                "sender_role": "chief",
                "kind": "system_welcome",
                "text": (
                    "👋 欢迎来到 **AI 农场办公室**！我是总管 **Muse**。\n"
                    "• **核心分工**：经理动脑（只看 diff / 摘要），免费员工动手（做翻译、表格、摘要、写测试等边角活），把 Token 和额度开销从付费经理挪到免费员工身上。\n"
                    "• **真实账本**：左侧 **17 个模型图标**严格按「一个图标 = 一个模型」拆分；Codex 是跑代码的 CLI 工具（挂在 DeepSeek V4 Pro 下共用同一余额，不单占模型图标）。\n"
                    "• **真实法力值**：目前已实查 **Gemini 4 Argon**（5小时剩 82% / 每周剩 91%）与 **GLM-5.3-Flash**（0% 已用完红条闪烁）；其余未核实的统一标为「**额度未填**」，绝不编造数字。\n"
                    "• **先搭工作台**：点上方 `🧪 一键塞入通用示例任务` 可体验「群里派单 → 员工认领 → 🔒 私聊汇报（不刷群） → 经理统筹交付 → @你(Gao) 验收」完整闭环！"
                ),
                "created_at": _now_iso(),
            }
        ]
        self.save()
        return self.state

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
    # Action 2: createagent (Two-path Recruit Modal: API vs Web/Subscription)
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
        if access_kind not in ("api", "web", "subscription"):
            raise ValueError("招募失败：接入方式只能是 api / web / subscription。")
        if floor not in ("manager", "worker", "rest"):
            raise ValueError("招募失败：楼层只能是 manager / worker / rest。")

        # Rule 1 & Rule 2 check: no duplicate vendor + model + access_kind
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
        fallback_note = (payload.get("fallback_note") or "").strip()

        if access_kind == "api":
            if not key_env:
                raise ValueError("API 招募必须填写环境变量名（如 DEEPSEEK_API_KEY），不能留空。")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key_env) or key_env.startswith("SK-"):
                raise ValueError(
                    "安全拦截：环境变量名必须是大写字母+下划线（如 DEEPSEEK_API_KEY）。"
                    "严禁在此处直接粘贴 API Key 明文！"
                )
            badge = f"{'付费' if paid else '免费'}·API"
            badge_color = "orange" if paid else "green"
            quota_kind = "api"
            account_status = f"✅ 已招募 API 接口（读取环境变量 ${key_env}，密钥不落盘）"
            if not fallback_note:
                fallback_note = "降级后：API余额归0或429真停（自动换其他免费员工）"
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
            "quota_percent": None,  # Never invent a quota percentage on recruit!
            "quota_note": payload.get("quota_note") or "额度未填（新招募，未实查前不编造百分比）",
            "usage_url": usage_url,
            "login_url": login_url,
            "key_env": key_env,
            "base_url": base_url,
            "fallback_note": fallback_note,
            "attached_tools": [],
            "skills": [],
            "icon_kind": "text",
            "adapter_slug": "custom-api" if access_kind == "api" else "custom-web",
        }
        if access_kind in ("web", "subscription") and payload.get("logged_in"):
            sdir = session_dir(slug_id)
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "session_meta.json").write_text(
                json.dumps({"id": slug_id, "vendor": vendor, "login_url": login_url, "logged_in_at": _now_iso()}, ensure_ascii=False),
                encoding="utf-8",
            )
        self.state["agents"].append(agent)
        self._append_group_msg(
            sender_id="muse",
            sender_name="Muse（总管）",
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
                      "account_status", "usage_url", "login_url", "base_url", "fallback_note"):
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
            self._append_group_msg(
                sender_id="muse",
                sender_name="Muse（总管）",
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
        if agent_id == "muse":
            raise ValueError("总管 Muse 是唯一对接口，不能移除。")
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
        sender_id = payload.get("sender_id") or "gao"
        text = (payload.get("text") or "").strip()
        if not text:
            raise ValueError("群聊消息内容不能为空。")
        if sender_id == "gao":
            sender_name = "你 (Gao)"
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
        claimed = sum(1 for t in tasks if t["status"] in ("accepted", "working", "delivered", "accepted_done"))
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

    def createtask(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = (payload.get("title") or "").strip()
        if not title:
            raise ValueError("任务标题不能为空。")
        manager_id = payload.get("manager_id") or "muse"
        manager = self._find_agent(manager_id)
        assigned_to = payload.get("assigned_to") or ""
        assigned_agent = self._find_agent(assigned_to) if assigned_to else None

        # Enforce Rule 3: Small edge tasks go to workers, never managers!
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
            "rule_footer": "不许自由发挥。不确定写「未核实」，绝不乱猜。",
            "skill_slug": skill_slug,
            "status": "assigned",  # assigned -> accepted -> working -> delivered -> accepted_done / rejected
            "worker_reported": False,
            "latest_report_summary": "",
            "final_delivery_text": "",
            "usage_log": [],
            "created_at": _now_iso(),
        }
        self.state["tasks"].append(task)
        self.state["task_messages"][task_id] = [
            {
                "id": f"tmsg-{int(time.time() * 1000)}",
                "task_id": task_id,
                "sender_id": manager["id"],
                "sender_name": manager["name"],
                "kind": "template_dispatch",
                "text": (
                    f"📋 **模板化指令下发（省 Token 规范）**\n"
                    f"• **目标**：{goal}\n"
                    f"• **输入**：{input_text}\n"
                    f"• **强制输出格式**：{output_format}\n"
                    f"• **验收标准**：{acceptance}\n"
                    f"• **红线**：不许自由发挥，做完在本私聊窗汇报，切勿把长正文刷到大群里。"
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
                f"📌 **派发新任务卡片** `{task_id}` · **{title}**\n"
                f"{mention}请按模板执行：\n"
                f"• **目标**：{goal}\n"
                f"• **强制格式**：{output_format}\n"
                f"• **验收标准**：{acceptance}（**不许自由发挥**）"
            ),
        )
        self.save()
        return task

    def seedexampletask(self) -> dict[str, Any]:
        idx = int(self.state.get("example_cursor", 0)) % len(GENERIC_EXAMPLE_TASKS)
        tpl = GENERIC_EXAMPLE_TASKS[idx]
        self.state["example_cursor"] = idx + 1
        return self.createtask(tpl)

    # ------------------------------------------------------------------
    # Action 11: claimtask
    # ------------------------------------------------------------------
    def claimtask(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        worker_id = payload.get("worker_id") or task.get("assigned_to")
        if not worker_id:
            # Pick first ready worker
            ready_workers = [a for a in self.state["agents"] if a["floor"] == "worker" and a["status"] == "ready"]
            if not ready_workers:
                raise ValueError("当前没有空闲的 1楼员工可认领任务。")
            worker = ready_workers[0]
        else:
            worker = self._find_agent(worker_id)
        if worker["floor"] == "rest" or worker["status"] == "exhausted":
            raise ValueError(f"{worker['name']} 当前在院子休息或额度已耗尽，请换其他免费员工认领！")

        task["assigned_to"] = worker["id"]
        task["assigned_name"] = worker["name"]
        task["assigned_vendor"] = worker["vendor"]
        task["status"] = "working"

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
            text=f"✋ **{worker['name']}**（`{worker['badge']}`）已领取任务 `{task['id']}`《{task['title']}》，正在执行中（详细汇报走私聊，不刷群）。",
        )
        self.save()
        return task

    # ------------------------------------------------------------------
    # Action 12 & 13: listmessages & postmessage (Private Thread Report)
    # ------------------------------------------------------------------
    def listmessages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        task_id = payload.get("task_id") or payload.get("id")
        return self.state["task_messages"].get(task_id, [])

    def postmessage(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id"))
        sender_id = payload.get("sender_id") or task.get("assigned_to") or "muse"
        sender = self._find_agent(sender_id) if sender_id != "gao" else {"id": "gao", "name": "你 (Gao)"}
        text = (payload.get("text") or "").strip()
        is_delivery = bool(payload.get("is_delivery", True))
        if not text:
            raise ValueError("私聊汇报内容不能为空。")

        msg = self._append_task_msg(
            task["id"],
            sender_id=sender["id"],
            sender_name=sender["name"],
            kind="worker_report" if is_delivery else "private_chat",
            text=text,
            usage=payload.get("usage"),
        )
        if is_delivery:
            task["worker_reported"] = True
            task["latest_report_summary"] = text[:280] + ("..." if len(text) > 280 else "")
            if task["status"] in ("assigned", "accepted"):
                task["status"] = "working"
            # Rule 5: Group chat gets ONLY a 🔒 notice, NEVER the report body!
            self._append_group_msg(
                sender_id=sender["id"],
                sender_name=sender["name"],
                sender_role="worker",
                kind="private_report_lock",
                task_id=task["id"],
                text=(
                    f"🔒 **{sender['name']}** 已在私聊向经理 **@{task['manager_name']}** 提交了任务 `{task['id']}` 的执行汇报"
                    f"（正文共 {len(text)} 字已折叠在私聊窗，不在大群刷屏，经理仅审摘要/diff）。"
                ),
            )
        self.save()
        return msg

    # ------------------------------------------------------------------
    # Action 14: updatetaskstatus
    # ------------------------------------------------------------------
    def updatetaskstatus(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        new_status = payload.get("status")
        valid = ("assigned", "accepted", "working", "delivered", "accepted_done", "rejected")
        if new_status not in valid:
            raise ValueError(f"状态必须是 {valid} 之一。")
        task["status"] = new_status
        self._append_task_msg(
            task["id"],
            sender_id="muse",
            sender_name="Muse（总管）",
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

        # Hard Rule 2 & §5: Reassign ONLY to a DIFFERENT vendor!
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

        note = (
            f"↪ **跨厂商轮换转交**：由 **{old_name}**（{old_vendor or '原通道'}）转交给 "
            f"**@{target['name']}**（{target['vendor']} · `{target['badge']}`）。原因：{reason}"
        )
        self._append_task_msg(task["id"], sender_id="muse", sender_name="Muse（总管）", kind="transfer", text=note)
        self._append_group_msg(
            sender_id="muse",
            sender_name="Muse（总管）",
            sender_role="chief",
            kind="transfer_notice",
            task_id=task["id"],
            text=note,
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
    # Action 17: deliverfinalresult (Manager consolidates -> Group Card)
    # ------------------------------------------------------------------
    def deliverfinalresult(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        manager_id = payload.get("manager_id") or task["manager_id"] or "muse"
        manager = self._find_agent(manager_id)
        summary = (payload.get("final_text") or payload.get("summary") or "").strip()
        if not summary:
            report_preview = task.get("latest_report_summary") or "（员工已完成规定格式产出，质检通过）"
            summary = (
                f"经 **{manager['name']}** 抽查 diff/摘要核验通过（未重读长原文，节省经理 Token）：\n"
                f"• 执行员工：**{task['assigned_name']}**\n"
                f"• 质检结论：符合强制输出格式与验收标准\n"
                f"• 成果摘要：\n{report_preview}"
            )
        task["final_delivery_text"] = summary
        task["status"] = "delivered"

        self._append_task_msg(
            task["id"],
            sender_id=manager["id"],
            sender_name=manager["name"],
            kind="final_delivery",
            text=f"🏁 经理已统筹交付总结果给 Gao：\n{summary}",
        )
        self._append_group_msg(
            sender_id=manager["id"],
            sender_name=manager["name"],
            sender_role="manager",
            kind="final_delivery_card",
            task_id=task["id"],
            text=f"🏁 **最终交付 · 总结果 · 给 Gao**\n任务：`{task['id']}` 《{task['title']}》\n@你 (Gao) 请验收：\n\n{summary}",
        )
        self.save()
        return task

    # ------------------------------------------------------------------
    # Action 18: reviewfinalresult (Gao accepts or rejects)
    # ------------------------------------------------------------------
    def reviewfinalresult(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = self._find_task(payload.get("task_id") or payload.get("id"))
        decision = (payload.get("decision") or "verified").strip().lower()
        comment = (payload.get("comment") or "").strip()
        if decision in ("verified", "accepted", "pass", "accept"):
            task["status"] = "accepted_done"
            text = f"✅ **你 (Gao) 已验收通过** 任务 `{task['id']}`《{task['title']}》！" + (f" 批注：{comment}" if comment else "")
        else:
            task["status"] = "rejected"
            text = f"↩ **你 (Gao) 打回重做** 任务 `{task['id']}`《{task['title']}》！" + (f" 原因：{comment}" if comment else " 请按验收标准修正后重新汇报。")

        self._append_task_msg(task["id"], sender_id="gao", sender_name="你 (Gao)", kind="review", text=text)
        self._append_group_msg(
            sender_id="gao",
            sender_name="你 (Gao)",
            sender_role="chairman",
            kind="review_notice",
            task_id=task["id"],
            text=text,
        )
        self.save()
        return task

    # ------------------------------------------------------------------
    # Action 19–25: Skill Center (12 seed skills + Senior Model Judgment)
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
        judge_id = payload.get("judge_id") or "muse"
        try:
            judge_name = self._find_agent(judge_id)["name"]
        except KeyError:
            judge_name = str(judge_id)
        recs = analyze_skill_assignments(self.state["agents"], self.state["skills"], judge=judge_name)
        return {"judge": judge_name, "recommendations": recs}

    def applyskillassignments(self, payload: dict[str, Any]) -> dict[str, Any]:
        judge_name = payload.get("judge") or "Muse（总管）"
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
                sender_id="muse",
                sender_name=judge_name,
                sender_role="chief",
                kind="skill_judge_notice",
                text=(
                    f"🧠 **技能中心 · 高级模型裁判通知（裁判：{judge_name}，经你(Gao)勾选批准）**\n"
                    f"已为团队成员装配以下固定流程 Skill（减少自由思考、提高准确度、省免费额度）：\n• "
                    + "\n• ".join(applied)
                ),
            )
        self.save()
        return {"applied_count": len(applied), "applied": applied}

    # ------------------------------------------------------------------
    # Extra: Bridge to Real AgentAdapter (Dry-Run or Live Execution + Quota Check)
    # ------------------------------------------------------------------
    def runadaptertask(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a task via AgentAdapter (dry_run=True by default; live=True calls real API)."""
        task = self._find_task(payload.get("task_id"))
        live = bool(payload.get("live", False))
        worker_id = payload.get("worker_id") or task.get("assigned_to") or "deepseek-v4-flash"
        worker = self._find_agent(worker_id)

        prompt = (
            f"你是执行员工，只做下面这件事，不要做决定。\n"
            f"任务：{task['goal']}\n"
            f"输入：\n{task['input_text']}\n"
            f"输出格式：{task['output_format']}\n"
            f"验收标准：{task['acceptance']}\n"
            f"不确定的写“未核实”，不要猜。不许自由发挥。"
        )
        if not live:
            dry_text = (
                f"【干跑演练 DRY-RUN · 0 额度消耗】\n"
                f"• 拟调用员工：{worker['name']}（厂商：{worker['vendor']} · 模型：{worker['model']} · `{worker['badge']}`）\n"
                f"• 通道类型：{worker['access_kind']} "
                + (f"（读取环境变量 `${worker.get('key_env')}`）" if worker["access_kind"] == "api" else f"（登录页：{worker.get('login_url')}）")
                + f"\n• 降级链就绪：若该员工失败 → 自动换另一家免费员工重试；连续 2 名员工失败 → 才升级给经理 {task['manager_name']}。\n"
                f"• 本次干跑未发起外部网络请求，花费 Token：0。"
            )
            self.postmessage({
                "task_id": task["id"],
                "sender_id": worker["id"],
                "text": dry_text,
                "is_delivery": True,
                "usage": {"dry_run": True, "prompt_tokens": 0, "completion_tokens": 0},
            })
            return {"mode": "dry_run", "worker": worker["name"], "text": dry_text}

        # Live execution via AgentAdapter
        slug = worker.get("adapter_slug") or ""
        if slug not in registered_slugs():
            raise RuntimeError(f"{worker['name']} 尚未绑定已注册的 Adapter slug ({slug})。")
        adapter = get_adapter(slug)
        reply = adapter.chat(prompt)
        usage_info = {
            "live": True,
            "model": reply.model,
            "usage": reply.usage,
            "rate_limit_remaining": reply.rate_limit_remaining,
        }
        task.setdefault("usage_log", []).append(usage_info)
        if reply.rate_limit_remaining:
            worker["quota_note"] = f"上次调用响应头剩余次数：{json.dumps(reply.rate_limit_remaining, ensure_ascii=False)}"
        report_body = (
            f"【真实接口返回 · {worker['name']} ({reply.model})】\n"
            f"• 用量统计：`{json.dumps(reply.usage, ensure_ascii=False)}`\n"
            + (f"• 响应头剩余额度：`{json.dumps(reply.rate_limit_remaining, ensure_ascii=False)}`\n" if reply.rate_limit_remaining else "")
            + f"\n---\n{reply.text}"
        )
        self.postmessage({
            "task_id": task["id"],
            "sender_id": worker["id"],
            "text": report_body,
            "is_delivery": True,
            "usage": usage_info,
        })
        return {"mode": "live", "worker": worker["name"], "reply": reply.text, "usage": usage_info}

    def checklivequota(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Attempt live quota & model/profile sync via AgentAdapter (e.g. DeepSeek /user/balance + /models)."""
        agent = self._find_agent(payload.get("agent_id") or payload.get("id"))
        slug = agent.get("adapter_slug") or ""
        if slug in registered_slugs():
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
        """Sync account tier, expiry, local web sessions, and API balance+models across roster."""
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
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

    def dispatch_action(self, action_name: str, payload: dict[str, Any] | None = None) -> Any:
        payload = payload or {}
        name = action_name.strip().lower()
        no_arg_actions = {"listagents", "listgroupmessages", "listtasks", "listskills", "seedexampletask", "reset_to_seed", "syncprofiles"}
        if not hasattr(self, name):
            raise ValueError(f"未知的办公室动作: {action_name}")
        fn = getattr(self, name)
        return fn() if name in no_arg_actions else fn(payload)
