"""Public in-office MCP Relay (stdlib JSON-RPC 2.0 over stdio, zero deps).

Design borrowed from `jazzenchen/agent-hud-open` (Apache-2.0)
``src/apps/mcp/src/index.ts`` + ``docs/agent-messages.md``: the relay ONLY
aligns the MCP protocol. All state reads, the bus ledger and log indexing are
computed in the host Core (:class:`OfficeStore`). The relay never re-parses
chat transcripts and never invents quota/token numbers.

This upgrades the closed-source ``mcp_bridge_private.py`` from "HTTP polling
forward" into a first-class part of the in-office message bus:
  * Keeps the original 6 tool names + behavior compatible.
  * Adds bus / discussion tools backed by Core bus actions.
  * Default backend is an in-process OfficeStore (Core). ``--office-url``
    forwards to a running ``ai-farm office`` so external MCP clients join the
    SAME live bus the web office uses.

Red line (enforced in Core, not here): web / subscription free workers are NOT
bus members — they keep using the browser courier extension / .md mailbox.

Run:  python -m ai_farm.mcp_relay [--office-url http://127.0.0.1:8765]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from .office_store import OfficeStore

# Bus membership mirrors Core._bus_eligible: API / CLI / Desktop / Chief only.
MCP_ELIGIBLE_ACCESS = {"api", "cli", "desktop", "chief"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "farm_list_agents",
        "description": "List ai-farm agents with real quota ('额度未填' if unknown), floor, and mcp_eligible flag.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "farm_list_tasks",
        "description": "List tasks on the office board (optional status filter: assigned/working/in_review/rejected/delivered/accepted_done).",
        "inputSchema": {"type": "object", "properties": {"status": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "farm_claim_task",
        "description": "Claim an assigned or open task from the office board.",
        "inputSchema": {"type": "object", "required": ["task_id"],
                        "properties": {"task_id": {"type": "string"}, "worker_id": {"type": "string"}}},
    },
    {
        "name": "farm_send_conclusion",
        "description": ("Send a Conclusion-Only message (conclusion + changed_files + test_result, NOT full chat) "
                        "between bus-eligible local agents (api/cli/desktop/chief). Rides the in-office bus "
                        "(queue-if-busy, pass-counted). Web/subscription agents use the browser extension."),
        "inputSchema": {"type": "object", "required": ["sender_id", "to_id", "conclusion"],
                        "properties": {
                            "sender_id": {"type": "string"}, "to_id": {"type": "string"},
                            "task_id": {"type": "string"}, "conclusion": {"type": "string"},
                            "changed_files": {"type": "array", "items": {"type": "string"}},
                            "test_result": {"type": "string"}, "diff_summary": {"type": "string"},
                            "tokens": {"type": "integer"}}},
    },
    {
        "name": "farm_submit_code_review",
        "description": "Submit an independent code-review issue checklist (reviewer_id must differ from author).",
        "inputSchema": {"type": "object", "required": ["task_id", "reviewer_id", "passed"],
                        "properties": {"task_id": {"type": "string"}, "reviewer_id": {"type": "string"},
                                       "passed": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}},
                                       "dry_run": {"type": "boolean"}}},
    },
    {
        "name": "farm_request_approval",
        "description": "Queue a human authorization request for merge / delete_code / deploy (critical ops always ask).",
        "inputSchema": {"type": "object", "required": ["op_type", "target"],
                        "properties": {"op_type": {"type": "string", "enum": ["merge", "delete_code", "deploy", "auto_dispatch", "low_risk_run"]},
                                       "target": {"type": "string"}, "task_id": {"type": "string"},
                                       "requested_by": {"type": "string"}, "title": {"type": "string"}}},
    },
    {
        "name": "farm_bus_send",
        "description": "Send one conclusion-only envelope on the in-office bus (kind: conclusion/handoff/discussion/review/question/answer).",
        "inputSchema": {"type": "object", "required": ["from_id", "to_id", "text"],
                        "properties": {"from_id": {"type": "string"}, "to_id": {"type": "string"},
                                       "text": {"type": "string"}, "kind": {"type": "string"},
                                       "task_id": {"type": "string"}, "chain_id": {"type": "string"},
                                       "tokens": {"type": "integer"}}},
    },
    {
        "name": "farm_bus_inbox",
        "description": "Read an agent's bus inbox (delivered + queued; include_blocked to see breaker hits).",
        "inputSchema": {"type": "object", "required": ["agent_id"],
                        "properties": {"agent_id": {"type": "string"}, "include_blocked": {"type": "boolean"}}},
    },
    {
        "name": "farm_bus_ledger",
        "description": "Bus accounting computed in Core: totals, by-kind, by-agent sent/received, real tokens, blocked/queued counts.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "farm_start_discussion",
        "description": "Open a manager roundtable discussion thread (>=2 manager/chief participants, bus-eligible only).",
        "inputSchema": {"type": "object", "required": ["participants"],
                        "properties": {"task_id": {"type": "string"}, "topic": {"type": "string"},
                                       "participants": {"type": "array", "items": {"type": "string"}}}},
    },
    {
        "name": "farm_post_discussion",
        "description": "Post a conclusion-only opinion to a discussion thread (stance: support/oppose/revise/comment). Bounded rounds.",
        "inputSchema": {"type": "object", "required": ["discussion_id", "from_id", "text"],
                        "properties": {"discussion_id": {"type": "string"}, "from_id": {"type": "string"},
                                       "text": {"type": "string"}, "stance": {"type": "string"},
                                       "tokens": {"type": "integer"}}},
    },
    {
        "name": "farm_resolve_discussion",
        "description": "Close a discussion thread with a resolution and whose opinion was adopted.",
        "inputSchema": {"type": "object", "required": ["discussion_id"],
                        "properties": {"discussion_id": {"type": "string"}, "resolution": {"type": "string"},
                                       "adopted": {"type": "string"}}},
    },
]


class CoreBackend:
    """In-process backend: the relay talks straight to the host Core store."""

    def __init__(self, store: OfficeStore):
        self.store = store

    def action(self, name: str, payload: dict[str, Any]) -> Any:
        return self.store.dispatch_action(name, payload)

    def snapshot(self) -> dict[str, Any]:
        return {
            "agents": self.store.listagents(),
            "tasks": self.store.listtasks(),
            "settings": self.store.getsettings(),
        }


class HTTPBackend:
    """Forward to a running `ai-farm office`; the remote Core computes state."""

    def __init__(self, office_url: str = "http://127.0.0.1:8765"):
        self.office_url = office_url.rstrip("/")

    def action(self, name: str, payload: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            f"{self.office_url}/api/action",
            data=json.dumps({"action": name, "payload": payload}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or f"Action {name} failed")
        return data.get("result")

    def snapshot(self) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.office_url}/api/state", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))


class FarmMCPRelay:
    """Stdlib JSON-RPC 2.0 MCP server. Protocol alignment only; Core does the work."""

    def __init__(self, backend: Any):
        self.backend = backend

    def handle_request(self, req: dict[str, Any]) -> dict[str, Any] | None:
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params") or {}
        if method == "notifications/initialized":
            return None
        try:
            if method == "initialize":
                result: Any = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "ai-farm-mcp-relay", "version": "1.0.0"},
                }
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._call_tool(params.get("name", ""), params.get("arguments") or {})
            else:
                return self._error(req_id, -32601, f"Method not found: {method}")
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:  # noqa: BLE001
            return self._error(req_id, -32000, str(exc))

    def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "farm_list_agents":
            snap = self.backend.snapshot()
            agents = snap.get("agents", {}).get("agents", [])
            data: Any = {
                "agents": [
                    {
                        "id": a["id"], "name": a["name"], "vendor": a["vendor"],
                        "floor": a["floor"], "access_kind": a["access_kind"],
                        "mcp_eligible": a.get("access_kind") in MCP_ELIGIBLE_ACCESS,
                        "quota_percent": a.get("quota_percent"),
                        "tokens_used": a.get("tokens_used", 0),
                        "session_count": a.get("session_count", 0),
                    }
                    for a in agents
                ],
                "settings": snap.get("settings", {}),
            }
        elif name == "farm_list_tasks":
            snap = self.backend.snapshot()
            tasks = snap.get("tasks", {}).get("tasks", [])
            want = (args.get("status") or "").strip().lower()
            if want:
                tasks = [t for t in tasks if str(t.get("status", "")).lower() == want]
            data = {
                "count": len(tasks),
                "tasks": [
                    {
                        "id": t.get("id"), "title": t.get("title"), "status": t.get("status"),
                        "task_kind": t.get("task_kind", "small"), "mode": t.get("mode", "solo"),
                        "requires_code_review": bool(t.get("requires_code_review", False)),
                        "assigned_to": t.get("assigned_to", ""), "assigned_name": t.get("assigned_name", ""),
                        "reviewer_id": t.get("reviewer_id", ""), "review_status": t.get("review_status", "not_needed"),
                        "circuit_breaker": t.get("circuit_breaker", ""), "goal": t.get("goal", ""),
                    }
                    for t in tasks
                ],
            }
        elif name == "farm_claim_task":
            data = self.backend.action("claimtask", {"task_id": args["task_id"], "worker_id": args.get("worker_id") or ""})
        elif name == "farm_send_conclusion":
            data = self.backend.action("sendconclusion", args)
        elif name == "farm_submit_code_review":
            data = self.backend.action("submitcodereview", args)
        elif name == "farm_request_approval":
            data = self.backend.action("requestapproval", args)
        elif name == "farm_bus_send":
            data = self.backend.action("bussend", args)
        elif name == "farm_bus_inbox":
            data = self.backend.action("businbox", args)
        elif name == "farm_bus_ledger":
            data = self.backend.action("busledger", {})
        elif name == "farm_start_discussion":
            data = self.backend.action("startdiscussion", args)
        elif name == "farm_post_discussion":
            data = self.backend.action("postdiscussionmessage", args)
        elif name == "farm_resolve_discussion":
            data = self.backend.action("resolvediscussion", args)
        else:
            raise ValueError(f"Unknown MCP tool: {name}")
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}], "isError": False}

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="AI Farm public in-office MCP Relay (stdio)")
    parser.add_argument("--office-url", default="", help="Forward to a running ai-farm office (join its live bus).")
    parser.add_argument("--state-path", default="", help="In-process Core state file (default ~/.ai-farm/office_state.json).")
    parser.add_argument("--dry-run", action="store_true", help="Use an ephemeral in-memory Core (no persistence).")
    args = parser.parse_args()

    tmp_dir = None
    if args.office_url:
        backend: Any = HTTPBackend(args.office_url)
    else:
        if args.dry_run:
            tmp_dir = tempfile.TemporaryDirectory()
            state_path = Path(tmp_dir.name) / "office.json"
        else:
            state_path = Path(args.state_path) if args.state_path else None
        backend = CoreBackend(OfficeStore(state_path=state_path))

    relay = FarmMCPRelay(backend)
    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                resp = FarmMCPRelay._error(None, -32700, f"Invalid JSON: {exc}")
            else:
                resp = relay.handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())