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
  * Production requires ``--office-url`` and a member Bearer credential read
    from an environment variable (default ``AI_FARM_MEMBER_TOKEN``). The host
    binds identity and task scope; owner browser cookies are never used.
  * In-process OfficeStore is available only for isolated ``--dry-run`` fixtures.

Red line (enforced in Core, not here): web / subscription free workers are NOT
bus members — they keep using the browser courier extension / .md mailbox.

Run:  python -m ai_farm.mcp_relay --office-url http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
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


# Compatibility identity arguments are assertions, never impersonation controls.
for _tool in TOOLS:
    _tool["description"] += (
        " Requires server permission within this member credential's bound task scope; "
        "identity is bound to the authenticated member, not chosen by arguments. "
        "This tool grants no execution or wake permission."
    )
    for _field in ("sender_id", "from_id", "worker_id", "reviewer_id", "requested_by", "agent_id"):
        _property = _tool["inputSchema"]["properties"].get(_field)
        if _property is not None:
            _property["description"] = "Must match the authenticated member; cannot impersonate another agent."


from .collaboration_service import ACTION_FIELDS

for _action, (_required, _fields) in ACTION_FIELDS.items():
    TOOLS.append({
        "name": "farm_" + _action,
        "description": (
            "Collaboration within the credential's bound task scope. Identity comes from the member credential. "
            "Owner-only connection/room/execute/close/resolve actions reject member credentials. "
            "Only owner or room supervisor can authorize. Active members cannot be auto-woken. "
            "Wait is one bounded condition wait; cancel via notifications/cancelled or "
            "farm_collabcancelwait with the same wait_id (no polling)."
        ),
        "inputSchema": {"type": "object", "required": _required, "additionalProperties": False,
                        "properties": {k: {"type": v, **({"items": {"type": "string"}} if v == "array" else {})}
                                       for k, v in _fields.items()}},
    })
    if "agent_id" in _fields:
        TOOLS[-1]["inputSchema"]["properties"]["agent_id"]["description"] = (
            "Owner-only selection of a registered scoped target; members cannot impersonate another agent."
        )


class CoreBackend:
    """In-process backend for explicitly supplied test stores, never production."""

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


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Returning None makes urllib raise HTTPError; _request closes it.
        return None


class HTTPBackend:
    """Authenticated loopback transport; the server filters identity and scope."""

    def __init__(self, office_url: str, member_token_env: str = "AI_FARM_MEMBER_TOKEN"):
        # Match the complete input, rather than a parser that may discard controls
        # or normalize userinfo, paths, escaped hosts, or empty query delimiters.
        match = re.fullmatch(r"http://(localhost|127\.0\.0\.1):([0-9]{1,5})", office_url)
        if not match or not 1 <= int(match[2]) <= 65535:
            raise ValueError("Office URL must be http://localhost:PORT or http://127.0.0.1:PORT")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", member_token_env):
            raise ValueError("Invalid member credential environment variable name")
        token = os.environ.get(member_token_env, "")
        if not token:
            raise ValueError("Member credential environment variable is required")
        if not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token):
            raise ValueError("Invalid member credential format")
        self.office_url = office_url
        self._token = token
        # Do not inherit global cookie handlers or environment proxy settings.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _RejectRedirects()
        )

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            req = urllib.request.Request(
                f"{self.office_url}{path}",
                data=None if payload is None else json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
                method="GET" if payload is None else "POST",
            )
            timeout = 310 if payload and payload.get("action") == "collabwait" else (10 if payload is None else 20)
            with self._opener.open(req, timeout=timeout) as resp:
                if not 200 <= resp.status < 300:
                    raise RuntimeError("Unexpected office response")
                data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, dict) or data.get("ok") is not True:
                raise RuntimeError("Office rejected request")
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise RuntimeError(f"Office request rejected (HTTP {status})") from None
        except Exception:
            # Never forward response bodies, URLs, headers, or transport exception
            # text into MCP: even an error response may reflect a credential.
            raise RuntimeError("Office request failed; verify connection, member permission and task scope") from None
        return data

    def action(self, name: str, payload: dict[str, Any]) -> Any:
        return self._request("/api/action", {"action": name, "payload": payload}).get("result")

    def snapshot(self) -> dict[str, Any]:
        return self._request("/api/state")


