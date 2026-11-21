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
import threading
import time
from pathlib import Path

from .base import AgentAdapter, AgentReply, Quota

_WEB_PLAYWRIGHT_LOCK = threading.Lock()


def session_dir(slug: str) -> Path:
    """Local-only session directory (~/.ai-farm/sessions/<slug>/), never in repo."""
    return Path.home() / ".ai-farm" / "sessions" / slug.strip().lower()


def is_web_auto_ready(slug: str) -> bool:
    meta_file = session_dir(slug) / "session_meta.json"
    if not meta_file.exists():
        return False
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        return bool(data.get("auto_ready")) and (session_dir(slug) / "browser_profile").exists()
    except Exception:
        return False


def open_web_login_browser(login_url: str, slug: str, vendor: str = "web") -> Path:
    """Launch a headed persistent Playwright window so the user can log in once."""
    from playwright.sync_api import sync_playwright

    sdir = session_dir(slug)
    profile = sdir / "browser_profile"
    profile.mkdir(parents=True, exist_ok=True)
    meta = sdir / "session_meta.json"
    meta.write_text(json.dumps({
        "vendor": vendor,
        "login_url": login_url,
        "status": "login_opened_in_user_browser",
        "auto_ready": True,
        "note": "Session cookies stay in local browser_profile; no password stored here.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run():
        with _WEB_PLAYWRIGHT_LOCK:
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(str(profile), headless=False)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                # Keep open until user closes the browser window (max 10 min).
                deadline = time.monotonic() + 600
                while time.monotonic() < deadline and ctx.pages:
                    time.sleep(0.5)
                ctx.close()

    threading.Thread(target=_run, name=f"web-login-{slug}", daemon=True).start()
    return meta


def playwright_chat(login_url: str, slug: str, prompt: str, timeout_sec: int = 120) -> AgentReply:
    """Drive a logged-in persistent Playwright profile to send prompt & read reply."""
    from playwright.sync_api import sync_playwright

    profile = session_dir(slug) / "browser_profile"
    if not profile.exists():
        raise RuntimeError(f"网页通道 {slug} 尚未完成一次登录，请先点「后台登录一次」。")

    input_selectors = [
        "rich-textarea div[contenteditable='true']",
        "div[contenteditable='true'][role='textbox']",
        "textarea#prompt-textarea",
        "textarea",
        "div[contenteditable='true']",
    ]
    reply_selectors = [
        "message-content",
        "[data-message-author-role='assistant']",
        ".markdown-body",
        ".prose",
        "article",
    ]
    with _WEB_PLAYWRIGHT_LOCK:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(profile), headless=True)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                box = None
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and box is None:
                    for sel in input_selectors:
                        loc = page.locator(sel).first
                        try:
                            if loc.count() > 0 and loc.is_visible():
                                box = loc
                                break
                        except Exception:
                            pass
                    if box is None:
                        time.sleep(0.5)
                if box is None:
                    raise RuntimeError("网页未就绪（可能需要重新登录或通过人机验证），已停下交由你处理。")

                before_count = 0
                active_reply_sel = None
                for rsel in reply_selectors:
                    cnt = page.locator(rsel).count()
                    if cnt > 0:
                        active_reply_sel = rsel
                        before_count = cnt
                        break

                box.click()
                box.fill(prompt)
                page.keyboard.press("Enter")

                # Wait for assistant reply to stabilize.
                last_text = ""
                stable_since = None
                end_at = time.monotonic() + timeout_sec
                while time.monotonic() < end_at:
                    time.sleep(0.8)
                    text = ""
                    for rsel in ([active_reply_sel] if active_reply_sel else []) + reply_selectors:
                        try:
                            loc = page.locator(rsel)
                            cnt = loc.count()
                            if cnt > before_count or (cnt > 0 and not active_reply_sel):
                                text = loc.nth(cnt - 1).inner_text().strip()
                                if text:
                                    break
                        except Exception:
                            pass
                    if text and text != last_text:
                        last_text = text
                        stable_since = time.monotonic()
                    elif text and stable_since and (time.monotonic() - stable_since) >= 2.5:
                        return AgentReply(text=text, dry_run=False, usage={"live": True, "channel": "web_playwright"})
                if last_text:
                    return AgentReply(text=last_text, dry_run=False, usage={"live": True, "channel": "web_playwright"})
                raise RuntimeError("网页回复超时或未检测到新回答（请检查是否掉登录/遇验证码）。")
            finally:
                ctx.close()


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
        slug = self.slug or self.vendor
        if is_web_auto_ready(slug) and self.login_url:
            return playwright_chat(self.login_url, slug, prompt)
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
