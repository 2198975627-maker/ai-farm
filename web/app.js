/* AI 农场办公室前端控制器 (支持 Python 后端 API + 本地离线双模运行) */

let APP_STATE = {
  backendOnline: false,
  agents: [],
  tasks: [],
  taskSummary: { total: 0, claimed: 0, reported: 0, delivered: 0, accepted: 0 },
  groupMessages: [],
  taskMessages: {},
  hudFlights: [],
  pendingApprovals: [],
  discussions: [],
  savingsLedger: { free_calls: 0, free_tokens: 0, paid_calls: 0, paid_tokens: 0, by_day: [], by_week: [] },
  courierLog: [],
  busMessages: [],
  settings: { auto_execute_low_risk: false },
  skills: [],
  equippedBy: {},
  byFloor: { manager: [], worker: [], rest: [] },
  selectedAgentId: "chief",
  selectedTaskId: null,
  recruitLoggedInClicked: false,
  latestRecommendations: [],
  exampleCursor: 0,
  customWorkspaceDir: "",
  reportDrafts: {},
};

// =========================================================================
// 离线后备种子数据（纯开源空白工作台：只保留 1 个通用总管槽位，具体模型由用户自己招募）
// =========================================================================
const SEED_AGENTS = [
  {
    id: "chief", name: "总管 (Chief)", brand: "Orchestrator", vendor: "Chief",
    model: "待绑定你的统筹模型", verified_version: false, access_kind: "chief", paid: false,
    floor: "manager", role_label: "第1层 总管 · 唯一对接口", badge: "总管·唯一入口", badge_color: "blue",
    status: "ready", account_status: "工作台已就绪：点左下角「➕ 招募新 AI Agent」接入你自己的模型，或点顶部「🎭 载入示例团队」体验。",
    specialty: "听任务、拆单、派单、记账、质检、整合汇报",
    quota_kind: "none", quota_percent: null, quota_note: "总管槽位，不绑死特定厂商",
    usage_url: "", login_url: "", key_env: "", base_url: "",
    fallback_note: "由当前最高层级助手或你指定的统筹模型担任", attached_tools: [], skills: ["doc-drafting-frame"], icon_kind: "chief"
  }
];

const SEED_SKILLS = [
  { slug: "batch-translate", name: "批量翻译", category: "语言与翻译", steps: "1. 逐条翻译，不增不减 2. 术语统一 3. 输出双语对照表，不许自由发挥", best_for: "API / 网页免费员工", savings_note: "10条合成1次员工调用，经理只审表格不重读原文，省80%经理Token" },
  { slug: "table-cleanup", name: "名单整理成表格", category: "数据格式化", steps: "1. 去重 2. 按列对齐为Markdown表格 3. 空值统一标[缺失]，不编造数据", best_for: "中文免费员工", savings_note: "纯格式体力活交免费员工，零经理算力消耗" },
  { slug: "three-tier-summary", name: "三档摘要", category: "阅读与摘要", steps: "1. 一句话结论(≤50字) 2. 300字核心摘要 3. 要点清单；数字、人名、日期严格照原文", best_for: "长文网页员工", savings_note: "让免费长文模型先压成300字，经理只读摘要不读万字原文" },
  { slug: "long-text-speed-read", name: "长文速读", category: "阅读与摘要", steps: "1. 提取章节骨架 2. 列出所有数字/日期/专有名词原句定位 3. 标注存疑处", best_for: "长上下文免费员工", savings_note: "用长窗口免费档做预筛，避免付费主模型一次性吞入数万Token" },
  { slug: "code-review-checklist", name: "代码审查清单", category: "代码与研发", steps: "1. 逐项核对安全/边界/类型/密钥泄露 2. 只报问题+文件行号+简短原因，不重写全文件", best_for: "2楼代码经理", savings_note: "只看git diff不看全仓，输出限定行号清单，大幅压缩输出Token" },
  { slug: "test-cases", name: "测试用例生成", category: "代码与研发", steps: "1. 覆盖正常/边界/异常三类输入 2. 只写测试文件代码，绝不修改业务源码", best_for: "便宜/免费代码员工", savings_note: "测试样板代码由便宜/免费代码员工生成，本地跑通后再交经理核验" },
  { slug: "cheap-code-jobs", name: "便宜代码小活", category: "代码与研发", steps: "1. 单文件小函数/类型补齐/注释规范化 2. 仅输出改动片段或完整单文件，不讲原理", best_for: "便宜/免费代码员工", savings_note: "边角代码不唤醒付费主模型，直接省下主力额度" },
  { slug: "chinese-polish", name: "中文润色", category: "语言与翻译", steps: "1. 修正语病与生硬翻译腔 2. 保持原意与全部事实数字不变 3. 给修改前后对比", best_for: "中文网页免费员工", savings_note: "用免费网页模型润色段落，不耗付费订阅周期" },
  { slug: "promo-slogans", name: "宣传口号", category: "创意与文案", steps: "1. 按目标受众生成5条不同风格备选 2. 每条≤20字 3. 附一句适用场景说明", best_for: "网页免费员工", savings_note: "发散型短文案由免费员工批量出备选，董事长直接挑" },
  { slug: "english-writing", name: "英文写作小活", category: "语言与翻译", steps: "1. 语法与地道表达检查 2. 按指定语气输出 3. 不增删核心信息", best_for: "英文免费员工", savings_note: "英文短文交给免费网页或免费API，无需动用付费经理" },
  { slug: "batch-classify", name: "批量分类打标", category: "数据格式化", steps: "1. 严格按给定标签集合分类 2. 每条输出[编号 -> 标签] 3. 不确定的标unknown，绝不乱猜", best_for: "免费API批量员工", savings_note: "分类输出仅几个词，极省completion tokens，适合免费API批量跑" },
  { slug: "doc-drafting-frame", name: "文档起草框架", category: "规划与架构", steps: "1. 先列二级目录大纲与验收点 2. 标记哪些小节由哪个员工填内容 3. 经理审完大纲再填正文", best_for: "总管 / 2楼经理", savings_note: "经理只写200字骨架，几千字正文拆给免费员工填，省大量输出额度" },
];

// =========================================================================
// 初始化与 API 通信
// =========================================================================
async function initOffice() {
  try {
    const resp = await fetch("/api/state", { cache: "no-store" });
    if (resp.ok) {
      const data = await resp.json();
      APP_STATE.backendOnline = true;
      document.getElementById("connModeBadge").textContent = "Python 后端已连接 (4通道接口 + AgentAdapter)";
      applySnapshot(data);
      applyShotParams();
      return;
    }
  } catch (_) {
    // 离线文件模式
  }
  APP_STATE.backendOnline = false;
  document.getElementById("connModeBadge").textContent = "本地演示模式 (运行 python -m ai_farm office 可连后端)";
  APP_STATE.agents = JSON.parse(JSON.stringify(SEED_AGENTS));
  APP_STATE.skills = JSON.parse(JSON.stringify(SEED_SKILLS));
  APP_STATE.groupMessages = [
    {
      id: "msg-welcome-1",
      sender_id: "chief",
      sender_name: "总管 (Chief)",
      kind: "system_welcome",
      text: "👋 欢迎来到 **AI Farm 开源工作台**！本框架只提供标准接口与协作场地，具体接什么网页 AI、API 或桌面 Agent，全部由你自己按需招募。",
      created_at: new Date().toLocaleTimeString(),
    }
  ];
  renderAll();
  applyShotParams();
}

function applySnapshot(snap) {
  if (snap.agents && snap.agents.agents) {
    APP_STATE.agents = snap.agents.agents;
  }
  if (snap.tasks && snap.tasks.tasks) {
    APP_STATE.tasks = snap.tasks.tasks;
    APP_STATE.taskSummary = snap.tasks.summary || APP_STATE.taskSummary;
  }
  if (snap.group_messages) {
    APP_STATE.groupMessages = snap.group_messages;
  }
  if (snap.hud_flights) {
    APP_STATE.hudFlights = snap.hud_flights;
  }
  if (snap.pending_approvals) {
    APP_STATE.pendingApprovals = snap.pending_approvals;
  }
  if (snap.discussions) {
    APP_STATE.discussions = snap.discussions;
  }
  if (snap.savings_ledger) {
    APP_STATE.savingsLedger = snap.savings_ledger;
  }
  if (snap.courier_log) {
    APP_STATE.courierLog = snap.courier_log;
  }
  if (snap.bus_messages) {
    APP_STATE.busMessages = snap.bus_messages;
  }
  if (snap.settings) {
    APP_STATE.settings = snap.settings;
  }
  if (snap.skills && snap.skills.skills) {
    APP_STATE.skills = snap.skills.skills;
    APP_STATE.equippedBy = snap.skills.equipped_by || {};
    APP_STATE.byFloor = snap.skills.by_floor || { manager: [], worker: [], rest: [] };
  }
  if (!APP_STATE.selectedTaskId && APP_STATE.tasks.length > 0) {
    APP_STATE.selectedTaskId = APP_STATE.tasks[0].id;
  }
  renderAll();
}

async function callOfficeAction(action, payload = {}) {
  if (APP_STATE.backendOnline) {
    const resp = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, payload }),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      showToast("❌ " + (data.error || "操作失败"), true);
      throw new Error(data.error || "Action failed");
    }
    if (data.snapshot) {
      applySnapshot(data.snapshot);
    }
    return data.result;
  }
  showToast("💡 当前为纯静态预览，请运行 python -m ai_farm office 使用完整后端接口");
  return null;
}

