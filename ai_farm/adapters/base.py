"""AgentAdapter: the one interface every model must implement.

Whether a model is reached by API key or by a one-time web login, the
dispatcher and the office only ever talk to this interface. That is what
makes manager and worker slots interchangeable: a slot does not care
which vendor fills it, only that the vendor speaks this interface.

Access kinds (badge on the icon):
  - "api"          — OpenAI-compatible HTTP API, key in an env var
  - "web"          — free web chat, one-time login, browser-driven
  - "subscription" — paid web subscription, one-time login, browser-driven

Quota kinds:
  - "api"          — balance that runs down to zero, then truly stops
  - "subscription" — a fixed refresh cycle (e.g. 5 hours / 1 week);
                     at the limit the vendor downgrades to a lite model,
                     it does NOT truly stop. The fallback model must be
                     recorded on the agent (see roster.Agent.fallback_model).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class AgentReply:
    text: str
    model: str
    usage: dict = field(default_factory=dict)
    # Rate-limit headers the provider returned on this call, e.g.
    # {"x-day-rate-limit-remaining": "42"}. Some providers have no
    # total-quota API at all; headers are the only live signal.
    rate_limit_remaining: dict = field(default_factory=dict)


@dataclass
class Quota:
    kind: str  # "api" | "subscription" | "unknown"
    # Percent remaining in the current cycle / balance, 0-100.
    # None means "not checked yet" — display as "额度未填", never invent it.
    percent_remaining: Optional[float] = None
    # Human-readable note, e.g. "resets in 2h39m" or "expires 2026-12-10".
    note: str = ""
    # Subscription-only: model the vendor falls back to at the limit.
    fallback_model: Optional[str] = None
    # Account tier & expiry (e.g. "Pro", "Plus", "Free", "API") and available models.
    tier: str = "待核实"
    expires_at: str = ""
    available_models: list[str] = field(default_factory=list)

    @property
    def is_low(self) -> bool:
        return self.percent_remaining is not None and self.percent_remaining <= 10

    @property
    def is_exhausted(self) -> bool:
        if self.kind == "api":
            return self.percent_remaining == 0
        return False  # subscription downgrades instead of stopping


class AgentAdapter(Protocol):
    """Every agent, API or web, speaks this."""

    vendor: str
    model_id: str
    access_kind: str  # "api" | "web" | "subscription"

    def chat(self, prompt: str, max_tokens: int = 1000) -> AgentReply:
        """Send one prompt, return one reply. Raises on auth / rate limit."""
        ...

    def check_quota(self) -> Quota:
        """Return the live quota, or Quota(kind='unknown') when the vendor
        offers no way to read it. Never invent a percentage."""
        ...
