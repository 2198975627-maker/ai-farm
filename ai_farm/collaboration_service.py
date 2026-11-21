"""Credential-scoped boundary around the local collaboration runtime.

No implicit owner authority: automation may only consume an exact existing grant.
Runtime tokens, client processes and workspace paths remain in memory.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import threading
import time

from .adapters.codex_mcp import CodexMCPClient
from .collaboration import CollaborationConflict, CollaborationDenied, CollaborationRuntime
from .office_auth import AccessDenied


# Also used by the relay, keeping the wire schema and action names in one place.
# Required fields precede optional fields; identity is never supplied by a member.
ACTION_FIELDS = {
    "collabconnect": ([], {}),
    "collabcreateroom": (["task_id", "participants"], {"task_id": "string", "participants": "array", "supervisor_id": "string", "max_calls": "integer", "max_messages": "integer", "timeout_seconds": "integer"}),
    "collabpost": (["room_id", "text", "request_id"], {"room_id": "string", "text": "string", "request_id": "string", "reply_to": "string"}),
    "collabinbox": (["room_id"], {"room_id": "string"}),
    "collabwait": (["room_id", "wait_id"], {"room_id": "string", "wait_id": "string", "timeout_seconds": "integer"}),
    "collabcancelwait": (["wait_id"], {"wait_id": "string"}),
    "collaback": (["room_id", "sequence"], {"room_id": "string", "sequence": "integer"}),
    "collabauthorize": (["room_id", "target", "prompt", "request_id"], {"room_id": "string", "target": "string", "prompt": "string", "request_id": "string", "supersedes": "string"}),
    "collabclaim": (["grant_id"], {"grant_id": "string"}),
    "collabcomplete": (["grant_id", "conclusion", "test_result"], {"grant_id": "string", "conclusion": "string", "test_result": "string", "changed_files": "array", "usage_tokens": "integer"}),
    "collabfail": (["grant_id", "reason"], {"grant_id": "string", "reason": "string", "uncertain": "boolean"}),
    "collabreview": (["grant_id", "accepted", "evidence"], {"grant_id": "string", "accepted": "boolean", "evidence": "string"}),
    "collabsnapshot": (["room_id"], {"room_id": "string"}),
    "collabclose": (["room_id", "accept", "summary"], {"room_id": "string", "accept": "boolean", "summary": "string"}),
    "collabresolve": (["grant_id", "evidence"], {"grant_id": "string", "evidence": "string"}),
    "collabexecute": (["grant_id"], {"grant_id": "string"}),
    "collabconnectcodex": (["agent_id", "task_ids", "workspace_dir"], {"agent_id": "string", "task_ids": "array", "workspace_dir": "string", "executable": "string", "executable_env": "string", "sandbox": "string", "approval_policy": "string"}),
}


class CollaborationService:
    def __init__(self, access):
        self.access = access
        self.store = access.store
        self._runtime = None
        self._tokens = {}  # Office credential ID -> private Runtime token
        self._managed = {}  # agent ID -> process + frozen Office principal
        self._waits = {}
        self._active_waits = set()
        self._closed = False

    @property
    def runtime(self):
        if self._closed:
            raise AccessDenied("Collaboration service is closed")
        if self._runtime is None:
            self._runtime = CollaborationRuntime(self.store)
        return self._runtime

    def _principal(self, principal):
        self.access._revalidate(principal)
        current = next(p for p in self.access.credentials.values() if p["id"] == principal["id"])
        if current != principal:
            raise AccessDenied("Principal must match its bound credential")
        if principal["role"] not in ("owner", "member"):
            raise AccessDenied("Courier connections cannot use collaboration")
        if principal["role"] == "member":
            agent = self.store._find_agent(principal["agent_id"])
            if agent.get("access_kind") not in ("api", "cli", "desktop", "chief"):
                raise AccessDenied("Member is not eligible")

    def _scope(self, principal, task_id):
        self._principal(principal)
        task = self.store._find_task(task_id)
        if principal["role"] != "owner" and (task_id not in principal["task_ids"] or
                principal["agent_id"] not in (task.get("assigned_to"), task.get("reviewer_id"))):
            raise AccessDenied("Task scope is no longer valid")
        return task

    def _token(self, principal):
        if principal["role"] == "owner":
            self._tokens[principal["id"]] = self.runtime.owner_token
        token = self._tokens.get(principal["id"])
        if not token:
            raise AccessDenied("Connect this member before using collaboration")
        self.runtime._auth(token)
        return token

    def _member(self, agent_id, task_id):
        for principal in self.access.credentials.values():
            if principal.get("agent_id") == agent_id and principal["id"] in self._tokens:
                self._scope(principal, task_id)
                self._token(principal)
                return principal
        raise AccessDenied("Participant needs a current task-scoped connection")

    def _room_scope(self, principal, payload):
        grant = None
        if "grant_id" in payload:
            grant = self.runtime._data["grants"].get(payload["grant_id"])
            if grant is None:
                raise AccessDenied("Execution is not accessible")
        room_id = grant["room_id"] if grant else payload.get("room_id")
        room = self.runtime._room(self.runtime._auth(self._token(principal)), room_id)
        self._scope(principal, room["task_id"])
        return room, grant

    def _authorization(self, room, grant):
        if grant["authorized_by"] != "owner":
            if grant["authorized_by"] != room["supervisor_id"]:
                raise AccessDenied("Grant no longer has a valid supervisor")
            self._member(grant["authorized_by"], grant["task_id"])

    @staticmethod
    def _public(value):
        if isinstance(value, dict):
            return {k: CollaborationService._public(v) for k, v in value.items()
                    if k not in ("binding_id", "client_session", "fingerprint")}
        if isinstance(value, list):
            return [CollaborationService._public(v) for v in value]
        return value

    def action(self, principal, name, payload):
        name = "collabcreateroom" if name == "createroom" else name
        try:
            if name not in ACTION_FIELDS:
                raise ValueError("Unknown collaboration action")
            required, fields = ACTION_FIELDS[name]
            if set(payload) - set(fields) or any(k not in payload for k in required):
                raise ValueError("Invalid collaboration arguments")
            types = {"string": str, "integer": int, "boolean": bool, "array": list}
            if any(type(v) is not types[fields[k]] for k, v in payload.items()):
                raise ValueError("Invalid collaboration argument type")
            with self.access.lock, self.store._lock:
                self._principal(principal)
            if name == "collabconnectcodex":
                return self._connect_codex(principal, payload)
            if name == "collabexecute":
                with self.access.lock, self.store._lock:
                    self.access.require_owner(principal)
                    self._room_scope(principal, payload)
                return self._execute(payload["grant_id"], principal)
            if name == "collabwait":
                return self._wait(principal, payload)
            with self.access.lock, self.store._lock:
                self._principal(principal)
                return self._public(self._short_action(principal, name, payload))
        except (AccessDenied, CollaborationDenied):
            raise AccessDenied("Collaboration identity, permission or task scope denied") from None
        except (ValueError, KeyError, TypeError):
            raise ValueError("Collaboration arguments or execution state are invalid") from None
        except Exception:
            raise RuntimeError("Collaboration outcome unconfirmed; inspect state before retrying") from None

    def _short_action(self, principal, name, payload):
        if name == "collabcancelwait":
            key, event = self._wait_event(principal, payload["wait_id"])
            event.set()
            if self._runtime:
                with self._runtime._condition:
                    self._runtime._condition.notify_all()
            return {"wait_id": key[1], "cancelled": True}
        if name == "collabconnect":
            if principal["role"] != "member":
                raise AccessDenied("Only scoped members actively connect")
            for task_id in principal["task_ids"]:
                self._scope(principal, task_id)
            if principal["id"] not in self._tokens:
                ttl = max(1, min(28800, int(principal["expires"] - time.monotonic())))
                self._tokens[principal["id"]] = self.runtime.pair(
                    self.runtime.owner_token, principal["agent_id"], principal["id"], ttl)
            self._token(principal)
            return {"agent_id": principal["agent_id"], "connection_mode": "active_member",
                    "connected": True, "automatic_wake": False}
        if name == "collabcreateroom":
            self.access.require_owner(principal)
            self._scope(principal, payload["task_id"])
            for member in payload["participants"]:
                self._member(member, payload["task_id"])
            return self.runtime.create_room(self._token(principal), **payload)
        room, grant = self._room_scope(principal, payload)
        if name in ("collabclose", "collabresolve"):
            self.access.require_owner(principal)
        if name == "collabauthorize":
            self._member(payload["target"], room["task_id"])
        if name == "collabreview" and principal["role"] != "owner":
            task = self._scope(principal, room["task_id"])
            if task.get("reviewer_id") != principal["agent_id"]:
                raise AccessDenied("Only the current task reviewer may review")
        if name in ("collabclaim", "collabcomplete", "collabfail"):
            if name != "collabfail":
                self._authorization(room, grant)
            if principal.get("agent_id") in self._managed:
                raise AccessDenied("Managed executions can only use the managed transport")
            if name == "collabcomplete":
                self.runtime._room(self.runtime._auth(self._token(principal)), room["id"], active=True)
        method = {"collabpost": "post", "collabinbox": "inbox", "collaback": "acknowledge",
                  "collabauthorize": "authorize", "collabclaim": "claim", "collabcomplete": "complete",
                  "collabfail": "fail", "collabreview": "review", "collabsnapshot": "snapshot",
                  "collabclose": "close_room", "collabresolve": "resolve_unknown"}[name]
        if name == "collabresolve" and grant["target"] in self._managed and self._managed[grant["target"]]["busy"]:
            raise CollaborationConflict("An in-flight process cannot be reconciled yet")
        return getattr(self.runtime, method)(self._token(principal), **payload)

    def _wait_event(self, principal, wait_id):
        if not wait_id.strip() or len(wait_id) > 128:
            raise ValueError("Invalid wait ID")
        key = (principal["id"], wait_id)
        if key not in self._waits:
            if sum(k[0] == principal["id"] for k in self._waits) >= 16:
                raise CollaborationConflict("Too many waits")
            self._waits[key] = threading.Event()
        return key, self._waits[key]

    def _wait(self, principal, payload):
        with self.access.lock, self.store._lock:
            self._room_scope(principal, payload)
            key, event = self._wait_event(principal, payload["wait_id"])
            if key in self._active_waits:
                raise CollaborationConflict("Wait ID already active")
            self._active_waits.add(key)
            token = self._token(principal)
            timeout = payload.get("timeout_seconds", 30)
            if type(timeout) is not int or not 0 <= timeout <= 300:
                self._active_waits.discard(key)
                self._waits.pop(key, None)
                raise ValueError("Invalid wait timeout")
            # Bound the wait by Office credential expiry too (Runtime token may differ).
            timeout = min(timeout, max(0, int(principal["expires"] - time.monotonic())))
        try:
            result = self.runtime.wait(token, payload["room_id"], timeout, cancel=event)
            with self.access.lock, self.store._lock:
                self._room_scope(principal, payload)
                return self._public({**result, "wait_id": key[1]})
        finally:
            with self.access.lock:
                self._active_waits.discard(key)
                self._waits.pop(key, None)

    def _connect_codex(self, owner, payload):
        client = None
        member = None
        agent_id = payload["agent_id"]
        try:
            with self.access.lock, self.store._lock:
                self._principal(owner)
                self.access.require_owner(owner)
                agent = self.store._find_agent(agent_id)
                codex_identity = "codex" in str(agent.get("model", "")).lower() or "codex" in str(agent.get("name", "")).lower()
                if agent.get("vendor", "").lower() != "openai" or agent.get("access_kind") not in ("cli", "desktop") or not codex_identity:
                    raise AccessDenied("Managed Codex requires a registered OpenAI Codex CLI/desktop identity")
                if agent_id in self._managed or self.runtime._connected(agent_id):
                    raise CollaborationConflict("Revoke the old connection first")
                model = agent.get("model")
                if not isinstance(model, str) or not model.strip():
                    raise ValueError("An explicit frozen model is required")
                sandbox = payload.get("sandbox", "read-only")
                approval = payload.get("approval_policy", "on-request")
                if sandbox not in ("read-only", "workspace-write") or approval not in ("on-request", "untrusted"):
                    raise ValueError("Unsafe execution policy")
                executable = payload.get("executable")
                env_name = payload.get("executable_env")
                if bool(executable) == bool(env_name):
                    raise ValueError("Specify an executable or its environment variable name")
                if env_name:
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
                        raise ValueError("Invalid environment variable name")
                    executable = os.environ.get(env_name, "")
                path = Path(executable)
                workspace = Path(payload["workspace_dir"])
                if not path.is_absolute() or not path.is_file() or path.suffix.lower() in (".cmd", ".bat", ".ps1", ".py", ".sh"):
                    raise ValueError("An absolute native executable is required")
                if not workspace.is_absolute() or not workspace.is_dir():
                    raise ValueError("An explicit existing workspace is required")
                workspace = Path(self.store._validate_safe_workspace(str(workspace)))
                issued = self.access.issue_member(owner, {"agent_id": agent_id, "task_ids": payload["task_ids"]})
                member = self.access.authenticate(issued["token"])
                client = CodexMCPClient([str(path), "mcp-server"], workspace)
                connection = {"principal": member, "client": client, "model": model, "sandbox": sandbox,
                              "approval_policy": approval, "connected": False, "busy": False,
                              "threads": {}, "receipts": {}}
                self._managed[agent_id] = connection
            client.__enter__()  # Handshake only; never invokes a model tool.
            with self.access.lock, self.store._lock:
                self._principal(owner)
                for task_id in member["task_ids"]:
                    self._scope(member, task_id)
                self._short_action(member, "collabconnect", {})
                connection["connected"] = True
                return {"agent_id": agent_id, "credential_id": member["id"], "connected": True,
                        "connection_mode": "managed_codex", "model": model, "task_ids": list(member["task_ids"])}
        except BaseException:
            with self.access.lock, self.store._lock:
                if member:
                    self._managed.pop(agent_id, None)
                    self._tokens.pop(member["id"], None)
                    for key, p in list(self.access.credentials.items()):
                        if p["id"] == member["id"]:
                            del self.access.credentials[key]
            if client:
                self._dispose(client)
            raise

    def supports(self, agent_id, task_id):
        with self.access.lock, self.store._lock:
            connection = self._managed.get(agent_id)
            if self._closed or not connection or not connection["connected"]:
                return False
            try:
                self._scope(connection["principal"], task_id)
                self._token(connection["principal"])
                return True
            except (PermissionError, ValueError):
                return False

    def execute_authorized(self, agent_id, task_id, prompt, request_id):
        """Consume ONE existing exact grant; never authorize or assume owner identity.

        Returns {state, grant_id, text, thread_id} for confirmed success, otherwise
        {state: unknown|pending|running|..., grant_id}; ambiguous work is not retried.
        """
        with self.access.lock, self.store._lock:
            if not self.supports(agent_id, task_id):
                raise AccessDenied("No scoped managed connection")
            matches = [g for g in self.runtime._data["grants"].values()
                       if (g["target"], g["task_id"], g["prompt"], g["request_id"]) ==
                       (agent_id, task_id, prompt, request_id)]
            if len(matches) != 1:
                raise AccessDenied("Exactly one matching explicit authorization is required")
            grant_id = matches[0]["id"]
        try:
            return self._execute(grant_id)
        except PermissionError:
            raise AccessDenied("Authorized execution permission is no longer valid") from None
        except ValueError:
            raise ValueError("Authorized execution state is invalid") from None
        except Exception:
            raise RuntimeError("Authorized execution unconfirmed; inspect state before retrying") from None

    def _execute(self, grant_id, owner=None):
        with self.access.lock, self.store._lock:
            if owner:
                self._principal(owner)
                self.access.require_owner(owner)
            grant = self.runtime._data["grants"].get(grant_id)
            if not grant or not self.supports(grant["target"], grant["task_id"]):
                raise AccessDenied("No scoped managed connection")
            connection = self._managed[grant["target"]]
            member = connection["principal"]
            room, grant = self._room_scope(member, {"grant_id": grant_id})
            self.runtime._room(self.runtime._auth(self._token(member)), room["id"], active=True)
            if connection["busy"]:
                raise CollaborationConflict("Member already has an in-flight execution")
            if grant["state"] != "pending":
                return copy.deepcopy(connection["receipts"].get(grant_id,
                    {"grant_id": grant_id, "state": grant["state"]}))
            self._authorization(room, grant)
            if re.search(r"\b(?:merge|deploy|delete_code)\b|\b(?:rm|del|rmdir)\s|合并|部署|删除", grant["prompt"], re.I):
                raise AccessDenied("Critical operations are not executable through collaboration")
            # claim() must successfully persist BEFORE even entering client.start/reply.
            claimed = self.runtime.claim(self._token(member), grant_id)
            if not claimed["claimed"]:
                return {"grant_id": grant_id, "state": claimed["execution"]["state"]}
            connection["busy"] = True
            prompt = ("Task-scoped collaboration: report only task conclusions, workspace-relative changed_files, "
                      "and actual test_result (say not provided if none). Never read personal histories or credentials, "
                      "change client settings, merge, delete code, or deploy. Request human approval for critical operations.\n\n"
                      + grant["prompt"])
            room_id = room["id"]
            thread_id = connection["threads"].get(room_id)
        try:
            client = connection["client"]
            result = (client.reply(prompt, thread_id=thread_id) if thread_id else
                      client.start(prompt, model=connection["model"], sandbox=connection["sandbox"],
                                   approval_policy=connection["approval_policy"]))
            if not isinstance(result.thread_id, str) or not result.thread_id.strip():
                raise ValueError("Missing actual thread ID")
            conclusion, test_result, files = self._result(result.content)
            with self.access.lock, self.store._lock:
                if owner:
                    self._principal(owner)
                self._scope(member, grant["task_id"])
                current_room, current_grant = self._room_scope(member, {"grant_id": grant_id})
                self._authorization(current_room, current_grant)
                self.runtime.complete(self._token(member), grant_id, conclusion, test_result, files)
                connection["threads"][room_id] = result.thread_id
                receipt = {"grant_id": grant_id, "state": "succeeded", "text": result.content,
                           "thread_id": result.thread_id}
                connection["receipts"][grant_id] = receipt
                return copy.deepcopy(receipt)
        except Exception:
            with self.access.lock, self.store._lock:
                # Revocation/room stop already marks running as unknown. Never turn
                # a late output into success, and never expose transport exceptions.
                try:
                    self.runtime.fail(self._tokens.get(member["id"], ""), grant_id, "managed_outcome_unknown")
                except Exception:
                    pass
                connection["connected"] = False
            self._dispose(connection["client"])
            return {"grant_id": grant_id, "state": "unknown"}
        finally:
            with self.access.lock:
                connection["busy"] = False
                if not any(p["id"] == member["id"] for p in self.access.credentials.values()):
                    self._managed.pop(member["agent_id"], None)

    @staticmethod
    def _result(text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Empty model result")
        try:
            value = json.loads(text)
        except ValueError:
            value = None
        if isinstance(value, dict) and "conclusion" in value:
            return value["conclusion"], value.get("test_result") or "未提供测试结果", value.get("changed_files", [])
        return text, "未提供测试结果", []

    @staticmethod
    def _dispose(client):
        def close():
            try:
                client.close()
            except Exception:
                pass
        # close() can wait on an in-flight transport lock; never block auth/revoke.
        threading.Thread(target=close, name="collaboration-client-close", daemon=True).start()

    def revoke(self, credential_id):
        """Called under OfficeAccess lock, BEFORE removing the Office credential."""
        with self.store._lock:
            principal = next((p for p in self.access.credentials.values() if p["id"] == credential_id), None)
            if principal and principal["role"] == "owner":
                self.close()
                return
            if principal and credential_id in self._tokens:
                self.runtime.revoke(self.runtime.owner_token, principal["agent_id"])
                self._tokens.pop(credential_id, None)
            if principal:
                connection = self._managed.get(principal.get("agent_id"))
                if connection and connection["principal"]["id"] == credential_id:
                    connection["connected"] = False
                    self._dispose(connection["client"])
                    # Keep busy tombstones until the call returns, preventing reconnect
                    # plus reconciliation from creating concurrent execution.
                    if not connection["busy"]:
                        self._managed.pop(principal["agent_id"], None)
            for key, event in self._waits.items():
                if key[0] == credential_id:
                    event.set()

    def close(self):
        with self.access.lock, self.store._lock:
            self._closed = True
            if self._runtime:
                self._runtime.close()
            self._tokens.clear()
            for connection in self._managed.values():
                connection["connected"] = False
                self._dispose(connection["client"])
            for event in self._waits.values():
                event.set()
