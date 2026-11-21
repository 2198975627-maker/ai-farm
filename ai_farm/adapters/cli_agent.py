"""CLI / Desktop Agent channel: headless subprocess execution for local coding/file CLIs.

Covers local CLI agents (such as Codex CLI, CodeBuddy Code, etc.) that
read/write files inside a chosen workspace directory. Implements the same
``AgentAdapter`` interface (chat + check_quota) as API and Web adapters.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .base import AgentAdapter, AgentReply, Quota


class CLIAdapter:
    """Base adapter for local CLI agents that operate on a workspace directory."""

    access_kind = "cli"

    def __init__(
        self,
        vendor: str,
        model_id: str,
        executable: str,
        args_template: list[str] | None = None,
        workspace: str = ".",
        timeout_sec: int = 180,
        paid: bool = False,
        fallback_model: str | None = None,
    ):
        self.vendor = vendor
        self.model_id = model_id
        self.executable = executable
        self.args_template = args_template or ["exec", "{prompt}"]
        self.workspace = str(Path(workspace).resolve())
        self.timeout_sec = timeout_sec
        self.paid = paid
        self.fallback_model = fallback_model

    def is_installed(self) -> bool:
        return shutil.which(self.executable) is not None

    def chat(self, prompt: str, max_tokens: int = 1000) -> AgentReply:
        resolved = shutil.which(self.executable)
        if not resolved:
            raise RuntimeError(
                f"本地未检测到 CLI 工具 `{self.executable}`，无法自动调用；"
                "自动触发降级链换其他员工。"
            )
        stdin_text = None
        if self.args_template == ["exec", "{prompt}"]:
            is_codex = Path(resolved).stem.lower() == "codex"
            cmd = [resolved, "exec"] + (["--skip-git-repo-check"] if is_codex else []) + ["-"]
            stdin_text = prompt
        else:
            cmd = [resolved] + [a.replace("{prompt}", prompt) for a in self.args_template]
        proc = subprocess.run(
            cmd,
            input=stdin_text,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_sec,
            check=False,
        )
        if proc.returncode != 0:
            err_preview = (proc.stderr or proc.stdout or "").strip()[:300]
            raise RuntimeError(f"{self.vendor} CLI exit {proc.returncode}: {err_preview}")

        diff_stat = ""
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            if diff_proc.returncode == 0 and diff_proc.stdout.strip():
                diff_stat = diff_proc.stdout.strip()
        except Exception:  # noqa: BLE001
            pass

        out_text = (proc.stdout or "").strip()
        if diff_stat:
            out_text = f"{out_text}\n\n[本地工作区 git diff --stat 摘要（供经理只看 diff 质检）]\n{diff_stat}"
        return AgentReply(
            text=out_text,
            model=self.model_id,
            usage={"channel": "cli", "executable": self.executable, "workspace": self.workspace, "has_diff": bool(diff_stat)},
        )

    def check_quota(self) -> Quota:
        installed = self.is_installed()
        return Quota(
            kind="unknown",
            note=(
                f"CLI `{self.executable}` 已就绪（本地执行）；额度跟随所绑定的账号/API余额"
                if installed
                else f"本机未安装 CLI `{self.executable}`"
            ),
            tier="CLI 工具执行端",
            fallback_model=self.fallback_model,
        )


def codex_cli(workspace: str = ".") -> CLIAdapter:
    """Codex CLI running on DeepSeek balance (tool wrapper, not an independent model pool)."""
    return CLIAdapter(
        vendor="DeepSeek / Codex CLI",
        model_id="deepseek-v4-pro",
        executable="codex",
        args_template=["exec", "{prompt}"],
        workspace=workspace,
        paid=True,
        fallback_model="换其他免费员工",
    )
