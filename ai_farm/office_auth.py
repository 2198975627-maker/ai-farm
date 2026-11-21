from __future__ import annotations

import copy
import hashlib
import secrets
import threading
import time
from typing import Any


class AccessDenied(PermissionError):
    pass


class OfficeAccess:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.pair_code = secrets.token_urlsafe(32)
        self.pair_deadline = time.monotonic() + 600
        self.credentials = {}
        from .collaboration_service import CollaborationService
        self.collaboration = CollaborationService(self)
        store._collaboration_service = self.collaboration

    def _issue(self, principal):
        token = secrets.token_urlsafe(32)
        principal = {**principal, "id": secrets.token_hex(12), "expires": time.monotonic() + 28800}
        self.credentials[hashlib.sha256(token.encode()).hexdigest()] = principal
        return {"token": token, "credential_id": principal["id"], "role": principal["role"], "csrf": principal.get("csrf", "")}

    def pair_owner(self, code):
        with self.lock:
            if (not isinstance(code, str) or not self.pair_code or time.monotonic() >= self.pair_deadline
                    or not secrets.compare_digest(code, self.pair_code)):
                raise AccessDenied("配对码无效、已使用或已过期；请在本机重启服务取得新配对码。")
            self.pair_code = ""
            return self._issue({"role": "owner", "csrf": secrets.token_urlsafe(32)})

    def authenticate(self, token):
        with self.lock, self.store._lock:
            principal = self.credentials.get(hashlib.sha256(token.encode()).hexdigest()) if isinstance(token, str) else None
            if not principal or principal["expires"] <= time.monotonic():
                raise AccessDenied("请先完成本机配对，或重新取得有效的成员凭据。")
            if principal["role"] != "owner":
                agent = next((a for a in self.store.state["agents"] if a["id"] == principal["agent_id"]), None)
                if agent is None or self._identity(agent) != principal["identity"]:
                    raise AccessDenied("成员身份已变更，请重新配对。")
            return copy.deepcopy(principal)

    @staticmethod
    def _identity(agent):
        return [agent.get(k) for k in ("id", "vendor", "model", "access_kind")]

    def issue_member(self, principal, payload):
        self.require_owner(principal)
        with self.lock, self.store._lock:
            self._revalidate(principal)
            agent = self.store._find_agent(payload.get("agent_id"))
            role = payload.get("role", "member")
            tasks = payload.get("task_ids")
            if role not in ("member", "courier") or not isinstance(tasks, list) or not 1 <= len(tasks) <= 32:
                raise ValueError("请选择成员类型及 1–32 张授权工单。")
            if not all(isinstance(t, str) for t in tasks):
                raise ValueError("工单编号必须为字符串。")
            if role == "member" and agent.get("access_kind") not in ("api", "cli", "desktop", "chief"):
                raise AccessDenied("网页员工不能取得 MCP 成员凭据。")
            if role == "courier" and (len(tasks) != 1 or agent.get("access_kind") not in ("web", "subscription")):
                raise AccessDenied("传令兵凭据只绑定一张网页员工工单。")
            for task_id in tasks:
                task = self.store._find_task(task_id)
                if agent["id"] not in (task.get("assigned_to"), task.get("reviewer_id")):
                    raise AccessDenied("成员必须是授权工单的执行者或审查者。")
                if role == "courier" and task.get("assigned_to") != agent["id"]:
                    raise AccessDenied("传令兵只能绑定本工单执行者。")
            return self._issue({"role": role, "agent_id": agent["id"], "identity": self._identity(agent),
                                "task_ids": list(dict.fromkeys(tasks))})

    @staticmethod
    def require_owner(principal):
        if principal["role"] != "owner":
            raise AccessDenied("仅主人可管理连接、授权执行和最终验收。")

    def _stop_active_automations(self):
        if any(p["role"] == "owner" and p["expires"] > time.monotonic() for p in self.credentials.values()):
            return
        with self.store._lock:
            for task in self.store.state.get("tasks", []):
                if task.get("automation", {}).get("status") in ("authorized", "running"):
                    self.store.stopautomation({"task_id": task["id"]})

    def revoke(self, principal, credential_id):
        self.require_owner(principal)
        with self.lock, self.store._lock:
            self._revalidate(principal)
            self.collaboration.revoke(credential_id)
            revoked_owner = False
            for key, value in list(self.credentials.items()):
                if value["id"] == credential_id:
                    if value.get("role") == "owner":
                        revoked_owner = True
                    del self.credentials[key]
            if revoked_owner:
                self._stop_active_automations()
            with self.store._state_events:
                self.store._state_events.notify_all()
            return {"revoked": credential_id}

    def connections(self, principal):
        self.require_owner(principal)
        with self.lock:
            return [{"id": p["id"], "role": p["role"], "agent_id": p.get("agent_id"),
                     "task_ids": p.get("task_ids", []), "current": p["id"] == principal["id"]}
                    for p in self.credentials.values() if p["expires"] > time.monotonic()]

    def snapshot(self, principal):
        with self.store._lock:
            if principal["role"] == "owner":
                return copy.deepcopy({"agents": self.store.listagents(), "tasks": self.store.listtasks(),
                    "group_messages": self.store.listgroupmessages(), "skills": self.store.listskills(),
                    "hud_flights": self.store.listhudflights(), "pending_approvals": self.store.listapprovals(),
                    "bus_messages": self.store.listbusmessages(), "discussions": self.store.listdiscussions(),
                    "savings_ledger": self.store.savingsledger(), "courier_log": self.store.state.get("courier_log", []),
                    "settings": self.store.getsettings(),
                    "managed_connections": self.collaboration.managed_snapshot()})
            if principal["role"] == "courier":
                raise AccessDenied("传令兵不能读取办公室快照。")
            tasks = [t for t in self.store.state["tasks"] if t["id"] in principal["task_ids"]
                     and principal["agent_id"] in (t.get("assigned_to"), t.get("reviewer_id"))]
            agent_keys = ("id", "name", "vendor", "floor", "access_kind", "quota_percent", "tokens_used", "session_count")
            task_keys = ("id", "title", "status", "task_kind", "mode", "requires_code_review", "assigned_to", "assigned_name", "reviewer_id", "review_status", "circuit_breaker", "goal")
            agent_ids = {a for t in tasks for a in (t.get("assigned_to"), t.get("reviewer_id"))}
            return {"agents": {"agents": [{k: a.get(k) for k in agent_keys} for a in self.store.state["agents"] if a["id"] in agent_ids]},
                    "tasks": {"tasks": [{k: t.get(k) for k in task_keys} for t in tasks]}, "settings": {}}

    def _revalidate(self, principal):
        current = next((p for p in self.credentials.values() if p["id"] == principal["id"]), None)
        if current is None or current["expires"] <= time.monotonic():
            if principal.get("role") == "owner":
                self._stop_active_automations()
            raise AccessDenied("连接已撤销或过期。")
        if current["role"] != "owner":
            agent = self.store._find_agent(current["agent_id"])
            if self._identity(agent) != current["identity"]:
                raise AccessDenied("成员身份已变更。")

    def action(self, principal, name: str, payload: dict[str, Any]):
        if name.startswith("collab") or name == "createroom":
            # Service owns short critical sections; network/model waits must not
            # inherit either lock (otherwise revoke/post could never wake them).
            return self.collaboration.action(principal, name, payload)
        if principal["role"] == "owner":
            with self.lock, self.store._lock:
                self._revalidate(principal)
            return self._action(principal, name, payload)
        with self.lock, self.store._lock:
            self._revalidate(principal)
            return self._action(principal, name, payload)

    def _action(self, principal, name: str, payload: dict[str, Any]):
        if principal["role"] == "owner":
            if name in ("reset_to_seed", "deleteagent"):
                with self.lock:
                    if any(p["role"] != "owner" for p in self.credentials.values()):
                        raise AccessDenied("请先撤销成员及传令兵连接，再重置或删除成员。")
            return self.store.dispatch_action(name, payload)
        agent_id = principal["agent_id"]
        courier = principal["role"] == "courier"
        allowed = {"gettaskprompt", "courierstatus", "courierclaim", "postmessage"} if courier else {
            "claimtask", "gettaskprompt", "postmessage", "submitcodereview", "requestapproval", "sendconclusion", "bussend", "businbox"}
        if name not in allowed:
            raise AccessDenied("此连接没有该操作权限；发消息不等于获得执行授权。")
        payload = copy.deepcopy(payload)
        for field in ("sender_id", "from_id", "worker_id", "reviewer_id", "requested_by", "agent_id"):
            if payload.get(field) not in (None, "", agent_id):
                raise AccessDenied("发送身份必须与当前连接一致。")
        if payload.get("interrupt"):
            raise AccessDenied("成员消息不能中断或唤醒其他成员。")
        if name == "businbox":
            with self.store._lock:
                current_tasks = {t["id"] for t in self.store.state["tasks"] if t["id"] in principal["task_ids"]
                                 and agent_id in (t.get("assigned_to"), t.get("reviewer_id"))}
                return copy.deepcopy([m for m in self.store.state.get("bus_messages", [])
                                      if m.get("to_id") == agent_id and m.get("task_id") in current_tasks])
        task_id = payload.get("task_id")
        if not task_id or task_id not in principal["task_ids"]:
            raise AccessDenied("必须指定此连接获准访问的工单。")
        with self.store._lock:
            task = self.store._find_task(task_id)
            reviewer = name == "submitcodereview"
            if (task.get("reviewer_id") if reviewer else task.get("assigned_to")) != agent_id:
                raise AccessDenied("工单负责人已变更，或此成员不是该工单的审查者。")
            if name in ("bussend", "sendconclusion"):
                recipient = payload.get("to_id")
                if not isinstance(recipient, str) or not recipient or recipient not in {"owner", "chief", task.get("reviewer_id")}:
                    raise AccessDenied("仅允许向本工单审查者或主人提交结论。")
            if name == "gettaskprompt":
                if courier and self.store._rt_child_parent(task):
                    self.store._rt_child_open(task)
                    dispatch = task.get("roundtable_dispatch", {})
                    receipt = dispatch.get("receipts", {}).get(dispatch.get("current"), {})
                    if receipt:
                        available = (receipt.get("status") == "pending_manual"
                                     and task.get("courier_dispatch", {}).get("agent_id") != agent_id)
                        return {"task_id": task_id, "title": task["title"], "assigned_to": agent_id,
                                "assigned_name": task["assigned_name"], "status": receipt["status"],
                                "receipt_id": receipt["fingerprint"], "dispatch_allowed": available,
                                "prompt": receipt["prompt"] if available else ""}
                return self.store.gettaskprompt({"task_id": task_id})
            if name == "claimtask":
                return self.store.claimtask({"task_id": task_id, "worker_id": agent_id})
            if name == "courierclaim":
                if self.store._rt_child_parent(task):
                    self.store._rt_child_open(task)
                    dispatch = task.get("roundtable_dispatch", {})
                    receipt = dispatch.get("receipts", {}).get(dispatch.get("current"), {})
                    if receipt.get("status") != "pending_manual":
                        raise AccessDenied("先取得本子单待发送回执；未知或已完成回执不可再次投喂。")
                if task.get("worker_reported") or task.get("courier_dispatch", {}).get("agent_id") == agent_id:
                    raise AccessDenied("此工单已派发或回收；结果未知时不可再次投喂，请由主人核查或单点转交。")
                previous = copy.deepcopy(task.get("courier_dispatch"))
                task["courier_dispatch"] = {"agent_id": agent_id, "state": "unknown", "credential_id": principal["id"]}
                try:
                    self.store.save()
                except Exception:
                    if previous is None:
                        task.pop("courier_dispatch", None)
                    else:
                        task["courier_dispatch"] = previous
                    raise
                return {"claimed": True, "task_id": task_id}
            if name in ("postmessage", "sendconclusion", "submitcodereview"):
                if payload.get("usage") is not None and not isinstance(payload["usage"], dict):
                    raise ValueError("usage 必须为对象。")
                if payload.get("dry_run") or (payload.get("usage") or {}).get("dry_run"):
                    raise ValueError("成员凭据不能把干跑结果作为真实报告或审查提交。")
            if name == "postmessage":
                report = {"task_id": task_id, "sender_id": agent_id, "text": payload.get("text", ""),
                          "is_delivery": bool(payload.get("is_delivery", True)), "conclusion": payload.get("conclusion", ""),
                          "changed_files": payload.get("changed_files", []), "test_result": payload.get("test_result", ""),
                          "diff_summary": payload.get("diff_summary", ""), "receipt_id": payload.get("receipt_id"),
                          "dry_run": bool(payload.get("dry_run") or (payload.get("usage") or {}).get("dry_run"))}
                fingerprint = self.store._request_fingerprint("scoped_report", report)
                receipt = task.get("scoped_reports", {}).get(fingerprint)
                if receipt:
                    if receipt["state"] != "complete":
                        raise AccessDenied("该报告提交结果未知，请主人核查已有报告，不要重复回填。")
                    return copy.deepcopy(receipt["result"])
                before = copy.deepcopy(self.store.state)
                task.setdefault("scoped_reports", {})[fingerprint] = {"state": "unknown"}
                try:
                    self.store.save()
                except Exception:
                    self.store.state = before
                    raise
                reserved = copy.deepcopy(self.store.state)
                try:
                    result = self.store.postmessage(report)
                    task["scoped_reports"][fingerprint] = {"state": "complete", "result": copy.deepcopy(result)}
                    if courier:
                        task.setdefault("courier_dispatch", {})["state"] = "reported"
                    self.store.save()
                except Exception:
                    self.store.state = reserved
                    raise
                return result
            if name == "courierstatus":
                return self.store.courierstatus({"task_id": task_id, "agent_id": agent_id,
                    "status": payload.get("status"), "detail": payload.get("detail", ""), "url": ""})
            if name == "submitcodereview":
                return self.store.submitcodereview({"task_id": task_id, "reviewer_id": agent_id,
                    "passed": payload.get("passed"), "issues": payload.get("issues", []), "dry_run": False})
            if name == "requestapproval":
                return self.store.requestapproval({"task_id": task_id, "requested_by": agent_id,
                    "op_type": payload.get("op_type"), "target": payload.get("target"), "title": payload.get("title", "")})
            clean = {key: payload[key] for key in ("to_id", "task_id", "text", "kind", "conclusion", "changed_files", "test_result", "diff_summary", "tokens") if key in payload}
            clean.update(from_id=agent_id, sender_id=agent_id, chain_id=task_id, interrupt=False)
            return self.store.dispatch_action(name, clean)
