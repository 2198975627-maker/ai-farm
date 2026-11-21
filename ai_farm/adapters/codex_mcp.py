"""Opt-in stdio transport; ambiguous submissions must never be retried implicitly."""
from __future__ import annotations

import json
import math
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


class CodexMCPError(RuntimeError):
    """Sanitized error: server output, prompts and environment are never included."""


class MCPTransportError(CodexMCPError):
    pass


class MCPRemoteError(CodexMCPError):
    """An explicit JSON-RPC error or MCP tool error (not successful output)."""


class MCPOutcomeUnknown(CodexMCPError):
    """Submission may have executed; callers must not automatically resubmit."""

    outcome_unknown = True
    status = "outcome_unknown"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Codex MCP outcome unknown ({reason}); do not auto-retry.")


class MCPApprovalRequired(MCPOutcomeUnknown):
    status = "approval_required"

    def __init__(self):
        super().__init__("approval_required")


class MCPUnsupportedRequest(MCPOutcomeUnknown):
    status = "unsupported_server_request"

    def __init__(self):
        super().__init__("unsupported_server_request")


@dataclass(frozen=True)
class CodexMCPResult:
    thread_id: str
    content: str


class _TransportFault(Exception):
    pass


@dataclass
class _Write:
    payload: bytes | None
    done: threading.Event = field(default_factory=threading.Event)
    failed: bool = False