class FarmMCPRelay:
    """Stdlib JSON-RPC 2.0 MCP server. Protocol alignment only; Core does the work."""

    def __init__(self, backend: Any):
        self.backend = backend

    def handle_request(self, req: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(req, dict):
            return self._error(None, -32600, "Invalid request")
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params") or {}
        if method in ("notifications/initialized", "notifications/cancelled"):
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
                return self._error(req_id, -32601, "Method not found")
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception:  # Never reflect local paths, secrets or raw exceptions.
            return self._error(req_id, -32000, "Office tool failed; check permission and outcome before retrying")

    def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name.startswith("farm_collab") and name[5:] in ACTION_FIELDS:
            data = self.backend.action(name[5:], args)
        elif name == "farm_list_agents":
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
            raise ValueError("Unknown MCP tool")
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}], "isError": False}

    def serve_stdio(self, source, sink):
        """Only waits run concurrently so stdin remains able to receive cancellation."""
        lock = threading.RLock()
        waits = {}

        def emit(response):
            if response is not None:
                with lock:
                    sink.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sink.flush()

        def cancel(wait_id):
            try:
                self.backend.action("collabcancelwait", {"wait_id": wait_id})
            except Exception:
                pass

        def waiting(request, request_id):
            try:
                emit(self.handle_request(request))
            finally:
                with lock:
                    waits.pop(request_id, None)

        try:
            for line in source:
                if not line.strip():
                    continue
                try:
                    request = json.loads(line)
                except (ValueError, RecursionError):
                    emit(self._error(None, -32700, "Invalid JSON"))
                    continue
                if not isinstance(request, dict):
                    emit(self._error(None, -32600, "Invalid request"))
                    continue
                params = request.get("params") or {}
                if not isinstance(params, dict):
                    emit(self._error(request.get("id"), -32602, "Invalid parameters"))
                    continue
                if request.get("method") == "notifications/cancelled":
                    request_id = params.get("requestId")
                    with lock:
                        wait_id = waits.get(request_id) if type(request_id) in (str, int) else None
                    if wait_id is not None:
                        cancel(wait_id)
                    continue
                args = params.get("arguments") or {}
                if request.get("method") == "tools/call" and params.get("name") == "farm_collabwait":
                    request_id = request.get("id")
                    wait_id = args.get("wait_id") if isinstance(args, dict) else None
                    with lock:
                        if (type(request_id) not in (str, int) or not isinstance(wait_id, str)
                                or request_id in waits or len(waits) >= 8):
                            emit(self._error(request_id, -32602, "Invalid or excessive wait request"))
                            continue
                        waits[request_id] = wait_id
                    threading.Thread(target=waiting, args=(request, request_id), daemon=True).start()
                else:
                    emit(self.handle_request(request))
        finally:
            with lock:
                pending = list(waits.values())
            for wait_id in pending:
                cancel(wait_id)

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="AI Farm public in-office MCP Relay (stdio)")
    parser.add_argument("--office-url", default="", help="Required in production: authenticated loopback office URL.")
    parser.add_argument("--member-token-env", default="AI_FARM_MEMBER_TOKEN",
                        help="Name of the environment variable holding a member token (never pass the token itself).")
    parser.add_argument("--dry-run", action="store_true", help="Use only an isolated temporary Core test fixture.")
    args = parser.parse_args()

    tmp_dir = None
    if args.dry_run:
        if args.office_url:
            parser.error("--dry-run cannot be combined with --office-url")
        tmp_dir = tempfile.TemporaryDirectory()
        try:
            backend: Any = CoreBackend(OfficeStore(state_path=Path(tmp_dir.name) / "office.json"))
        except Exception:
            tmp_dir.cleanup()
            raise
    else:
        if not args.office_url:
            parser.error("--office-url is required; local personal state is not an MCP backend")
        try:
            backend = HTTPBackend(args.office_url, member_token_env=args.member_token_env)
        except ValueError as exc:
            parser.error(str(exc))

    relay = FarmMCPRelay(backend)
    try:
        relay.serve_stdio(sys.stdin, sys.stdout)
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())