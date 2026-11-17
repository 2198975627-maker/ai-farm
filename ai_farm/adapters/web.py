"""Web / subscription channel: one-time login, browser-driven.

Free web chats and paid subscriptions (Gemini web, ChatGPT web, Grok
web, ...) have no stable public API for quota or chat. They are reached
by opening the vendor's own site in a browser, logging in once with the
user's own account, and driving the chat page.

Rules that implementers must follow:
  1. Login happens on the vendor's own page, in the user's own browser.
     This library never asks for, receives, or stores a password.
  2. The session (cookies / profile) lives in the user's local browser
     profile or in ``~/.ai-farm/sessions/<slug>/``. It is never committed.
  3. One web agent = one browser tab at a time. Web agents cannot be
     parallelised like API agents; the dispatcher must run them serially.
  4. Quota cannot be auto-read. ``check_quota`` returns unknown and the
     office must link to the vendor's usage page (e.g. gemini.google.com/usage).
  5. Subclass this and implement ``chat`` for one vendor with a browser
     driver of your choice. Do not fake a reply when the browser is down:
     raise, so the dispatcher can fall back to another worker.
"""
from __future__ import annotations

import json
from pathlib import Path

from .base import AgentAdapter, AgentReply, Quota


def session_dir(slug: str) -> Path:
    """Local-only session directory (~/.ai-farm/sessions/<slug>/), never in repo."""
    return Path.home() / ".ai-farm" / "sessions" / slug.strip().lower()


class WebAdapter:
    """Base class for web / subscription agents."""

    vendor: str = "web"
    model_id: str = "待核实具体版本"
    access_kind: str = "web"  # or "subscription" for paid web tiers
    login_url: str = ""
    usage_url: str = ""
    fallback_model: str | None = None
    slug: str = "web-generic"

    def __init__(self, vendor: str | None = None, model_id: str | None = None,
                 access_kind: str | None = None, login_url: str | None = None,
                 usage_url: str | None = None, fallback_model: str | None = None,
                 slug: str | None = None):
        if vendor is not None:
            self.vendor = vendor
        if model_id is not None:
            self.model_id = model_id
        if access_kind is not None:
            self.access_kind = access_kind
        if login_url is not None:
            self.login_url = login_url
        if usage_url is not None:
            self.usage_url = usage_url
        if fallback_model is not None:
            self.fallback_model = fallback_model
        if slug is not None:
            self.slug = slug

    def mark_login_initiated(self) -> Path:
        """Record locally (in ~/.ai-farm/sessions/) that the user opened login_url."""
        sdir = session_dir(self.slug or self.vendor)
        sdir.mkdir(parents=True, exist_ok=True)
        meta = sdir / "session_meta.json"
        meta.write_text(json.dumps({
            "vendor": self.vendor,
            "login_url": self.login_url,
            "status": "login_opened_in_user_browser",
            "note": "Session cookies stay in user's browser profile; no password stored here.",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def chat(self, prompt: str, max_tokens: int = 1000) -> AgentReply:
        raise NotImplementedError(
            f"{self.vendor} ({self.model_id}) 走网页/订阅通道，需由浏览器串行代管执行 "
            f"(登录页: {self.login_url})；当前未挂载活动浏览器驱动，不伪造回复，自动触发降级换员工。"
        )

    def check_quota(self) -> Quota:
        tier_label = "付费·订阅（待桌面端自动同步会员页）" if self.access_kind == "subscription" else "免费版"
        return Quota(
            kind="subscription" if self.access_kind == "subscription" else "unknown",
            note=f"check live at {self.usage_url}" if self.usage_url else
                 "no quota API; check the vendor usage page",
            fallback_model=self.fallback_model,
            tier=tier_label,
        )


class GeminiArgonSubscriptionAdapter(WebAdapter):
    vendor = "Gemini"
    model_id = "gemini-4-argon"
    access_kind = "subscription"
    login_url = "https://gemini.google.com/"
    usage_url = "https://gemini.google.com/usage"
    fallback_model = "Gemini Flash-Lite"
    slug = "gemini-web"


class GeminiFlashWebAdapter(WebAdapter):
    vendor = "Gemini"
    model_id = "待核实具体版本"
    access_kind = "web"
    login_url = "https://gemini.google.com/"
    usage_url = "https://gemini.google.com/usage"
    fallback_model = "Flash-Lite"
    slug = "gemini-flash-web"


class ChatGPTFreeWebAdapter(WebAdapter):
    vendor = "ChatGPT"
    model_id = "待核实具体版本"
    access_kind = "web"
    login_url = "https://chatgpt.com/"
    usage_url = "https://chatgpt.com/#settings/Usage"
    fallback_model = "mini"
    slug = "chatgpt-web"


class ChatGPTPlusWebAdapter(WebAdapter):
    vendor = "ChatGPT"
    model_id = "待核实具体版本"
    access_kind = "subscription"
    login_url = "https://chatgpt.com/"
    usage_url = "https://chatgpt.com/#settings/Usage"
    fallback_model = "mini"
    slug = "chatgpt-plus-web"


class GrokFreeWebAdapter(WebAdapter):
    vendor = "Grok"
    model_id = "待核实具体版本"
    access_kind = "web"
    login_url = "https://grok.com/"
    usage_url = "https://grok.com/"
    fallback_model = "限流等待 / 换其他免费员工"
    slug = "grok-web"


class KimiFreeWebAdapter(WebAdapter):
    vendor = "Kimi"
    model_id = "待核实具体版本"
    access_kind = "web"
    login_url = "https://kimi.com/"
    usage_url = "https://kimi.com/"
    fallback_model = "限流等待 / 换其他免费员工"
    slug = "kimi-web"


class DoubaoFreeWebAdapter(WebAdapter):
    vendor = "豆包"
    model_id = "待核实具体版本"
    access_kind = "web"
    login_url = "https://www.doubao.com/"
    usage_url = ""
    fallback_model = "重活排队 / 换其他免费员工"
    slug = "doubao-web"


class QwenFreeWebAdapter(WebAdapter):
    vendor = "千问"
    model_id = "待核实具体版本"
    access_kind = "web"
    login_url = "https://www.qianwen.com/"
    usage_url = "https://www.qianwen.com/"
    fallback_model = "限流等待 / 换其他免费员工"
    slug = "qwen-web"


class DolaFreeWebAdapter(WebAdapter):
    vendor = "Dola"
    model_id = "待核实具体版本"
    access_kind = "web"
    login_url = "https://www.dola.com/chat/"
    usage_url = ""
    fallback_model = "限流等待 / 换其他免费员工"
    slug = "dola-web"


class QwenChatIntlWebAdapter(WebAdapter):
    vendor = "Qwen Chat (国际版)"
    model_id = "Qwen4-Max"
    access_kind = "web"
    login_url = "https://chat.qwen.ai/"
    usage_url = "https://chat.qwen.ai/"
    fallback_model = "限流等待 / 换其他免费员工"
    slug = "qwen-intl-web"
