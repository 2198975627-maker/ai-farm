"""Quota display rules (aligned with Agent HUD's 3-band green/yellow/red model).

Thresholds by usage / remaining:
  - Unknown (`None`)            -> "额度未填" (never invent a number)
  - Green (`remaining > 30%`)   -> < 70% used, healthy
  - Yellow (`10% < rem <= 30%`) -> 70%-90% used, warning band
  - Red (`remaining <= 10%`)    -> >= 90% used, urgent / flashing alert

Subscription: show only the CURRENT refresh cycle (e.g. 5h / 1 week).
  At the limit the vendor downgrades to a lite model — show "已降级，
  只能干小活" and never show it as stopped.
API: show the balance down to zero. At zero it truly stops —
  show "已停用，等明天 / 等充值".
"""
from __future__ import annotations

from .adapters.base import Quota


def quota_label(q: Quota) -> str:
    if q.percent_remaining is None:
        return "额度未填"
    return f"剩 {q.percent_remaining:.0f}%"


def quota_band(percent_remaining: float | None) -> str:
    """Return HUD color band: 'unknown' | 'green' | 'yellow' | 'red'."""
    if percent_remaining is None:
        return "unknown"
    pct = float(percent_remaining)
    if pct <= 10:
        return "red"
    if pct <= 30:
        return "yellow"
    return "green"


def quota_state(q: Quota) -> str:
    if q.percent_remaining is None:
        return "unknown"
    if q.is_low:
        if q.kind == "subscription":
            return "downgraded"  # 已降级，只能干小活
        return "exhausted" if q.is_exhausted else "low"
    if q.percent_remaining <= 30:
        return "warn"
    return "ok"
