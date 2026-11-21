from __future__ import annotations

import copy
import hashlib
import json
import secrets
import threading
import time
import uuid
from functools import wraps
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from .office_store import OfficeStore


class CollaborationDenied(PermissionError):
    pass


class CollaborationConflict(ValueError):
    pass


def _text(value: str, name: str, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonempty text of at most {limit} characters")
    return value.strip()


def _number(value: int, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _change(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._condition:
            before = copy.deepcopy(self._data)
            bindings_before = copy.deepcopy(self._bindings)
            try:
                result = method(self, *args, **kwargs)
                self.store.save()
            except Exception:
                self.store.state["collaboration"] = before
                self._bindings = bindings_before
                raise
            self._condition.notify_all()
            return copy.deepcopy(result)
    return wrapped


class CollaborationRuntime:
    """One trusted, in-process coordinator; not an HTTP authentication boundary."""

    def __init__(self, store: OfficeStore):
        self.store = store
        self._condition = threading.Condition(store._lock)
        self._bindings: dict[str, dict[str, Any]] = {}
        self._offered: dict[tuple[str, str], int] = {}
        self._closed = False
        with self._condition:
            previous = getattr(store, "_collaboration_runtime", None)
            if previous is not None and not previous._closed:
                raise CollaborationConflict("A coordinator already owns this store")
            data = store.state.setdefault("collaboration", {
                "rooms": {}, "grants": {}, "messages": [], "sequence": 0,
            })
            before = copy.deepcopy(data)
            for grant in data["grants"].values():
                if grant["state"] in ("running", "pending"):
                    grant["state"] = "unknown" if grant["state"] == "running" else "cancelled"
                    grant["reason"] = "coordinator_restart"
            try:
                store.save()
            except Exception:
                store.state["collaboration"] = before
                raise
            store._collaboration_runtime = self
            self.owner_token = self._issue("owner", "owner", 28800)

    @property
    def _data(self) -> dict[str, Any]:
        return self.store.state["collaboration"]

    def _issue(self, agent_id: str, client_session: str, ttl_seconds: int) -> str:
        token = secrets.token_urlsafe(32)
        self._bindings[hashlib.sha256(token.encode()).hexdigest()] = {
            "agent_id": agent_id, "client_session": client_session,
            "binding_id": uuid.uuid4().hex, "expires": time.monotonic() + ttl_seconds,
        }
        return token

    def _auth(self, token: str) -> dict[str, Any]:
        if self._closed:
            raise CollaborationDenied("Coordinator is closed")
        if not isinstance(token, str):
            raise CollaborationDenied("Invalid connection credential")
        binding = self._bindings.get(hashlib.sha256(token.encode()).hexdigest())
        if binding is None or binding["expires"] <= time.monotonic():
            raise CollaborationDenied("Connection credential is missing, expired or revoked")
        if binding["agent_id"] != "owner":
            agent = next((a for a in self.store.state["agents"] if a["id"] == binding["agent_id"]), None)
            if agent is None or agent.get("access_kind") not in ("api", "cli", "desktop", "chief"):
                raise CollaborationDenied("Member is no longer eligible for the local bus")
        return binding

    def _owner(self, token: str) -> dict[str, Any]:
        binding = self._auth(token)
        if binding["agent_id"] != "owner":
            raise CollaborationDenied("Only the owner may manage connections or accept a room")
        return binding

    def _room(self, binding: dict[str, Any], room_id: str, active: bool = False) -> dict[str, Any]:
        room = self._data["rooms"].get(room_id)
        if room is None or (binding["agent_id"] != "owner" and binding["agent_id"] not in room["participants"]):
            raise CollaborationDenied("Room is not accessible")
        if active and (room["state"] != "open" or time.time() >= room["deadline"]):
            raise CollaborationConflict("Room is closed or its time budget has expired")
        return room

    def _connected(self, agent_id: str) -> bool:
        return any(b["agent_id"] == agent_id and b["expires"] > time.monotonic()
                   for b in self._bindings.values())

    def _message(self, room: dict[str, Any], author: str, kind: str, text: str, **extra) -> dict[str, Any]:
        self._data["sequence"] += 1
        message = {"id": uuid.uuid4().hex, "sequence": self._data["sequence"],
                   "room_id": room["id"], "author": author, "kind": kind,
                   "text": text, "created_at": time.time(), **extra}
        self._data["messages"].append(message)
        return message

    def pair(self, owner_token: str, agent_id: str, client_session: str, ttl_seconds: int = 28800) -> str:
        with self._condition:
            self._owner(owner_token)
            _number(ttl_seconds, "ttl_seconds", 1, 28800)
            client_session = _text(client_session, "client_session", 200)
            agent = next((a for a in self.store.state["agents"] if a["id"] == agent_id), None)
            if agent is None or agent_id in ("owner", "gao") or agent.get("access_kind") not in ("api", "cli", "desktop", "chief"):
                raise CollaborationDenied("Only registered local bus members can be paired")
            if self._connected(agent_id):
                raise CollaborationConflict("Revoke the existing connection before pairing another session")
            token = self._issue(agent_id, client_session, ttl_seconds)
            self._condition.notify_all()
            return token

    @_change
    def revoke(self, owner_token: str, agent_id: str) -> dict[str, Any]:
        self._owner(owner_token)
        if agent_id == "owner":
            raise CollaborationDenied("Close the coordinator to revoke the owner")
        for key in [k for k, b in self._bindings.items() if b["agent_id"] == agent_id]:
            del self._bindings[key]
        for grant in self._data["grants"].values():
            if (grant["target"] == agent_id or grant["authorized_by"] == agent_id) and grant["state"] in ("pending", "running"):
                grant["state"] = "unknown" if grant["state"] == "running" else "cancelled"
                grant["reason"] = "connection_revoked"
        return {"agent_id": agent_id, "revoked": True}

    @_change
    def create_room(self, owner_token: str, task_id: str, participants: list[str],
                    supervisor_id: str | None = None, max_calls: int = 8,
                    max_messages: int = 32, timeout_seconds: int = 900) -> dict[str, Any]:
        self._owner(owner_token)
        _number(max_calls, "max_calls", 1, 32)
        _number(max_messages, "max_messages", 1, 128)
        _number(timeout_seconds, "timeout_seconds", 1, 86400)
        if not isinstance(participants, list) or not all(isinstance(p, str) for p in participants):
            raise ValueError("participants must be member IDs")
        if not 2 <= len(participants) <= 8 or len(set(participants)) != len(participants):
            raise ValueError("A room requires 2 to 8 distinct members")
        if not any(t["id"] == task_id for t in self.store.state["tasks"]):
            raise ValueError("The room must reference an existing task")
        if any(p == "owner" or not self._connected(p) for p in participants):
            raise CollaborationDenied("Every participant must have an owner-paired connection")
        if supervisor_id is not None and supervisor_id not in participants:
            raise ValueError("The designated supervisor must be a participant")
        room = {"id": uuid.uuid4().hex, "task_id": task_id, "participants": list(participants),
                "supervisor_id": supervisor_id, "max_calls": max_calls, "max_messages": max_messages,
                "deadline": time.time() + timeout_seconds, "state": "open", "read_cursors": {}}
        self._data["rooms"][room["id"]] = room
        return room

    @_change
    def post(self, token: str, room_id: str, text: str, request_id: str,
             reply_to: str | None = None) -> dict[str, Any]:
        binding = self._auth(token)
        room = self._room(binding, room_id)
        text = _text(text, "text")
        request_id = _text(request_id, "request_id", 128)
        self.store._reject_full_conversation_paste(text)
        author = binding["agent_id"]
        digest = _fingerprint([author, room_id, text, reply_to])
        messages = [m for m in self._data["messages"] if m["room_id"] == room_id]
        old = next((m for m in messages if m.get("request_id") == request_id and m["author"] == author), None)
        if old:
            if old["fingerprint"] != digest:
                raise CollaborationConflict("Request ID was already used for different content")
            return old
        self._room(binding, room_id, active=True)
        if reply_to is not None and not any(m["id"] == reply_to for m in messages):
            raise ValueError("reply_to must identify a message in this room")
        if sum(m["kind"] == "discussion" for m in messages) >= room["max_messages"]:
            raise CollaborationConflict("Discussion message budget exhausted")
        return self._message(room, author, "discussion", text, request_id=request_id,
                             reply_to=reply_to, fingerprint=digest)

    def _inbox(self, binding: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
        agent_id = binding["agent_id"]
        cursor = room["read_cursors"].get(agent_id, 0)
        messages = [m for m in self._data["messages"] if m["room_id"] == room["id"] and m["sequence"] > cursor]
        offered = messages[-1]["sequence"] if messages else cursor
        self._offered[(binding["binding_id"], room["id"])] = offered
        return {"messages": copy.deepcopy(messages), "offered_cursor": offered, "acknowledged_cursor": cursor}

    def inbox(self, token: str, room_id: str) -> dict[str, Any]:
        with self._condition:
            binding = self._auth(token)
            return self._inbox(binding, self._room(binding, room_id))

    @_change
    def acknowledge(self, token: str, room_id: str, sequence: int) -> dict[str, Any]:
        binding = self._auth(token)
        room = self._room(binding, room_id)
        _number(sequence, "sequence", 0, self._data["sequence"])
        cursor = room["read_cursors"].get(binding["agent_id"], 0)
        if sequence <= cursor:
            return {"acknowledged_cursor": cursor}
        offered = self._offered.get((binding["binding_id"], room_id), cursor)
        if sequence > offered or not any(m["room_id"] == room_id and m["sequence"] == sequence for m in self._data["messages"]):
            raise CollaborationDenied("Cannot acknowledge a message that was not offered")
        room["read_cursors"][binding["agent_id"]] = sequence
        return {"acknowledged_cursor": sequence}

    def _busy(self, agent_id: str) -> bool:
        return any(g["target"] == agent_id and g["state"] in ("running", "unknown")
                   for g in self._data["grants"].values())

    def wait(self, token: str, room_id: str, timeout_seconds: int = 30,
             cancel: threading.Event | None = None) -> dict[str, Any]:
        """One condition wait, never polling; callers revalidate external scope."""
        _number(timeout_seconds, "timeout_seconds", 0, 300)
        with self._condition:
            def available():
                binding = self._auth(token)
                room = self._room(binding, room_id)
                inbox = self._inbox(binding, room)
                active = room["state"] == "open" and time.time() < room["deadline"]
                grants = [g for g in self._data["grants"].values()
                          if active and g["room_id"] == room_id and g["target"] == binding["agent_id"]
                          and g["state"] == "pending" and not self._busy(binding["agent_id"])]
                return binding, room, inbox, active, grants

            binding, room, inbox, active, grants = available()
            remaining = min(timeout_seconds, binding["expires"] - time.monotonic(),
                            max(0, room["deadline"] - time.time()))
            if not inbox["messages"] and not grants and active and remaining > 0 and not (cancel and cancel.is_set()):
                self._condition.wait(remaining)
            binding, room, inbox, active, grants = available()
            return {**inbox, "grants": copy.deepcopy(grants), "room_state": room["state"],
                    "expired": time.time() >= room["deadline"],
                    "cancelled": bool(cancel and cancel.is_set())}

    @_change
    def authorize(self, token: str, room_id: str, target: str, prompt: str,
                  request_id: str, supersedes: str | None = None) -> dict[str, Any]:
        binding = self._auth(token)
        room = self._room(binding, room_id)
        if binding["agent_id"] not in ("owner", room["supervisor_id"]):
            raise CollaborationDenied("Only the owner or designated supervisor may authorize execution")
        prompt = _text(prompt, "prompt", 8000)
        self.store._reject_full_conversation_paste(prompt)
        request_id = _text(request_id, "request_id", 128)
        digest = _fingerprint([binding["agent_id"], room_id, target, prompt, supersedes])
        grants = [g for g in self._data["grants"].values() if g["room_id"] == room_id]
        old = next((g for g in grants if g["request_id"] == request_id), None)
        if old:
            if old["fingerprint"] != digest:
                raise CollaborationConflict("Execution request ID was reused with different content")
            return old
        self._room(binding, room_id, active=True)
        if target not in room["participants"] or not self._connected(target):
            raise CollaborationDenied("Target is not a connected participant")
        if len(grants) >= room["max_calls"]:
            raise CollaborationConflict("Execution authorization budget exhausted")
        previous = self._data["grants"].get(supersedes) if supersedes else None
        if supersedes and (previous is None or previous["room_id"] != room_id or previous["target"] != target
                           or previous.get("superseded_by") or not (previous["state"] in ("failed", "cancelled")
                           or (previous["state"] == "succeeded" and previous.get("review", {}).get("accepted") is False))):
            raise CollaborationConflict("Only a failed, cancelled or review-rejected execution may be superseded")
        grant = {"id": uuid.uuid4().hex, "room_id": room_id, "task_id": room["task_id"],
                 "target": target, "prompt": prompt, "request_id": request_id, "fingerprint": digest,
                 "authorized_by": binding["agent_id"], "state": "pending", "supersedes": supersedes,
                 "created_at": time.time()}
        if previous:
            previous["superseded_by"] = grant["id"]
        self._data["grants"][grant["id"]] = grant
        return grant

    def _own_grant(self, binding: dict[str, Any], grant_id: str) -> dict[str, Any]:
        grant = self._data["grants"].get(grant_id)
        if grant is None or grant["target"] != binding["agent_id"]:
            raise CollaborationDenied("Execution is assigned to another participant")
        self._room(binding, grant["room_id"])
        return grant

    @_change
    def claim(self, token: str, grant_id: str) -> dict[str, Any]:
        binding = self._auth(token)
        grant = self._own_grant(binding, grant_id)
        self._room(binding, grant["room_id"], active=True)
        if grant["state"] != "pending" or self._busy(binding["agent_id"]):
            return {"claimed": False, "execution": grant}
        grant.update(state="running", binding_id=binding["binding_id"],
                     client_session=binding["client_session"], started_at=time.time())
        return {"claimed": True, "execution": grant}

    @_change
    def complete(self, token: str, grant_id: str, conclusion: str, test_result: str,
                 changed_files: list[str] | None = None, usage_tokens: int | None = None) -> dict[str, Any]:
        binding = self._auth(token)
        grant = self._own_grant(binding, grant_id)
        if grant.get("binding_id") != binding["binding_id"]:
            raise CollaborationDenied("Only the claiming client session may report this execution")
        conclusion = _text(conclusion, "conclusion")
        test_result = _text(test_result, "test_result", 2000)
        self.store._reject_full_conversation_paste(conclusion)
        files = [] if changed_files is None else changed_files
        if not isinstance(files, list) or len(files) > 100:
            raise ValueError("changed_files must be a bounded list of relative paths")
        for path in files:
            _text(path, "changed_file", 300)
            posix = PurePosixPath(path.replace("\\", "/"))
            if PureWindowsPath(path).drive or posix.is_absolute() or ".." in posix.parts:
                raise ValueError("Changed file paths must be workspace-relative")
        if usage_tokens is not None:
            _number(usage_tokens, "usage_tokens", 0, 1_000_000_000)
        result = {"conclusion": conclusion, "test_result": test_result,
                  "changed_files": list(files), "usage_tokens": usage_tokens}
        if grant["state"] == "succeeded":
            if grant.get("result") != result:
                raise CollaborationConflict("Execution already has a different result")
            return grant
        self._room(binding, grant["room_id"], active=True)
        if grant.get("reason") in ("connection_revoked", "room_stopped", "coordinator_closed", "coordinator_restart"):
            raise CollaborationDenied("Revoked execution cannot accept a late result")
        if grant["state"] not in ("running", "unknown"):
            raise CollaborationConflict("Execution was not claimed or is already terminal")
        grant.update(state="succeeded", result=result, completed_at=time.time())
        self._message(self._data["rooms"][grant["room_id"]], binding["agent_id"], "result", conclusion,
                      execution_id=grant_id)
        return grant

    @_change
    def fail(self, token: str, grant_id: str, reason: str, uncertain: bool = True) -> dict[str, Any]:
        binding = self._auth(token)
        grant = self._own_grant(binding, grant_id)
        if type(uncertain) is not bool:
            raise ValueError("uncertain must be boolean")
        if grant.get("binding_id") != binding["binding_id"]:
            raise CollaborationDenied("Only the claiming session may report failure")
        if grant["state"] != "running":
            raise CollaborationConflict("Execution is not running")
        grant.update(state="unknown" if uncertain else "failed", reason=_text(reason, "reason", 1000))
        return grant

    @_change
    def resolve_unknown(self, owner_token: str, grant_id: str, evidence: str) -> dict[str, Any]:
        self._owner(owner_token)
        grant = self._data["grants"].get(grant_id)
        if grant is None or grant["state"] != "unknown":
            raise CollaborationConflict("Only unknown executions require reconciliation")
        grant.update(state="failed", resolution={"by": "owner", "evidence": _text(evidence, "evidence", 2000),
                                               "meaning": "owner_confirmed_no_further_execution"})
        return grant

    @_change
    def review(self, token: str, grant_id: str, accepted: bool, evidence: str) -> dict[str, Any]:
        binding = self._auth(token)
        grant = self._data["grants"].get(grant_id)
        if grant is None:
            raise CollaborationDenied("Execution is not accessible")
        self._room(binding, grant["room_id"])
        if binding["agent_id"] == grant["target"]:
            raise CollaborationDenied("An executor cannot review its own work")
        if grant["state"] != "succeeded" or type(accepted) is not bool:
            raise CollaborationConflict("Review requires a completed result and a boolean decision")
        result = {"reviewer": binding["agent_id"], "accepted": accepted,
                  "evidence": _text(evidence, "evidence", 2000)}
        if grant.get("review") and grant["review"] != result:
            raise CollaborationConflict("Review is immutable; request a new execution for revisions")
        grant["review"] = result
        return grant

    def snapshot(self, token: str, room_id: str) -> dict[str, Any]:
        with self._condition:
            binding = self._auth(token)
            room = self._room(binding, room_id)
            return copy.deepcopy({"room": room, "messages": [m for m in self._data["messages"] if m["room_id"] == room_id],
                                  "executions": [g for g in self._data["grants"].values() if g["room_id"] == room_id]})

    @_change
    def close_room(self, owner_token: str, room_id: str, accept: bool, summary: str) -> dict[str, Any]:
        binding = self._owner(owner_token)
        room = self._room(binding, room_id)
        if type(accept) is not bool or room["state"] != "open":
            raise CollaborationConflict("Room must be open and acceptance must be boolean")
        summary = _text(summary, "summary")
        grants = [g for g in self._data["grants"].values() if g["room_id"] == room_id]
        current = [g for g in grants if not g.get("superseded_by")]
        if accept and (not current or any(g["state"] != "succeeded" or not g.get("review", {}).get("accepted") for g in current)):
            raise CollaborationConflict("Every current execution must succeed and pass independent review")
        if not accept:
            for grant in grants:
                if grant["state"] in ("running", "pending"):
                    grant["state"] = "unknown" if grant["state"] == "running" else "cancelled"
                    grant["reason"] = "room_stopped"
        room.update(state="accepted" if accept else "stopped", summary=summary, closed_by="owner")
        return room

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            before = copy.deepcopy(self._data)
            for grant in self._data["grants"].values():
                if grant["state"] in ("running", "pending"):
                    grant["state"] = "unknown" if grant["state"] == "running" else "cancelled"
                    grant["reason"] = "coordinator_closed"
            try:
                self.store.save()
            except Exception:
                self.store.state["collaboration"] = before
                raise
            finally:
                self._closed = True
                self._bindings.clear()
                self._condition.notify_all()
