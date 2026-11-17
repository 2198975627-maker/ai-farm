"""Roster: one icon = one model.

An agent is one model + one access mode. The same vendor with a paid
and a free tier is TWO agents (two icons, two badges, two quotas).
A tool (e.g. a coding CLI like Codex) is NOT an agent and gets no model icon.

agents.yaml is the user's own file. It is gitignored by default because
it may name personal accounts. Ship only examples/agents.example.yaml.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:  # keep the core usable without PyYAML
    yaml = None


@dataclass
class Agent:
    name: str
    slug: str  # adapter slug in adapters/registry.py
    role: str  # "manager" | "worker" | "chief" | "rest"
    vendor: str
    model_id: str
    access_kind: str  # "api" | "web" | "subscription"
    paid: bool = False
    # API: name of the env var holding the key (never the key itself).
    # Web/subscription: login_url the user opens once to log in.
    key_env: str = ""
    login_url: str = ""
    usage_url: str = ""
    base_url: str = ""
    model: str = ""
    fallback_model: str | None = None
    skills: list[str] = field(default_factory=list)
    status: str = "ready"  # ready | tired | pending | exhausted

    @property
    def badge(self) -> str:
        if self.role == "chief":
            return "总管·唯一入口"
        paid = "付费" if self.paid else "免费"
        kind = {"api": "API", "web": "网页", "subscription": "订阅"}.get(
            self.access_kind, self.access_kind)
        return f"{paid}·{kind}"

    def validate(self) -> list[str]:
        errors = []
        if self.role not in ("manager", "worker", "chief", "rest"):
            errors.append(f"{self.name}: bad role {self.role!r}")
        if self.access_kind not in ("api", "web", "subscription"):
            errors.append(f"{self.name}: bad access_kind {self.access_kind!r}")
        if self.access_kind == "api" and not self.key_env:
            errors.append(f"{self.name}: API agent needs key_env (env var name, not the key)")
        if self.access_kind in ("web", "subscription") and not self.login_url:
            errors.append(f"{self.name}: web/subscription agent needs login_url")
        if self.key_env and not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.key_env):
            errors.append(f"{self.name}: key_env must look like an env var name (e.g. DEEPSEEK_API_KEY), never a real key")
        return errors


@dataclass
class Roster:
    agents: list[Agent] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors = []
        seen = set()
        for a in self.agents:
            errors += a.validate()
            key = (a.vendor.lower(), a.model_id, a.access_kind)
            if key in seen:
                errors.append(f"duplicate icon: {a.vendor} {a.model_id} {a.access_kind} "
                              "(one icon = one model + one access mode)")
            seen.add(key)
        return errors

    def managers(self) -> list[Agent]:
        return [a for a in self.agents if a.role == "manager"]

    def workers(self, ready_only: bool = True) -> list[Agent]:
        ws = [a for a in self.agents if a.role == "worker"]
        return [a for a in ws if not ready_only or a.status == "ready"]


def _parse_simple_agents_yaml(text: str) -> dict:
    """Lightweight stdlib parser for agents.example.yaml when PyYAML is absent."""
    agents: list[dict] = []
    current: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped == "agents:":
            continue
        if stripped.startswith("- "):
            if current is not None:
                agents.append(current)
            current = {}
            stripped = stripped[2:].strip()
            if not stripped:
                continue
        if current is not None and ":" in stripped:
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            elif v.lower() == "true":
                v = True  # type: ignore[assignment]
            elif v.lower() == "false":
                v = False  # type: ignore[assignment]
            elif v.lower() in ("null", "none", "~"):
                v = None  # type: ignore[assignment]
            current[k] = v
    if current is not None:
        agents.append(current)
    return {"agents": agents}


def load_roster(path: str) -> Roster:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    if yaml is not None:
        data = yaml.safe_load(raw) or {}
    else:
        data = _parse_simple_agents_yaml(raw)
    agents = [Agent(**item) for item in data.get("agents", [])]
    roster = Roster(agents)
    errors = roster.validate()
    if errors:
        raise ValueError("agents.yaml invalid:\n" + "\n".join(errors))
    return roster
