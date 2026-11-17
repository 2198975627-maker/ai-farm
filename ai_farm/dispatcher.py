"""Dispatcher: workers do, managers think, chief integrates.

Rules (from the design doc, now enforced in code):
  1. Small tasks never call a manager.
  2. On failure, switch to another WORKER first.
  3. Only after 2 worker failures does the task escalate to a manager.
  4. A web agent runs serially (one browser tab); API agents may run
     in parallel — the caller is responsible for that split.
  5. Dry-run mode makes no network calls and spends nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from .adapters.base import AgentAdapter


@dataclass
class Task:
    title: str
    goal: str
    input_text: str
    output_format: str
    acceptance: str


@dataclass
class Delivery:
    worker_name: str
    text: str
    attempts: int


def dispatch(task: Task, workers: list[tuple[str, AgentAdapter]],
             managers: list[tuple[str, AgentAdapter]],
             dry_run: bool = True) -> Delivery:
    """Try workers in order; escalate to a manager only after 2 failures."""
    if dry_run:
        name = workers[0][0] if workers else "no-worker"
        return Delivery(worker_name=name,
                        text=f"[DRY RUN] {task.title}: would call {name}, no API call made.",
                        attempts=0)
    failures = 0
    last_error = None
    for name, adapter in workers:
        try:
            reply = adapter.chat(
                f"Goal: {task.goal}\nInput: {task.input_text}\n"
                f"Output format: {task.output_format}\n"
                f"Acceptance: {task.acceptance}\nDo not improvise.")
            return Delivery(worker_name=name, text=reply.text, attempts=failures + 1)
        except Exception as e:  # noqa: BLE001 - fall back to the next worker
            failures += 1
            last_error = e
            if failures >= 2:
                break
    for name, adapter in managers:
        try:
            reply = adapter.chat(
                f"Two workers failed ({last_error}). Goal: {task.goal}\n"
                f"Input: {task.input_text}\nOutput format: {task.output_format}")
            return Delivery(worker_name=f"manager:{name}", text=reply.text,
                            attempts=failures + 1)
        except Exception as e:  # noqa: BLE001
            last_error = e
    raise RuntimeError(f"all workers and managers failed, last error: {last_error}")
