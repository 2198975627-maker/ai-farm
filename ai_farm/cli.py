"""CLI: recruit / run / quota / office.

Recruit flow (the part the user asked for):
  API paid/free  -> ask for base URL + model ID + env var NAME.
                    Never ask for the key itself, never write it to a file.
                    Tell the user the exact export line to run in their shell.
  Web / subscription -> print the vendor login URL and say "log in once
                    in your own browser". The session stays in the browser
                    profile / ~/.ai-farm/sessions/, never in the repo.
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from .adapters.registry import get_adapter, registered_slugs
from .dispatcher import Task, dispatch
from .quota import quota_label, quota_state
from .roster import load_roster


def _recruit() -> int:
    print("招募一个新 Agent：一个图标 = 一个模型。")
    name = input("名字（例：DeepSeek V4 Flash）：").strip()
    vendor = input("厂商（例：DeepSeek）：").strip()
    model = input("模型 ID（例：deepseek-v4-flash）：").strip()
    kind = input("接入方式 [api / web / subscription]：").strip().lower()
    if kind == "api":
        base = input("Base URL（例：https://api.deepseek.com/v1）：").strip()
        key_env = input("环境变量名（例：DEEPSEEK_API_KEY，只填名字，不填 Key）：").strip().upper()
        print(f"\n已记录（只记名字，不记 Key）：{name} · {vendor} · {model} · 付费·API")
        print("请在你自己的 shell 里运行（Key 别写进文件，别发聊天里）：")
        print(f"  export {key_env}=\"<你的 Key>\"")
        print(f"  并在 agents.yaml 里加：base_url: {base} / key_env: {key_env}")
        return 0
    if kind in ("web", "subscription"):
        login_url = input("厂商登录页 URL（例：https://chatgpt.com/）：").strip()
        print(f"\n已记录：{name} · {vendor} · {model} · {'付费·订阅' if kind == 'subscription' else '免费·网页'}")
        print("现在点一下登录一次，在厂商自己的页面登你自己的号：")
        print(f"  {login_url}")
        if input("打开浏览器登录？[y/N] ").strip().lower() == "y":
            webbrowser.open(login_url)
        print("登完回来就行，会话只存在你本地浏览器里，不进仓库。")
        return 0
    print("接入方式只能是 api / web / subscription。")
    return 2


def _build_adapter_for_agent(agent):
    if agent.slug in registered_slugs():
        return get_adapter(agent.slug)
    if agent.access_kind == "api":
        return get_adapter(
            "custom-api",
            vendor=agent.vendor,
            model_id=agent.model_id,
            base_url=agent.base_url,
            key_env=agent.key_env,
            paid=agent.paid,
        )
    return get_adapter(
        "custom-web",
        vendor=agent.vendor,
        model_id=agent.model_id,
        access_kind=agent.access_kind,
        login_url=agent.login_url,
        usage_url=agent.usage_url,
        fallback_model=agent.fallback_model,
        slug=agent.slug,
    )


def _run(args) -> int:
    roster_path = args.roster
    if not os.path.exists(roster_path) and os.path.exists("examples/agents.example.yaml"):
        roster_path = "examples/agents.example.yaml"
    roster = load_roster(roster_path) if os.path.exists(roster_path) else None
    if roster is None:
        print(f"找不到 {args.roster}，先复制 examples/agents.example.yaml 过去再改。")
        return 2
    with open(args.task, encoding="utf-8") as f:
        body = f.read()
    task = Task(title=args.task, goal=body[:200], input_text=body,
                output_format="按工单里的验收标准输出", acceptance="见工单")
    if args.dry_run:
        workers = [(a.name, None) for a in roster.workers()]  # type: ignore[arg-type]
        managers = [(a.name, None) for a in roster.managers()]  # type: ignore[arg-type]
        d = dispatch(task, workers, managers, dry_run=True)
        print(d.text)
        return 0

    workers = [(a.name, _build_adapter_for_agent(a)) for a in roster.workers()]
    managers = [(a.name, _build_adapter_for_agent(a)) for a in roster.managers()]
    try:
        d = dispatch(task, workers, managers, dry_run=False)
        print(f"== 交付完成（执行者: {d.worker_name}，尝试次数: {d.attempts}）==")
        print(d.text)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"真跑未通过：{e}")
        return 1


def _quota(args) -> int:
    roster_path = args.roster if os.path.exists(args.roster) else "examples/agents.example.yaml"
    roster = load_roster(roster_path)
    print("== AI 农场额度核查（真实读账，查不到一律标「额度未填」）==")
    for a in roster.agents:
        adapter = _build_adapter_for_agent(a)
        q = adapter.check_quota()
        print(f"  {a.name:18} [{a.badge}] -> {quota_label(q)} (状态: {quota_state(q)}) | {q.note}")
    return 0


def _office(args) -> int:
    from .office_server import run_office_server
    run_office_server(host=args.host, port=args.port)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ai-farm")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("recruit", help="招募一个新 Agent（API 填环境变量名，网页点登录一次）")

    run = sub.add_parser("run", help="跑一个工单")
    run.add_argument("task")
    run.add_argument("--roster", default="agents.yaml")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--live", action="store_true")

    quota = sub.add_parser("quota", help="核查花名册中各模型的真实额度状态")
    quota.add_argument("--roster", default="agents.yaml")

    office = sub.add_parser("office", help="启动 AI 农场办公室网页端")
    office.add_argument("--host", default="127.0.0.1")
    office.add_argument("--port", type=int, default=8765)

    args = p.parse_args(argv)
    if args.cmd == "recruit":
        return _recruit()
    if args.cmd == "run":
        if args.live and not args.dry_run:
            return _run(args)
        args.dry_run = True
        return _run(args)
    if args.cmd == "quota":
        return _quota(args)
    if args.cmd == "office":
        return _office(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
