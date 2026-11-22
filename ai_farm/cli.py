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
import re
import sys
import webbrowser
from pathlib import Path

from .adapters.registry import get_adapter, registered_slugs
from .dispatcher import Task, dispatch
from .quota import quota_label, quota_state
from .roster import Agent, Roster, load_roster


def _append_agent_to_yaml(path: str, agent: Agent) -> None:
    """Persist a recruited agent into agents.yaml using stdlib only (no plaintext keys)."""
    errors = agent.validate()
    if errors:
        raise ValueError("; ".join(errors))
    p = Path(path)
    if p.exists():
        existing = load_roster(str(p))
        for a in existing.agents:
            if (a.vendor.lower(), a.model_id, a.access_kind) == (agent.vendor.lower(), agent.model_id, agent.access_kind):
                raise ValueError(f"花名册中已存在 {agent.vendor} / {agent.model_id} ({agent.access_kind})，禁止重复招募。")
        text = p.read_text(encoding="utf-8").rstrip() + "\n"
    else:
        text = "# Your local roster — gitignored by default. Never put plaintext keys here.\nagents:\n"

    lines = [
        f'  - name: "{agent.name}"',
        f'    slug: "{agent.slug}"',
        f'    role: "{agent.role}"',
        f'    vendor: "{agent.vendor}"',
        f'    model_id: "{agent.model_id}"',
        f'    access_kind: "{agent.access_kind}"',
        f'    paid: {"true" if agent.paid else "false"}',
    ]
    if agent.key_env:
        lines.append(f'    key_env: "{agent.key_env}"')
    if agent.base_url:
        lines.append(f'    base_url: "{agent.base_url}"')
    if agent.login_url:
        lines.append(f'    login_url: "{agent.login_url}"')
    if agent.usage_url:
        lines.append(f'    usage_url: "{agent.usage_url}"')
    p.write_text(text + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def _recruit(roster_path: str = "agents.yaml") -> int:
    print("招募一个新 Agent：一个图标 = 一个模型。")
    name = input("名字（例：DeepSeek V4 Flash）：").strip()
    vendor = input("厂商（例：DeepSeek）：").strip()
    model = input("模型 ID（例：deepseek-v4-flash）：").strip() or "待核实具体版本"
    role = (input("楼层角色 [worker / manager]（默认 worker）：").strip().lower()) or "worker"
    kind = input("接入方式 [api / web / subscription]：").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", f"{vendor}-{model}-{kind}".lower()).strip("-") or "custom-agent"

    if kind == "api":
        paid = input("是否付费？[y/N] ").strip().lower() == "y"
        base = input("Base URL（例：https://api.deepseek.com/v1）：").strip()
        key_env = input("环境变量名（例：DEEPSEEK_API_KEY，只填名字，不填 Key）：").strip().upper()
        usage_url = input("官方查额度页 URL（选填）：").strip()
        ag = Agent(name=name, slug="custom-api", role=role, vendor=vendor, model_id=model,
                   access_kind="api", paid=paid, key_env=key_env, base_url=base, usage_url=usage_url)
        _append_agent_to_yaml(roster_path, ag)
        print(f"\n✅ 已写入 {roster_path}（只记环境变量名，不记 Key）：{name} · {vendor} · {model} · {ag.badge}")
        print("请在你自己的 shell 里运行（Key 别写进文件，别发聊天里）：")
        print(f"  export {key_env}=\"<你的 Key>\"")
        return 0
    if kind in ("web", "subscription"):
        login_url = input("厂商登录页 URL（例：https://chatgpt.com/）：").strip()
        usage_url = input("官方查额度页 URL（选填）：").strip()
        ag = Agent(name=name, slug=slug, role=role, vendor=vendor, model_id=model,
                   access_kind=kind, paid=(kind == "subscription"), login_url=login_url, usage_url=usage_url)
        _append_agent_to_yaml(roster_path, ag)
        print(f"\n✅ 已写入 {roster_path}：{name} · {vendor} · {model} · {ag.badge}")
        print("现在点一下登录一次，在厂商自己的页面登你自己的号：")
        print(f"  {login_url}")
        if input("打开浏览器登录？[y/N] ").strip().lower() == "y":
            webbrowser.open(login_url)
        print("登完回来就行，会话只存在你本地浏览器里，不进仓库。")
        return 0
    print("接入方式只能是 api / web / subscription。")
    return 2


def _build_adapter_for_agent(agent):
    if agent.access_kind == "api" and agent.base_url and agent.key_env:
        return get_adapter(
            "custom-api",
            vendor=agent.vendor,
            model_id=agent.model_id,
            base_url=agent.base_url,
            key_env=agent.key_env,
            paid=agent.paid,
        )
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


def filter_live_executable_agents(agents: list[Agent]) -> tuple[list[Agent], list[Agent]]:
    """Separate auto-executable (api/cli) agents from browser-only web agents for CLI --live runs."""
    auto_exec = [a for a in agents if a.access_kind in ("api", "cli")]
    skipped_web = [a for a in agents if a.access_kind not in ("api", "cli")]
    return auto_exec, skipped_web


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

    live_workers, skipped_w = filter_live_executable_agents(roster.workers())
    live_managers, _ = filter_live_executable_agents(roster.managers())
    if skipped_w:
        print(f"提示：已跳过 {len(skipped_w)} 名网页/桌面员工（未挂载浏览器驱动，防止误触发升级烧经理）。")
    workers = [(a.name, _build_adapter_for_agent(a)) for a in live_workers]
    managers = [(a.name, _build_adapter_for_agent(a)) for a in live_managers]
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
    run_office_server(host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ai-farm")
    sub = p.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("recruit", help="招募一个新 Agent（API 填环境变量名，网页点登录一次）")
    rec.add_argument("--roster", default="agents.yaml")

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
    office.add_argument("--no-open", action="store_true", help="仅启动服务，不自动打开浏览器")

    args = p.parse_args(argv)
    if args.cmd == "recruit":
        return _recruit(args.roster)
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