class CodexMCPClient:
    """Serialized requests; explicit env replaces inheritance and excludes AI_FARM_* secrets."""

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        command: list[str],
        workspace: Path,
        timeout_sec: float = 120,
        env: Mapping[str, str] | None = None,
        *,
        max_message_bytes: int = 1024 * 1024,
    ):
        if (not isinstance(command, list) or not command
                or any(not isinstance(arg, str) or "\x00" in arg for arg in command)
                or not command[0]
                or Path(command[0]).suffix.lower() in {".cmd", ".bat"}):
            raise ValueError("Use an explicit executable argument vector, not a shell shim.")
        if not math.isfinite(timeout_sec) or timeout_sec <= 0:
            raise ValueError("timeout_sec must be finite and positive.")
        if not isinstance(max_message_bytes, int) or max_message_bytes < 256:
            raise ValueError("max_message_bytes must be at least 256.")
        self._command = list(command)
        self.workspace = Path(workspace).resolve()
        self.timeout_sec = timeout_sec
        self.max_message_bytes = max_message_bytes
        self._env = {
            key: value for key, value in (os.environ if env is None else env).items()
            if not key.upper().startswith("AI_FARM_")
        }
        self.thread_id: str | None = None
        self.tools: tuple[str, ...] = ()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._overflow = threading.Event()
        self._inbox: queue.Queue = queue.Queue(maxsize=8)
        self._outbox: queue.Queue = queue.Queue(maxsize=1)
        self._process: subprocess.Popen | None = None
        self._threads: list[threading.Thread] = []
        self._next_id = 0
        self._ready = False
        self._closed = False

    def __enter__(self) -> CodexMCPClient:
        with self._lock:
            if self._closed or self._process is not None:
                raise CodexMCPError("Client cannot be reopened.")
            try:
                self._process = subprocess.Popen(
                    self._command, cwd=str(self.workspace), env=self._env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, shell=False,
                    start_new_session=(os.name != "nt"),
                )
            except (OSError, ValueError):
                self._closed = True
                raise MCPTransportError("Cannot start Codex MCP executable.") from None
            self._threads = [
                threading.Thread(target=self._read_loop, name="codex-mcp-reader"),
                threading.Thread(target=self._write_loop, name="codex-mcp-writer"),
            ]
            try:
                for thread in self._threads:
                    thread.start()
                result = self._request("initialize", {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "ai-farm-codex-mcp", "version": "0.1"},
                })
                if (not isinstance(result, dict)
                        or result.get("protocolVersion") != self.PROTOCOL_VERSION
                        or not isinstance(result.get("capabilities"), dict)
                        or not isinstance(result["capabilities"].get("tools"), dict)):
                    raise MCPTransportError("Unsupported MCP initialization result.")
                self._send({"jsonrpc": "2.0", "method": "notifications/initialized"},
                           time.monotonic() + self.timeout_sec)
                listing = self._request("tools/list", {})
                tools = listing.get("tools") if isinstance(listing, dict) else None
                if not isinstance(tools, list) or any(
                    not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                    for tool in tools
                ):
                    raise MCPTransportError("Invalid MCP tools listing.")
                self.tools = tuple(tool["name"] for tool in tools)
                if not {"codex", "codex-reply"}.issubset(self.tools):
                    raise MCPTransportError("Required Codex MCP tools are unavailable.")
                self._ready = True
                return self
            except _TransportFault:
                self.close()
                raise MCPTransportError("MCP initialization transport failed.") from None
            except BaseException:
                self.close()
                raise

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def start(
        self, prompt: str, *, model: str | None = None,
        sandbox: str = "read-only", approval_policy: str = "on-request",
    ) -> CodexMCPResult:
        """Start a new thread; unsafe sandbox/approval policies are not exposed."""
        self._validate_text(prompt)
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("Unsupported sandbox policy.")
        if approval_policy not in {"on-request", "untrusted"}:
            raise ValueError("Unsupported approval policy.")
        arguments = {"prompt": prompt, "cwd": str(self.workspace),
                     "sandbox": sandbox, "approval-policy": approval_policy}
        if model is not None:
            self._validate_text(model)
            arguments["model"] = model
        with self._lock:
            return self._call_tool("codex", arguments)

    run = start

    def reply(self, prompt: str, *, thread_id: str | None = None) -> CodexMCPResult:
        """Continue the actual returned thread (or an explicitly supplied thread)."""
        self._validate_text(prompt)
        with self._lock:
            target = self.thread_id if thread_id is None else thread_id
            self._validate_text(target)
            return self._call_tool("codex-reply", {"prompt": prompt, "threadId": target})

    @staticmethod
    def _validate_text(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A nonempty string is required.")

    def _call_tool(self, name: str, arguments: dict) -> CodexMCPResult:
        if not self._ready or self._closed:
            raise CodexMCPError("MCP client is not connected.")
        result = self._request("tools/call", {"name": name, "arguments": arguments},
                               model_call=True)
        if isinstance(result, dict) and result.get("isError") is True:
            raise MCPRemoteError("Codex MCP tool reported an error.")
        structured = result.get("structuredContent") if isinstance(result, dict) else None
        if (not isinstance(result, dict)
                or ("isError" in result and type(result["isError"]) is not bool)
                or not isinstance(structured, dict)
                or not isinstance(structured.get("threadId"), str)
                or not structured["threadId"].strip()
                or not isinstance(structured.get("content"), str)):
            self.close()
            raise MCPOutcomeUnknown("invalid_tool_result")
        if name == "codex-reply" and structured["threadId"] != arguments["threadId"]:
            self.close()
            raise MCPOutcomeUnknown("thread_mismatch")
        self.thread_id = structured["threadId"]
        return CodexMCPResult(self.thread_id, structured["content"])

    def _request(self, method: str, params: dict, *, model_call: bool = False):
        self._next_id += 1
        request_id = self._next_id
        deadline = time.monotonic() + self.timeout_sec
        # Encoding/size validation happens before submission; these are not ambiguous.
        payload = self._encode({"jsonrpc": "2.0", "id": request_id,
                                "method": method, "params": params})
        try:
            self._send_payload(payload, deadline)
            del payload
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _TransportFault("timeout")
                try:
                    kind, message = self._inbox.get(timeout=remaining)
                except queue.Empty:
                    raise _TransportFault("timeout") from None
                if self._overflow.is_set():
                    raise _TransportFault("output_limit")
                if kind == "fault":
                    raise _TransportFault(message)
                if "method" in message:
                    self._reject_request(message, deadline)
                if (type(message.get("id")) is not int or message["id"] != request_id
                        or ("result" in message) == ("error" in message)):
                    raise _TransportFault("invalid_response")
                if "error" in message:
                    error = message["error"]
                    if (not isinstance(error, dict) or type(error.get("code")) is not int
                            or not isinstance(error.get("message"), str)):
                        raise _TransportFault("invalid_response")
                    raise MCPRemoteError("Codex MCP returned a JSON-RPC error.")
                return message["result"]
        except _TransportFault as error:
            self.close()
            if model_call:
                raise MCPOutcomeUnknown(str(error)) from None
            raise MCPTransportError("MCP handshake transport failed.") from None
        except (MCPApprovalRequired, MCPUnsupportedRequest):
            self.close()
            raise
        except BaseException:
            # Even interruption must not leave a child or permit reuse of pending replies.
            self.close()
            raise

    def _reject_request(self, message: dict, deadline: float):
        method = message["method"].lower()
        approval = any(word in method for word in ("approval", "permission", "elicitation"))
        try:
            self._send({"jsonrpc": "2.0", "id": message["id"], "error": {
                "code": -32001 if approval else -32601,
                "message": "Approval required; denied by client." if approval
                else "Unsupported server request; denied by client.",
            }}, deadline)
        except (_TransportFault, CodexMCPError):
            pass  # Still refuse explicitly if the denial cannot be delivered.
        raise MCPApprovalRequired() if approval else MCPUnsupportedRequest()

    def _encode(self, message: dict) -> bytes:
        try:
            payload = (json.dumps(message, ensure_ascii=True, allow_nan=False) + "\n").encode()
        except (ValueError, TypeError):
            raise CodexMCPError("Cannot encode MCP request.") from None
        if len(payload) > self.max_message_bytes:
            raise CodexMCPError("MCP request exceeds payload limit.")
        return payload

    def _send(self, message: dict, deadline: float):
        self._send_payload(self._encode(message), deadline)

    def _send_payload(self, payload: bytes, deadline: float):
        job = _Write(payload)
        try:
            self._outbox.put_nowait(job)
        except queue.Full:
            raise _TransportFault("disconnected") from None
        if not job.done.wait(max(0, deadline - time.monotonic())):
            raise _TransportFault("timeout")
        if job.failed:
            raise _TransportFault("disconnected")

    def _write_loop(self):
        while not self._stop.is_set():
            job = self._outbox.get()
            if job is None:
                return
            try:
                if job.payload is None:
                    self._process.stdin.close()
                    return
                self._process.stdin.write(job.payload)
                self._process.stdin.flush()
            except (OSError, ValueError):
                job.failed = True
            finally:
                job.payload = None
                job.done.set()
            del job

    def _publish(self, kind: str, value):
        try:
            self._inbox.put_nowait((kind, value))
        except queue.Full:
            self._overflow.set()

    def _read_loop(self):
        try:
            while not self._stop.is_set():
                line = self._process.stdout.readline(self.max_message_bytes + 1)
                if not line:
                    self._publish("fault", "disconnected")
                    return
                if len(line) > self.max_message_bytes:
                    self._publish("fault", "output_limit")
                    return
                if not line.endswith(b"\n"):
                    self._publish("fault", "disconnected")
                    return
                message = json.loads(line)
                del line
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError
                if "method" in message and not isinstance(message["method"], str):
                    raise ValueError
                if "method" in message and "id" not in message:
                    del message  # Progress/log notifications are never tool results.
                    continue
                if "method" in message and type(message["id"]) not in (str, int):
                    raise ValueError
                self._publish("message", message)
                del message
                if self._overflow.is_set():
                    return
        except (ValueError, UnicodeError, RecursionError):
            self._publish("fault", "invalid_response")
        except OSError:
            self._publish("fault", "disconnected")

    def close(self):
        """Terminate/reap the child tree, unblock I/O, join workers and close pipes."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._ready = False
            process = self._process
            if process is None:
                self._stop.set()
                return
            try:
                self._outbox.put_nowait(_Write(None))
            except queue.Full:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            self._stop.set()
            if os.name == "nt":
                # Only force the owned process tree if EOF did not stop it.
                if process.poll() is None:
                    try:
                        subprocess.run(
                            [str(Path(os.environ.get("SystemRoot", "C:/Windows"))
                                 / "System32" / "taskkill.exe"),
                             "/PID", str(process.pid), "/T", "/F"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=5, shell=False,
                            env=self._env,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            try:
                self._outbox.put_nowait(None)
            except queue.Full:
                pass
            for thread in self._threads:
                if thread.ident is not None:
                    thread.join(timeout=5)
            # Closing a buffered pipe while a live worker holds its lock can hang.
            if any(thread.is_alive() for thread in self._threads):
                raise MCPTransportError("MCP I/O worker cleanup failed.")
            for pipe in (process.stdin, process.stdout):
                try:
                    pipe.close()
                except OSError:
                    pass
            for inbox in (self._inbox, self._outbox):
                while True:
                    try:
                        inbox.get_nowait()
                    except queue.Empty:
                        break
