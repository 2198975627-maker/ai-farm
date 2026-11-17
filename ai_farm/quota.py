"""Quota display rules.

Subscription: show only the CURRENT refresh cycle (e.g. 5h / 1 week).
  At the limit the vendor downgrades to a lite model — show "已降级，
  只能干小活" and never show it as stopped.
API: show the balance down to zero. At zero it truly stops —
  show "已停用，等明天 / 等充值".
Unknown: show "额度未填" and link to the vendor usage page.
<= 10%: red bar. Never invent a percentage.
"""
from __future__ import annotations

from .adapters.base import Quota


def quota_label(q: Quota) -> str:
    if q.percent_remaining is None:
        return "额度未填"
    return f"剩 {q.percent_remaining:.0f}%"


def quota_state(q: Quota) -> str:
    if q.percent_remaining is None:
        return "unknown"
    if q.is_low:
        if q.kind == "subscription":
            return "downgraded"  # 已降级，只能干小活
        return "exhausted" if q.is_exhausted else "low"
    return "ok"