// =========================================================================
// UI 重做 helpers（§六）：线性 SVG 图标 / 去 emoji / 模式选择 / 审批抽屉 / 招募向导
// =========================================================================
const ICON_PATHS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.27 6.96L12 12l8.73-5.04M12 22V12"/>',
  send: '<path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  refresh: '<path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  star: '<path d="M12 2l3 6 6 .9-4.5 4.3 1 6.3-5.5-3-5.5 3 1-6.3L3 8.9 9 8z"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  undo: '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-15-6.7L3 13"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>',
};
function icon(name, cls = "") {
  return `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON_PATHS[name] || ""}</svg>`;
}
const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{2714}\u{2716}-\u{27BF}\u{2B00}-\u{2BFF}\u{2300}-\u{23FF}\u{FE0F}\u{200D}\u{2190}-\u{21FF}]/gu;
function stripEmoji(str) {
  return String(str == null ? "" : str).replace(EMOJI_RE, "").replace(/\s{2,}/g, " ").trim();
}
const HEX_TOKEN_MAP = [
  [/#(?:38bdf8|3b82f6|a5b4fc|22d3ee|60a5fa|818cf8)\b/gi, "var(--accent)"],
  [/#(?:94a3b8|64748b|71717a|a1a1aa)\b/gi, "var(--text-muted)"],
  [/#(?:f87171|ef4444|fca5a5)\b/gi, "var(--danger)"],
  [/#(?:10b981|22c55e|86efac|4ade80)\b/gi, "var(--quota-green)"],
  [/#(?:f59e0b|fbbf24|eab308|facc15)\b/gi, "var(--quota-yellow)"],
  [/#(?:0f172a|1e293b)\b/gi, "var(--bg-card-elevated)"],
  [/#(?:334155|475569)\b/gi, "var(--border-strong)"],
];
function neutralizeHTML(html) {
  let out = String(html == null ? "" : html).replace(EMOJI_RE, "");
  for (const [re, tok] of HEX_TOKEN_MAP) out = out.replace(re, tok);
  return out;
}
function neutralizePanels() {
  ["agentProfileContent", "taskThreadContent", "skillsGrid", "floorSkillOverview", "judgeResultSection"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = neutralizeHTML(el.innerHTML);
  });
}
function neutralizeStaticChrome() {
  document.querySelectorAll(".modal-card, .skills-top-card, .stage-header, .chat-composer, .security-banner, .login-once-box").forEach(el => {
    el.innerHTML = neutralizeHTML(el.innerHTML);
  });
}
// 只读截图/演示入口：?view=skills / ?modal=recruit|newtask|approval（不改变任何数据）
function applyShotParams() {
  neutralizeStaticChrome();
  const p = new URLSearchParams(location.search);
  if (p.get("view") === "skills") switchMainView("skills");
  const pane = p.get("pane");
  if (pane === "chat" || pane === "detail" || pane === "roster") switchMobilePane(pane);
  const modal = p.get("modal");
  if (modal === "recruit") openRecruitModal();
  else if (modal === "newtask") openNewTaskModal();
  else if (modal === "approval") toggleApprovalDrawer(true);
}

function selectTaskMode(mode) {
  const input = document.getElementById("taskModeInput");
  if (input) input.value = mode;
  document.querySelectorAll("#taskModeSelector .mode-option").forEach(el => {
    el.classList.toggle("active", el.dataset.mode === mode);
  });
  const kind = document.getElementById("taskKindSelect");
  if (kind && mode === "critic") { kind.value = "code_change"; toggleReviewerField(); }
}

function toggleApprovalDrawer(force) {
  const drawer = document.getElementById("approvalDrawer");
  const backdrop = document.getElementById("approvalDrawerBackdrop");
  if (!drawer) return;
  const open = typeof force === "boolean" ? force : !drawer.classList.contains("open");
  drawer.classList.toggle("open", open);
  if (backdrop) backdrop.classList.toggle("hidden", !open);
  if (open) renderApprovalDrawerBody();
}

function renderApprovalDrawerBody() {
  const body = document.getElementById("approvalDrawerBody");
  if (!body) return;
  const all = APP_STATE.pendingApprovals || [];
  const pending = all.filter(a => a.status === "pending");
  const executed = all.filter(a => a.status === "executed" && a.rollback_available && a.backup_ref);
  let html = "";
  if (pending.length === 0 && executed.length === 0) {
    html = `<div class="meta-line" style="color:var(--text-muted);">暂无待授权或可回滚的关键操作。合并 / 删代码 / 部署默认先问主人。</div>`;
  }
  html += pending.map(item => `
    <div class="approval-item ${item.risk_level === 'critical' ? 'critical' : ''}">
      <div class="op-line">${item.risk_level === 'critical' ? '关键操作待人工授权' : '待确认操作'} · <code>${escapeHTML(item.op_type)}</code></div>
      <div class="meta-line">${escapeHTML(item.title || '')} → <code>${escapeHTML(item.target || '')}</code></div>
      <div class="meta-line">发起：${escapeHTML(item.requested_by_name || '')}</div>
      ${item.expires_at ? `<div class="timeout-line">超时自动退回（不默认放行）：${escapeHTML(item.expires_at)}</div>` : ''}
      <div class="card-actions-bar">
        <button class="btn btn-success" onclick="handleResolveApproval('${escapeHTML(item.id)}', 'allow_once')">${icon('check')}允许一次</button>
        ${item.risk_level !== 'critical' ? `<button class="btn btn-ghost" onclick="handleResolveApproval('${escapeHTML(item.id)}', 'always_allow')">总是允许低风险</button>` : ''}
        <button class="btn btn-danger" onclick="handleResolveApproval('${escapeHTML(item.id)}', 'deny')">${icon('x')}拒绝</button>
      </div>
    </div>`).join("");
  if (executed.length) {
    html += `<div class="meta-line" style="margin-top:8px;color:var(--text-secondary);font-weight:600;">最近真实执行（可一键回滚到备份）</div>`;
    html += executed.slice(-5).reverse().map(item => `
      <div class="approval-item">
        <div class="op-line"><code>${escapeHTML(item.op_type)}</code> → <code>${escapeHTML(item.target || '')}</code></div>
        <div class="meta-line">备份：<code>${escapeHTML(item.backup_ref)}</code></div>
        <div class="card-actions-bar">
          <button class="btn btn-danger" onclick="handleRollbackCritical('${escapeHTML(item.backup_ref)}', '${escapeHTML(item.workspace_dir || '')}')">${icon('undo')}一键回滚</button>
        </div>
      </div>`).join("");
  }
  body.innerHTML = html;
}

async function handleRollbackCritical(backupRef, workspaceDir) {
  if (!window.confirm(`确认把仓库回滚到备份 ${backupRef}？这是破坏性操作（git reset --hard），仅恢复到受控执行器创建的备份。`)) return;
  try {
    await callOfficeAction("rollbackcriticalop", { backup_ref: backupRef, workspace_dir: workspaceDir || undefined, confirm: true });
    showToast("已回滚到备份 " + backupRef);
    renderApprovalDrawerBody();
  } catch (_) { /* toast 已提示 */ }
}

function recruitWizardGo(delta) {
  const modal = document.getElementById("recruitModal");
  if (!modal) return;
  let step = (APP_STATE.recruitStep || 1) + delta;
  step = Math.max(1, Math.min(3, step));
  APP_STATE.recruitStep = step;
  const pathSwitcher = modal.querySelector(".path-switcher");
  const form = document.getElementById("recruitForm");
  const fieldEls = form ? form.querySelectorAll(".form-grid, .channel-box") : [];
  const specialty = document.getElementById("recSpecialty");
  const specialtyGroup = specialty ? specialty.closest(".form-group") : null;
  const confirm = document.getElementById("recStep3");
  const submit = document.getElementById("recSubmitBtn");
  const prev = document.getElementById("recWizardPrev");
  const next = document.getElementById("recWizardNext");
  if (pathSwitcher) pathSwitcher.style.display = step === 1 ? "" : "none";
  fieldEls.forEach(el => { el.style.display = step === 2 ? "" : "none"; });
  if (specialtyGroup) specialtyGroup.style.display = step === 2 ? "" : "none";
  if (confirm) confirm.classList.toggle("active", step === 3);
  if (submit) submit.style.display = step === 3 ? "" : "none";
  if (prev) prev.style.visibility = step === 1 ? "hidden" : "visible";
  if (next) next.style.display = step === 3 ? "none" : "";
  modal.querySelectorAll("#recWizardSteps .wizard-step").forEach(el => {
    const s = Number(el.dataset.step);
    el.classList.toggle("active", s === step);
    el.classList.toggle("done", s < step);
  });
  if (step === 3) {
    const name = (document.getElementById("recName") || {}).value || "(未填名字)";
    const vendor = (document.getElementById("recVendor") || {}).value || "(未填厂商)";
    const model = (document.getElementById("recModel") || {}).value || "";
    const path = (document.getElementById("recPathInput") || {}).value || "api";
    const floor = (document.getElementById("recFloor") || {}).value || "worker";
    const summary = document.getElementById("recConfirmSummary");
    if (summary) summary.innerHTML = `名字：<strong>${escapeHTML(name)}</strong><br>厂商：${escapeHTML(vendor)} · 模型：${escapeHTML(model)}<br>通道：${escapeHTML(path)} · 楼层：${escapeHTML(floor)}<br><span style="color:var(--text-muted);">API Key 永不落盘，只存环境变量名。</span>`;
  }
}

// =========================================================================
// 头像生成（严守铁律：Muse 是白底圆角方块 + 蓝色手写一笔 M，绝非 Claude 星芒；其他用诚实文字标识）
// =========================================================================
function renderAvatarHTML(agent) {
  const dotClass = agent.status || "ready";
  if (agent.icon_kind === "muse" || agent.id === "muse") {
    return `
      <div class="agent-avatar muse-official-icon" title="Meta Muse (白底圆角方块 + 蓝色手写一笔 M，绝非 Claude)">
        <svg width="24" height="24" viewBox="0 0 32 32" fill="none" aria-label="Muse Logo">
          <path d="M5.5 23.5 C6.8 14.5, 9.2 8.5, 11.2 8.8 C13.0 9.1, 13.6 18.2, 15.6 18.2 C17.6 18.2, 20.2 8.5, 22.4 8.8 C24.4 9.1, 24.8 19.8, 26.8 22.8"
                stroke="#1d4ed8" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        </svg>
        <span class="status-dot ${dotClass}"></span>
      </div>
    `;
  }
  const shortLabel = (agent.vendor || agent.name || "AI").slice(0, 4);
  return `
    <div class="agent-avatar" title="${escapeHTML(agent.brand)} · 诚实文字标识（不凭印象画假Logo）">
      <span>${escapeHTML(shortLabel)}</span>
      <span class="status-dot ${dotClass}"></span>
    </div>
  `;
}

// =========================================================================
// 渲染主函数
// =========================================================================
function renderAll() {
  renderTopBar();
  renderRoster();
  renderHudFlightStrip();
  renderApprovalBanner();
  renderGroupChat();
  renderSelectedAgentProfile();
  renderSelectedTaskThread();
  renderTeamOverview();
  renderSkillCenter();
  neutralizePanels();
}

function renderTopBar() {
  // 自动执行低风险开关（默认关闭；现收纳在「更多」菜单内）
  const autoBtn = document.getElementById("autoExecuteToggleBtn");
  if (autoBtn) {
    const autoOn = Boolean(APP_STATE.settings && APP_STATE.settings.auto_execute_low_risk);
    autoBtn.textContent = autoOn ? "自动执行低风险: 开" : "自动执行低风险: 关";
    autoBtn.className = "btn btn-ghost dropdown-item " + (autoOn ? "btn-safety-on" : "btn-safety-off");
  }

  // 厂商条
  const vendors = [...new Set(APP_STATE.agents.map(a => `${a.vendor}`))];
  const strip = document.getElementById("vendorStrip");
  if (strip) strip.innerHTML = `<span style="font-size:10px;color:var(--text-muted);">独立厂商池 (${vendors.length}家，各走各号)：</span>` +
    vendors.map(v => `<span class="vendor-chip">${escapeHTML(v)}</span>`).join("");

  // 顶部进度条 + 统计
  const s = APP_STATE.taskSummary;
  document.getElementById("statClaimed").textContent = `${s.claimed}/${s.total}`;
  document.getElementById("statReported").textContent = `${s.reported}/${s.total}`;
  document.getElementById("statDelivered").textContent = `${s.delivered}`;
  document.getElementById("statAccepted").textContent = `${s.accepted}`;
  const fill = document.getElementById("topProgressFill");
  if (fill) {
    const pct = s.total > 0 ? Math.round((Number(s.accepted) / Number(s.total)) * 100) : 0;
    fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  }

  // 低额度告警 (≤10%)
  const lowAgents = APP_STATE.agents.filter(a => a.quota_percent !== null && a.quota_percent !== undefined && Number(a.quota_percent) <= 10);
  const lowEl = document.getElementById("statLowQuota");
  if (lowAgents.length > 0) {
    lowEl.classList.remove("hidden");
    lowEl.textContent = `低额度告警 (≤10%): ` + lowAgents.map(a => `${a.name} (${a.quota_percent}%)`).join(", ");
    lowEl.onclick = () => selectAgent(lowAgents[0].id);
  } else {
    lowEl.classList.add("hidden");
  }

  // 审批徽章计数
  const badge = document.getElementById("approvalBadgeCount");
  if (badge) {
    const n = (APP_STATE.pendingApprovals || []).filter(a => a.status === "pending").length;
    badge.textContent = String(n);
    badge.classList.toggle("hidden", n === 0);
  }
}

function renderRoster() {
  const q = (document.getElementById("agentSearchInput").value || "").trim().toLowerCase();
  const filtered = APP_STATE.agents.filter(a => {
    if (!q) return true;
    return [a.name, a.vendor, a.model, a.badge, a.specialty].join(" ").toLowerCase().includes(q);
  });

  const floors = { manager: [], worker: [], rest: [] };
  filtered.forEach(a => {
    (floors[a.floor] || floors.worker).push(a);
  });

  document.getElementById("countManager").textContent = floors.manager.length;
  document.getElementById("countWorker").textContent = floors.worker.length;
  document.getElementById("countRest").textContent = floors.rest.length;
  document.getElementById("rosterTotalBadge").textContent = `${APP_STATE.agents.length} 模型/通道`;

  const emptyHint = {
    manager: `<div style="font-size:11px;color:var(--text-muted);padding:6px;">暂无经理，可招募强推理模型或拖入此层</div>`,
    worker: `<div style="font-size:11px;color:var(--text-muted);padding:8px;border:1px dashed var(--border-strong);border-radius:6px;">暂无 1楼员工。点左下角「招募」接入你的免费模型，或点顶部「更多 → 载入示例团队」</div>`,
    rest: `<div style="font-size:11px;color:var(--text-muted);padding:6px;">暂无休息成员</div>`,
  };

  ["manager", "worker", "rest"].forEach(fl => {
    const container = document.getElementById(
      fl === "manager" ? "listManager" : fl === "worker" ? "listWorker" : "listRest"
    );
    container.innerHTML = floors[fl].length
      ? floors[fl].map(agent => renderAgentCardHTML(agent)).join("")
      : emptyHint[fl];
  });

  // 动态同步发言下拉框、@人按钮、技能中心裁判选择
  const senderSel = document.getElementById("groupSenderSelect");
  if (senderSel) {
    const prev = senderSel.value;
    const managers = APP_STATE.agents.filter(a => a.floor === "manager");
    senderSel.innerHTML = `<option value="owner">你 (董事长)</option>` +
      managers.map(m => `<option value="${m.id}">${escapeHTML(m.name)}</option>`).join("");
    if ([...senderSel.options].some(o => o.value === prev)) senderSel.value = prev;
  }

  const mentionBar = document.getElementById("quickMentionBar");
  if (mentionBar) {
    const workers = APP_STATE.agents.filter(a => a.floor === "worker");
    mentionBar.innerHTML = workers.length
      ? `<span class="mention-tip">点此 @人派活：</span>` +
        workers.slice(0, 6).map(w => `<button type="button" class="chip-btn" onclick="insertMention('@${escapeHTML(w.name)}')">@${escapeHTML(w.name)}</button>`).join("")
      : `<span class="mention-tip">招募 1楼员工后可在此快捷 @人派活</span>`;
  }

  const judgeSel = document.getElementById("skillJudgeSelect");
  if (judgeSel) {
    const prevJ = judgeSel.value;
    const managers = APP_STATE.agents.filter(a => a.floor === "manager");
    judgeSel.innerHTML = managers.map(m => `<option value="${m.id}">${escapeHTML(m.name)}</option>`).join("") || `<option value="chief">总管 (默认裁判)</option>`;
    if ([...judgeSel.options].some(o => o.value === prevJ)) judgeSel.value = prevJ;
  }
}

function renderAgentCardHTML(agent) {
  const isSelected = agent.id === APP_STATE.selectedAgentId ? "selected" : "";
  const hasPct = agent.quota_percent !== null && agent.quota_percent !== undefined;
  const pct = hasPct ? Number(agent.quota_percent) : null;
  // 对齐 Agent HUD：已用<70%(剩>30%)绿、已用70%-90%(剩11-30%)黄、剩<=10%变红闪烁
  const isLow = hasPct && pct <= 10;
  const isWarn = hasPct && pct > 10 && pct <= 30;
  const fillClass = !hasPct ? "unknown" : isLow ? "low-red" : isWarn ? "quota-yellow" : "quota-green";
  const labelText = !hasPct ? "额度未填" : `剩 ${pct}%`;
  const widthPct = !hasPct ? 100 : Math.max(4, pct);
  const tokensUsed = Number(agent.tokens_used || 0);
  const sessCount = Number(agent.session_count || 0);
  const hoverTelemetry = `剩余额度: ${hasPct ? pct + '%' : '额度未填'} | Token花费: ${tokensUsed} | 会话数: ${sessCount} | ${agent.quota_note || ''}`;

  const toolsHTML = (agent.attached_tools || []).map(t =>
    `<div class="tool-attachment-pill">${escapeHTML(t)}</div>`
  ).join("");

  const loginState = agent.login_state || "";
  const loginCls = loginState === "已登录" ? "ok" : (loginState === "会话过期" ? "expired" : "");
  const loginBadge = loginState ? `<span class="login-badge ${loginCls}" title="登录态（不显示任何密钥明文）">${escapeHTML(loginState)}</span>` : "";

  return `
    <div class="agent-card ${isSelected}" draggable="true"
         ondragstart="onAgentDragStart(event, '${agent.id}')"
         onclick="selectAgent('${agent.id}')"
         title="${escapeHTML(hoverTelemetry)}">
      <div class="agent-row-top">
        ${renderAvatarHTML(agent)}
        <div class="agent-meta">
          <div class="agent-name-line">
            <span class="agent-name">${escapeHTML(agent.name)}</span>
            <span class="access-badge ${agent.badge_color || 'green'}">${escapeHTML(agent.badge)}</span>
            ${loginBadge}
            <button type="button" class="card-expand-btn" title="展开/收起详情" onclick="event.stopPropagation(); this.closest('.agent-card').classList.toggle('expanded')">${icon('eye')}</button>
          </div>
          <div class="agent-extra-info">
            <div class="agent-subline">
              模型: <strong>${escapeHTML(agent.model)}</strong> · ${escapeHTML(agent.vendor)}
            </div>
            ${(agent.tier || agent.expires_at) ? `
            <div class="agent-subline" style="color:#a5b4fc;">
              ${agent.tier ? `等级: <strong>${escapeHTML(agent.tier)}</strong>` : ''}${agent.tier && agent.expires_at ? ' · ' : ''}${agent.expires_at ? `到期: ${escapeHTML(agent.expires_at)}` : ''}
            </div>` : ''}
            <div class="agent-fallback-line" title="${escapeHTML(agent.fallback_note || '')}">
              ↳ ${escapeHTML(agent.fallback_note || '降级后：换其他免费员工')}
            </div>
            ${toolsHTML}
          </div>
        </div>
      </div>
      <div class="mana-bar-wrap" onclick="handleManaBarClick(event, '${agent.id}')"
           title="${escapeHTML(hoverTelemetry)}${agent.usage_url ? '（点击跳转官方实时查额度页）' : '（无独立查额度链接）'}">
        <div class="mana-track">
          <div class="mana-fill ${fillClass}" style="width:${widthPct}%"></div>
        </div>
        <span class="mana-label ${fillClass}">${labelText} ${agent.usage_url ? '↗' : ''}</span>
      </div>
      <div class="agent-telemetry-line">
        <span>Token: ${tokensUsed}</span>
        <span>会话: ${sessCount}</span>
      </div>
    </div>
  `;
}

function handleManaBarClick(event, agentId) {
  event.stopPropagation();
  const agent = APP_STATE.agents.find(a => a.id === agentId);
  if (!agent) return;
  selectAgent(agentId);
  if (agent.usage_url) {
    window.open(agent.usage_url, "_blank", "noopener");
    showToast(`🔗 已打开 ${agent.name} 官方实时查额度页: ${agent.usage_url}`);
  } else {
    showToast(`ℹ️ ${agent.name} 无独立查额度链接（遵循不编造链接规则）`);
  }
}

// =========================================================================
// 拖放换岗 (2楼经理 <-> 1楼员工 <-> 院子休息)
// =========================================================================
let draggedAgentId = null;

function onAgentDragStart(event, agentId) {
  draggedAgentId = agentId;
  event.dataTransfer.setData("text/plain", agentId);
}

function onFloorDragOver(event) {
  event.preventDefault();
  event.currentTarget.classList.add("drag-over");
}

function onFloorDragLeave(event) {
  event.currentTarget.classList.remove("drag-over");
}

async function onFloorDrop(event, targetFloor) {
  event.preventDefault();
  event.currentTarget.classList.remove("drag-over");
  const agentId = draggedAgentId || event.dataTransfer.getData("text/plain");
  if (!agentId) return;
  await callOfficeAction("moveagent", { id: agentId, floor: targetFloor });
  showToast(`🔄 已将成员调动至 ${targetFloor === 'manager' ? '2楼经理层' : targetFloor === 'worker' ? '1楼员工层' : '院子休息'}`);
}

// =========================================================================
// 中栏：全员大群聊 + 任务卡片
// =========================================================================
function formatChatTextWithMentions(text) {
  const safe = escapeHTML(text || "");
  return safe
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/@([^\s:：,，。！\n]+)/g, '<span class="mention-highlight">@$1</span>');
}

function renderHudFlightStrip() {
  const strip = document.getElementById("hudFlightStrip");
  if (!strip) return;
  const flights = (APP_STATE.hudFlights || []).slice(-6).reverse();
  if (flights.length === 0) {
    strip.innerHTML = `<span class="hud-flight-label">HUD 飞线：</span><span style="font-size:11px;color:var(--text-muted);">等待派单或汇报飞线（谁发给谁 · 卡在哪一步）</span>`;
    return;
  }
  // 收集唯一节点（按出现顺序），横向布局画弧线节点图
  const nodes = [];
  const nodeIndex = (id, name) => {
    let i = nodes.findIndex(n => n.id === id);
    if (i < 0) { nodes.push({ id, name }); i = nodes.length - 1; }
    return i;
  };
  const edges = flights.map(fl => {
    const blocked = fl.status === "blocked" || /blocked|卡住|超时|退回/.test(fl.channel || "") || fl.kind === "bus_error";
    return { from: nodeIndex(fl.from_id, fl.from_name), to: nodeIndex(fl.to_id, fl.to_name), fl, blocked };
  });
  const gap = 130, padX = 46, baseY = 78, W = padX * 2 + gap * Math.max(1, nodes.length - 1), H = 110;
  const x = i => padX + i * gap;
  let arcs = "";
  edges.forEach((e, idx) => {
    const x1 = x(e.from), x2 = x(e.to);
    const mx = (x1 + x2) / 2, lift = 26 + (idx % 3) * 12;
    const cy = baseY - lift;
    const dropY = e.blocked ? baseY - 6 : cy + 6;
    const onclick = e.fl.task_id ? `openTaskPrivateThread('${escapeHTML(e.fl.task_id)}')` : `selectAgent('${escapeHTML(e.fl.from_id)}')`;
    const title = `${escapeHTML(e.fl.created_at || '')} · ${escapeHTML(e.fl.channel || '')} · ${escapeHTML(e.fl.summary || e.fl.kind || '')}`;
    arcs += `
      <g onclick="${onclick}" style="cursor:pointer">
        <title>${title}</title>
        <path class="arc ${e.blocked ? 'blocked' : ''}" d="M ${x1} ${baseY} Q ${mx} ${cy} ${x2} ${baseY}"/>
        <path class="plane ${e.blocked ? 'blocked' : ''}" d="M ${mx - 5} ${dropY} l 10 3 l -10 3 l 2.5 -3 z"/>
        <text class="node-label" x="${mx}" y="${cy - 2}" text-anchor="middle">${escapeHTML((e.fl.summary || e.fl.kind || '').slice(0, 10))}</text>
      </g>`;
  });
  const nodeSvg = nodes.map((n, i) => `
    <g onclick="selectAgent('${escapeHTML(n.id)}')" style="cursor:pointer">
      <circle class="node-circle" cx="${x(i)}" cy="${baseY}" r="6"/>
      <text class="node-label" x="${x(i)}" y="${baseY + 20}" text-anchor="middle">${escapeHTML((n.name || '').slice(0, 8))}</text>
    </g>`).join("");
  strip.innerHTML = `<span class="hud-flight-label">HUD 飞线 (${flights.length})：</span>
    <div class="flight-svg-wrap"><svg class="flight-svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${arcs}${nodeSvg}</svg></div>`;
}

function renderApprovalBanner() {
  // §六：审批条改为右上角徽章 + 抽屉。内联 banner 隐藏，计数与抽屉内容在此更新。
  const banner = document.getElementById("approvalBanner");
  if (banner) { banner.classList.add("hidden"); banner.innerHTML = ""; }
  const badge = document.getElementById("approvalBadgeCount");
  const pending = (APP_STATE.pendingApprovals || []).filter(a => a.status === "pending");
  if (badge) {
    badge.textContent = String(pending.length);
    badge.classList.toggle("hidden", pending.length === 0);
  }
  const drawer = document.getElementById("approvalDrawer");
  if (drawer && drawer.classList.contains("open")) renderApprovalDrawerBody();
}

function renderTaskStepFlow(status, task = null) {
  const needReview = Boolean(task && task.requires_code_review);
  const order = needReview
    ? ["assigned", "accepted", "working", "in_review", "delivered", "accepted_done"]
    : ["assigned", "accepted", "working", "delivered", "accepted_done"];
  const labels = needReview
    ? [
        { key: "assigned", text: "1.派单" },
        { key: "accepted", text: "2.接单" },
        { key: "working", text: "3.写代码" },
        { key: "in_review", text: "4.独立审查" },
        { key: "delivered", text: "5.交付" },
        { key: "accepted_done", text: "6.验收" },
      ]
    : [
        { key: "assigned", text: "1.派单" },
        { key: "accepted", text: "2.接单" },
        { key: "working", text: "3.进行中" },
        { key: "delivered", text: "4.交付" },
        { key: "accepted_done", text: "5.验收" },
      ];
  const currIdx = status === "rejected" ? 2 : order.indexOf(status);
  return `<div class="step-flow-bar">` + labels.map((st, idx) => {
    const cls = idx < currIdx ? "done" : idx === currIdx ? "curr" : "";
    return `<span class="step-item ${cls}">${st.text}</span>`;
  }).join("<span>→</span>") + (status === "rejected" ? ` <span style="color:#f87171;font-weight:700;">(↩审查打回重做)</span>` : "") + `</div>`;
}

function renderDiscussionThread(taskId) {
  const discs = (APP_STATE.discussions || []).filter(d => d.task_id === taskId);
  if (discs.length === 0) return "";
  return discs.map(d => {
    const msgs = (d.messages || []).map(m => `
      <div class="discussion-msg"><span class="who">${escapeHTML(m.sender_name || m.sender_id || '')}</span>：${escapeHTML(stripEmoji(m.text || ''))}</div>
    `).join("") || `<div class="discussion-msg" style="color:var(--text-muted);">暂无发言（需真实模型调用，不伪造讨论）。</div>`;
    const status = d.status === "closed" ? `已收敛${d.adopted ? ' · 采纳：' + escapeHTML(d.adopted) : ''}` : "进行中";
    return `<details class="discussion-thread">
      <summary>${icon('chat')} 经理讨论 · ${escapeHTML(d.topic || '')}（${(d.messages || []).length} 条 · ${status}）</summary>
      ${msgs}
      ${d.circuit_breaker ? `<div class="discussion-msg" style="color:var(--quota-yellow);">熔断：${escapeHTML(d.circuit_breaker)}</div>` : ''}
    </details>`;
  }).join("");
}

function renderGroupChat() {
  // 顶部快速切换任务条
  const strip = document.getElementById("activeTaskStrip");
  if (APP_STATE.tasks.length === 0) {
    strip.innerHTML = `<span style="font-size:11px;color:var(--text-muted);">当前暂无派单，可在右上角「更多 → 塞入示例任务」测试完整流程</span>`;
  } else {
    strip.innerHTML = APP_STATE.tasks.map(t => `
      <button class="task-pill ${t.id === APP_STATE.selectedTaskId ? 'active' : ''}"
              onclick="openTaskPrivateThread('${t.id}')">
        ${escapeHTML(t.id)} · ${escapeHTML(t.title.slice(0, 14))} (${escapeHTML(t.status)})
      </button>
    `).join("");
  }

  const stream = document.getElementById("groupChatStream");
  stream.innerHTML = APP_STATE.groupMessages.map(msg => {
    const isGao = msg.sender_id === "owner" || msg.sender_id === "gao";
    const task = msg.task_id ? APP_STATE.tasks.find(t => t.id === msg.task_id) : null;
    let actionBarHTML = "";
    let discussionHTML = "";

    if (task && msg.kind === "task_card") {
      discussionHTML = renderDiscussionThread(task.id);
      actionBarHTML = `
        <div class="card-actions-bar">
          ${renderTaskStepFlow(task.status, task)}
          ${task.status === "assigned" ? `
            <button class="btn btn-example" onclick="handleClaimTask('${task.id}', '${task.assigned_to || ''}')">
              员工点击领取 (${escapeHTML(task.assigned_name)})
            </button>
          ` : ""}
          <button class="btn btn-ghost" onclick="openTaskPrivateThread('${task.id}')">
            ${icon('lock')}私聊汇报窗 (${task.worker_reported ? '已汇报' : '待汇报'})
          </button>
          ${task.status !== "accepted_done" ? `
            <button class="btn btn-primary" onclick="handleDeliverFinalResult('${task.id}')">
              ${icon('box')}经理统筹交付总结果
            </button>
          ` : ""}
        </div>
      `;
    } else if (task && msg.kind === "private_report_lock") {
      actionBarHTML = `
        <div class="card-actions-bar">
          <button class="btn btn-ghost" onclick="openTaskPrivateThread('${task.id}')">
            ${icon('eye')}经理点此审阅结论/diff
          </button>
          <button class="btn btn-primary" onclick="handleDeliverFinalResult('${task.id}')">
            ${icon('box')}经理统筹交付给 Gao
          </button>
        </div>
      `;
    } else if (task && msg.kind === "big_task_card") {
      discussionHTML = renderDiscussionThread(task.id);
      actionBarHTML = `
        <div class="card-actions-bar">
          <button class="btn btn-ghost" onclick="handleRunBigTaskSubtasks('${task.id}', false)">
            批量干跑全部子单 (0消耗)
          </button>
          <button class="btn btn-primary" onclick="handleRunBigTaskSubtasks('${task.id}', true)">
            ${icon('send')}并行真调 API/CLI 子单
          </button>
          <button class="btn btn-ghost" onclick="handleAggregateBigTask('${task.id}')">
            ${icon('box')}汇总全部子单总交付
          </button>
          <button class="btn btn-ghost" onclick="openTaskPrivateThread('${task.id}')">
            ${icon('eye')}查看子单进度 (${(task.subtask_ids || []).length})
          </button>
        </div>
      `;
    } else if (task && msg.kind === "final_delivery_card") {
      discussionHTML = renderDiscussionThread(task.id);
      actionBarHTML = `
        <div class="card-actions-bar">
          ${renderTaskStepFlow(task.status, task)}
          <button class="btn btn-success" onclick="handleReviewFinalResult('${task.id}', 'verified')">
            ${icon('check')}验收通过
          </button>
          <button class="btn btn-danger" onclick="handleReviewFinalResult('${task.id}', 'rejected')">
            ${icon('undo')}打回重做
          </button>
        </div>
      `;
    }

    return `
      <div class="chat-bubble ${isGao ? 'from-gao' : ''} kind-${msg.kind || 'chat'}">
        <div class="bubble-header">
          <span class="bubble-sender">${escapeHTML(stripEmoji(msg.sender_name))}</span>
          <span>${escapeHTML(msg.created_at || '')}</span>
        </div>
        <div class="bubble-body">${formatChatTextWithMentions(stripEmoji(msg.text))}</div>
        ${discussionHTML}
        ${actionBarHTML}
      </div>
    `;
  }).join("");

  stream.scrollTop = stream.scrollHeight;
}

// =========================================================================
// 右栏 Tab 1：成员独立身份档案 (Profile)
// =========================================================================
function selectAgent(agentId) {
  APP_STATE.selectedAgentId = agentId;
  switchRightTab("profile");
  renderRoster();
  renderSelectedAgentProfile();
}

function renderSelectedAgentProfile() {
  const agent = APP_STATE.agents.find(a => a.id === APP_STATE.selectedAgentId) || APP_STATE.agents[0];
  if (!agent) return;
  const container = document.getElementById("agentProfileContent");
  const hasPct = agent.quota_percent !== null && agent.quota_percent !== undefined;
  const pct = hasPct ? Number(agent.quota_percent) : null;
  const isLow = hasPct && pct <= 10;

  const skillBadges = (agent.skills || []).map(slug => {
    const sk = APP_STATE.skills.find(s => s.slug === slug);
    return `<span class="vendor-chip">${escapeHTML(sk ? sk.name : slug)}</span>`;
  }).join(" ") || `<span style="color:#64748b;font-size:11px;">暂未装配固定技能</span>`;

  container.innerHTML = `
    <div class="profile-box">
      <div class="identity-block">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
          ${renderAvatarHTML(agent)}
          <div>
            <div style="font-size:15px;font-weight:800;">${escapeHTML(agent.name)}</div>
            <div style="font-size:11px;color:#94a3b8;">${escapeHTML(agent.role_label)} · <span class="access-badge ${agent.badge_color}">${escapeHTML(agent.badge)}</span></div>
          </div>
        </div>
        <h4>🪪 独立身份（一图标一模型 · 绝非共用 Token 池）</h4>
        <div class="kv-row"><span>所属厂商</span><span><strong>${escapeHTML(agent.vendor)}</strong> (${escapeHTML(agent.brand)})</span></div>
        <div class="kv-row"><span>会员等级</span><span><strong>${escapeHTML(agent.tier || (agent.access_kind === 'api' ? (agent.paid ? '付费·API' : '免费·API') : '待同步'))}</strong></span></div>
        <div class="kv-row"><span>到期时间</span><span>${escapeHTML(agent.expires_at || (agent.access_kind === 'api' ? '按余额消耗无固定到期日' : '未填/待同步'))}</span></div>
        <div class="kv-row"><span>真实模型版本</span><span><code>${escapeHTML(agent.model)}</code> ${agent.verified_version ? '✅已核实' : '⚠️待核实'}</span></div>
        ${(agent.available_models && agent.available_models.length) ? `<div class="kv-row"><span>接口实查可用模型</span><span><code>${escapeHTML(agent.available_models.join(', '))}</code></span></div>` : ''}
        ${(agent.sub_models && agent.sub_models.length) ? `<div class="kv-row"><span>内置子模型与倍率</span><span>${agent.sub_models.map(m => `<span class="vendor-chip">${escapeHTML(m)}</span>`).join(' ')}</span></div>` : ''}
        ${agent.last_synced_at ? `<div class="kv-row"><span>上次同步时间</span><span>${escapeHTML(agent.last_synced_at)}</span></div>` : ''}
        <div class="kv-row"><span>接入通道</span><span>${escapeHTML(agent.access_kind)} (${escapeHTML(agent.badge)})</span></div>
        <div class="kv-row"><span>降级规则</span><span style="color:#93c5fd;">${escapeHTML(agent.fallback_note || '未指定')}</span></div>
        <div class="kv-row"><span>账号核实状态</span><span>${escapeHTML(agent.account_status)}</span></div>
        ${agent.key_env ? `<div class="kv-row"><span>环境变量名</span><span><code>$${escapeHTML(agent.key_env)}</code>（密钥不落盘）</span></div>` : ""}
        ${agent.login_url ? `<div class="kv-row"><span>厂商登录页</span><span><a href="${escapeHTML(agent.login_url)}" target="_blank" style="color:#38bdf8;">点此去官网登录 ↗</a></span></div>` : ""}
      </div>

      ${isLow ? `
        <div class="security-banner" style="background:rgba(239,68,68,0.2);border-color:#ef4444;color:#fca5a5;">
          🚨 <strong>低额度红色告警 (≤10%)：</strong>当前剩余额度为 <strong>${pct}%</strong>！
          ${agent.access_kind === 'subscription' ? '订阅制到限额将自动降级为轻量模型，请只派边角小活。' : 'API 额度归零已真停，请移至院子休息并轮换其他免费员工。'}
        </div>
      ` : ""}

      <div class="identity-block">
        <h4>💧 真实法力值额度（查不到一律写「额度未填」，绝不编数字）</h4>
        <div style="font-size:12px;margin-bottom:6px;">
          当前显示：<strong>${hasPct ? `剩 ${pct}%` : '额度未填'}</strong>
        </div>
        <div style="font-size:11px;color:#94a3b8;margin-bottom:8px;">
          说明：${escapeHTML(agent.quota_note || '暂无说明')}
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
          ${agent.usage_url ? `
            <a class="btn btn-primary" href="${escapeHTML(agent.usage_url)}" target="_blank" rel="noopener" style="text-decoration:none;">
              🔗 跳该账号实时查额度页 ↗
            </a>
          ` : `
            <span class="vendor-chip">无独立查额度链接（遵循不编造原则）</span>
          `}
          ${agent.access_kind === 'api' ? `
            <button class="btn btn-ghost" onclick="handleCheckLiveQuota('${agent.id}')">🔌 调接口实查余额</button>
          ` : ""}
        </div>
        <div style="border-top:1px dashed #334155;padding-top:8px;margin-top:6px;">
          <label style="font-size:11px;color:#cbd5e1;display:block;margin-bottom:4px;">去官网查完后手动登记真实百分比（留空=恢复「额度未填」）：</label>
          <div style="display:flex;gap:6px;">
            <input type="number" id="manualQuotaPct" min="0" max="100" step="1" placeholder="0-100 或留空"
                   value="${hasPct ? pct : ''}" style="width:110px;background:#0f172a;border:1px solid #334155;color:#fff;padding:4px 6px;border-radius:4px;font-size:12px;" />
            <button class="btn btn-ghost" onclick="handleUpdateManualQuota('${agent.id}')">保存实查值</button>
            <button class="btn btn-ghost" onclick="handleClearManualQuota('${agent.id}')">标为额度未填</button>
          </div>
        </div>
      </div>

      <div class="identity-block">
        <h4>🛠️ 擅长与已装备技能</h4>
        <div style="font-size:12px;color:#cbd5e1;margin-bottom:6px;">特长：${escapeHTML(agent.specialty)}</div>
        <div style="display:flex;gap:4px;flex-wrap:wrap;">${skillBadges}</div>
      </div>

      <div class="identity-block">
        <h4>🔄 楼层调岗（也可直接拖拽左侧图标）</h4>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <button class="btn btn-ghost" onclick="callOfficeAction('moveagent', {id:'${agent.id}', floor:'manager'})">🏢 调至 2楼经理</button>
          <button class="btn btn-ghost" onclick="callOfficeAction('moveagent', {id:'${agent.id}', floor:'worker'})">🛠️ 调至 1楼员工</button>
          <button class="btn btn-ghost" onclick="callOfficeAction('moveagent', {id:'${agent.id}', floor:'rest'})">🌿 调至 院子休息</button>
        </div>
      </div>
    </div>
  `;
}

async function handleUpdateManualQuota(agentId) {
  const raw = document.getElementById("manualQuotaPct").value;
  const val = raw === "" ? null : Number(raw);
  await callOfficeAction("setagentquota", {
    id: agentId,
    percent_remaining: val,
    note: val === null ? "额度未填（未实查）" : `人工实查登记剩余 ${val}%`,
  });
  showToast("✅ 已更新实查额度状态");
}

async function handleClearManualQuota(agentId) {
  await callOfficeAction("setagentquota", {
    id: agentId,
    percent_remaining: null,
    note: "额度未填（查不到绝不编数字）",
  });
  showToast("✅ 已重置为「额度未填」");
}

async function handleCheckLiveQuota(agentId) {
  const res = await callOfficeAction("checklivequota", { id: agentId });
  if (res && res.checked) {
    const modelsMsg = (res.checked.available_models && res.checked.available_models.length)
      ? `｜可用模型: ${res.checked.available_models.slice(0, 4).join(", ")}`
      : "";
    showToast(`📊 实查结果: ${res.checked.note}${modelsMsg}`);
  }
}

async function handleSyncProfiles() {
  const res = await callOfficeAction("syncprofiles");
  if (res) {
    showToast(`🔄 已完成全队资料与可用接口同步（共检查 ${res.count} 个成员，时间 ${res.synced_at}）`);
  }
}

// =========================================================================
// 右栏 Tab 2：任务私聊汇报窗 (Private Thread + 跨厂商转交 + 干跑/真跑)
// =========================================================================
async function openTaskPrivateThread(taskId) {
  APP_STATE.selectedTaskId = taskId;
  switchRightTab("thread");
  if (APP_STATE.backendOnline) {
    const msgs = await callOfficeAction("listmessages", { task_id: taskId });
    APP_STATE.taskMessages[taskId] = msgs;
  }
  renderGroupChat();
  renderSelectedTaskThread();
}

function renderSelectedTaskThread() {
  const container = document.getElementById("taskThreadContent");
  const badge = document.getElementById("threadTaskBadge");
  const task = APP_STATE.tasks.find(t => t.id === APP_STATE.selectedTaskId) || APP_STATE.tasks[0];
  if (!task) {
    badge.textContent = "";
    container.innerHTML = `
      <div class="identity-block">
        <h4>🔒 任务私聊汇报窗</h4>
        <p style="font-size:12px;color:#94a3b8;line-height:1.5;">
          当前还没有选中的任务。点击顶部 <strong>「🧪 一键塞入通用示例任务」</strong>，员工领单后即可在此处<strong>单独私聊汇报给经理</strong>（群里只留一条 🔒 提示，正文不刷屏，省经理 Token）。
        </p>
      </div>
    `;
    return;
  }

  APP_STATE.selectedTaskId = task.id;
  badge.textContent = `(${task.id})`;
  const msgs = APP_STATE.taskMessages[task.id] || [];

  // 可转交的其他厂商员工列表（页面上直观标注同厂商拦截）
  const workers = APP_STATE.agents.filter(a => a.floor === "worker" && a.status !== "exhausted");
  const transferOptions = workers.map(w => {
    const sameVendor = task.assigned_vendor && w.vendor.toLowerCase() === task.assigned_vendor.toLowerCase();
    return `<option value="${w.id}">${escapeHTML(w.name)} (${escapeHTML(w.vendor)} · ${escapeHTML(w.badge)})${sameVendor ? ' [同厂商将拦截]' : ' [可跨厂商轮换]'}</option>`;
  }).join("");

  const draft = APP_STATE.reportDrafts[task.id] || {};
  const reviewerCandidates = APP_STATE.agents.filter(
    a => a.floor !== "rest" && a.status !== "exhausted" && a.id !== task.assigned_to
  );
  const reviewerOptions = reviewerCandidates.map(r =>
    `<option value="${r.id}" ${r.id === task.reviewer_id ? 'selected' : ''}>${escapeHTML(r.name)} (${escapeHTML(r.badge)})</option>`
  ).join("");
  const reviewIssues = task.review_issues || [];
  const childSubtasks = (task.subtask_ids || [])
    .map(sid => APP_STATE.tasks.find(t => t.id === sid))
    .filter(Boolean);

  container.innerHTML = `
    <div class="profile-box">
      <div class="identity-block">
        <h4>🔒 私聊专线：${escapeHTML(task.assigned_name)} ⇄ 经理 ${escapeHTML(task.manager_name)}</h4>
        <div style="font-size:12px;font-weight:700;margin-bottom:4px;">${escapeHTML(task.id)} · ${escapeHTML(task.title)}</div>
        ${renderTaskStepFlow(task.status, task)}
        <div style="font-size:11px;color:var(--text-secondary);margin-top:6px;">
          • <strong>当前执行员工</strong>：${escapeHTML(task.assigned_name)}（厂商：${escapeHTML(task.assigned_vendor || '待认领')}）<br/>
          • <strong>A message, not the conversation</strong>：汇报只传【结论 / 改动文件 / 测试结果】，不传全对话记录。
        </div>
      </div>

      ${task.is_parent ? `
      <div class="identity-block">
        <h4>🧩 大任务子单进度看板 (${childSubtasks.length} 张子单)</h4>
        <div style="display:flex;flex-direction:column;gap:5px;margin-bottom:8px;">
          ${childSubtasks.map(sub => `
            <button type="button" class="btn btn-ghost" style="justify-content:space-between;width:100%;" onclick="openTaskPrivateThread('${sub.id}')">
              <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHTML(sub.id)} · ${escapeHTML(sub.title)}</span>
              <span class="access-badge ${sub.review_status === 'approved' || sub.status === 'delivered' ? 'green' : sub.status === 'rejected' ? 'red' : 'orange'}">${escapeHTML(sub.requires_code_review ? (sub.review_status || sub.status) : sub.status)}</span>
            </button>
          `).join("")}
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <button type="button" class="btn btn-ghost btn-xs" onclick="handleRunBigTaskSubtasks('${task.id}', false)">🧪 批量干跑子单</button>
          <button type="button" class="btn btn-primary btn-xs" onclick="handleRunBigTaskSubtasks('${task.id}', true)">🚀 并行真调 API/CLI</button>
          <button type="button" class="btn btn-ghost btn-xs" onclick="handleAggregateBigTask('${task.id}')">📦 汇总总交付</button>
        </div>
      </div>
      ` : ""}

      ${task.requires_code_review ? `
      <div class="identity-block">
        <h4>🔍 写—审—改闭环（改代码任务专属 · 写手与审查必须分开）</h4>
        <div style="font-size:11px;color:var(--text-secondary);margin-bottom:6px;">
          写代码：<strong>${escapeHTML(task.assigned_name)}</strong> → 独立审查：<strong>${escapeHTML(task.reviewer_name || '待指定')}</strong>
          · 状态：<span class="access-badge ${task.review_status === 'approved' ? 'green' : task.review_status === 'changes_requested' ? 'red' : 'orange'}">${escapeHTML(task.review_status || 'pending_review')}</span>
          ${task.revision_round ? ` · 已返修 ${task.revision_round} 轮` : ''}
        </div>
        ${reviewIssues.length > 0 ? `
          <div class="review-checklist-box">
            <div style="font-weight:700;margin-bottom:4px;color:#fca5a5;">当前待修改问题清单：</div>
            ${reviewIssues.map((it, idx) => `<div class="review-issue-item">${idx + 1}. ${escapeHTML(it)}</div>`).join("")}
          </div>
        ` : ""}
        <div style="display:flex;gap:6px;margin-bottom:6px;align-items:center;">
          <select id="reviewAgentSelect" class="select-sm" style="flex:1;">${reviewerOptions}</select>
        </div>
        <textarea id="reviewIssuesInput" rows="2" class="obsidian-input" placeholder="审查只写问题清单（每行一条：文件:行号 问题描述）；点下方「通过」则无需填问题" style="margin-bottom:6px;"></textarea>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <button type="button" class="btn btn-ghost btn-xs" onclick="handleAutoCodeReview('${task.id}', false)">🤖 自动读 diff 审查 (干跑)</button>
          <button type="button" class="btn btn-primary btn-xs" onclick="handleAutoCodeReview('${task.id}', true)">🚀 真调审查者读 diff</button>
          <button type="button" class="btn btn-success btn-xs" onclick="handleSubmitCodeReview('${task.id}', true, false)">✅ 手动审查通过</button>
          <button type="button" class="btn btn-danger btn-xs" onclick="handleSubmitCodeReview('${task.id}', false, true)">↩ 打回重做 (问题清单)</button>
        </div>
      </div>
      ` : ""}

      <!-- 快捷操作栏：4种调用方法 + 结论-only 汇报模板 + 关键操作门禁 -->
      <div class="identity-block">
        <h4>⚡ 员工执行与结论-only 汇报</h4>
        <div style="margin-bottom:8px;">
          <label style="font-size:11px;color:var(--text-secondary);display:block;margin-bottom:3px;">
            📁 目标工作文件夹路径（选填，供 CLI 执行或给 WorkBuddy 导出 .md 工单用）：
          </label>
          <input type="text" id="customWorkspaceInput" class="obsidian-input"
                 placeholder="例：C:\\Users\\你的用户名\\Desktop\\my-project（留空默认本仓库）"
                 value="${escapeHTML(APP_STATE.customWorkspaceDir || '')}"
                 oninput="APP_STATE.customWorkspaceDir = this.value.trim()" />
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
          <button class="btn btn-ghost" onclick="handleRunAdapterTask('${task.id}', false)" title="不花钱演练路由与降级链">
            🧪 干跑演练 (0消耗)
          </button>
          <button class="btn btn-primary" onclick="handleRunAdapterTask('${task.id}', true)" title="调用真实 API（读环境变量 Key）或本地 CLI（如 Codex）执行并回填结论">
            🚀 真调执行 (API / CLI)
          </button>
          <button class="btn btn-ghost" onclick="handleOpenWebAndCopyPrompt('${task.id}')" title="方式1：直接打开该员工的免费聊天网页，并自动把标准工单指令复制到剪贴板">
            🌐 打开网页 + 复制指令
          </button>
          <button class="btn btn-ghost" onclick="handleExportTaskMd('${task.id}')" title="生成工单 .md 并复制 @文件 触发句，供桌面端/信箱执行">
            📂 导出 .md + 复制 @触发句
          </button>
          <button class="btn btn-ghost" onclick="handleCollectGitDiff('${task.id}')" title="读取工作区 git status/diff 摘要并填入改动文件（0 Token 质检）">
            🔍 抓取本地 git diff 摘要
          </button>
          <button class="btn btn-ghost" onclick="handleCopyWorkerPrompt('${task.id}')" title="仅复制纯文本模板指令">
            📋 仅复制指令
          </button>
          <button class="btn btn-ghost" onclick="handleDeliverFinalResult('${task.id}')">
            📦 经理统筹交付总结果
          </button>
        </div>

        <form onsubmit="handleWorkerPrivateReport(event, '${task.id}')" class="conclusion-grid">
          <label style="font-size:11px;color:var(--text-secondary);">📤 固定「结论-only」汇报模板（经理不读整段对话）：</label>
          <input type="text" id="reportConclusionInput" class="obsidian-input" required
                 placeholder="1. 【结论】一句话说清做了什么、是否完成..."
                 value="${escapeHTML(draft.conclusion || '')}"
                 oninput="updateReportDraft('${task.id}', 'conclusion', this.value)" />
          <input type="text" id="reportFilesInput" class="obsidian-input"
                 placeholder="2. 【改动文件】例：ai_farm/office_store.py, web/app.js（或填 无）"
                 value="${escapeHTML(draft.files || '')}"
                 oninput="updateReportDraft('${task.id}', 'files', this.value)" />
          <input type="text" id="reportTestInput" class="obsidian-input"
                 placeholder="3. 【测试结果】例：python tests/test_farm.py 全部 PASS（或 未运行）"
                 value="${escapeHTML(draft.tests || '')}"
                 oninput="updateReportDraft('${task.id}', 'tests', this.value)" />
          <button type="submit" class="btn btn-ghost" style="width:100%;">🔒 发送结论-only 私聊汇报（不刷大群）</button>
        </form>

        <div style="border-top:1px dashed var(--border);padding-top:8px;margin-bottom:8px;">
          <label style="font-size:11px;color:var(--text-secondary);display:block;margin-bottom:4px;">🛡️ 关键操作人工授权测试（合并 / 删代码 / 部署，默认先问老板）：</label>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <button type="button" class="btn btn-ghost btn-xs" onclick="handleRequestCriticalApproval('${task.id}', 'merge')">请求合并授权</button>
            <button type="button" class="btn btn-ghost btn-xs" onclick="handleRequestCriticalApproval('${task.id}', 'delete_code')">请求删代码授权</button>
            <button type="button" class="btn btn-ghost btn-xs" onclick="handleRequestCriticalApproval('${task.id}', 'deploy')">请求部署授权</button>
          </div>
        </div>

        <div style="border-top:1px dashed var(--border);padding-top:8px;">
          <label style="font-size:11px;color:var(--text-secondary);display:block;margin-bottom:4px;">↪ 跨厂商轮换转交（强制仅限不同厂商，禁止同家多开倒手）：</label>
          <div style="display:flex;gap:6px;">
            <select id="reassignTargetSelect" class="select-sm" style="flex:1;">${transferOptions}</select>
            <button type="button" class="btn btn-ghost" onclick="handleReassignTask('${task.id}')">↪ 转交</button>
          </div>
        </div>
      </div>

      <!-- 私聊消息流 -->
      <div class="identity-block">
        <h4>💬 私聊汇报记录 (${msgs.length} 条)</h4>
        <div style="display:flex;flex-direction:column;gap:8px;max-height:260px;overflow-y:auto;">
          ${msgs.map(m => `
            <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-sm);padding:7px 9px;font-size:12px;">
              <div style="display:flex;justify-content:space-between;color:var(--text-muted);font-size:10px;margin-bottom:3px;">
                <strong>${escapeHTML(m.sender_name)}</strong>
                <span>${escapeHTML(m.created_at || '')}</span>
              </div>
              <div style="white-space:pre-wrap;line-height:1.45;">${escapeHTML(m.text)}</div>
            </div>
          `).join("")}
        </div>
      </div>
    </div>
  `;
}

// =========================================================================
// 底部：团队真实账本总览
// =========================================================================
function renderSavingsChart() {
  const led = APP_STATE.savingsLedger || {};
  const days = (led.by_day || []).slice(-7);
  if (days.length === 0) {
    return `<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">省钱账本：暂无真实记录（干跑计 0，不编造数字）。</div>`;
  }
  const max = Math.max(1, ...days.map(d => Number(d.free_tokens || 0)));
  const bars = days.map(d => {
    const v = Number(d.free_tokens || 0);
    const h = Math.round((v / max) * 64);
    const label = (d.date || "").slice(5);
    return `<div class="savings-bar" title="${escapeHTML(d.date)} · 免费替执行 ${d.free_calls || 0} 次 / ${v} Token · 付费 ${d.paid_tokens || 0} Token">
      <span class="bar-val">${v}</span><div class="bar" style="height:${Math.max(2, h)}px"></div><span class="bar-label">${escapeHTML(label)}</span>
    </div>`;
  }).join("");
  return `<div style="font-size:11px;color:var(--text-secondary);margin-top:6px;">省钱账本（近 7 日免费员工替付费经理执行的真实 Token）</div>
    <div class="savings-chart">${bars}</div>
    <div style="font-size:10px;color:var(--text-muted);">累计免费 ${led.free_calls || 0} 次 / ${led.free_tokens || 0} Token · 付费 ${led.paid_calls || 0} 次 / ${led.paid_tokens || 0} Token</div>`;
}

function renderTeamOverview() {
  const managers = APP_STATE.agents.filter(a => a.floor === "manager").length;
  const workers = APP_STATE.agents.filter(a => a.floor === "worker").length;
  const rest = APP_STATE.agents.filter(a => a.floor === "rest").length;
  const verifiedReady = APP_STATE.agents.filter(a => a.floor !== "rest" && a.status === "ready").length;
  const el = document.getElementById("teamOverviewBox");
  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
      <strong>当前农场账本总览</strong>
      <span style="color:var(--accent);">在岗就绪：${verifiedReady} / 总计 ${APP_STATE.agents.length}</span>
    </div>
    <div>2楼经理 <strong>${managers}</strong> · 1楼员工 <strong>${workers}</strong> · 院子休息 <strong>${rest}</strong></div>
    <div style="color:var(--text-muted);margin-top:2px;">一图标一模型/通道 · 密钥仅读环境变量 · 具体模型全部由你按需招募</div>
    ${renderSavingsChart()}
  `;
}

// =========================================================================
// 技能中心 (Skill Center — 12 种子技能 + 高级模型裁判)
// =========================================================================
function renderSkillCenter() {
  const ov = document.getElementById("floorSkillOverview");
  const floors = [
    { key: "manager", title: "🏢 2楼 经理层技能装配" },
    { key: "worker", title: "🛠️ 1楼 员工层技能装配" },
    { key: "rest", title: "🌿 院子休息区" },
  ];
  ov.innerHTML = floors.map(f => {
    const list = APP_STATE.agents.filter(a => a.floor === f.key);
    return `
      <div class="floor-ov-box">
        <div style="font-weight:700;margin-bottom:6px;color:#38bdf8;">${f.title} (${list.length})</div>
        ${list.map(ag => `
          <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px dashed #334155;font-size:11px;">
            <span>${escapeHTML(ag.name)}</span>
            <span style="color:#94a3b8;">${(ag.skills || []).length} 个技能</span>
          </div>
        `).join("")}
      </div>
    `;
  }).join("");

  const grid = document.getElementById("skillsGrid");
  grid.innerHTML = APP_STATE.skills.map(sk => {
    const carriers = APP_STATE.agents.filter(a => (a.skills || []).includes(sk.slug));
    return `
      <div class="skill-card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong style="font-size:14px;">🛠️ ${escapeHTML(sk.name)}</strong>
          <span class="vendor-chip">${escapeHTML(sk.category || '通用')}</span>
        </div>
        <div style="font-size:11px;color:#cbd5e1;background:#0f172a;padding:6px;border-radius:6px;border:1px solid #334155;">
          <strong>固定步骤 (SOP)：</strong>${escapeHTML(sk.steps)}
        </div>
        <div style="font-size:11px;color:#34d399;">
          💡 <strong>省额度原理：</strong>${escapeHTML(sk.savings_note || '')}
        </div>
        <div style="font-size:11px;color:#94a3b8;">
          推荐模型：${escapeHTML(sk.best_for)}
        </div>
        <div style="margin-top:auto;padding-top:6px;border-top:1px dashed #334155;font-size:11px;">
          <span>当前装备者 (${carriers.length})：</span>
          ${carriers.map(c => `<span class="vendor-chip">${escapeHTML(c.name)}</span>`).join(" ") || '<span style="color:#64748b;">暂无</span>'}
        </div>
      </div>
    `;
  }).join("");
}

async function handleRunSkillJudge() {
  const judgeId = document.getElementById("skillJudgeSelect").value;
  const res = await callOfficeAction("analyzeskillassignments", { judge_id: judgeId });
  if (!res) return;
  APP_STATE.latestRecommendations = res.recommendations || [];
  const box = document.getElementById("judgeResultSection");
  box.classList.remove("hidden");

  if (APP_STATE.latestRecommendations.length === 0) {
    box.innerHTML = `<div>✅ 高级模型裁判 <strong>${escapeHTML(res.judge)}</strong> 评估完毕：当前所有在岗成员的技能均已处于最优配置！</div>`;
    return;
  }

  box.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
      <strong>🧠 高级模型裁判「${escapeHTML(res.judge)}」打分推荐清单（请勾选批准后应用）：</strong>
      <button class="btn btn-success" onclick="handleApplyApprovedSkills('${escapeHTML(res.judge)}')">
        ✅ 批准并应用勾选项（同步发群通知）
      </button>
    </div>
    <div style="display:flex;flex-direction:column;gap:6px;max-height:240px;overflow-y:auto;">
      ${APP_STATE.latestRecommendations.map((r, idx) => `
        <label style="display:flex;align-items:flex-start;gap:8px;background:#0f172a;padding:7px 10px;border-radius:6px;font-size:12px;cursor:pointer;">
          <input type="checkbox" class="rec-skill-chk" data-idx="${idx}" checked style="margin-top:3px;" />
          <div>
            <div>
              <strong>${escapeHTML(r.agent_name)}</strong> ➕ 装配技能 <strong>「${escapeHTML(r.skill_name)}」</strong>
              <span class="access-badge green">匹配度 ${r.score} 分</span>
            </div>
            <div style="font-size:11px;color:#94a3b8;margin-top:2px;">${escapeHTML(r.reason)}</div>
          </div>
        </label>
      `).join("")}
    </div>
  `;
}

async function handleApplyApprovedSkills(judgeName) {
  const checks = document.querySelectorAll(".rec-skill-chk");
  const approved = [];
  checks.forEach(chk => {
    if (chk.checked) {
      const idx = Number(chk.getAttribute("data-idx"));
      if (APP_STATE.latestRecommendations[idx]) {
        approved.push(APP_STATE.latestRecommendations[idx]);
      }
    }
  });
  if (approved.length === 0) {
    showToast("请至少勾选一项推荐");
    return;
  }
  await callOfficeAction("applyskillassignments", { judge: judgeName, assignments: approved });
  document.getElementById("judgeResultSection").classList.add("hidden");
  showToast(`✅ 已应用 ${approved.length} 项技能分配，并在大群发布裁判通知！`);
}

// =========================================================================
// 交互事件处理：示例任务、认领、私聊汇报、转交、统筹交付、验收、招募
// =========================================================================
async function handleSeedExampleTask() {
  const task = await callOfficeAction("seedexampletask");
  if (task) {
    APP_STATE.selectedTaskId = task.id;
    showToast(`🧪 已塞入通用示例任务：${task.title}`);
  }
}

async function handleClaimTask(taskId, workerId) {
  await callOfficeAction("claimtask", { task_id: taskId, worker_id: workerId });
  await openTaskPrivateThread(taskId);
  showToast("✋ 员工已认领任务，私聊汇报窗已打开！");
}

function updateReportDraft(taskId, field, value) {
  if (!APP_STATE.reportDrafts[taskId]) APP_STATE.reportDrafts[taskId] = {};
  APP_STATE.reportDrafts[taskId][field] = value;
}

async function handleWorkerPrivateReport(event, taskId) {
  event.preventDefault();
  const conclusion = document.getElementById("reportConclusionInput").value.trim();
  const filesRaw = document.getElementById("reportFilesInput").value.trim();
  const testResult = document.getElementById("reportTestInput").value.trim();
  if (!conclusion) return;
  const changed_files = filesRaw ? filesRaw.split(/[,，\n]/).map(s => s.trim()).filter(Boolean) : ["无"];
  const task = APP_STATE.tasks.find(t => t.id === taskId);
  await callOfficeAction("postmessage", {
    task_id: taskId,
    sender_id: task ? task.assigned_to : "",
    conclusion,
    changed_files,
    test_result: testResult || "未运行测试",
    is_delivery: true,
  });
  delete APP_STATE.reportDrafts[taskId];
  await openTaskPrivateThread(taskId);
  showToast("🔒 结论-only 汇报已发送给经理（未贴全对话，大群仅留折叠提示）！");
}

async function handleCollectGitDiff(taskId) {
  const wsInput = document.getElementById("customWorkspaceInput");
  const workspace_dir = wsInput ? wsInput.value.trim() : (APP_STATE.customWorkspaceDir || "");
  const res = await callOfficeAction("collectgitdiff", { workspace_dir });
  if (!res) return;
  const filesStr = (res.changed_files && res.changed_files.length) ? res.changed_files.join(", ") : "无未提交改动";
  updateReportDraft(taskId, "files", filesStr);
  if (res.diff_stat) {
    updateReportDraft(taskId, "conclusion", `已完成本地代码改动 (${res.changed_files ? res.changed_files.length : 0} 个文件)`);
  }
  const fBox = document.getElementById("reportFilesInput");
  if (fBox) fBox.value = filesStr;
  const cBox = document.getElementById("reportConclusionInput");
  if (cBox && !cBox.value && res.diff_stat) cBox.value = `已完成本地代码改动 (${res.changed_files ? res.changed_files.length : 0} 个文件)`;
  showToast("🔍 已抓取本地改动文件清单填入汇报模板（0 Token 质检）！");
}

async function handleToggleAutoExecute() {
  const res = await callOfficeAction("toggleautoexecute", {});
  if (res) {
    showToast(res.auto_execute_low_risk
      ? "⚡ 低风险任务自动执行已开启（合并/删代码/部署依然每次人工授权）"
      : "🛡️ 低风险自动执行已关闭（安全默认）");
  }
}

async function handleResolveApproval(approvalId, decision) {
  await callOfficeAction("resolveapproval", { approval_id: approvalId, decision });
  showToast(decision === "deny" ? "🚫 已拒绝该操作" : "✅ 已批准该授权请求");
}

async function handleRequestCriticalApproval(taskId, opType) {
  await callOfficeAction("requestapproval", {
    op_type: opType,
    target: opType === "merge" ? "main" : opType === "deploy" ? "production" : "src/legacy",
    task_id: taskId,
    requested_by: "chief",
  });
  showToast("🛡️ 已在 HUD 顶部发起人工授权请求，请点击「允许一次」或「拒绝」！");
}

async function handleSubmitCodeReview(taskId, passed, simulateReject = false) {
  const reviewerId = (document.getElementById("reviewAgentSelect") || {}).value || "";
  const rawIssues = (document.getElementById("reviewIssuesInput") || {}).value || "";
  const issues = rawIssues.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  await callOfficeAction("submitcodereview", {
    task_id: taskId,
    reviewer_id: reviewerId,
    passed,
    issues,
    dry_run: true,
    simulate_reject: Boolean(simulateReject && issues.length === 0),
  });
  await openTaskPrivateThread(taskId);
  showToast(passed ? "✅ 独立审查通过，可交付！" : "↩ 已退回问题清单给写代码员工重做！");
}

async function handleAutoCodeReview(taskId, live = false) {
  const reviewerId = (document.getElementById("reviewAgentSelect") || {}).value || "";
  const wsInput = document.getElementById("customWorkspaceInput");
  const workspace_dir = wsInput ? wsInput.value.trim() : (APP_STATE.customWorkspaceDir || "");
  const res = await callOfficeAction("runautocodereview", {
    task_id: taskId,
    reviewer_id: reviewerId,
    workspace_dir,
    live,
  });
  await openTaskPrivateThread(taskId);
  if (res) {
    showToast(`🔍 独立审查完成 (${res.mode})：${res.reviewer} → ${res.review_status}`);
  }
}

function openBigTaskModal() {
  const mgrSel = document.getElementById("bigTaskManagerSelect");
  const managers = APP_STATE.agents.filter(a => a.floor === "manager");
  if (mgrSel) {
    mgrSel.innerHTML = managers.map(m => `<option value="${m.id}">${escapeHTML(m.name)} (${escapeHTML(m.badge)})</option>`).join("");
  }
  document.getElementById("bigTaskModal").classList.remove("hidden");
}

function closeBigTaskModal() {
  document.getElementById("bigTaskModal").classList.add("hidden");
}

async function handleCreateBigTaskSubmit(event) {
  event.preventDefault();
  const res = await callOfficeAction("createbigtask", {
    title: document.getElementById("bigTaskTitle").value.trim(),
    manager_id: document.getElementById("bigTaskManagerSelect").value,
    goal: document.getElementById("bigTaskGoal").value.trim(),
    raw_steps: document.getElementById("bigTaskSteps").value,
  });
  closeBigTaskModal();
  if (res && res.parent) {
    APP_STATE.selectedTaskId = res.parent.id;
    await openTaskPrivateThread(res.parent.id);
    showToast(`🧩 大任务已拆成 ${(res.subtasks || []).length} 张子单并跨厂商分派！`);
  }
}

async function handleRunBigTaskSubtasks(parentId, live = false) {
  const wsInput = document.getElementById("customWorkspaceInput");
  const workspace_dir = wsInput ? wsInput.value.trim() : (APP_STATE.customWorkspaceDir || "");
  const res = await callOfficeAction("runbigtasksubtasks", {
    parent_task_id: parentId,
    live,
    workspace_dir,
  });
  if (res) {
    showToast(`⚡ 已批量执行 ${res.executed_count} 张子单 (${res.mode === 'dry_run' ? '0消耗干跑' : 'API/CLI并行真调'})`);
  }
}

async function handleAggregateBigTask(parentId) {
  await callOfficeAction("aggregatebigtask", { parent_task_id: parentId });
  showToast("🏁 已汇总全部子单结论并发回大群等待董事长验收！");
}

async function handleRunAdapterTask(taskId, live = false) {
  const wsInput = document.getElementById("customWorkspaceInput");
  const workspace_dir = wsInput ? wsInput.value.trim() : (APP_STATE.customWorkspaceDir || "");
  const res = await callOfficeAction("runadaptertask", { task_id: taskId, live, workspace_dir });
  await openTaskPrivateThread(taskId);
  if (res) {
    showToast(`🔌 ${res.mode === 'dry_run' ? 'AgentAdapter 干跑完成 (0消耗)' : '🚀 真实调用完成，结果已写入私聊窗！'}`);
  }
}

function _buildWorkerPromptText(task) {
  return (
    `你是执行员工，只做下面这件事，不要做决定。\n` +
    `任务目标：${task.goal}\n` +
    `输入内容：\n${task.input_text}\n` +
    `强制输出格式：${task.output_format}\n` +
    `验收标准：${task.acceptance}\n` +
    `红线：不确定的写“未核实”，不要猜。不许自由发挥。`
  );
}

async function handleCopyWorkerPrompt(taskId) {
  const task = APP_STATE.tasks.find(t => t.id === taskId);
  if (!task) return;
  const promptText = _buildWorkerPromptText(task);
  try {
    await navigator.clipboard.writeText(promptText);
    showToast("📋 已复制标准派单指令！直接粘贴运行，完成后把结果贴回下方汇报框即可。");
  } catch (_) {
    showToast("复制失败，请手动从下方系统消息框复制指令", true);
  }
}

async function handleOpenWebAndCopyPrompt(taskId) {
  const task = APP_STATE.tasks.find(t => t.id === taskId);
  if (!task) return;
  const promptText = _buildWorkerPromptText(task);
  try {
    await navigator.clipboard.writeText(promptText);
  } catch (_) {}

  if (APP_STATE.backendOnline) {
    try {
      await callOfficeAction("gettaskprompt", { task_id: taskId, mark_dispatched: true });
    } catch (_) {}
  }

  let worker = APP_STATE.agents.find(a => a.id === task.assigned_to);
  if (!worker) {
    worker = APP_STATE.agents.find(a => a.floor === "worker" && (a.login_url || a.usage_url));
  }
  const baseUrl = worker ? (worker.login_url || worker.usage_url) : "";
  if (baseUrl) {
    const sep = baseUrl.includes("?") ? "&" : "?";
    const shortQ = promptText.length <= 1200 ? `&q=${encodeURIComponent(promptText)}` : "";
    const targetUrl = `${baseUrl}${sep}ai_farm_task=${encodeURIComponent(taskId)}${shortQ}#ai_farm_task=${encodeURIComponent(taskId)}`;
    window.open(targetUrl, "_blank", "noopener");
    showToast(`🌐 已打开 ${worker.name} 网页（已装传令兵插件会自动填入发送；未装插件直接 Ctrl+V 回车即可）！`);
  } else {
    showToast("📋 已复制标准指令（当前指派员工未填写网页 URL，请手动切到聊天网页粘贴）。");
  }
}

async function handleExportTaskMd(taskId) {
  const wsInput = document.getElementById("customWorkspaceInput");
  const workspace_dir = wsInput ? wsInput.value.trim() : (APP_STATE.customWorkspaceDir || "");
  const res = await callOfficeAction("exporttaskmd", { task_id: taskId, workspace_dir });
  if (!res) return;
  try {
    await navigator.clipboard.writeText(res.trigger_text);
    showToast(`📂 已生成 ${res.file_path} 并复制 @触发句！直接去 WorkBuddy 粘贴按回车即可。`);
  } catch (_) {
    showToast(`📂 已生成 ${res.file_path}，触发句：${res.trigger_text}`);
  }
}

async function handleReassignTask(taskId) {
  const toWorkerId = document.getElementById("reassignTargetSelect").value;
  await callOfficeAction("reassigntask", {
    task_id: taskId,
    to_worker_id: toWorkerId,
    reason: "当前员工额度轮休，跨厂商转交给其他免费员工",
  });
  await openTaskPrivateThread(taskId);
  showToast("↪ 已成功跨厂商转交任务！");
}

async function handleDeliverFinalResult(taskId) {
  await callOfficeAction("deliverfinalresult", { task_id: taskId });
  showToast("🏁 经理已将统筹最终结果发回大群，请董事长验收！");
}

async function handleReviewFinalResult(taskId, decision) {
  await callOfficeAction("reviewfinalresult", { task_id: taskId, decision });
  showToast(decision === "verified" ? "✅ 已验收通过！" : "↩ 已打回重做！");
}

async function handleSendGroupMessage(event) {
  event.preventDefault();
  const input = document.getElementById("groupChatInput");
  const senderId = document.getElementById("groupSenderSelect").value;
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  await callOfficeAction("postgroupmessage", { sender_id: senderId, text });
}

function insertMention(tag) {
  const input = document.getElementById("groupChatInput");
  input.value = (input.value ? input.value + " " : "") + tag + " ";
  input.focus();
}

async function handleResetDemo() {
  await callOfficeAction("reset_to_seed");
  showToast("↺ 已重置回初始核实状态");
}

// =========================================================================
// 招募弹窗（两路：API 只填环境变量名 vs 网页点登录一次）
// =========================================================================
function openRecruitModal() {
  APP_STATE.recruitLoggedInClicked = false;
  document.getElementById("loginOnceStatusBadge").textContent = "未点登录";
  document.getElementById("loginOnceStatusBadge").className = "login-status-pill";
  document.getElementById("recruitModal").classList.remove("hidden");
  APP_STATE.recruitStep = 1;
  recruitWizardGo(0);
}

function closeRecruitModal() {
  document.getElementById("recruitModal").classList.add("hidden");
}

function switchRecruitPath(path) {
  document.getElementById("recPathInput").value = path;
  document.getElementById("pathBtnApi").classList.toggle("active", path === "api");
  document.getElementById("pathBtnWeb").classList.toggle("active", path === "web");
  document.getElementById("pathBtnCli").classList.toggle("active", path === "cli");
  document.getElementById("pathBtnDesktop").classList.toggle("active", path === "desktop");
  document.getElementById("recApiFields").classList.toggle("hidden", path !== "api");
  document.getElementById("recWebFields").classList.toggle("hidden", path !== "web");
  document.getElementById("recCliFields").classList.toggle("hidden", path !== "cli");
  document.getElementById("recDesktopFields").classList.toggle("hidden", path !== "desktop");
}

function handleLoginOnceClick() {
  const url = document.getElementById("recLoginUrl").value.trim();
  if (!url) {
    showToast("请先填写厂商登录页 URL（如 https://chatgpt.com/）", true);
    return;
  }
  window.open(url, "_blank", "noopener");
  APP_STATE.recruitLoggedInClicked = true;
  const badge = document.getElementById("loginOnceStatusBadge");
  badge.textContent = "✅ 已登录（本地会话已就绪）";
  badge.className = "login-status-pill ok";
  showToast("🔑 已打开厂商登录页，登完回来直接保存即可（密码只交厂商，会话存本地）");
}

async function handleRecruitSubmit(event) {
  event.preventDefault();
  const path = document.getElementById("recPathInput").value;
  const name = document.getElementById("recName").value.trim();
  const vendor = document.getElementById("recVendor").value.trim();
  const model = document.getElementById("recModel").value.trim();
  const floor = document.getElementById("recFloor").value;
  const specialty = document.getElementById("recSpecialty").value.trim();

  if (path === "api") {
    const keyEnv = document.getElementById("recKeyEnv").value.trim().toUpperCase();
    const baseUrl = document.getElementById("recBaseUrl").value.trim();
    const paid = document.getElementById("recApiPaid").value === "true";
    const usageUrl = document.getElementById("recApiUsageUrl").value.trim();
    if (!keyEnv || !/^[A-Z][A-Z0-9_]*$/.test(keyEnv)) {
      showToast("安全拦截：环境变量名必须是大写字母+下划线（如 DEEPSEEK_API_KEY），禁止填真实 Key！", true);
      return;
    }
    await callOfficeAction("createagent", {
      name, vendor, model, floor, specialty,
      access_kind: "api",
      paid,
      key_env: keyEnv,
      base_url: baseUrl,
      usage_url: usageUrl,
    });
  } else if (path === "cli") {
    const paid = document.getElementById("recCliPaid").value === "true";
    const executable = document.getElementById("recCliExec").value.trim();
    if (!executable) {
      showToast("CLI 工具招募必须填写可执行命令名（如 codex）", true);
      return;
    }
    await callOfficeAction("createagent", {
      name, vendor, model, floor, specialty,
      access_kind: "cli",
      paid,
      executable,
    });
  } else if (path === "desktop") {
    const paid = document.getElementById("recDesktopPaid").value === "true";
    const rawSubs = document.getElementById("recDesktopSubModels").value.trim();
    const sub_models = rawSubs ? rawSubs.split(/[,，]/).map(s => s.trim()).filter(Boolean) : [];
    await callOfficeAction("createagent", {
      name, vendor, model, floor, specialty,
      access_kind: "desktop",
      paid,
      sub_models,
    });
  } else {
    const webKind = document.getElementById("recWebKind").value;
    const loginUrl = document.getElementById("recLoginUrl").value.trim();
    const usageUrl = document.getElementById("recWebUsageUrl").value.trim();
    const fallbackNote = document.getElementById("recFallbackNote").value.trim();
    if (!loginUrl) {
      showToast("网页/订阅接入必须填写厂商登录页 URL", true);
      return;
    }
    await callOfficeAction("createagent", {
      name, vendor, model, floor, specialty,
      access_kind: webKind,
      paid: webKind === "subscription",
      login_url: loginUrl,
      usage_url: usageUrl,
      fallback_note: fallbackNote,
      logged_in: APP_STATE.recruitLoggedInClicked,
    });
  }
  closeRecruitModal();
  showToast(`🎉 已招募新成员：${name}`);
}

async function handleLoadSampleTeam() {
  const res = await callOfficeAction("loadsampleteam");
  if (res) {
    showToast(`🎭 已载入 ${res.added_count} 名通用示例团队成员（全部为匿名占位示例，随时可删改）`);
  }
}

// =========================================================================
// 派新任务弹窗 & 新增技能弹窗
// =========================================================================
function openNewTaskModal() {
  const mgrSel = document.getElementById("taskManagerSelect");
  const wrkSel = document.getElementById("taskWorkerSelect");
  const skSel = document.getElementById("taskSkillSelect");

  const managers = APP_STATE.agents.filter(a => a.floor === "manager");
  const workers = APP_STATE.agents.filter(a => a.floor === "worker");

  mgrSel.innerHTML = managers.map(m => `<option value="${m.id}">${escapeHTML(m.name)} (${escapeHTML(m.badge)})</option>`).join("");
  wrkSel.innerHTML = `<option value="">-- 留空（让1楼员工在群里认领） --</option>` +
    workers.map(w => `<option value="${w.id}">${escapeHTML(w.name)} (${escapeHTML(w.vendor)} · ${escapeHTML(w.badge)})</option>`).join("");
  skSel.innerHTML = `<option value="">-- 不限定固定技能 --</option>` +
    APP_STATE.skills.map(s => `<option value="${s.slug}">${escapeHTML(s.name)} (${escapeHTML(s.best_for)})</option>`).join("");

  const revSel = document.getElementById("taskReviewerSelect");
  if (revSel) {
    const allOnline = APP_STATE.agents.filter(a => a.floor !== "rest" && a.status !== "exhausted");
    revSel.innerHTML = allOnline.map(a => `<option value="${a.id}">${escapeHTML(a.name)} (${escapeHTML(a.badge)})</option>`).join("");
  }
  toggleReviewerField();
  selectTaskMode("solo");
  document.getElementById("newTaskModal").classList.remove("hidden");
}

function syncNewTaskKindFromSkill() {
  const sk = document.getElementById("taskSkillSelect").value;
  const kindSel = document.getElementById("taskKindSelect");
  if (!kindSel) return;
  if (["cheap-code-jobs", "code-review-checklist", "test-cases"].includes(sk)) {
    kindSel.value = "code_change";
  }
  toggleReviewerField();
}

function toggleReviewerField() {
  const kindSel = document.getElementById("taskKindSelect");
  const grp = document.getElementById("taskReviewerGroup");
  if (!kindSel || !grp) return;
  grp.classList.toggle("hidden", kindSel.value !== "code_change");
}

function closeNewTaskModal() {
  document.getElementById("newTaskModal").classList.add("hidden");
}

async function handleCreateTaskSubmit(event) {
  event.preventDefault();
  const task_kind = (document.getElementById("taskKindSelect") || {}).value || "small";
  const reviewer_id = task_kind === "code_change"
    ? ((document.getElementById("taskReviewerSelect") || {}).value || "")
    : "";
  const payload = {
    title: document.getElementById("taskTitle").value.trim(),
    manager_id: document.getElementById("taskManagerSelect").value,
    assigned_to: document.getElementById("taskWorkerSelect").value,
    skill_slug: document.getElementById("taskSkillSelect").value,
    task_kind,
    reviewer_id,
    goal: document.getElementById("taskGoal").value.trim(),
    input_text: document.getElementById("taskInput").value.trim(),
    output_format: document.getElementById("taskFormat").value.trim(),
    acceptance: document.getElementById("taskAcceptance").value.trim(),
    mode: (document.getElementById("taskModeInput") || {}).value || "solo",
  };
  const task = await callOfficeAction("createtask", payload);
  closeNewTaskModal();
  if (task) {
    APP_STATE.selectedTaskId = task.id;
    showToast(`已在大群发布任务：${task.title}`);
  }
}

function openNewSkillModal() {
  document.getElementById("newSkillModal").classList.remove("hidden");
}
function closeNewSkillModal() {
  document.getElementById("newSkillModal").classList.add("hidden");
}
function openAutomationGuideModal() {
  document.getElementById("automationGuideModal").classList.remove("hidden");
}
function closeAutomationGuideModal() {
  document.getElementById("automationGuideModal").classList.add("hidden");
}
async function handleCreateSkillSubmit(event) {
  event.preventDefault();
  await callOfficeAction("createskill", {
    name: document.getElementById("skName").value.trim(),
    category: document.getElementById("skCat").value.trim(),
    steps: document.getElementById("skSteps").value.trim(),
    best_for: document.getElementById("skBestFor").value.trim(),
    savings_note: document.getElementById("skSavings").value.trim(),
  });
  closeNewSkillModal();
  showToast("✅ 已新增技能");
}

// =========================================================================
// 视图与辅助工具
// =========================================================================
function closeTopbarDropdown(id) {
  const el = document.getElementById(id);
  if (el) el.removeAttribute("open");
}

document.addEventListener("click", (ev) => {
  document.querySelectorAll("details.topbar-dropdown[open]").forEach((det) => {
    if (!det.contains(ev.target)) det.removeAttribute("open");
  });
});

function switchMainView(view) {
  document.getElementById("tabBtnWorkspace").classList.toggle("active", view === "workspace");
  document.getElementById("tabBtnSkills").classList.toggle("active", view === "skills");
  document.getElementById("workspaceView").classList.toggle("hidden", view !== "workspace");
  document.getElementById("skillsView").classList.toggle("hidden", view !== "skills");
}

function switchRightTab(tab) {
  document.getElementById("rTabProfile").classList.toggle("active", tab === "profile");
  document.getElementById("rTabThread").classList.toggle("active", tab === "thread");
  document.getElementById("panelProfile").classList.toggle("active", tab === "profile");
  document.getElementById("panelThread").classList.toggle("active", tab === "thread");
}

function switchMobilePane(pane) {
  ["Roster", "Chat", "Detail"].forEach(p => {
    const key = p.toLowerCase();
    document.getElementById("mTab" + p).classList.toggle("active", key === pane);
    document.getElementById("pane" + p).classList.toggle("active", key === pane);
  });
}

function showToast(msg, isError = false) {
  const c = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = "toast";
  if (isError) el.style.borderColor = "#ef4444";
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), 3600);
}

function escapeHTML(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

window.addEventListener("DOMContentLoaded", initOffice);
