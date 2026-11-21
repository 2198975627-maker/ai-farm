"""Disposable Python stdio fixtures only: never launches Codex or a live model."""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_farm.adapters.codex_mcp import (
    CodexMCPClient,
    CodexMCPError,
    MCPApprovalRequired,
    MCPOutcomeUnknown,
    MCPRemoteError,
    MCPTransportError,
    MCPUnsupportedRequest,
)


# A deliberately tiny fake MCP server, not an agent or a live-provider proxy.
FAKE_SERVER = r'''
import json, os, sys, threading
mode = sys.argv[1]
def read():
    line = sys.stdin.buffer.readline()
    return json.loads(line) if line else None
def send(value):
    sys.stdout.write(json.dumps(value) + "\n")
    sys.stdout.flush()
def result(request, value):
    send({"jsonrpc": "2.0", "id": request["id"], "result": value})
def error(request):
    send({"jsonrpc": "2.0", "id": request["id"], "error": {
        "code": -32000, "message": "SECRET_SERVER_MESSAGE", "data": "SECRET_DATA"}})
request = read()
assert request["method"] == "initialize"
assert request["params"]["protocolVersion"] == "2024-11-05"
assert request["params"]["capabilities"] == {}
if mode == "init_error":
    error(request)
    threading.Event().wait()
result(request, {"protocolVersion": "bad" if mode == "bad_protocol" else "2024-11-05",
                 "capabilities": {"tools": {}},
                 "serverInfo": {"name": "disposable-fixture", "version": "1"}})
request = read()
assert request == {"jsonrpc": "2.0", "method": "notifications/initialized"}
request = read()
assert request["method"] == "tools/list"
tools = [
    {"name": "codex", "inputSchema": {"type": "object", "required": ["prompt"]},
     "outputSchema": {"type": "object", "required": ["threadId", "content"]}},
    {"name": "codex-reply", "inputSchema": {
        "type": "object", "required": ["prompt", "threadId"]}},
]
result(request, {"tools": tools[:1] if mode == "missing_tool" else tools})
if mode == "blocked_write":
    threading.Event().wait()
turn = 0
thread = None
while True:
    request = read()
    if request is None:
        break
    assert request["method"] == "tools/call"
    tool = request["params"]
    args = tool["arguments"]
    assert "conversationId" not in args
    if tool["name"] == "codex":
        assert set(args).issubset({"prompt", "cwd", "model", "sandbox", "approval-policy"})
        assert args["sandbox"] in {"read-only", "workspace-write"}
        assert args["approval-policy"] in {"on-request", "untrusted"}
        assert args["cwd"] == os.getcwd()
    else:
        assert tool["name"] == "codex-reply"
        assert set(args) == {"prompt", "threadId"}
        assert args["threadId"] == thread or args["threadId"] == "external-thread"
    if mode == "timeout":
        threading.Event().wait()
    if mode == "disconnect":
        sys.exit(0)
    if mode == "oversized":
        sys.stdout.write("X" * 4097)
        sys.stdout.flush()
        threading.Event().wait()
    if mode == "oversized_result":
        result(request, {"structuredContent": {"threadId": "too-large", "content": "X" * 5000}})
        threading.Event().wait()
    if mode == "stderr_flood":
        sys.stderr.write("SECRET_STDERR" * 100000)
        sys.stderr.flush()
    if mode == "malformed":
        sys.stdout.write("SECRET_NOT_JSON\n")
        sys.stdout.flush()
        threading.Event().wait()
    if mode == "wrong_id":
        send({"jsonrpc": "2.0", "id": 99999, "result": {}})
        threading.Event().wait()
    if mode == "rpc_error":
        error(request)
        continue
    if mode == "tool_error":
        result(request, {"isError": True, "content": [{"type": "text", "text": "SECRET"}]})
        continue
    if mode in {"approval", "permission", "elicitation", "unsupported"}:
        methods = {"approval": "codex/execApproval", "permission": "requestPermission",
                   "elicitation": "elicitation/create", "unsupported": "sampling/createMessage"}
        send({"jsonrpc": "2.0", "id": "server-1", "method": methods[mode],
              "params": {"secret": "SECRET_PERMISSION"}})
        denial = read()
        # A response error, never a result/approval. The client also closes this process.
        assert denial["id"] == "server-1" and "error" in denial and "result" not in denial
        threading.Event().wait()
    if mode == "notification_flood":
        for i in range(200):
            send({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"i": i}})
    send({"jsonrpc": "2.0", "method": "notifications/message", "params": {
        "structuredContent": {"threadId": "not-final", "content": "NOT_A_RESULT"}}})
    if mode == "notification_only":
        threading.Event().wait()
    turn += 1
    thread = "thread-" + str(turn) if tool["name"] == "codex" else args["threadId"]
    if mode == "thread_mismatch" and tool["name"] == "codex-reply":
        thread = "unrelated-thread"
    content = json.dumps({"args": args, "tool": tool["name"], "turn": turn,
                         "farm_env_present": any(k.upper().startswith("AI_FARM_") for k in os.environ),
                         "test_marker": os.environ.get("MCP_TEST_MARKER")})
    structured = {"threadId": thread, "content": content}
    if mode == "missing_thread":
        structured.pop("threadId")
    if mode == "legacy_thread":
        structured["conversationId"] = structured.pop("threadId")
    if mode == "bad_content":
        structured["content"] = {"not": "text"}
    result(request, {"structuredContent": structured, "content": [
        {"type": "text", "text": "UNTRUSTED_TEXT_FALLBACK"}]})
'''


class CodexMCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex-mcp-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.clients = []
        self.addCleanup(self.cleanup_clients)

    def cleanup_clients(self):
        for client in self.clients:
            client.close()

    def client(self, mode="normal", **kwargs):
        # Explicit environment prevents this fixture from using provider credentials.
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}}
        kwargs.setdefault("env", env)
        client = CodexMCPClient(
            [sys.executable, "-B", "-u", "-c", FAKE_SERVER, mode],
            self.workspace, timeout_sec=5, **kwargs,
        )
        self.clients.append(client)
        return client

    def assert_clean(self, client):
        self.assertIsNotNone(client._process.poll())
        self.assertTrue(all(not thread.is_alive() for thread in client._threads))
        self.assertTrue(client._process.stdin.closed)
        self.assertTrue(client._process.stdout.closed)
        self.assertTrue(client._inbox.empty())
        self.assertTrue(client._outbox.empty())

    def test_handshake_defaults_and_actual_thread_continuity(self):
        client = self.client()
        self.assertIsNone(client._process)  # Construction is not an automatic model run.
        with client:
            self.assertEqual(client.tools, ("codex", "codex-reply"))
            self.assertIsNone(client.thread_id)
            first = client.run("fixture initial prompt")
            self.assertEqual(first.thread_id, "thread-1")
            args = json.loads(first.content)["args"]
            self.assertEqual(args, {"prompt": "fixture initial prompt", "cwd": str(self.workspace),
                                    "sandbox": "read-only", "approval-policy": "on-request"})
            second = client.reply("fixture continuation")
            self.assertEqual(second.thread_id, "thread-1")
            self.assertEqual(json.loads(second.content)["args"]["threadId"], "thread-1")
            third = client.reply("fixture next continuation")
            self.assertEqual(json.loads(third.content)["args"]["threadId"], "thread-1")
            self.assertEqual(client.thread_id, "thread-1")
        self.assert_clean(client)

    def test_reply_cannot_silently_switch_threads(self):
        with self.client("thread_mismatch") as client:
            client.start("fixture")
            with self.assertRaises(MCPOutcomeUnknown) as error:
                client.reply("continue")
            self.assertEqual(error.exception.reason, "thread_mismatch")
            self.assertEqual(client.thread_id, "thread-1")
        self.assert_clean(client)

    def test_safe_options_and_explicit_thread(self):
        with self.client() as client:
            first = client.start("fixture", model="fixture-model", sandbox="workspace-write",
                                 approval_policy="untrusted")
            self.assertEqual(json.loads(first.content)["args"]["model"], "fixture-model")
            reply = client.reply("fixture", thread_id="external-thread")
            self.assertEqual(json.loads(reply.content)["args"]["threadId"], "external-thread")

    def test_unsafe_policies_are_rejected_before_submission(self):
        with self.client() as client:
            for options in ({"sandbox": "danger-full-access"}, {"approval_policy": "never"},
                            {"approval_policy": "on-failure"}):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    client.run("fixture", **options)
            with self.assertRaises(ValueError):
                client.reply("fixture")
            self.assertEqual(client.run("first actual fixture call").thread_id, "thread-1")

    def test_notification_flood_is_discarded(self):
        with self.client("notification_flood") as client:
            result = client.run("fixture")
            self.assertEqual(result.thread_id, "thread-1")
            self.assertNotIn("NOT_A_RESULT", result.content)
            self.assertNotIn("UNTRUSTED_TEXT_FALLBACK", result.content)

    def test_explicit_errors_are_sanitized_and_not_success(self):
        for mode in ("rpc_error", "tool_error"):
            with self.subTest(mode=mode):
                client = self.client(mode)
                with client:
                    with self.assertRaises(MCPRemoteError) as error:
                        client.run("SECRET_PROMPT")
                    self.assertNotIn("SECRET", str(error.exception))
                    self.assertIsNone(client.thread_id)
                self.assert_clean(client)

    def test_handshake_failures_cleanup_without_model_submission(self):
        for mode, expected in (("init_error", MCPRemoteError),
                               ("bad_protocol", MCPTransportError),
                               ("missing_tool", MCPTransportError)):
            with self.subTest(mode=mode):
                client = self.client(mode)
                with self.assertRaises(expected):
                    client.__enter__()
                self.assert_clean(client)
                self.assertIsNone(client.thread_id)

    def test_permission_requests_are_denied_never_approved(self):
        for mode in ("approval", "permission", "elicitation", "unsupported"):
            with self.subTest(mode=mode):
                client = self.client(mode)
                sent = []
                original = client._send

                def capture(message, deadline):
                    sent.append(message)
                    return original(message, deadline)

                with client, patch.object(client, "_send", side_effect=capture):
                    expected = MCPUnsupportedRequest if mode == "unsupported" else MCPApprovalRequired
                    with self.assertRaises(expected) as error:
                        client.run("fixture")
                    self.assertTrue(error.exception.outcome_unknown)
                    self.assertEqual(error.exception.status,
                                     "unsupported_server_request" if mode == "unsupported"
                                     else "approval_required")
                    self.assertNotIn("SECRET", str(error.exception))
                self.assertEqual(len(sent), 1)
                self.assertEqual(sent[0]["id"], "server-1")
                self.assertIn("error", sent[0])
                self.assertNotIn("result", sent[0])
                self.assert_clean(client)

    def test_timeout_and_disconnect_are_unknown_and_not_retried(self):
        for mode, reason in (("timeout", "timeout"), ("disconnect", "disconnected"),
                             ("notification_only", "timeout")):
            with self.subTest(mode=mode):
                client = self.client(mode)
                with client:
                    client.timeout_sec = 0.2
                    before = time.monotonic()
                    with self.assertRaises(MCPOutcomeUnknown) as error:
                        client.run("fixture")
                    self.assertEqual(error.exception.reason, reason)
                    self.assertLess(time.monotonic() - before, 10)
                    with self.assertRaises(CodexMCPError):
                        client.run("must not restart")
                    self.assertEqual(client._next_id, 3)  # init, list, exactly one call
                    self.assertIsNone(client.thread_id)
                self.assert_clean(client)

    def test_blocked_stdin_write_is_also_bounded_and_ambiguous(self):
        client = self.client("blocked_write", max_message_bytes=2 * 1024 * 1024)
        with client:
            client.timeout_sec = 0.2
            with self.assertRaises(MCPOutcomeUnknown) as error:
                client.start("X" * (1024 * 1024))
            self.assertEqual(error.exception.reason, "timeout")
        self.assert_clean(client)

    def test_malformed_results_and_output_cap_fail_closed(self):
        for mode, reason in (("oversized", "output_limit"), ("oversized_result", "output_limit"),
                             ("malformed", "invalid_response"),
                             ("wrong_id", "invalid_response"),
                             ("missing_thread", "invalid_tool_result"),
                             ("legacy_thread", "invalid_tool_result"),
                             ("bad_content", "invalid_tool_result")):
            with self.subTest(mode=mode):
                client = self.client(mode, max_message_bytes=4096)
                with client:
                    with self.assertRaises(MCPOutcomeUnknown) as error:
                        client.run("fixture")
                    self.assertEqual(error.exception.reason, reason)
                    self.assertNotIn("SECRET", str(error.exception))
                    self.assertIsNone(client.thread_id)
                self.assert_clean(client)

    def test_oversized_outgoing_request_is_not_submitted(self):
        with self.client(max_message_bytes=4096) as client:
            with self.assertRaises(CodexMCPError) as error:
                client.run("X" * 5000)
            self.assertNotIsInstance(error.exception, MCPOutcomeUnknown)
            self.assertEqual(client.run("small fixture").thread_id, "thread-1")

    def test_concurrent_replies_serialize_thread_selection_and_io(self):
        with self.client() as client:
            client.start("fixture")
            barrier = threading.Barrier(8)

            def reply(index):
                barrier.wait(timeout=5)
                return client.reply(f"fixture-{index}")

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(reply, range(8)))
            turns = sorted(json.loads(result.content)["turn"] for result in results)
            self.assertEqual(turns, list(range(2, 10)))
            self.assertEqual(client.thread_id, "thread-1")
        self.assert_clean(client)

    def test_stderr_is_discarded_without_blocking_or_retention(self):
        with self.client("stderr_flood") as client:
            self.assertNotIn("SECRET", client.run("fixture").content)
        self.assert_clean(client)

    def test_environment_is_explicit_and_farm_secrets_are_filtered(self):
        original_environment = dict(os.environ)
        for inherit in (False, True):
            with self.subTest(inherit=inherit):
                controlled = {"AI_FARM_OWNER_TOKEN": "SECRET_OWNER", "ai_farm_key": "SECRET_KEY",
                              "MCP_TEST_MARKER": "fixture-marker"}
                with patch.dict(os.environ, controlled):
                    env = None if inherit else dict(controlled)
                    with self.client(env=env) as client:
                        result = json.loads(client.run("fixture").content)
                        self.assertFalse(result["farm_env_present"])
                        self.assertEqual(result["test_marker"], "fixture-marker")
                self.assertEqual(dict(os.environ), original_environment)

    def test_cleanup_is_idempotent_and_context_exception_is_preserved(self):
        client = self.client()
        with self.assertRaisesRegex(RuntimeError, "fixture-context-error"):
            with client:
                raise RuntimeError("fixture-context-error")
        client.close()
        self.assert_clean(client)
        with self.assertRaises(CodexMCPError):
            client.__enter__()

    def test_no_process_or_shell_for_invalid_commands(self):
        for command in ([], "codex mcp-server", ["codex.cmd"], ["codex.BAT"], ["bad\x00name"]):
            with self.subTest(command=command), self.assertRaises(ValueError):
                CodexMCPClient(command, self.workspace)
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                CodexMCPClient([sys.executable], self.workspace, timeout_sec=timeout)
        client = CodexMCPClient([str(self.workspace / "does-not-exist.exe")], self.workspace)
        with self.assertRaises(MCPTransportError) as error:
            client.__enter__()
        self.assertNotIn(str(self.workspace), str(error.exception))
        client.close()


if __name__ == "__main__":
    unittest.main()
