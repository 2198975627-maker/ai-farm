# AI Farm — Multi-Level AI Collaboration Workbench

> **🚧 Project Status: Work in Progress (WIP / Early Prototype)**  
> AI Farm currently provides working standard adapter interfaces, a local web-based "AI Farm Office" workbench, direct OpenAI-compatible API execution, a headless CLI runner, a semi-automated `@task.md` handoff for desktop GUI agents, and passing dry-run tests. However, it is **not yet packaged as a standalone desktop app**, and several orchestration features remain under active development (see [Current Progress & Known Gaps](#current-progress--known-gaps)).

> **One icon = one model. Managers think, workers do, the chief integrates.**

---

## Why AI Farm Exists (Core Goal)

**The goal is to cut paid token and quota costs through division of labor: offload small, repetitive, well-defined edge work to free-tier resources, while reserving strong paid models for planning, review, and integration.**

When building real projects with AI, two common extremes fail:
1. **Using flagship paid models for everything burns quota too fast:** Spending expensive reasoning tokens on batch translation, table formatting, boilerplate unit tests, or summarizing long drafts wastes budget.
2. **Relying solely on free/smaller models lacks depth:** Free or lightweight models often fail on architecture decisions, cross-file consistency, and strict judgment.

**AI Farm** solves this with a structured 3-layer hierarchy:
- **Layer 0 — Owner (You):** Publishes goals, makes final decisions, accepts/rejects deliveries, and manages your own environment variable keys.
- **Layer 1 — Chief (Sole Entrypoint):** Breaks requests into small templated tasks, dispatches by skill, tracks quotas, runs QA, and integrates results.
- **Layer 2 — Managers (2F · Paid / Strong Reasoning):** **Think only.** They plan architecture and review **diffs or summaries only** (never re-reading full source texts).
- **Layer 3 — Workers (1F · Free / Low-Cost Rotation):** **Execute only.** Drawn from many *different* vendors' free tiers (free APIs, free web chats, local CLIs, or desktop apps). When one vendor hits its daily limit or rate limit, it moves to the **Rest Yard** until tomorrow, and work rotates to another vendor.

> **Vendor-Agnostic Framework:** This open-source repository ships **only the collaboration office, rules, and standard adapter interfaces — zero pre-bundled personal accounts or hard-coded vendor locks**. Every user recruits their own APIs, web chats, CLI agents, or desktop tools after cloning.

---

## Current Progress & Known Gaps

### ✅ Working Now
- **4 Standard Access Channels (`ai_farm/adapters/`)** behind one unified `AgentAdapter` interface (`chat()` + `check_quota()`):
  - `🔌 API` (`OpenAICompatibleAdapter`): Zero-dependency stdlib client for `/chat/completions`; reads keys from env vars only; queries `GET /models` alongside balance checks.
  - `🌐 Web / Subscription` (`WebAdapter` + `browser-extension/`): One-time sign-in on the vendor's own page; includes a lightweight Chrome/Edge extension (`browser-extension/`) that auto-fills dispatched task prompts into web chat tabs and posts replies back to the Office private thread with one click.
  - `⌨️ CLI Agents` (`CLIAdapter`): Headless subprocess execution in the target workspace directory, returning diffs/output for review.
  - `🖥️ Desktop GUI Agents`: Exports structured `ai-team/tasks/inbox/<TASK_ID>.md` tickets and copies an `@file` trigger prompt for safe, zero-ban local workspace handoff.
- **Full-Stack "AI Farm Office" Web Workbench (`web/` + `office_server.py` + `office_store.py`)**:
  - Clean empty starter (only 1 generic Chief slot + optional **`🎭 Load Sample Team`** button for quick exploration); drag-and-drop icons across Manager / Worker / Rest floors.
  - End-to-end group chat flow: Manager posts templated task card → Worker claims → **🔒 Private thread reporting (keeps long outputs out of main group chat)** → Cross-vendor-only reassignment → Manager consolidates final card → Owner accepts or rejects.
  - 4-path Recruit modal: API path has **no key input box** (accepts env var names only and rejects plaintext `sk-...` keys).
  - Real quota mana bars: Subscriptions track the current refresh cycle (downgrading to lite models at limit); APIs track balance to zero; `≤10%` turns red and flashes; unverified quotas display `额度未填` (Not filled in) — never invented.
  - Independent **Skill Center**: 12 built-in SOP seed skills + senior-model judge scoring & batch approval.
- **Tests & Key Safety:** All **10 dry-run tests** in `tests/test_farm.py` pass with zero network calls and zero spend; includes a Windows helper (`scripts/set-deepseek-key.ps1`) to save API keys safely into user env vars without printing or logging them.

### 🚧 Work in Progress / Known Gaps (See [docs/ROADMAP.md](docs/ROADMAP.md))
1. **Parent-to-Child Task Auto-Split & Aggregation:** Currently 1 task card maps to 1 worker thread; splitting one large request into N parallel worker sub-cards and auto-merging them into one delivery card is still planned.
2. **Automated Zero-Token Pre-QA Gate:** Deterministic local verification scripts (character counts, number consistency checks, automated unit-test execution before manager review) are not yet wired into every task transition automatically.
3. **Autonomous Web-Worker Driving:** Due to browser cross-origin sandboxes, the web UI cannot directly drive third-party web chat tabs on its own; web workers currently rely on an external browser assistant or manual copy-paste until packaged into a desktop shell.
4. **Desktop App Packaging & Live Subscription Sync:** Packaging as an Electron/Tauri/PyWebView desktop app — to auto-sync subscription tiers/expiry dates at startup and connect desktop agents via a local MCP server — is planned for the next phase.

---

## Hard Rules

1. **One icon = one model / independent pool.** Paid and free tiers from the same vendor must be separate icons with clear badges (`Paid/Free` + `API/Web/Subscription/CLI/Desktop`). CLI wrappers without their own independent quota do not take separate model icons.
2. **One free account per vendor.** Never create multi-account clones on the same vendor or let bots clone themselves; reassignments are enforced to **different vendors only**.
3. **Managers think, workers do.** Small tasks never go to managers. Managers read diffs/summaries only. Instructions are strictly templated (`Goal + Input + Forced Output Format + Acceptance + "Do not improvise"`). Escalate to a manager only after **2 worker failures**.
4. **Quotas must be real.** Never fabricate percentages. Unknown quotas stay marked as unverified (`额度未填`) and link to the vendor's live usage page.
5. **Secrets never enter the repo.** API keys live strictly in environment variables; web sessions stay local (`~/.ai-farm/sessions/`); personal office state (`~/.ai-farm/office_state.json`) and `agents.yaml` are gitignored.

---

## Quick Start

```bash
# 1. Clone the open-source framework
git clone https://github.com/2198975627-maker/ai-farm.git
cd ai-farm

# 2. Start the "AI Farm Office" web workbench (Python 3.11+ stdlib only, zero extra dependencies)
python -m ai_farm office --port 8765
# Open http://127.0.0.1:8765 in your browser (or open web/index.html directly for static preview)

# 3. Recruit an agent interactively via CLI (asks for env var NAME only, or opens vendor login page)
python -m ai_farm recruit

# 4. Run dry-run tests (10 tests, zero network calls, zero cost)
python tests/test_farm.py
python -m ai_farm run examples/tasks/example-task.md --dry-run

# 5. Check live quota & available models for configured APIs
python -m ai_farm quota

# 6. Run a live API task (set your key in your shell env var first)
export DEEPSEEK_API_KEY="<YOUR_KEY>"   # PowerShell: $env:DEEPSEEK_API_KEY="<YOUR_KEY>"
python -m ai_farm run examples/tasks/example-task.md --live
```

## Semi-Automated Handoff for GUI Desktop Agents (No CLI / No Public API)

For desktop AI agents that can read/write local workspace folders but expose no public API or CLI (e.g., WorkBuddy, Doubao Desktop), AI Farm uses a zero-ban **Workspace File Mailbox (`@task.md`)** workflow:

1. **Bind the same workspace:** Point the desktop agent's workspace folder to this repository directory.
2. **Export & copy trigger:** Open any task's private thread in the Office web UI (`http://127.0.0.1:8765`) and click **`📂 导出 .md + 复制 @触发句`**. This writes `ai-team/tasks/inbox/<TASK_ID>.md` (noting any preferred `0.00x` free sub-model) and copies an `@file` trigger prompt to your clipboard.
3. **Execute & review diff:** Paste (`Ctrl+V`) into the desktop agent and hit Enter. Once it edits local files, review `git diff` in the farm and accept the delivery.

---

## Optional Automation Enhancements & Acknowledgements

AI Farm works out-of-the-box with Python's standard library alone — **no extra tools are required for beginners**. If you want deeper hands-free automation for web chats or desktop GUI apps, you can optionally enable either of the following:

1. **Web Chat Auto-Fill & Reply Capture (`browser-extension/`):** Load the included Chrome/Edge MV3 extension (`browser-extension/`) in Developer Mode to auto-fill dispatched prompts into free web chat tabs and send replies back with one click.
2. **Headless Desktop GUI Automation (powered by [`vercel-labs/agent-desktop`](https://github.com/vercel-labs/agent-desktop)):**
   - For desktop AI apps without public APIs or CLIs (e.g., WorkBuddy, Doubao Desktop), you can optionally install **`agent-desktop`** (Apache-2.0, Rust CLI using native OS Accessibility Trees — zero vision tokens, no mouse-focus stealing).
   - **Download & Docs:** [https://github.com/vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop)
   - **Quick usage:** Run `agent-desktop snapshot --app <AppName> -i --json` to locate the input box `ref`, then feed `@ai-team/tasks/inbox/<TASK_ID>.md` via `agent-desktop type` without interrupting your desktop workflow.

---

## Project Structure

```text
ai-farm/
  ai_farm/
    adapters/base.py               # Unified AgentAdapter protocol (chat + check_quota)
    adapters/openai_compatible.py  # API channel: /chat/completions + /models via env var keys
    adapters/web.py                # Web/Subscription channel: local one-time browser login
    adapters/cli_agent.py          # CLI channel: local subprocess workspace runner
    adapters/registry.py           # Slug registry (add a new vendor in <= 30 lines)
    roster.py                      # Roster validation: one icon = one model, blocks raw keys
    dispatcher.py                  # Worker-first fallback dispatcher (2 worker fails -> manager)
    quota.py                       # Quota state logic (subscription downgrade vs API hard stop)
    skills.py                      # Skill Center: 12 SOP seed skills + senior-model judge
    office_store.py                # Office state engine, profile sync & @task.md export
    office_server.py               # Local HTTP server (Python stdlib only)
    cli.py                         # CLI entrypoint: office / recruit / run / quota
  web/
    index.html                     # Office workbench UI (3-column layout, Skill Center, 4-path recruit)
    styles.css                     # Responsive styles & <=10% red flashing mana bars
    app.js                         # Frontend controller (live Python backend or static preview)
  ai-team/                         # Collaboration design docs, blank roster template, task template
  scripts/                         # Safe env-var key setup helpers (never store plaintext keys)
  docs/                            # ARCHITECTURE / OFFICE / RECRUITING / ROADMAP / SECURITY
  examples/
    agents.example.yaml            # Placeholder roster example (no real keys or accounts)
    tasks/example-task.md          # Generic sample task
  tests/
    test_farm.py                   # 10 dry-run tests (zero network, zero spend)
```

## License

MIT — see [LICENSE](LICENSE).

---

🌐 **Language:** English | [简体中文 (README_ZH.md)](README_ZH.md)
