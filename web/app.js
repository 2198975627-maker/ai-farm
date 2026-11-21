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
  draftMode: "standard",
  pendingAttachments: { single: [], big: [] },
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
let officeCsrf = "";
let officeEventSource = null;
let snapshotRefreshInFlight = false;
let snapshotRefreshQueued = false;

function connectOfficeEvents() {
  if (officeEventSource) {
    officeEventSource.close();
    officeEventSource = null;
  }
  if (!APP_STATE.backendOnline || typeof EventSource === "undefined") return;
  const es = new EventSource("/api/events");
  officeEventSource = es;
  es.addEventListener("state", () => {
    scheduleSnapshotRefresh();
  });
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      const badge = document.getElementById("connModeBadge");
      if (badge) {
        badge.textContent = "连接已断开 · 请刷新配对";
        badge.classList.remove("connected");
      }
      es.close();
      if (officeEventSource === es) officeEventSource = null;
    }
  };
}

async function scheduleSnapshotRefresh() {
  if (snapshotRefreshInFlight) {
    snapshotRefreshQueued = true;
    return;
  }
  snapshotRefreshInFlight = true;
  try {
    do {
      snapshotRefreshQueued = false;
      const resp = await fetch("/api/state", { cache: "no-store" });
      if (resp.status === 401 || resp.status === 403) {
        if (officeEventSource) {
          officeEventSource.close();
          officeEventSource = null;
        }
        APP_STATE.backendOnline = false;
        showPairingForm();
        return;
      }
      if (resp.ok) {
        applySnapshot(await resp.json());
      }
    } while (snapshotRefreshQueued);
  } catch (_) {
    // Wait for next SSE event rather than polling.
  } finally {
    snapshotRefreshInFlight = false;
  }
}

async function initOffice() {
  try {
    const session = await fetch("/api/session", { cache: "no-store" });
    if (session.status === 401 || session.status === 403) {
      APP_STATE.backendOnline = false;
      document.getElementById("connModeBadge").textContent = "等待本机配对";
      showPairingForm();
      return;
    }
    if (session.ok) officeCsrf = (await session.json()).csrf;
    const resp = await fetch("/api/state", { cache: "no-store" });
    if (resp.ok) {
      const data = await resp.json();
      APP_STATE.backendOnline = true;
      document.getElementById("connModeBadge").textContent = "本地服务已连接";
      document.getElementById("connModeBadge").classList.add("connected");
      applySnapshot(data);
      connectOfficeEvents();
      applyShotParams();
      return;
    }
  } catch (_) {
    // 离线文件模式
  }
  APP_STATE.backendOnline = false;
  document.getElementById("connModeBadge").textContent = "离线预览 · 操作不可用";
  document.getElementById("connModeBadge").title = "运行 python -m ai_farm office 连接本地后端";
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

function showPairingForm() {
  if (document.getElementById("officePairing")) return;
  const dialog = document.createElement("dialog");
  dialog.id = "officePairing";
  dialog.className = "auth-dialog";
  dialog.innerHTML = `<form id="officePairForm"><h2>连接你的本机农场</h2><p>从启动服务的终端粘贴一次性配对码。它不是模型 API Key，也不要分享给员工。</p><label for="officePairCode">本机配对码</label><input id="officePairCode" type="password" autocomplete="off" required maxlength="128"><p id="officePairError" role="alert"></p><button type="submit" class="btn btn-primary">配对并进入</button><p>配对码 10 分钟有效，只能使用一次；会话失效时请在本机重启服务。</p></form>`;
  document.body.appendChild(dialog);
  dialog.addEventListener("cancel", event => event.preventDefault());
  document.getElementById("officePairForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = event.target.querySelector("button");
    button.disabled = true;
    try {
      const response = await fetch("/api/pair", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: document.getElementById("officePairCode").value.trim() }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "配对失败");
      officeCsrf = data.csrf;
      document.getElementById("officePairCode").value = "";
      dialog.close();
      dialog.remove();
      await initOffice();
    } catch (error) {
      document.getElementById("officePairError").textContent = error.message;
    } finally { button.disabled = false; }
  });
  dialog.showModal();
}

async function openConnections() {
  if (!APP_STATE.backendOnline) return showPairingForm();
  document.getElementById("officeConnections")?.remove();
  const dialog = document.createElement("dialog");
  dialog.id = "officeConnections";
  dialog.className = "auth-dialog";
  dialog.innerHTML = `<h2>任务范围连接</h2><p>凭据仅在本次服务运行中有效，不保存到本地存储。MCP 使用成员凭据，网页员工使用单工单传令兵凭据。</p><form id="connectionForm"><label for="connectionTask">授权工单</label><select id="connectionTask" required>${APP_STATE.tasks.filter(t => !t.is_parent).map(t => `<option value="${escapeHTML(t.id)}">${escapeHTML(t.title)}</option>`).join("")}</select><label for="connectionAgent">执行者 / 审查者</label><select id="connectionAgent" required>${APP_STATE.agents.map(a => `<option value="${escapeHTML(a.id)}">${escapeHTML(a.name)}</option>`).join("")}</select><button class="btn btn-primary" type="submit">生成任务凭据</button></form><p id="connectionError" role="alert"></p><textarea id="connectionSecret" readonly aria-label="本次生成的凭据" placeholder="凭据只显示在此处；关闭后清空"></textarea><p>MCP：在启动中继的进程环境设置 AI_FARM_MEMBER_TOKEN。传令兵：在对应网页点击“绑定工单”粘贴此凭据。不要放进 URL 或公开配置。</p><div id="connectionList"></div><button id="connectionClose" class="btn">关闭并清空</button>`;
  document.body.appendChild(dialog);
  const api = async (path, body) => {
    const response = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json", "X-Farm-CSRF": officeCsrf }, body: JSON.stringify(body) } : { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "连接操作失败");
    return result;
  };
  const refresh = async () => {
    const data = await api("/api/connections");
    if (!dialog.isConnected) return;
    const list = dialog.querySelector("#connectionList");
    list.replaceChildren();
    for (const connection of data.connections.filter(c => c.role !== "owner")) {
      const row = document.createElement("p");
      row.textContent = `${connection.agent_id} · ${connection.task_ids.join(", ")} `;
      const button = document.createElement("button");
      button.className = "btn";
      button.textContent = "撤销";
      button.onclick = async () => { try { await api("/api/revoke", { credential_id: connection.id }); await refresh(); } catch (error) { document.getElementById("connectionError").textContent = error.message; } };
      row.appendChild(button); list.appendChild(row);
    }
  };
  document.getElementById("connectionForm").onsubmit = async event => {
    event.preventDefault();
    const button = event.target.querySelector("button"); button.disabled = true;
    try {
      const agent = APP_STATE.agents.find(a => a.id === document.getElementById("connectionAgent").value);
      const result = await api("/api/connections", { agent_id: agent.id, task_ids: [document.getElementById("connectionTask").value], role: ["web", "subscription"].includes(agent.access_kind) ? "courier" : "member" });
      if (!dialog.isConnected) return;
      dialog.querySelector("#connectionSecret").value = result.token;
      dialog.querySelector("#connectionError").textContent = "已生成；仅授予所选工单，不授权模型执行。";
      await refresh();
    } catch (error) { if (dialog.isConnected) dialog.querySelector("#connectionError").textContent = error.message; }
    finally { button.disabled = false; }
  };
  const clear = () => { dialog.querySelector("#connectionSecret").value = ""; dialog.remove(); };
  const close = () => { clear(); dialog.close(); };
  dialog.addEventListener("close", clear, { once: true });
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  document.getElementById("connectionClose").onclick = close;
  dialog.showModal();
  try { await refresh(); } catch (error) { document.getElementById("connectionError").textContent = error.message; }
}

function applySnapshot(snap) {
  const active = document.activeElement;
  const activeId = active && active.id ? active.id : null;
  const activeVal = active && ("value" in active) ? active.value : null;
  const activeStart = active && typeof active.selectionStart === "number" ? active.selectionStart : null;
  const activeEnd = active && typeof active.selectionEnd === "number" ? active.selectionEnd : null;
  const scrollState = {};
  for (const id of ["paneRoster", "groupChatStream", "panelThread", "panelProfile", "taskBoard"]) {
    const el = document.getElementById(id);
    if (el) scrollState[id] = el.scrollTop;
  }

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

  for (const [id, top] of Object.entries(scrollState)) {
    const el = document.getElementById(id);
    if (el) el.scrollTop = top;
  }
  if (activeId) {
    const restored = document.getElementById(activeId);
    if (restored) {
      if (activeVal !== null && "value" in restored && restored.value !== activeVal) restored.value = activeVal;
      restored.focus({ preventScroll: true });
      if (activeStart !== null && typeof restored.setSelectionRange === "function") {
        try { restored.setSelectionRange(activeStart, activeEnd ?? activeStart); } catch (_) {}
      }
    }
  }
}

async function callOfficeAction(action, payload = {}) {
  if (APP_STATE.backendOnline) {
    const resp = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Farm-CSRF": officeCsrf },
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
  external: '<path d="M15 3h6v6M10 14L21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>',
  corner: '<path d="M4 4v10h16M14 8l6 6-6 6"/>',
  chevron: '<path d="M9 5l7 7-7 7"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v2"/>',
  gauge: '<path d="M4.2 19a10 10 0 1 1 15.6 0M12 12l5-5M5 12H3M12 4V2M19 12h2"/><circle cx="12" cy="12" r="2"/>',
};
function icon(name, cls = "") {
  return `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON_PATHS[name] || ""}</svg>`;
}
// 保留箭头、技术符号与原始空白，避免改变消息中的流程和代码语义。
const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{2714}\u{2716}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{200D}]/gu;
function stripEmoji(str) {
  return String(str == null ? "" : str).replace(EMOJI_RE, "").trim();
}
const HEX_TOKEN_MAP = [
  [/#(?:38bdf8|3b82f6|a5b4fc|22d3ee|60a5fa|818cf8|93c5fd|cbd5e1)\b/gi, "var(--text-secondary)"],
  [/#(?:94a3b8|64748b|71717a|a1a1aa)\b/gi, "var(--text-muted)"],
  [/#(?:f87171|ef4444|fca5a5)\b/gi, "var(--danger)"],
  [/#(?:10b981|22c55e|86efac|4ade80|34d399)\b/gi, "var(--quota-green)"],
  [/#(?:f59e0b|fbbf24|eab308|facc15)\b/gi, "var(--quota-yellow)"],
  [/#(?:0f172a|1e293b)\b/gi, "var(--bg-card-elevated)"],
  [/#(?:334155|475569)\b/gi, "var(--border-strong)"],
  [/#(?:ffffff|fff)\b/gi, "var(--text-main)"],
];
function neutralizePanel(id) {
  const panel = document.getElementById(id);
  if (!panel) return;
  // 原位处理样式，不序列化/重建 DOM，不触碰 value、onclick、URL 或 Muse SVG。
  panel.querySelectorAll("[style]").forEach(el => {
    const original = el.getAttribute("style");
    let style = original;
    for (const [re, token] of HEX_TOKEN_MAP) style = style.replace(re, token);
    if (style !== original) el.setAttribute("style", style);
  });
  const walker = document.createTreeWalker(panel, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.parentElement.closest("[data-preserve-text], input, textarea, select, code, pre, svg, .kv-row, .vendor-chip, .agent-avatar")) continue;
    // 只移除 UI 文本节点开头的装饰，不清洗正文中的 emoji、箭头或颜色字面量。
    node.nodeValue = node.nodeValue.replace(/^(\s*)[\u{1F000}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{2714}\u{2716}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{200D}]+[ \t]*/u, "$1");
  }
}
// 只读截图/演示入口：?view=skills / ?modal=recruit|newtask|approval（不改变任何数据）
function applyShotParams() {
  const p = new URLSearchParams(location.search);
  if (p.get("view") === "skills" || p.get("view") === "team") switchMainView(p.get("view"));
  if (p.get("view") === "activity") switchWorkspaceTab("activity");
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
  if (delta > 0 && APP_STATE.recruitStep === 2) {
    const form = document.getElementById("recruitForm");
    if (!form.reportValidity()) return;
  }
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
    if (summary) summary.innerHTML = `名字：<strong data-preserve-text>${escapeHTML(name)}</strong><br>厂商：${escapeHTML(vendor)} · 模型：${escapeHTML(model)}<br>通道：${escapeHTML(path)} · 楼层：${escapeHTML(floor)}<br><span style="color:var(--text-muted);">API Key 永不落盘，只存环境变量名。</span>`;
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
      <span data-preserve-text>${escapeHTML(shortLabel)}</span>
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
}

function renderTopBar() {
  document.getElementById('workspaceDate').textContent = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date());
  document.getElementById('navTeamCount').textContent = APP_STATE.agents.length;
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
    manager: `<div class="roster-empty">${q ? '没有匹配的经理。' : '添加推理模型，负责拆单与审查。'}</div>`,
    worker: `<div class="roster-empty">${q ? '没有匹配的员工。' : '点击「添加成员」，接入执行任务的模型。'}</div>`,
    rest: `<div class="roster-empty">${q ? '没有匹配的休息成员。' : '暂时没有休息成员。'}</div>`,
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
      ? workers.map(w => `<button type="button" class="chip-btn" onclick="insertMention(${escapeHTML(JSON.stringify('@' + w.name))}); this.closest('details').open=false;">@${escapeHTML(w.name)}</button>`).join("")
      : `<span class="mention-tip">添加员工后，可以在这里指定任务接收人。</span>`;
  }

  const judgeSel = document.getElementById("skillJudgeSelect");
  if (judgeSel) {
    const prevJ = judgeSel.value;
    const managers = APP_STATE.agents.filter(a => a.floor === "manager");
    judgeSel.innerHTML = managers.map(m => `<option value="${m.id}">${escapeHTML(m.name)}</option>`).join("") || `<option value="chief">总管 (默认裁判)</option>`;
    if ([...judgeSel.options].some(o => o.value === prevJ)) judgeSel.value = prevJ;
  }
}

function getTruthfulAgentState(agent) {
  const related = (APP_STATE.tasks || []).filter(t => t.assigned_to === agent.id || t.reviewer_id === agent.id || t.manager_id === agent.id);
  const running = related.some(t => t.automation?.status === "running" || Object.values(t.roundtable_dispatch?.receipts || {}).some(r => r.status === "running"));
  if (running) return "运行中";
  const unknown = related.some(t => t.status === "unknown" || t.automation?.status === "unknown" || t.courier_dispatch?.state === "unknown");
  if (unknown) return "结果未知";
  const waitingManual = related.some(t => t.automation?.status === "waiting_manual" || Object.values(t.roundtable_dispatch?.receipts || {}).some(r => r.status === "pending_manual"));
  if (waitingManual) return "待手动回执";
  if (related.some(t => t.assigned_to === agent.id && t.status === "assigned")) return "已分配";
  if (agent.status === "exhausted") return "额度耗尽";
  if (agent.floor === "rest") return "待命/休息";
  return "就绪";
}

function renderAgentCardHTML(agent) {
  const hasQuota = agent.quota_percent !== null && agent.quota_percent !== undefined;
  const quotaClass = hasQuota ? Number(agent.quota_percent) <= 10 ? 'quota-low' : 'quota-known' : '';
  const selected = agent.id === APP_STATE.selectedAgentId && !document.getElementById('paneDetail').classList.contains('hidden');
  const truthStatus = getTruthfulAgentState(agent);
  return `<div class="agent-card ${selected ? 'selected' : ''}" draggable="true" role="button" tabindex="0"
    ondragstart="onAgentDragStart(event, '${escapeHTML(agent.id)}')" onclick="selectAgent('${escapeHTML(agent.id)}')"
    onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();selectAgent('${escapeHTML(agent.id)}')}"
    aria-label="查看 ${escapeHTML(agent.name)} 的档案">
    <div class="agent-row-top">${renderAvatarHTML(agent)}<div class="agent-meta">
      <span class="agent-name">${escapeHTML(agent.name)}</span><div class="agent-subline">${escapeHTML(agent.model)} · ${escapeHTML(truthStatus)}</div>
    </div></div>
    <div class="agent-summary">${escapeHTML(agent.specialty || '尚未填写擅长的工作')}</div>
    <div class="agent-card-footer"><span>${escapeHTML(agent.badge || agent.access_kind)}</span><span class="${quotaClass}">${hasQuota ? '剩余 ' + escapeHTML(agent.quota_percent) + '%' : '额度未填'}</span></div>
  </div>`;
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
  const gap = 130, padX = 60, baseY = 24 + edges.length * 17;
  const W = padX * 2 + gap * Math.max(1, nodes.length - 1), H = baseY + 28;
  const x = i => padX + i * gap;
  let arcs = "";
  edges.forEach((e, idx) => {
    const x1 = x(e.from), x2 = x(e.to);
    const mx = (x1 + x2) / 2, labelY = 12 + idx * 17;
    const cy = 2 * (labelY + 8) - baseY;
    const dropY = e.blocked ? baseY - 6 : labelY + 5;
    const onclick = e.fl.task_id ? `openTaskPrivateThread('${escapeHTML(e.fl.task_id)}')` : `selectAgent('${escapeHTML(e.fl.from_id)}')`;
    const title = `${escapeHTML(e.fl.created_at || '')} · ${escapeHTML(e.fl.channel || '')} · ${escapeHTML(e.fl.summary || e.fl.kind || '')}`;
    arcs += `
      <g onclick="${onclick}" style="cursor:pointer">
        <title>${title}</title>
        <path class="arc ${e.blocked ? 'blocked' : ''}" d="M ${x1} ${baseY} Q ${mx} ${cy} ${x2} ${baseY}"/>
        <path class="plane ${e.blocked ? 'blocked' : ''}" d="M ${mx - 5} ${dropY} l 10 3 l -10 3 l 2.5 -3 z"/>
        <text class="node-label" x="${mx}" y="${labelY}" text-anchor="middle">${escapeHTML((e.fl.summary || e.fl.kind || '').slice(0, 10))}</text>
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
  }).join(`<span class="step-sep">${icon('chevron')}</span>`) + (status === "rejected" ? ` <span class="step-rejected">${icon('undo')}(审查打回重做)</span>` : "") + `</div>`;
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

function taskStatusLabel(status) {
  return ({ assigned: '待认领', accepted: '已认领', working: '进行中', in_review: '待审查', delivered: '待验收', awaiting_owner: '待你定稿', accepted_done: '已完成', rejected: '待返修' })[status] || status;
}

function renderTaskBoard() {
  const strip = document.getElementById("activeTaskStrip");
  document.getElementById("taskTotalCount").textContent = APP_STATE.tasks.length;
  if (!APP_STATE.tasks.length) {
    const hasWorker = APP_STATE.agents.some(a => a.floor === "worker");
    strip.innerHTML = `<div class="empty-workspace">
      <span class="empty-symbol">${icon('box')}</span><h2>从一个任务开始。</h2>
      <p>${hasWorker ? '团队已在这里。点击右上角「新任务」，写下目标与验收标准。' : '接入你的 AI 员工，再把第一个任务交给团队。所有模型由你选择。'}</p>
      ${hasWorker ? '' : '<button class="btn btn-ghost" onclick="openRecruitModal()">添加第一位员工</button>'}
    </div>`;
    return;
  }
  const tasks = [...APP_STATE.tasks].reverse().sort((a, b) => Number(a.status === 'accepted_done') - Number(b.status === 'accepted_done'));
  strip.innerHTML = tasks.map(task => {
    const selected = task.id === APP_STATE.selectedTaskId && !document.getElementById("paneDetail").classList.contains("hidden");
    return `<button class="task-pill ${selected ? 'active' : ''}" data-open-task="${escapeHTML(task.id)}">
      <span><span class="task-name">${escapeHTML(task.title)}</span><span class="task-reference">${escapeHTML(task.id)}${isRoundtableParent(task) ? ' · 圆桌精雕' : task.is_parent ? ' · 拆分任务' : task.parent_task_id ? ' · 子任务' : ''}</span></span>
      <span class="task-assignee"><span class="assignee-initial" aria-hidden="true">${escapeHTML((task.assigned_name || '待').slice(0, 1))}</span><span>${escapeHTML(task.assigned_name || '待分配')}</span></span>
      <span class="task-state" data-status="${escapeHTML(task.status)}">${escapeHTML(taskStatusLabel(task.status))}</span>
    </button>`;
  }).join("") + `<p class="task-list-note">打开任务，查看进度、汇报与下一步操作。</p>`;
  strip.querySelectorAll('[data-open-task]').forEach(button => button.addEventListener('click', () => openTaskPrivateThread(button.dataset.openTask)));
}

function renderGroupChat() {
  renderTaskBoard();
  const stream = document.getElementById("groupChatStream");
  const nearBottom = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 100;
  stream.innerHTML = APP_STATE.groupMessages.map(msg => {
    const isOwner = msg.sender_id === "owner" || msg.sender_id === "gao";
    const kind = msg.kind || 'chat';
    const task = msg.task_id ? APP_STATE.tasks.find(t => t.id === msg.task_id) : null;
    const senderIcon = ({ task_card: 'box', big_task_card: 'users', private_report_lock: 'lock', final_delivery_card: 'check', error: 'alert', bus_error: 'alert', automation_status: 'check' })[kind] || (isOwner ? 'user' : 'chat');
    const bodyText = kind === 'private_report_lock' && task
      ? `${stripEmoji(msg.sender_name)} 已提交结论（${task.title}）`
      : (msg.text || '');
    const fullText = formatChatTextWithMentions(bodyText);
    return `<article class="chat-bubble ${isOwner ? 'from-gao' : ''} kind-${escapeHTML(kind)}">
      <div class="bubble-header"><span class="bubble-sender">${icon(senderIcon)}${escapeHTML(stripEmoji(msg.sender_name))}</span><span>${escapeHTML(msg.created_at || '')}</span></div>
      <div class="bubble-body">${fullText}</div>
      ${task ? `<div class="bubble-inline-action"><span class="task-state" data-status="${escapeHTML(task.status)}">${escapeHTML(taskStatusLabel(task.status))}</span><button type="button" class="bubble-task-link" onclick="openTaskPrivateThread('${escapeHTML(task.id)}')">查看任务 ${escapeHTML(task.id)} →</button></div>` : ''}
    </article>`;
  }).join("");
  if (nearBottom) stream.scrollTop = stream.scrollHeight;
}

// =========================================================================
// 右栏 Tab 1：成员独立身份档案 (Profile)
// =========================================================================
async function handleOpenWebLogin(agentId) {
  try {
    const res = await callOfficeAction('openweblogin', { agent_id: agentId });
    if (res && res.opened) {
      showToast('已打开专属后台登录窗口，请登录一次后关闭窗口即可开启自动抓取。');
    }
  } catch (err) {
    showToast(`打开登录窗口失败：${err.message}`, true);
  }
}

function selectAgent(agentId) {
  APP_STATE.selectedAgentId = agentId;
  switchRightTab("profile");
  renderRoster();
  renderSelectedAgentProfile();
  openDetailPanel();
  document.getElementById('panelProfile').scrollTop = 0;
}

// Keep disclosure choices only while the same member/task remains selected.
function captureDetailSections(container, selectionId) {
  const openSections = new Map();
  if (container.dataset.detailSelection === String(selectionId)) {
    container.querySelectorAll('details[data-section]').forEach(detail => {
      openSections.set(detail.dataset.section, detail.open);
    });
  }
  container.dataset.detailSelection = String(selectionId);
  return (section, initiallyOpen = false) =>
    (openSections.has(section) ? openSections.get(section) : initiallyOpen) ? ' open' : '';
}

function renderSelectedAgentProfile() {
  const agent = APP_STATE.agents.find(a => a.id === APP_STATE.selectedAgentId) || APP_STATE.agents[0];
  const container = document.getElementById("agentProfileContent");
  if (!container) return;
  const sectionOpen = captureDetailSections(container, agent ? agent.id : '');
  if (!agent) {
    container.innerHTML = `<section class="section-body"><h2 class="detail-title">成员档案</h2><p class="detail-meta">暂无成员，请先招募 AI Agent。</p></section>`;
    return;
  }
  const rawPct = agent.quota_percent;
  const hasPct = rawPct !== null && rawPct !== undefined && rawPct !== '' &&
    Number.isFinite(Number(rawPct)) && Number(rawPct) >= 0 && Number(rawPct) <= 100;
  const pct = hasPct ? Number(rawPct) : null;
  const agentArg = escapeHTML(JSON.stringify(String(agent.id)));
  const loginUrl = /^https?:\/\//i.test(agent.login_url || '') ? agent.login_url : '';
  const usageUrl = /^https?:\/\//i.test(agent.usage_url || '') ? agent.usage_url : '';
  const skillBadges = (agent.skills || []).map(slug => {
    const sk = APP_STATE.skills.find(s => s.slug === slug);
    return `<span class="vendor-chip" data-preserve-text>${escapeHTML(sk ? sk.name : slug)}</span>`;
  }).join(' ') || `<span class="detail-meta">暂未装配固定技能</span>`;

  container.innerHTML = `
    <header class="detail-header profile-header">
      ${renderAvatarHTML({ ...agent, status: escapeHTML(agent.status || 'ready') })}
      <div>
        <h2 class="detail-title" data-preserve-text>${escapeHTML(agent.name)}</h2>
        <p class="detail-meta" data-preserve-text>${escapeHTML(agent.role_label)} · ${escapeHTML(agent.badge)}</p>
      </div>
    </header>

    <section class="section-body" aria-label="模型与额度">
      <div class="kv-row"><span>厂商</span><strong data-preserve-text>${escapeHTML(agent.vendor)} · ${escapeHTML(agent.brand)}</strong></div>
      <div class="kv-row"><span>模型</span><span><code>${escapeHTML(agent.model)}</code> ${agent.verified_version ? icon('check') + '已核实' : icon('alert') + '待核实'}</span></div>
      <div class="kv-row"><span>通道</span><span data-preserve-text>${escapeHTML(agent.access_kind)} · ${escapeHTML(agent.badge)}</span></div>
      <div class="kv-row"><span>剩余额度</span><strong>${hasPct ? `${pct}%` : '额度未填'}</strong></div>
      ${agent.login_url ? `<div class="detail-actions" style="margin-top:10px;"><button type="button" class="btn btn-xs btn-primary" onclick="handleOpenWebLogin('${escapeHTML(agent.id)}')">后台登录一次（开启自动抓网页）</button></div>` : ''}
      <p class="detail-meta" data-preserve-text>${escapeHTML(agent.quota_note || '未实查，不推测可用额度。')}</p>
      ${hasPct && pct <= 10 ? `<p class="detail-meta quota-warning" role="status">${icon('alert')}剩余额度 ≤10%。${agent.access_kind === 'subscription' ? '订阅到限额可能降级，请核对下方降级规则。' : pct === 0 && agent.access_kind === 'api' ? 'API 额度已归零，请调至休息并轮换其他员工。' : '请核实用量，必要时轮换其他员工。'}</p>` : ''}
    </section>

    <details class="detail-section" data-section="account"${sectionOpen('account')}>
      <summary>账号与模型资料</summary>
      <div class="section-body">
        <p class="detail-meta">一位成员对应独立模型与通道，不共用 Token 池。</p>
        <div class="kv-row"><span>会员等级</span><span data-preserve-text>${escapeHTML(agent.tier || (agent.access_kind === 'api' ? (agent.paid ? '付费·API' : '免费·API') : '待同步'))}</span></div>
        <div class="kv-row"><span>到期时间</span><span data-preserve-text>${escapeHTML(agent.expires_at || (agent.access_kind === 'api' ? '按余额消耗，无固定到期日' : '未填/待同步'))}</span></div>
        <div class="kv-row"><span>核实状态</span><span data-preserve-text>${escapeHTML(agent.account_status || '待核实')}</span></div>
        <div class="kv-row"><span>登录状态</span><span data-preserve-text>${escapeHTML(agent.login_state || '未同步')}</span></div>
        <div class="kv-row"><span>已记录 Token</span><span>${agent.tokens_used == null ? '未记录' : escapeHTML(agent.tokens_used)}</span></div>
        <div class="kv-row"><span>已记录会话</span><span>${agent.session_count == null ? '未记录' : escapeHTML(agent.session_count)}</span></div>
        <div class="kv-row"><span>已挂载工具</span><span data-preserve-text>${escapeHTML((agent.attached_tools || []).join('、') || '暂无')}</span></div>
        <div class="kv-row"><span>降级规则</span><span data-preserve-text>${escapeHTML(agent.fallback_note || '未指定')}</span></div>
        ${agent.available_models && agent.available_models.length ? `<div class="kv-row"><span>接口实查模型</span><code>${escapeHTML(agent.available_models.join(', '))}</code></div>` : ''}
        ${agent.sub_models && agent.sub_models.length ? `<div class="kv-row"><span>子模型与倍率</span><span>${agent.sub_models.map(m => `<span class="vendor-chip">${escapeHTML(m)}</span>`).join(' ')}</span></div>` : ''}
        ${agent.last_synced_at ? `<div class="kv-row"><span>上次同步</span><span data-preserve-text>${escapeHTML(agent.last_synced_at)}</span></div>` : ''}
        ${agent.key_env ? `<div class="kv-row"><span>密钥环境变量</span><code>$${escapeHTML(agent.key_env)}</code></div>` : ''}
        <p class="detail-meta">密钥仅读环境变量，不展示、不落盘。</p>
        ${loginUrl ? `<a class="inline-link" href="${escapeHTML(loginUrl)}" target="_blank" rel="noopener noreferrer">前往厂商登录页 ${icon('external')}</a>` : ''}
      </div>
    </details>

    <details class="detail-section" data-section="quota"${sectionOpen('quota')}>
      <summary>查额度与登记实查值</summary>
      <div class="section-body">
        <p class="detail-meta">只登记实际查到的额度；查不到就保持「额度未填」。</p>
        <div class="detail-actions">
          ${usageUrl ? `<a class="btn btn-ghost" href="${escapeHTML(usageUrl)}" target="_blank" rel="noopener noreferrer">${icon('external')}官网查额度</a>` : `<span class="detail-meta">未提供独立查额度链接</span>`}
          ${agent.access_kind === 'api' ? `<button type="button" class="btn btn-ghost" onclick="handleCheckLiveQuota(${agentArg})">${icon('gauge')}接口实查余额</button>` : ''}
        </div>
        <div class="form-group">
          <label for="manualQuotaPct">实查剩余百分比（留空表示未知）</label>
          <input type="number" id="manualQuotaPct" class="obsidian-input" min="0" max="100" step="1" placeholder="0–100 或留空" value="${hasPct ? pct : ''}" />
        </div>
        <div class="detail-actions">
          <button type="button" class="btn btn-primary" onclick="handleUpdateManualQuota(${agentArg})">保存实查值</button>
          <button type="button" class="btn btn-ghost" onclick="handleClearManualQuota(${agentArg})">标为额度未填</button>
        </div>
      </div>
    </details>

    <section class="section-body">
      <h3 class="detail-title">擅长与技能</h3>
      <p class="detail-meta" data-preserve-text>${escapeHTML(agent.specialty || '暂未填写特长')}</p>
      <div class="detail-actions">${skillBadges}</div>
    </section>

    <details class="detail-section" data-section="role"${sectionOpen('role')}>
      <summary>调岗与休息</summary>
      <div class="section-body">
        <p class="detail-meta">更改成员岗位，也可拖拽成员到对应楼层。</p>
        <div class="detail-actions">
          <button type="button" class="btn btn-ghost" onclick="callOfficeAction('moveagent', {id:${agentArg}, floor:'manager'})">${icon('users')}调至经理</button>
          <button type="button" class="btn btn-ghost" onclick="callOfficeAction('moveagent', {id:${agentArg}, floor:'worker'})">${icon('user')}调至员工</button>
          <button type="button" class="btn btn-ghost" onclick="callOfficeAction('moveagent', {id:${agentArg}, floor:'rest'})">${icon('refresh')}调至休息</button>
        </div>
      </div>
    </details>
  `;
  neutralizePanel("agentProfileContent");
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
  renderSelectedTaskThread();
  openDetailPanel();
  document.getElementById('panelThread').scrollTop = 0;
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
  if (!container) return;
  const sameTask = task && container.dataset.detailSelection === String(task.id);
  const previousReviewer = sameTask && container.querySelector('#reviewAgentSelect');
  const previousIssues = sameTask && container.querySelector('#reviewIssuesInput');
  const sectionOpen = captureDetailSections(container, task ? task.id : '');
  if (!task) {
    if (badge) badge.textContent = '';
    container.innerHTML = `<section class="section-body"><h2 class="detail-title">任务详情</h2><p class="detail-meta">选择一个任务，查看进度、执行或向经理汇报。</p></section>`;
    return;
  }

  APP_STATE.selectedTaskId = task.id;
  if (badge) badge.textContent = task.id;
  document.getElementById('paneDetail').classList.toggle('roundtable-detail', isRoundtableParent(task));
  if (isRoundtableParent(task)) {
    renderRoundtablePanel(container, task, sectionOpen);
    return;
  }
  const roundtableParent = APP_STATE.tasks.find(parent => parent.id === task.parent_task_id && isRoundtableParent(parent));
  const taskArg = escapeHTML(JSON.stringify(String(task.id)));
  const terminal = task.status === 'accepted_done';
  const disabled = terminal ? ' disabled' : '';
  const msgs = APP_STATE.taskMessages[task.id] || [];
  const draft = APP_STATE.reportDrafts[task.id] || {};
  const worker = APP_STATE.agents.find(a => a.id === task.assigned_to);
  const channel = worker ? worker.access_kind : '';
  const statusLabels = {
    assigned: '待领取', accepted: '已领取', working: '进行中', in_review: '待独立审查',
    delivered: '待验收', accepted_done: '已验收', rejected: '待返修',
  };
  const workers = APP_STATE.agents.filter(a => a.floor === 'worker' && a.status !== 'exhausted');
  const transferOptions = workers.map(w => {
    const sameVendor = task.assigned_vendor && String(w.vendor).trim().toLowerCase() === String(task.assigned_vendor).trim().toLowerCase();
    return `<option value="${escapeHTML(w.id)}">${escapeHTML(w.name)} (${escapeHTML(w.vendor)} · ${escapeHTML(w.badge)})${sameVendor ? ' [同厂商将拦截]' : ' [可跨厂商轮换]'}</option>`;
  }).join('') || '<option value="">暂无可转交员工，请先招募或调岗</option>';
  const reviewerCandidates = APP_STATE.agents.filter(
    a => a.floor !== 'rest' && a.status !== 'exhausted' && a.id !== task.assigned_to
  );
  const reviewerId = previousReviewer ? previousReviewer.value : task.reviewer_id;
  const reviewerOptions = reviewerCandidates.map(r =>
    `<option value="${escapeHTML(r.id)}"${r.id === reviewerId ? ' selected' : ''}>${escapeHTML(r.name)} (${escapeHTML(r.badge)})</option>`
  ).join('') || '<option value="">暂无独立审查者，请先招募或调岗</option>';
  const reviewIssues = task.review_issues || [];
  const childSubtasks = (task.subtask_ids || []).map(sid => APP_STATE.tasks.find(t => t.id === sid)).filter(Boolean);
  const childrenReady = childSubtasks.length > 0 && childSubtasks.length === (task.subtask_ids || []).length &&
    childSubtasks.every(sub => sub.worker_reported && (!sub.requires_code_review || sub.review_status === 'approved'));

  // One contextual next step; all alternatives retain the existing handlers.
  const call = (handler, ...args) => `${handler}(${args.map(arg => JSON.stringify(arg)).join(', ')})`;
  const actions = {
    claim: { label: '领取任务', icon: 'check', code: call('handleClaimTask', task.id, task.assigned_to || '') },
    run: { label: channel === 'cli' ? '通过 CLI 执行' : channel === 'api' ? '通过 API 执行' : 'API / CLI 真调执行', icon: 'send', code: call('handleRunAdapterTask', task.id, true) },
    dryrun: { label: '干跑演练（0 消耗）', icon: 'refresh', code: call('handleRunAdapterTask', task.id, false) },
    web: { label: '打开网页并复制指令', icon: 'external', code: call('handleOpenWebAndCopyPrompt', task.id) },
    export: { label: '导出 .md 并复制触发句', icon: 'box', code: call('handleExportTaskMd', task.id) },
    copy: { label: '仅复制任务指令', icon: 'chat', code: call('handleCopyWorkerPrompt', task.id), readOnly: true },
    diff: { label: '抓取本地 git diff 摘要', icon: 'search', code: call('handleCollectGitDiff', task.id), readOnly: true },
    deliver: { label: '经理统筹交付', icon: 'box', code: call('handleDeliverFinalResult', task.id) },
    accept: { label: '验收通过', icon: 'check', code: call('handleReviewFinalResult', task.id, 'verified') },
    reject: { label: '打回重做', icon: 'undo', code: call('handleReviewFinalResult', task.id, 'rejected') },
    parentRun: { label: '并行执行 API / CLI 子单', icon: 'send', code: call('handleRunBigTaskSubtasks', task.id, true) },
    parentDryrun: { label: '批量干跑子单（0 消耗）', icon: 'refresh', code: call('handleRunBigTaskSubtasks', task.id, false) },
    aggregate: { label: '汇总全部子单交付', icon: 'box', code: call('handleAggregateBigTask', task.id) },
    review: { label: '审阅代码与问题清单', icon: 'eye', code: "document.querySelector('#taskThreadContent details[data-section=review]').open = true; document.getElementById('reviewAgentSelect').focus()", readOnly: true },
    reviewDryrun: { label: '干跑 diff 审查', icon: 'search', code: call('handleAutoCodeReview', task.id, false) },
    reviewLive: { label: '真调审查者读 diff', icon: 'eye', code: call('handleAutoCodeReview', task.id, true) },
    reviewPass: { label: '手动审查通过', icon: 'check', code: call('handleSubmitCodeReview', task.id, true, false) },
    reviewReject: { label: '提交问题并打回', icon: 'undo', code: `if (document.getElementById('reviewIssuesInput').value.trim()) { ${call('handleSubmitCodeReview', task.id, false, false)} } else { showToast('请填写实际问题清单后再打回', true); document.getElementById('reviewIssuesInput').focus(); }` },
    merge: { label: '请求合并授权', icon: 'lock', code: call('handleRequestCriticalApproval', task.id, 'merge') },
    deleteCode: { label: '请求删代码授权', icon: 'lock', code: call('handleRequestCriticalApproval', task.id, 'delete_code') },
    deploy: { label: '请求部署授权', icon: 'lock', code: call('handleRequestCriticalApproval', task.id, 'deploy') },
    reassign: { label: '转交任务', icon: 'corner', code: call('handleReassignTask', task.id) },
  };
  actions.claim.code += `.then(() => {
    const current = APP_STATE.tasks.find(t => t.id === ${JSON.stringify(task.id)});
    const report = document.querySelector('#taskThreadContent details[data-section=report]');
    if (report && current && ['accepted', 'working'].includes(current.status) && APP_STATE.selectedTaskId === current.id) report.open = true;
  })`;
  if (roundtableParent) {
    actions.export = { ...actions.copy, label: '复制桌面端单次工单（手动执行）', readOnly: false };
    actions.copy.readOnly = false;
  }
  const chosenExecution = channel === 'desktop' ? 'export' : ['web', 'subscription'].includes(channel) ? 'web' : ['api', 'cli'].includes(channel) ? 'run' : 'copy';
  let primaryKeys = [];
  if (!terminal) {
    if (task.status === 'delivered') primaryKeys = ['accept', 'reject'];
    else if (task.is_parent) primaryKeys = [childrenReady ? 'aggregate' : 'parentRun'];
    else if (task.status === 'assigned') primaryKeys = ['claim'];
    else if (task.requires_code_review && task.review_status !== 'approved' && (task.status === 'in_review' || (task.worker_reported && task.status !== 'rejected'))) primaryKeys = ['review'];
    else if (task.worker_reported && task.status !== 'rejected') primaryKeys = ['deliver'];
    else primaryKeys = [chosenExecution];
  }
  const childDispatch = roundtableParent && task.roundtable_dispatch;
  const childReceipt = childDispatch?.receipts?.[childDispatch.current];
  const childLocal = roundtableChildUI.get(task.id) || {};
  const actionButton = (key, primary = false) => {
    const action = actions[key];
    const locked = roundtableParent && (childLocal.busy || childLocal.uncertain ||
      (roundtableParent.roundtable_state?.stage !== 'collecting' && !action.readOnly) ||
      (childReceipt && ['run', 'web', 'export', 'copy'].includes(key)));
    return `<button type="button" class="btn ${primary && key !== 'reject' ? 'btn-primary' : 'btn-ghost'}" onclick="${escapeHTML(action.code)}"${locked || (terminal && !action.readOnly && !['merge', 'deleteCode', 'deploy'].includes(key)) ? ' disabled' : ''}>${icon(action.icon)}${escapeHTML(action.label)}</button>`;
  };
  const secondaryActions = keys => keys.filter(key => !primaryKeys.includes(key)).map(key => actionButton(key)).join('');
  const reportInitiallyOpen = !terminal && !task.is_parent && !task.worker_reported && ['accepted', 'working', 'rejected'].includes(task.status);

  container.innerHTML = `
    <header class="detail-header">
      <h2 class="detail-title" data-preserve-text>${escapeHTML(task.title)}</h2>
      <p class="detail-meta"><strong data-preserve-text>${escapeHTML(statusLabels[task.status] || task.status)}</strong> · <span data-preserve-text>${escapeHTML(task.id)}</span></p>
      <p class="detail-meta">执行：<strong data-preserve-text>${escapeHTML(task.assigned_name || '待指派')}</strong> · <span data-preserve-text>${escapeHTML(task.assigned_vendor || '厂商待确定')}${channel ? ` / ${escapeHTML(channel)}` : ''}</span><br>经理：<span data-preserve-text>${escapeHTML(task.manager_name || '待指定')}</span></p>
      ${renderTaskStepFlow(task.status, task)}
      ${primaryKeys.length ? `<div class="detail-actions">${primaryKeys.map(key => actionButton(key, true)).join('')}</div>` : '<p class="detail-meta">任务已验收，保留交付与汇报记录供查阅。</p>'}
      ${['api', 'cli'].includes(channel) && primaryKeys.includes('run') ? '<p class="detail-meta">调用已配置的真实模型；API 密钥仅读环境变量。</p>' : ''}
      ${task.circuit_breaker ? `<p class="detail-meta" data-preserve-text>${icon('alert')}需人工处理：${escapeHTML(task.circuit_breaker)}</p>` : ''}
    </header>

    ${roundtableParent ? `<section class="section-body"><h3 class="detail-title">圆桌采集 · 单发单收</h3><p class="detail-meta" data-preserve-text>实际回执：${escapeHTML(childReceipt?.status || '尚未派发')}${childLocal.uncertain ? ' · 上次请求未确认，请先到父单核对最新状态' : ''}。只回结论、改动文件和测试结果；进行中、未知或已回收的子单不重复投喂。</p>${childReceipt ? `<details class="detail-section" data-section="child-receipt"${sectionOpen('child-receipt')}><summary>查看派发回执与已派出指令（不要重复发送）</summary>${roundtableOutput(childReceipt)}</details>` : ''}</section>` : ''}

    ${task.final_delivery_text ? `<section class="section-body"><h3 class="detail-title">交付结果</h3><p data-preserve-text style="white-space:pre-wrap;overflow-wrap:anywhere;">${formatChatTextWithMentions(task.final_delivery_text)}</p></section>` : ''}

    ${task.is_parent ? `
      <section class="section-body">
        <h3 class="detail-title">子单进度 · ${childSubtasks.length}</h3>
        <div class="subtask-list">
          ${childSubtasks.map(sub => `<button type="button" class="btn btn-ghost subtask-row" onclick="${escapeHTML(call('openTaskPrivateThread', sub.id))}"><span data-preserve-text>${escapeHTML(sub.id)} · ${escapeHTML(sub.title)}</span><span class="detail-meta" data-preserve-text>${escapeHTML(statusLabels[sub.status] || sub.status)}${sub.requires_code_review ? ` · 审查 ${escapeHTML(sub.review_status || 'pending_review')}` : ''}</span></button>`).join('') || '<p class="detail-meta">暂无可显示的子单。</p>'}
        </div>
      </section>
      <details class="detail-section" data-section="subtasks"${sectionOpen('subtasks')}>
        <summary>子单批量执行与汇总</summary>
        <div class="section-body">
          <p class="detail-meta">真调仅执行 API / CLI 子单；网页与桌面通道等待实际回执。全部子单汇报、代码审查通过后再汇总。</p>
          <div class="detail-actions">${secondaryActions(['parentRun', 'parentDryrun', 'aggregate'])}</div>
        </div>
      </details>
    ` : ''}

    <details class="detail-section" data-section="brief"${sectionOpen('brief')}>
      <summary>任务目标与验收标准</summary>
      <div class="section-body">
        ${[['目标', task.goal], ['输入内容', task.input_text], ['输出格式', task.output_format], ['验收标准', task.acceptance], ['执行约束', task.rule_footer]].map(([label, value]) => `<h3 class="detail-title">${label}</h3><p data-preserve-text style="white-space:pre-wrap;overflow-wrap:anywhere;">${escapeHTML(value || '未填写')}</p>`).join('')}
        ${task.parent_task_id ? `<div class="detail-actions"><button type="button" class="btn btn-ghost" onclick="${escapeHTML(call('openTaskPrivateThread', task.parent_task_id))}">${icon('corner')}打开所属大任务</button></div>` : ''}
      </div>
    </details>

    <details class="detail-section${terminal ? ' hidden' : ''}" data-section="report"${sectionOpen('report', reportInitiallyOpen || (!terminal && Boolean(draft.conclusion || draft.files || draft.tests)))}>
      <summary>${task.worker_reported ? '补充私聊汇报' : '向经理汇报结果'}</summary>
      <div class="section-body">
        <p class="detail-meta">只传结论、改动文件与测试结果，不传完整对话。正文仅在任务私聊中展示，群里只留提示。</p>
        <form onsubmit="handleWorkerPrivateReport(event, ${taskArg})" class="conclusion-grid">
          <div class="form-group">
            <label for="reportConclusionInput">结论</label>
            <input type="text" id="reportConclusionInput" class="obsidian-input" required placeholder="做了什么，是否完成" value="${escapeHTML(draft.conclusion || '')}" oninput="updateReportDraft(${taskArg}, 'conclusion', this.value)"${disabled} />
          </div>
          <div class="form-group">
            <label for="reportFilesInput">改动文件</label>
            <input type="text" id="reportFilesInput" class="obsidian-input" placeholder="文件路径，用逗号分隔；没有则填「无」" value="${escapeHTML(draft.files || '')}" oninput="updateReportDraft(${taskArg}, 'files', this.value)"${disabled} />
          </div>
          <div class="form-group">
            <label for="reportTestInput">测试结果</label>
            <input type="text" id="reportTestInput" class="obsidian-input" placeholder="实际运行的测试及结果；未运行请如实填写" value="${escapeHTML(draft.tests || '')}" oninput="updateReportDraft(${taskArg}, 'tests', this.value)"${disabled} />
          </div>
          <div class="detail-actions"><button type="submit" class="btn btn-ghost"${disabled}>${icon('lock')}发送私聊汇报</button></div>
        </form>
      </div>
    </details>

    <details class="detail-section${terminal ? ' hidden' : ''}" data-section="execution"${sectionOpen('execution')}>
      <summary>其他执行方式</summary>
      <div class="section-body">
        <p class="detail-meta">干跑只演练路由，不代表真实完成。真调遵循模型、额度与降级限制；网页、桌面执行需实际回填结果。</p>
        <div class="detail-actions">${secondaryActions(['run', 'dryrun', 'web', 'export', 'copy'])}</div>
      </div>
    </details>

    ${task.requires_code_review ? `
      <details class="detail-section" data-section="review"${sectionOpen('review')}>
        <summary>独立代码审查</summary>
        <div class="section-body">
          <p class="detail-meta">写手与审查者必须分开。当前审查者：<strong data-preserve-text>${escapeHTML(task.reviewer_name || '待指定')}</strong> · <span data-preserve-text>${escapeHTML(task.review_status || 'pending_review')}</span>${task.revision_round ? ` · 已返修 ${escapeHTML(task.revision_round)} 轮` : ''}</p>
          ${reviewIssues.length ? `<h3 class="detail-title">待修改问题</h3><ol>${reviewIssues.map(issue => `<li data-preserve-text>${escapeHTML(issue)}</li>`).join('')}</ol>` : ''}
          <div class="form-group">
            <label for="reviewAgentSelect">独立审查者</label>
            <select id="reviewAgentSelect" class="select-sm"${disabled}>${reviewerOptions}</select>
          </div>
          <div class="form-group">
            <label for="reviewIssuesInput">问题清单</label>
            <textarea id="reviewIssuesInput" rows="3" class="obsidian-input" placeholder="每行一条：文件:行号 问题描述；通过时无需填写"${disabled}>${escapeHTML(previousIssues ? previousIssues.value : '')}</textarea>
          </div>
          <p class="detail-meta">手动打回必须填写实际问题。干跑仅用于演练，不代替真实审查。</p>
          <div class="detail-actions">${secondaryActions(['reviewLive', 'reviewDryrun', 'reviewPass', 'reviewReject'])}</div>
        </div>
      </details>
    ` : ''}

    <details class="detail-section${terminal ? ' hidden' : ''}" data-section="delivery"${sectionOpen('delivery')}>
      <summary>交付与验收</summary>
      <div class="section-body">
        <p class="detail-meta">请先汇报真实结论；代码任务必须独立审查通过，才能交付和验收。</p>
        <div class="detail-actions">${secondaryActions(['deliver', ...(task.status === 'delivered' || terminal ? ['accept', 'reject'] : [])])}</div>
      </div>
    </details>

    <details class="detail-section" data-section="workspace"${sectionOpen('workspace')}>
      <summary>工作区与本地改动</summary>
      <div class="section-body">
        <div class="form-group">
          <label for="customWorkspaceInput">目标工作文件夹（选填）</label>
          <input type="text" id="customWorkspaceInput" class="obsidian-input" placeholder="留空使用本仓库" value="${escapeHTML(APP_STATE.customWorkspaceDir || '')}" oninput="APP_STATE.customWorkspaceDir = this.value.trim()" />
        </div>
        <p class="detail-meta">用于 CLI、diff 审查与 .md 工单导出。抓取 diff 只读取本地改动摘要，不调用模型。</p>
        <div class="detail-actions">${actionButton('diff')}</div>
      </div>
    </details>

    <details class="detail-section" data-section="approval"${sectionOpen('approval')}>
      <summary>关键操作授权</summary>
      <div class="section-body">
        <p class="detail-meta">合并、删代码、部署必须先请求人工授权；请求不等于执行。</p>
        <div class="detail-actions">${secondaryActions(['merge', 'deleteCode', 'deploy'])}</div>
      </div>
    </details>

    ${roundtableParent ? renderRoundtableHandoff(task, roundtableParent) : `
    <details class="detail-section${terminal ? ' hidden' : ''}" data-section="reassign"${sectionOpen('reassign')}>
      <summary>跨厂商转交</summary>
      <div class="section-body">
        <p class="detail-meta">仅限不同厂商轮换；同厂商倒手、休息或额度耗尽的成员会被拦截。</p>
        <div class="form-group">
          <label for="reassignTargetSelect">接手员工</label>
          <select id="reassignTargetSelect" class="select-sm"${disabled}>${transferOptions}</select>
        </div>
        <div class="detail-actions">${actionButton('reassign')}</div>
      </div>
    </details>`}

    <section class="section-body">
      <h3 class="detail-title">私聊汇报记录 · ${msgs.length}</h3>
      <div class="thread-messages">
        ${msgs.map(m => `<article class="thread-message"><header class="detail-meta"><strong data-preserve-text>${escapeHTML(m.sender_name)}</strong> <span data-preserve-text>${escapeHTML(m.created_at || '')}</span></header><p data-preserve-text style="white-space:pre-wrap;overflow-wrap:anywhere;">${escapeHTML(m.text)}</p></article>`).join('') || '<p class="detail-meta">暂无私聊汇报。执行后请提交实际结果。</p>'}
      </div>
    </section>
  `;
  neutralizePanel("taskThreadContent");
  if (roundtableParent) {
    bindRoundtableHandoffs(container, roundtableParent);
    const freezeReport = childLocal.uncertain || roundtableParent.roundtable_state?.stage !== 'collecting' ||
      ['running', 'unknown', 'blocked', 'invalid', 'completed'].includes(childReceipt?.status);
    if (freezeReport) container.querySelectorAll('[data-section="report"] input, [data-section="report"] button').forEach(el => { el.disabled = true; });
    if (childLocal.busy) container.querySelectorAll('button, input, select, textarea').forEach(el => { el.disabled = true; });
  }
}

// =========================================================================
// 五阶段圆桌：独立父任务面板，不复用旧 runroundtable 或父单交付动作。
// =========================================================================
const roundtableUI = new Map();
const roundtableChildUI = new Map();
function roundtableChildParent(taskId) {
  const child = APP_STATE.tasks.find(task => task.id === taskId);
  return child && APP_STATE.tasks.find(task => task.id === child.parent_task_id && isRoundtableParent(task));
}
async function roundtableChildAction(taskId, action, payload) {
  const local = roundtableChildUI.get(taskId) || {};
  if (local.busy || local.uncertain) return null;
  local.busy = true;
  roundtableChildUI.set(taskId, local);
  renderSelectedTaskThread();
  try { return await callOfficeAction(action, payload); }
  catch (error) {
    local.uncertain = true;
    showToast(`${error.message}。已停止；请在圆桌父单核对最新状态，不要重复派发。`, true);
    return null;
  } finally { local.busy = false; renderSelectedTaskThread(); }
}
const ROUNDTABLE_STAGES = ['资料入篮', 'A 收料出策', 'B 整合产出', 'C 红队改良', 'A / B 对比与拍板'];
function isRoundtableParent(task) {
  return Boolean(task && task.is_parent && task.mode === 'roundtable');
}
function roundtableLocal(taskId) {
  if (!roundtableUI.has(taskId)) roundtableUI.set(taskId, { busy: false, prompt: null, drafts: {}, comment: '', notice: '', plan: null, uncertain: null });
  return roundtableUI.get(taskId);
}
function roundtableText(value) {
  return typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2);
}
function roundtableAttempts(state) {
  return Array.isArray(state.attempts) ? state.attempts : Object.entries(state.attempts || {}).map(([key, value]) => ({ stage_key: key, ...(typeof value === 'object' ? value : { status: value }) }));
}
function roundtableStageIndex(stage) {
  const key = String(stage ?? '').toLowerCase();
  const numbered = key.match(/^(?:stage_?)?([0-4])(?:$|[_-])/);
  if (numbered) return Number(numbered[1]);
  const aliases = {
    collecting: 0, collection: 0, basket: 0, collecting_materials: 0,
    a: 1, architect: 1, manager_a: 1, manager_a_prompt: 1,
    b: 2, builder: 2, draft_v1: 2, manager_b: 2,
    c: 3, critic: 3, refiner: 3, refined_v2: 3, manager_c: 3,
    'a-comparison': 4, 'b-comparison': 4, rejected: 4,
    compare_a: 4, compare_b: 4, comparison_a: 4, comparison_b: 4, compare: 4,
    awaiting_owner: 4, completed: 4, accepted: 4, accepted_done: 4, revision_requested: 4,
  };
  return Object.hasOwn(aliases, key) ? aliases[key] : -1;
}
function roundtableSeat(state, seat) {
  const stored = state.seats?.[seat] ?? state.seats?.[seat.toLowerCase()] ?? state.seats?.[`seat_${seat.toLowerCase()}`];
  const id = typeof stored === 'object' && stored ? (stored.agent_id || stored.id) : stored;
  return (typeof stored === 'object' && stored ? stored : APP_STATE.agents.find(a => a.id === id)) || { id, name: id || '未指定', vendor: '未标注', model: '未标注' };
}
function roundtableGate(task) {
  const state = task.roundtable_state || {};
  const stage = roundtableStageIndex(state.stage);
  const attempts = roundtableAttempts(state);
  const waiting = state.stage === 'awaiting_owner';
  const done = ['completed', 'accepted', 'accepted_done', 'revision_requested', 'rejected'].includes(state.stage) || task.status === 'accepted_done';
  const blocked = attempts.some(a => ['pending', 'running', 'unknown', 'invalid', 'blocked', 'error', 'failed'].includes(a.status)) ||
    ['pending', 'running', 'unknown', 'invalid', 'blocked', 'error', 'failed'].includes(state.status) || Boolean(task.circuit_breaker);
  const activeSeat = stage === 1 ? 'A' : stage === 2 ? 'B' : stage === 3 ? 'C' : /(?:compare|comparison).*b|b-comparison|stage_?4_b/i.test(String(state.stage)) ? 'B' : 'A';
  const manager = roundtableSeat(state, activeSeat);
  const pendingManual = attempts.find(a => a.stage_key === state.stage && a.status === 'pending_manual');
  const manual = ['web', 'subscription', 'desktop'].includes(manager.access_kind) || Boolean(pendingManual);
  const children = (task.subtask_ids || []).map(id => APP_STATE.tasks.find(child => child.id === id));
  const basketReady = stage !== 0 || (children.length > 0 && children.every(child => child?.worker_reported &&
    (!child.requires_code_review || (child.review_status === 'approved' && child.roundtable_review?.dry_run === false))));
  return { stage, waiting, done, blocked, manual, pendingManual, basketReady, activeSeat, manager };
}
function roundtableSource(state, keys) {
  const records = roundtableAttempts(state).filter(a => keys.includes(String(a.stage_key || a.stage)));
  const receipt = records.at(-1);
  if (!receipt) return '回执来源：未标注';
  const source = receipt.provenance || receipt.source || receipt.result_source || receipt.mode;
  const label = source === 'manual' ? '人工粘贴的外部模型输出' : source === 'adapter' ? '实际 API / CLI 调用' : source ? roundtableText(source) : '未标注';
  const seat = receipt.seat;
  return `回执来源：${label}${seat ? ` · ${seat.vendor} / ${seat.model}` : receipt.agent_id ? ` · ${receipt.agent_id}` : ''}`;
}
function roundtableOutput(value, empty = '尚未收到实际结果。') {
  return value == null || value === '' || (Array.isArray(value) && !value.length)
    ? `<p class="detail-meta">${empty}</p>`
    : `<pre class="roundtable-output" tabindex="0" data-preserve-text>${escapeHTML(roundtableText(value))}</pre>`;
}
function renderRoundtableHandoff(child, parent) {
  if (roundtableStageIndex(parent.roundtable_state?.stage) !== 0 || child.worker_reported || child.status === 'accepted_done') return '';
  const dispatch = child.roundtable_dispatch || {};
  const receipt = dispatch.receipts?.[dispatch.current];
  if (!receipt || !['unknown', 'blocked', 'pending_manual'].includes(receipt.status)) return '';
  const previousWorkers = Object.values(dispatch.receipts || {}).map(entry => entry.worker_id);
  const source = APP_STATE.agents.find(a => a.id === child.assigned_to);
  const vendor = roundtableIdentity(child.assigned_vendor || source?.vendor);
  const choices = APP_STATE.agents.filter(a => a.floor === 'worker' && !a.paid && a.status === 'ready' && !previousWorkers.includes(a.id) &&
    vendor && roundtableIdentity(a.vendor) && roundtableIdentity(a.vendor) !== vendor);
  return `<div class="roundtable-handoff" data-rt-child="${escapeHTML(child.id)}">
    <p class="detail-meta">若验证码或执行卡住，先在原客户端确认任务已停止，再单点转交。进行中或已回收的子单不得重复派发。</p>
    <label>跨厂商接手员工<select class="select-sm" data-rt-target${choices.length ? '' : ' disabled'}><option value="">选择另一位 1F 员工</option>${choices.map(a => `<option value="${escapeHTML(a.id)}">${escapeHTML(a.name)} · ${escapeHTML(a.vendor)}</option>`).join('')}</select></label>
    ${choices.length ? '' : '<p class="detail-meta">暂无不同厂商的可用员工，请先在团队接入或调岗。</p>'}
    <button type="button" class="btn btn-ghost" data-rt-handoff${choices.length ? '' : ' disabled'}>确认原任务已停止并转交</button>
  </div>`;
}
function bindRoundtableHandoffs(container, parent) {
  const local = roundtableLocal(parent.id);
  container.querySelectorAll('[data-rt-handoff]').forEach(button => {
    button.disabled = button.disabled || local.busy || Boolean(local.uncertain);
    button.addEventListener('click', async () => {
      const row = button.closest('[data-rt-child]');
      const targetId = row.querySelector('[data-rt-target]').value;
      if (!targetId) return showToast('请先选择不同厂商的接手员工。', true);
      if (!window.confirm('请核对原客户端：这张子单确实已卡住，当前没有运行，也没有尚未回收的结果。确认后才转交；转交本身不执行新模型。')) return;
      await roundtableRequest(parent.id, 'roundtablehandoff', { task_id: row.dataset.rtChild, target_id: targetId, to_worker_id: targetId, blocked: true, confirmed_not_running: true }, () => { roundtableChildUI.delete(row.dataset.rtChild); });
    });
  });
  if (local.busy) container.querySelectorAll('button, input, select, textarea').forEach(el => { el.disabled = true; });
}
function renderRoundtablePanel(container, task, sectionOpen) {
  const state = task.roundtable_state || {};
  const local = roundtableLocal(task.id);
  const gate = roundtableGate(task);
  const children = (task.subtask_ids || []).map(id => APP_STATE.tasks.find(child => child.id === id)).filter(Boolean);
  if (local.prompt && local.prompt.stage_key !== state.stage && state.stage !== 'collecting') local.prompt = null;
  const prompt = local.prompt || gate.pendingManual;
  if (prompt && !local.prompt) local.prompt = { stage_key: prompt.stage_key, prompt: prompt.prompt, request_id: prompt.request_id };
  const promptKey = prompt?.stage_key || '';
  const canRun = gate.stage >= 0 && gate.basketReady && !gate.waiting && !gate.done && !gate.blocked && !local.uncertain && !gate.pendingManual;
  const canManual = gate.stage >= 0 && gate.basketReady && !gate.waiting && !gate.done && !gate.blocked && !local.uncertain;
  const content = (title, value, source) => `<section class="roundtable-version"><h3>${title}</h3><p class="roundtable-source" data-preserve-text>${escapeHTML(source)}</p>${roundtableOutput(value)}</section>`;
  const notice = local.uncertain ? '结果尚未确认，已停止。请核对服务端回执及原客户端，不要重复发送。' : gate.blocked ? '存在进行中、未知或失败回执，已停止推进。请核对下方回执；不会自动重试。' : gate.waiting ? 'A / B 对比已结束。只有你可以采纳 B、采纳 C 或退回重修。' : gate.done ? '本轮已停止；保留全部原稿和回执，不自动开启下一轮。' : gate.stage < 0 ? '阶段未识别，已停止执行。请刷新状态或核对服务端阶段字段。' : !gate.basketReady ? '先完成并汇报全部 1F 子单；改代码子单还需独立真实审查。资料齐备后才能启动 A 席。' : gate.manual ? '当前席位需半自动交接：获取提示词，在外部模型运行后人工回填 JSON。' : '每次只推进一阶段；Stage 4 的 A、B 对比分别返回后停止，等待你拍板。';
  container.innerHTML = `<section class="roundtable-panel" aria-labelledby="roundtableTitle" aria-busy="${local.busy}">
    <header class="detail-header"><h2 class="detail-title" id="roundtableTitle" data-preserve-text>${escapeHTML(task.title)}</h2>
      <p class="detail-meta">圆桌精雕 · <span data-preserve-text>${escapeHTML(task.id)} · ${escapeHTML(state.stage ?? '阶段未提供')}</span></p>
      <p class="detail-meta" data-preserve-text>${escapeHTML(task.goal || '未填写总目标')}</p>
    </header>
    <ol class="roundtable-progress" aria-label="圆桌五阶段">${ROUNDTABLE_STAGES.map((label, index) => `<li class="${index < gate.stage ? 'done' : index === gate.stage ? 'current' : ''}"${index === gate.stage ? ' aria-current="step"' : ''}><span>Stage ${index}</span><strong>${label}</strong></li>`).join('')}</ol>
    <p class="detail-meta roundtable-pass">已用 Pass ${escapeHTML(state.passes_used ?? '未提供')} / 2 · 固定 1 轮对抗 + 1 轮对比 · 自动调用 ${escapeHTML(state.calls_used ?? '未提供')} / 5</p>
    <p class="detail-meta">Stage 4：A、B 各不超过 3 条短评，reply_hint=false；只传结论、问题清单和增量差异，不重写全文。</p>
    <dl class="roundtable-seats">${['A', 'B', 'C'].map(seat => { const a = roundtableSeat(state, seat); return `<div><dt>经理 ${seat}</dt><dd data-preserve-text>${escapeHTML(a.name || a.id)}<small>${escapeHTML(a.vendor)} / ${escapeHTML(a.model)} · ${['web', 'subscription', 'desktop'].includes(a.access_kind) ? '人工回填' : escapeHTML(a.access_kind || '通道未标注')}</small></dd></div>`; }).join('')}</dl>
    <div class="roundtable-notice" role="status"><p>${notice}</p>${local.notice ? `<p data-preserve-text>${escapeHTML(local.notice)}</p>` : ''}${local.busy ? '<p>请求处理中，操作已锁定。请勿重复提交。</p>' : ''}</div>
    <fieldset class="roundtable-controls"${local.busy ? ' disabled' : ''}><legend class="roundtable-sr-only">圆桌操作</legend>
      <div class="detail-actions">
        <button type="button" class="btn btn-primary" data-rt-action="auto_start"${['running', 'waiting_manual'].includes(task.automation?.status) ? ' disabled' : ''}>一键自动运行</button>
        ${['running', 'waiting_manual'].includes(task.automation?.status) ? '<button type="button" class="btn btn-danger" data-rt-action="auto_stop">停止自动</button>' : ''}
        <button type="button" class="btn btn-ghost" data-rt-action="step"${canRun ? '' : ' disabled'}>${gate.manual ? '准备当前席位交接' : '推进单步'}</button>
        <button type="button" class="btn btn-ghost" data-rt-action="plan">干跑预览</button>
        <button type="button" class="btn btn-ghost" data-rt-action="refresh">刷新</button>
      </div>
      ${task.automation?.status ? `<p class="detail-meta">自动编排状态：<strong>${escapeHTML(task.automation.status)}</strong>（${escapeHTML(task.automation.reason || '')} · 已用 ${escapeHTML(task.automation.calls_used || 0)} / ${escapeHTML(task.automation.max_calls || 0)} 次）</p>` : ''}
      <p class="detail-meta">不自动轮询、不自动重发。API Key 仅读环境变量；额度未知时以「额度未填」为准。</p>
      ${local.plan ? `<details class="detail-section" data-section="rt-plan"${sectionOpen('rt-plan', true)}><summary>干跑计划 · 未调用模型，未生成任何成果</summary>${roundtableOutput(local.plan)}</details>` : ''}
      <details class="detail-section" data-section="rt-basket"${sectionOpen('rt-basket', gate.stage === 0)}><summary>Stage 0 · 资料篮与 1F 子单</summary><div class="section-body">
        <p class="detail-meta">资料篮只收【结论】【改动文件】【测试结果】，不把 1F 对话全文带上圆桌。点开子单，沿用原执行与汇报流程。</p>
        ${Array.isArray(state.basket) && state.basket.length ? `<ul class="roundtable-materials">${state.basket.map(item => `<li><h4 data-preserve-text>${escapeHTML(item.task_id || '子单结论')} · ${escapeHTML(item.sender_id || '来源未标注')}</h4><p data-preserve-text>${escapeHTML(item.conclusion || '')}</p><p class="detail-meta" data-preserve-text>改动文件：${escapeHTML(roundtableText(item.changed_files || []))}<br>测试结果：${escapeHTML(item.test_result || '未填写')}<br>实际来源：${escapeHTML(item.provenance || '未标注')}</p>${item.diff_summary ? roundtableOutput(item.diff_summary) : ''}</li>`).join('')}</ul>` : roundtableOutput(state.basket, '资料篮尚无结论。请先完成并汇报子单。')}
        <div class="subtask-list">${children.map(child => `<div class="roundtable-child"><button type="button" class="btn btn-ghost subtask-row" data-rt-open-child="${escapeHTML(child.id)}"><span data-preserve-text>${escapeHTML(child.title)}</span><span class="detail-meta" data-preserve-text>${escapeHTML(child.status)} · ${escapeHTML(child.assigned_name || '未指派')}${child.worker_reported ? ' · 已汇报' : ' · 待回收'}</span></button>${renderRoundtableHandoff(child, task)}</div>`).join('') || '<p class="detail-meta">暂无子单记录，请核对服务端拆单结果。</p>'}</div>
      </div></details>
      <details class="detail-section" data-section="rt-architect"${sectionOpen('rt-architect')}><summary>Stage 1 · A 的执行提示词与验收约束</summary><p class="roundtable-source" data-preserve-text>${escapeHTML(roundtableSource(state, ['A']))}</p>${roundtableOutput(state.manager_a_prompt)}</details>
      <section class="roundtable-section"><h3>成果对比</h3><div class="roundtable-comparison">
        ${content('B · Draft v1', state.draft_v1, roundtableSource(state, ['B', 'builder', 'manager_b', 'stage2', 'stage_2', 'draft_v1']))}
        ${content('C · Refined v2', state.refined_v2, roundtableSource(state, ['C', 'critic', 'manager_c', 'stage3', 'stage_3', 'refined_v2']))}
      </div></section>
      <section class="roundtable-section"><h3>C · P0 / P1 问题清单</h3>${Array.isArray(state.critic_issues) && state.critic_issues.length ? `<ol class="roundtable-issues">${state.critic_issues.map(issue => `<li data-preserve-text>${escapeHTML(issue?.severity ? `${issue.severity} · ${issue.detail || ''}` : roundtableText(issue))}</li>`).join('')}</ol>` : roundtableOutput(state.critic_issues, '尚未收到问题清单；不代表已通过审查。')}</section>
      <section class="roundtable-section"><h3>Stage 4 · A / B 对比短评</h3><div class="roundtable-comparison">${['A', 'B'].map(seat => { const opinion = state.ab_opinions?.[seat]; return `<section class="roundtable-opinion"><h4>经理 ${seat} · ${opinion ? '已回议' : '待回议'}</h4><p class="roundtable-source" data-preserve-text>${escapeHTML(roundtableSource(state, [`${seat}-comparison`]))}</p>${opinion ? `<p class="detail-meta" data-preserve-text>建议采纳：${escapeHTML(opinion.recommendation || '未标注')}（不代表你的决定）</p>${Array.isArray(opinion.comments) ? `<ul>${opinion.comments.map(comment => `<li data-preserve-text>${escapeHTML(comment)}</li>`).join('')}</ul>` : roundtableOutput(opinion)}` : '<p class="detail-meta">尚未收到实际短评。</p>'}</section>`; }).join('')}</div></section>
      ${gate.waiting ? `<section class="roundtable-section roundtable-owner"><h3>董事长定稿</h3><p class="detail-meta">采纳不会覆盖另一份原稿。退回重修会停止本轮，不自动续费重跑。</p><div class="form-group"><label for="roundtableOwnerComment">定稿说明 / 重修要求</label><textarea id="roundtableOwnerComment" rows="3" maxlength="2000" placeholder="退回重修时请说明要改什么">${escapeHTML(local.comment)}</textarea></div><div class="detail-actions"><button type="button" class="btn btn-primary" data-rt-choice="C"${local.uncertain ? ' disabled' : ''}>采纳 C 版</button><button type="button" class="btn btn-ghost" data-rt-choice="B"${local.uncertain ? ' disabled' : ''}>采纳 B 版</button><button type="button" class="btn btn-ghost" data-rt-choice="revise"${local.uncertain ? ' disabled' : ''}>退回重修</button></div></section>` : ''}
      ${canManual || prompt ? `<details class="detail-section" data-section="rt-manual"${sectionOpen('rt-manual', gate.manual || Boolean(prompt))}><summary>半自动席位 · 复制提示词 / 人工回填</summary><div class="section-body"><p class="detail-meta">必须来自当前付费经理的真实外部模型输出；这是人工粘贴，不是农场自动生成。不要粘贴整段聊天或凭据。</p><button type="button" class="btn btn-ghost" data-rt-action="prompt"${canManual ? '' : ' disabled'}>获取当前席位提示词（不调用模型）</button>
        ${prompt ? `<p class="detail-meta" data-preserve-text>服务端阶段：${escapeHTML(promptKey)} · 人工交接</p><div class="form-group"><label for="roundtableManualPrompt">本席完整提示词（只读）</label><textarea id="roundtableManualPrompt" rows="7" readonly>${escapeHTML(prompt.prompt)}</textarea></div><button type="button" class="btn btn-ghost" data-rt-action="copy">复制本席提示词</button><form id="roundtableResultForm"><div class="form-group"><label for="roundtableManualResult">实际外部模型结果 · JSON 对象</label><textarea id="roundtableManualResult" rows="9" required spellcheck="false" placeholder="粘贴本席提示词要求的 JSON 对象；不接受 Markdown 代码围栏或数组">${escapeHTML(local.drafts[promptKey] || '')}</textarea></div><label class="roundtable-check"><input type="checkbox" id="roundtableManualConfirmed" required><span>我确认这是本席外部模型的真实结果，授权人工回填。</span></label><button type="submit" class="btn btn-primary"${canManual ? '' : ' disabled'}>提交人工回填结果</button></form>` : ''}
      </div></details>` : ''}
      <details class="detail-section" data-section="rt-receipts"${sectionOpen('rt-receipts', gate.blocked || Boolean(local.uncertain))}><summary>请求回执与实际来源</summary><p class="detail-meta">pending / unknown 表示没有可确认的结果，不等于失败后可安全重试。</p>${roundtableOutput(state.attempts, '尚无请求回执。')}${local.uncertain ? roundtableOutput(local.uncertain) : ''}</details>
      ${state.decision ? `<section class="roundtable-section"><h3>已记录的人工决定</h3>${roundtableOutput(state.decision)}</section>` : ''}
      ${task.final_delivery_text ? `<section class="roundtable-section"><h3>人工决定后的交付记录</h3>${roundtableOutput(task.final_delivery_text)}</section>` : ''}
    </fieldset></section>`;
  container.querySelectorAll('[data-rt-open-child]').forEach(button => button.addEventListener('click', () => openTaskPrivateThread(button.dataset.rtOpenChild)));
  container.querySelectorAll('[data-rt-action]').forEach(button => button.addEventListener('click', () => handleRoundtableAction(task.id, button.dataset.rtAction)));
  container.querySelectorAll('[data-rt-choice]').forEach(button => button.addEventListener('click', () => handleRoundtableChoice(task.id, button.dataset.rtChoice)));
  container.querySelector('#roundtableOwnerComment')?.addEventListener('input', event => { local.comment = event.target.value; });
  container.querySelector('#roundtableManualResult')?.addEventListener('input', event => { local.drafts[promptKey] = event.target.value; });
  container.querySelector('#roundtableResultForm')?.addEventListener('submit', event => { event.preventDefault(); handleRoundtableResult(task.id); });
  bindRoundtableHandoffs(container, task);
}
function roundtableRequestId() {
  return globalThis.crypto?.randomUUID ? crypto.randomUUID() : `rt-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
async function roundtableRequest(taskId, action, payload, onSuccess) {
  const local = roundtableLocal(taskId);
  const mutation = ['runroundtablestep', 'submitroundtableresult', 'chooseroundtable', 'roundtablehandoff'].includes(action) && payload.live !== false;
  if (local.busy || (mutation && local.uncertain)) return;
  if (!APP_STATE.backendOnline) return showToast('请先连接本机服务；离线预览不会生成圆桌结果。', true);
  const task = APP_STATE.tasks.find(t => t.id === taskId);
  local.busy = true;
  local.notice = '';
  renderSelectedTaskThread();
  try {
    const result = await callOfficeAction(action, payload);
    if (result == null) throw new Error('服务端未返回可确认的回执');
    if (onSuccess) onSuccess(result);
    if (mutation) local.notice = '已收到服务端响应。以阶段、成果及请求回执为准；没有自动发起下一步。';
    return result;
  } catch (error) {
    local.notice = `${error.message}。操作已停止，不会自动重试。`;
    if (mutation) local.uncertain = { action, request_id: payload.request_id || '', stage_before: task?.roundtable_state?.stage, child_id: action === 'roundtablehandoff' ? payload.task_id : '', target_id: payload.target_id || '' };
  } finally {
    local.busy = false;
    renderSelectedTaskThread();
  }
}
async function handleRoundtableAction(taskId, action) {
  const local = roundtableLocal(taskId);
  const task = APP_STATE.tasks.find(t => t.id === taskId);
  if (!task || local.busy) return;
  const gate = roundtableGate(task);
  if (action === 'refresh') {
    local.busy = true;
    renderSelectedTaskThread();
    try {
      const response = await fetch('/api/state', { cache: 'no-store' });
      if (!response.ok) throw new Error('读取状态失败；请检查本机连接与配对状态');
      applySnapshot(await response.json());
      for (const child of APP_STATE.tasks.filter(t => t.parent_task_id === taskId)) {
        const receipt = child.roundtable_dispatch?.receipts?.[child.roundtable_dispatch.current];
        if (receipt && ['completed', 'pending_manual'].includes(receipt.status)) roundtableChildUI.delete(child.id);
      }
      const current = APP_STATE.tasks.find(t => t.id === taskId);
      const uncertain = local.uncertain;
      if (uncertain && current && !roundtableGate(current).blocked && (uncertain.child_id
        ? APP_STATE.tasks.find(t => t.id === uncertain.child_id)?.assigned_to === uncertain.target_id
        : current.roundtable_state?.stage !== uncertain.stage_before || current.status === 'accepted_done' ||
          (uncertain.action === 'submitroundtableresult' && roundtableAttempts(current.roundtable_state || {}).some(a => a.request_id === uncertain.request_id && a.status === 'pending_manual')))) local.uncertain = null;
      local.notice = local.uncertain ? '已读取最新状态，但尚未确认上次请求完成。保留未知状态，请核对回执，不要重发。' : '已读取最新状态，未调用任何模型。';
    } catch (error) { local.notice = error.message; }
    finally { local.busy = false; renderSelectedTaskThread(); }
    return;
  }
  if (action === 'auto_start') {
    return roundtableRequest(taskId, 'startautomation', {
      task_id: taskId, confirmed: true, live: true,
      request_id: roundtableRequestId(), max_calls: 16,
      workspace_dir: APP_STATE.customWorkspaceDir || '.',
    }, () => { local.notice = '已授权自动编排，后台正在推进；结果会实时推送到群聊。'; });
  }
  if (action === 'auto_stop') {
    return roundtableRequest(taskId, 'stopautomation', { task_id: taskId }, () => { local.notice = '已停止自动编排。'; });
  }
  if (action === 'plan') return roundtableRequest(taskId, 'runroundtablestep', { task_id: taskId, live: false }, result => { local.plan = result; });
  if (action === 'copy') {
    try { await navigator.clipboard.writeText(local.prompt?.prompt || ''); showToast('已复制本席提示词；请在对应外部模型运行后回填真实结果。'); }
    catch (_) { showToast('剪贴板不可用，请选中只读提示词框手动复制。', true); }
    return;
  }
  if (gate.waiting || gate.done || gate.blocked || gate.stage < 0 || !gate.basketReady || local.uncertain) return;
  if (action === 'prompt' || (action === 'step' && gate.manual)) return roundtableRequest(taskId, 'getroundtableprompt', { task_id: taskId }, result => {
    if (!result.stage_key || !result.request_id || typeof result.prompt !== 'string') throw new Error('服务端未返回 stage_key、request_id 与 prompt，不能回填');
    local.prompt = { stage_key: result.stage_key, prompt: result.prompt, request_id: result.request_id };
  });
  if (action === 'step' && !gate.pendingManual) {
    if (!window.confirm('只推进当前一阶段。API / CLI 席位会调用真实模型并消耗额度；网页 / 订阅席位停在人工交接。不会自动定稿或重试。继续？')) return;
    return roundtableRequest(taskId, 'runroundtablestep', { task_id: taskId, live: true, request_id: roundtableRequestId() }, () => { local.prompt = null; });
  }
}
async function handleRoundtableResult(taskId) {
  const local = roundtableLocal(taskId);
  if (!local.prompt || local.busy || local.uncertain || !document.getElementById('roundtableManualConfirmed')?.checked) return;
  const task = APP_STATE.tasks.find(t => t.id === taskId);
  const gate = roundtableGate(task);
  if (gate.waiting || gate.done || gate.blocked) return;
  let result;
  try {
    result = JSON.parse(local.drafts[local.prompt.stage_key] || '');
    if (!result || Array.isArray(result) || typeof result !== 'object') throw new Error('必须为 JSON 对象，不能是数组、字符串或 null');
  } catch (error) {
    showToast(`JSON 未提交：${error.message}。请按本席提示词的格式修正。`, true);
    return;
  }
  return roundtableRequest(taskId, 'submitroundtableresult', { task_id: taskId, stage_key: local.prompt.stage_key, result, request_id: local.prompt.request_id, provenance: 'manual' }, () => { local.prompt = null; });
}
async function handleRoundtableChoice(taskId, decision) {
  const task = APP_STATE.tasks.find(t => t.id === taskId);
  const local = roundtableLocal(taskId);
  if (!task || task.roundtable_state?.stage !== 'awaiting_owner' || !['B', 'C', 'revise'].includes(decision) || local.busy || local.uncertain) return;
  if (decision === 'revise' && !local.comment.trim()) return showToast('请写明重修要求；不会自动开启下一轮。', true);
  if (!window.confirm(decision === 'revise' ? '确认退回重修并停止本轮？不会自动重跑。' : `确认采纳 ${decision} 版？另一版和全部回执仍会保留。`)) return;
  return roundtableRequest(taskId, 'chooseroundtable', { task_id: taskId, decision, comment: local.comment.trim() });
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
  const ov = document.getElementById('floorSkillOverview');
  const floors = [{ key: 'manager', title: '经理' }, { key: 'worker', title: '员工' }, { key: 'rest', title: '休息成员' }];
  ov.innerHTML = floors.map(floor => {
    const agents = APP_STATE.agents.filter(agent => agent.floor === floor.key);
    return `<div class="floor-ov-box"><h4>${floor.title} · ${agents.length}</h4>
      ${agents.map(agent => `<div class="kv-row"><span>${escapeHTML(agent.name)}</span><span>${(agent.skills || []).length} 个技能</span></div>`).join('') || '<p class="detail-meta">尚无成员</p>'}</div>`;
  }).join('');
  const grid = document.getElementById('skillsGrid');
  const openSkills = new Set([...grid.querySelectorAll('details[open]')].map(el => el.dataset.skill));
  grid.innerHTML = APP_STATE.skills.map(skill => {
    const carriers = APP_STATE.agents.filter(agent => (agent.skills || []).includes(skill.slug));
    return `<details class="skill-card" data-skill="${escapeHTML(skill.slug)}" ${openSkills.has(skill.slug) ? 'open' : ''}>
      <summary><span class="skill-card-name">${escapeHTML(skill.name)}</span><span class="skill-card-category">${escapeHTML(skill.category || '通用')}</span>${icon('chevron')}</summary>
      <div class="skill-detail"><div><h4>固定执行步骤</h4><p>${escapeHTML(skill.steps)}</p><h4>省额度原理</h4><p>${escapeHTML(skill.savings_note || '暂无说明')}</p></div>
      <div><h4>适合的成员</h4><p>${escapeHTML(skill.best_for)}</p><h4>当前装配 · ${carriers.length}</h4><p>${carriers.map(agent => `<span class="vendor-chip">${escapeHTML(agent.name)}</span>`).join(' ') || '尚未装配'}</p></div></div>
    </details>`;
  }).join('');
}

async function handleRunSkillJudge() {
  const judgeId = document.getElementById("skillJudgeSelect").value;
  const res = await callOfficeAction("analyzeskillassignments", { judge_id: judgeId });
  if (!res) {
    neutralizePanel("judgeResultSection");
    return;
  }
  APP_STATE.latestRecommendations = res.recommendations || [];
  const box = document.getElementById("judgeResultSection");
  box.classList.remove("hidden");

  if (APP_STATE.latestRecommendations.length === 0) {
    box.innerHTML = `<div>${icon('check')}高级模型裁判 <strong data-preserve-text>${escapeHTML(res.judge)}</strong> 评估完毕：当前所有在岗成员的技能均已处于最优配置！</div>`;
    neutralizePanel("judgeResultSection");
    return;
  }

  box.innerHTML = `
    <div class="recommendation-heading">
      <strong data-preserve-text>${escapeHTML(res.judge)} 的技能推荐</strong>
      <button class="btn btn-primary" onclick="handleApplyApprovedSkills(${escapeHTML(JSON.stringify(res.judge))})">应用勾选项</button>
    </div>
    <p class="detail-meta">由你确认后装配，并同步通知团队。</p>
    <div class="recommendation-list">
      ${APP_STATE.latestRecommendations.map((r, idx) => `
        <div class="recommendation-row">
          <label class="recommendation-choice">
            <input type="checkbox" class="rec-skill-chk" data-idx="${idx}" checked />
            <span><strong data-preserve-text>${escapeHTML(r.agent_name)}</strong> · <span data-preserve-text>${escapeHTML(r.skill_name)}</span></span>
            <span class="access-badge green">${escapeHTML(r.score)} 分</span>
          </label>
          <details class="recommendation-reason"><summary>推荐理由</summary><p data-preserve-text>${escapeHTML(r.reason)}</p></details>
        </div>
      `).join("")}
    </div>
  `;
  neutralizePanel("judgeResultSection");
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
  const payload = {
    task_id: taskId,
    sender_id: task ? task.assigned_to : "",
    conclusion,
    changed_files,
    test_result: testResult || "未运行测试",
    is_delivery: true,
  };
  if (roundtableChildParent(taskId)) {
    const result = await roundtableChildAction(taskId, 'postmessage', payload);
    if (!result) return;
  } else await callOfficeAction('postmessage', payload);
  delete APP_STATE.reportDrafts[taskId];
  await openTaskPrivateThread(taskId);
  document.querySelector('#taskThreadContent details[data-section=report]').open = false;
  document.querySelector('#taskThreadContent details[data-section=execution]').open = false;
  showToast("结论汇报已发送给经理，群里仅保留提示。");
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
  const roundtableChild = Boolean(roundtableChildParent(taskId));
  if (roundtableChild && !window.confirm('确认独立审查者已实际审阅本次代码改动？此处记录真实人工审查，不是干跑结果。')) return;
  await callOfficeAction("submitcodereview", {
    task_id: taskId,
    reviewer_id: reviewerId,
    passed,
    issues,
    dry_run: !roundtableChild,
    simulate_reject: Boolean(!roundtableChild && simulateReject && issues.length === 0),
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

const roundtableIdentity = value => String(value || '').trim().toLowerCase();
function usableRoundtableManagers() {
  return APP_STATE.agents.filter(a => a.floor === 'manager' && a.paid === true &&
    !['exhausted', 'disabled'].includes(a.status) && ['api', 'cli', 'web', 'subscription', 'desktop'].includes(a.access_kind) &&
    roundtableIdentity(a.vendor) && roundtableIdentity(a.model) && !/待|unknown|unverified/i.test(a.model));
}

function validateRoundtableSeats(ids) {
  const managers = usableRoundtableManagers();
  const seats = ids.map(id => managers.find(a => a.id === id));
  return seats.every(Boolean) && new Set(ids).size === 3 &&
    new Set(seats.map(a => roundtableIdentity(a.vendor))).size === 3 &&
    new Set(seats.map(a => roundtableIdentity(a.model))).size === 3;
}

function updateBigTaskRoundtableMode() {
  const enabled = document.getElementById('bigTaskRoundtable').checked;
  document.getElementById('bigTaskRoundtableSeats').classList.toggle('hidden', !enabled);
  const selectors = ['A', 'B', 'C'].map(seat => document.getElementById(`bigTaskSeat${seat}`));
  selectors.forEach(select => { select.disabled = !enabled; select.required = enabled; });
  const valid = validateRoundtableSeats(selectors.map(select => select.value));
  const guidance = document.getElementById('bigTaskSeatGuidance');
  guidance.textContent = valid
    ? '三席厂商与模型均不同。API / CLI 需你确认才真调；付费网页、订阅与桌面席位只走复制提示词和人工 JSON 回填。'
    : '请选择三位不同厂商、不同模型的付费经理。席位不足？先到团队接入或调岗，也可添加跨厂商付费网页/订阅经理做半自动席位；免费、1F 员工和未绑定模型不可入席。';
  guidance.classList.toggle('roundtable-warning', !valid);
  document.querySelector('#bigTaskForm button[type="submit"]').disabled = enabled && !valid;
}

function renderAttachmentChips(scope) {
  const listEl = document.getElementById(scope === 'big' ? 'bigTaskFileList' : 'newTaskFileList');
  if (!listEl) return;
  const items = APP_STATE.pendingAttachments[scope] || [];
  listEl.innerHTML = items.map((att, idx) => `<span class="attachment-chip">${escapeHTML(att.name)} (${Math.max(1, Math.round((att.size || 0) / 1024))}KB) <button type="button" aria-label="移除 ${escapeHTML(att.name)}" onclick="removePendingAttachment('${scope}', ${idx})">×</button></span>`).join('');
}

function removePendingAttachment(scope, index) {
  APP_STATE.pendingAttachments[scope].splice(index, 1);
  renderAttachmentChips(scope);
}

async function handleTaskFileSelect(input, scope) {
  const files = Array.from(input.files || []);
  if (!files.length) return;
  if (!APP_STATE.backendOnline) {
    showToast('上传文件/图片需要连接本地服务（python -m ai_farm office）', true);
    input.value = '';
    return;
  }
  for (const file of files) {
    if (file.size > 5 * 1024 * 1024) {
      showToast(`附件 ${file.name} 超过 5MB 上限`, true);
      continue;
    }
    try {
      const b64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const res = String(reader.result || '');
          resolve(res.includes(',') ? res.split(',')[1] : res);
        };
        reader.onerror = () => reject(new Error('读取文件失败'));
        reader.readAsDataURL(file);
      });
      const resp = await fetch('/api/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Farm-CSRF': officeCsrf },
        body: JSON.stringify({ name: file.name, mime: file.type || '', content_base64: b64 }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || '上传失败');
      APP_STATE.pendingAttachments[scope].push(data.attachment);
      renderAttachmentChips(scope);
    } catch (err) {
      showToast(`上传 ${file.name} 失败：${err.message}`, true);
    }
  }
  input.value = '';
}

function openBigTaskModal(forceRoundtable = false) {
  const mgrSel = document.getElementById('bigTaskManagerSelect');
  const managers = APP_STATE.agents.filter(a => a.floor === 'manager');
  if (mgrSel) {
    mgrSel.innerHTML = managers.map(m => `<option value="${escapeHTML(m.id)}">${escapeHTML(m.name)} (${escapeHTML(m.badge)})</option>`).join('');
  }
  document.getElementById('bigTaskRoundtable').checked = Boolean(forceRoundtable || APP_STATE.draftMode === 'roundtable');
  const candidates = usableRoundtableManagers();
  const picked = [];
  const usedVendors = new Set();
  for (const cand of candidates) {
    const v = roundtableIdentity(cand.vendor);
    if (!usedVendors.has(v)) {
      usedVendors.add(v);
      picked.push(cand.id);
      if (picked.length === 3) break;
    }
  }
  ['A', 'B', 'C'].forEach((seat, idx) => {
    const sel = document.getElementById(`bigTaskSeat${seat}`);
    sel.innerHTML = '<option value="">请选择经理</option>' + candidates.map(a =>
      `<option value="${escapeHTML(a.id)}">${escapeHTML(a.name)} · ${escapeHTML(a.vendor)} / ${escapeHTML(a.model)} · ${['api', 'cli'].includes(a.access_kind) ? '真调' : '人工回填'}</option>`
    ).join('');
    if (picked[idx]) sel.value = picked[idx];
  });
  APP_STATE.pendingAttachments.big = [];
  renderAttachmentChips('big');
  updateBigTaskRoundtableMode();
  document.getElementById('bigTaskModal').classList.remove('hidden');
}

function closeBigTaskModal() {
  document.getElementById('bigTaskModal').classList.add('hidden');
}

async function handleCreateBigTaskSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (form.dataset.busy === 'true') return;
  const mode = document.getElementById('bigTaskRoundtable').checked ? 'roundtable' : 'standard';
  const ids = ['A', 'B', 'C'].map(seat => document.getElementById(`bigTaskSeat${seat}`).value);
  if (mode === 'roundtable' && !validateRoundtableSeats(ids)) {
    showToast('圆桌需要三个不同厂商、不同模型的付费经理；请调整席位。', true);
    return;
  }
  const goal = document.getElementById('bigTaskGoal').value.trim();
  const rawTitle = document.getElementById('bigTaskTitle').value.trim();
  const title = rawTitle || goal.split(/\r?\n/)[0].slice(0, 28) || '圆桌任务';
  const payload = {
    title,
    manager_id: document.getElementById('bigTaskManagerSelect').value || ids[0] || '',
    goal,
    raw_steps: document.getElementById('bigTaskSteps').value,
    attachments: APP_STATE.pendingAttachments.big || [],
    mode,
    ...(mode === 'roundtable' ? { seat_a: ids[0], seat_b: ids[1], seat_c: ids[2] } : {}),
  };
  const autoRun = Boolean(document.getElementById('bigTaskAutoRun')?.checked);
  const controls = [...form.querySelectorAll('input, select, textarea, button')].map(el => [el, el.disabled]);
  form.dataset.busy = 'true';
  controls.forEach(([el]) => { el.disabled = true; });
  try {
    const res = await callOfficeAction('createbigtask', payload);
    if (!res) return;
    closeBigTaskModal();
    if (res.parent) {
      APP_STATE.selectedTaskId = res.parent.id;
      if (autoRun) {
        try {
          await callOfficeAction('startautomation', {
            task_id: res.parent.id, confirmed: true, live: true,
            request_id: `auto-create-${Date.now()}`, max_calls: 16,
            workspace_dir: APP_STATE.customWorkspaceDir || '.',
          });
          showToast('🚀 已发布并启动自动运行，群聊坐等结果。');
        } catch (autoErr) {
          showToast(`已发布任务，但自动运行未启动：${autoErr.message}`, true);
        }
      } else {
        showToast(mode === 'roundtable' ? '圆桌任务已创建。' : `大任务已拆成 ${(res.subtasks || []).length} 张子单。`);
      }
      await openTaskPrivateThread(res.parent.id);
    }
  } catch (error) {
    showToast(`创建未确认：${error.message}。请检查任务列表，不要重复提交。`, true);
  } finally {
    form.dataset.busy = 'false';
    controls.forEach(([el, wasDisabled]) => { el.disabled = wasDisabled; });
    APP_STATE.pendingAttachments.big = [];
    renderAttachmentChips('big');
    updateBigTaskRoundtableMode();
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
  const payload = { task_id: taskId, live, workspace_dir };
  const res = roundtableChildParent(taskId)
    ? await roundtableChildAction(taskId, 'runadaptertask', payload)
    : await callOfficeAction('runadaptertask', payload);
  if (!res) return;
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

async function handleRoundtableChildPrompt(taskId, openWeb = false) {
  const result = await roundtableChildAction(taskId, 'gettaskprompt', { task_id: taskId, mark_dispatched: true });
  if (!result) return;
  if (!result.dispatch_allowed || !result.prompt) {
    showToast('已有子单派发回执，未再次打开或投喂。请检查原任务；卡住时在父单确认后单点转交。', true);
    return;
  }
  try { await navigator.clipboard.writeText(result.prompt); showToast('已复制单次采集指令。手动执行后回填实际结论，不要重复投喂。'); }
  catch (_) { showToast('剪贴板不可用；请展开「派发回执与已派出指令」手动复制。不要再次派发。', true); }
  if (openWeb) {
    const task = APP_STATE.tasks.find(t => t.id === taskId);
    const worker = APP_STATE.agents.find(a => a.id === task?.assigned_to);
    try {
      const url = new URL(worker?.login_url || worker?.usage_url || '');
      if (['https:', 'http:'].includes(url.protocol)) window.open(url.href, '_blank', 'noopener');
    } catch (_) { showToast('未配置有效的厂商网页地址，请自行打开对应模型。'); }
  }
}

async function handleCopyWorkerPrompt(taskId) {
  if (roundtableChildParent(taskId)) return handleRoundtableChildPrompt(taskId);
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
  if (roundtableChildParent(taskId)) return handleRoundtableChildPrompt(taskId, true);
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
  switchRecruitPath(document.getElementById("recPathInput").value);
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
  for (const [channel, id] of Object.entries({ api: "recApiFields", web: "recWebFields", cli: "recCliFields", desktop: "recDesktopFields" })) {
    document.getElementById(id).querySelectorAll("input, select").forEach(el => { el.disabled = channel !== path; });
  }
  document.getElementById("recKeyEnv").required = path === "api";
  document.getElementById("recBaseUrl").required = path === "api";
  document.getElementById("recLoginUrl").required = path === "web";
  document.getElementById("recCliExec").required = path === "cli";
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
  if (APP_STATE.draftMode === "roundtable") {
    openBigTaskModal(true);
    return;
  }
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
  selectTaskMode(APP_STATE.draftMode === "roundtable" ? "roundtable" : "solo");
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
    attachments: APP_STATE.pendingAttachments.single || [],
  };
  const task = await callOfficeAction("createtask", payload);
  APP_STATE.pendingAttachments.single = [];
  renderAttachmentChips('single');
  closeNewTaskModal();
  if (task) {
    APP_STATE.selectedTaskId = task.id;
    switchMainView('workspace');
    switchWorkspaceTab('tasks');
    showToast(`已发布任务：${task.title}`);
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
document.addEventListener("keydown", event => {
  const overlay = document.querySelector('.modal-backdrop:not(.hidden)') || document.querySelector('.approval-drawer.open') || document.querySelector('#paneDetail:not(.hidden)');
  if (!overlay) return;
  if (event.key === "Escape") {
    event.preventDefault();
    overlay.querySelector(".close-btn").click();
    return;
  }
  if (event.key !== "Tab") return;
  const controls = [...overlay.querySelectorAll("button, input, select, textarea, a[href], [tabindex]")]
    .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden");
  if (!controls.length) return;
  const first = controls[0], last = controls[controls.length - 1];
  if (!overlay.contains(document.activeElement) || (event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  }
});

function closeTopbarDropdown(id) {
  const el = document.getElementById(id);
  if (el) el.removeAttribute("open");
}

document.addEventListener("click", (ev) => {
  document.querySelectorAll("details.topbar-dropdown[open]").forEach((det) => {
    if (!det.contains(ev.target)) det.removeAttribute("open");
  });
});

function setDraftMode(mode) {
  APP_STATE.draftMode = mode === "roundtable" ? "roundtable" : "standard";
  const stdBtn = document.getElementById("topModeStandard");
  const rtBtn = document.getElementById("topModeRoundtable");
  if (stdBtn) {
    stdBtn.classList.toggle("active", APP_STATE.draftMode === "standard");
    stdBtn.setAttribute("aria-pressed", String(APP_STATE.draftMode === "standard"));
  }
  if (rtBtn) {
    rtBtn.classList.toggle("active", APP_STATE.draftMode === "roundtable");
    rtBtn.setAttribute("aria-pressed", String(APP_STATE.draftMode === "roundtable"));
  }
}

function toggleMobileRoster() {
  const roster = document.getElementById("paneRoster");
  const btn = document.getElementById("mobileRosterToggle");
  if (!roster) return;
  const open = roster.classList.toggle("mobile-open");
  if (btn) btn.setAttribute("aria-expanded", String(open));
}

function onTaskPaneDragOver(event) {
  event.preventDefault();
  event.currentTarget.classList.add("drag-over");
}

function onTaskPaneDragLeave(event) {
  event.currentTarget.classList.remove("drag-over");
}

function onTaskPaneDrop(event) {
  event.preventDefault();
  event.currentTarget.classList.remove("drag-over");
  const toId = draggedAgentId || event.dataTransfer.getData("text/plain");
  if (!toId) return;
  openReplaceAgentDialog(toId);
}

function openReplaceAgentDialog(preselectedToId = "") {
  const candidates = (APP_STATE.tasks || []).filter(t => !["delivered", "awaiting_owner", "accepted_done", "rejected"].includes(t.status));
  if (candidates.length === 0) {
    showToast("当前没有可替换成员的进行中/待分配任务", true);
    return;
  }
  const activeAgents = (APP_STATE.agents || []).filter(a => a.access_kind !== "chief");
  if (activeAgents.length === 0) {
    showToast("请先添加可替换的目标成员", true);
    return;
  }
  document.getElementById("replaceAgentDialog")?.remove();
  const dialog = document.createElement("dialog");
  dialog.id = "replaceAgentDialog";
  dialog.className = "auth-dialog";
  const defaultTaskId = candidates.length === 1 ? candidates[0].id : "";
  dialog.innerHTML = `<form id="replaceAgentForm">
    <h2>替换任务成员</h2>
    <p>仅支持未开跑且无未决回执的任务；跨厂商替换，经理换人需二次确认。</p>
    <label for="replaceTaskSelect">选择目标任务${candidates.length > 1 ? "（多任务关联，请明确选择）" : ""}</label>
    <select id="replaceTaskSelect" required>
      ${candidates.length > 1 ? '<option value="">-- 请选择要替换的任务 --</option>' : ''}
      ${candidates.map(t => `<option value="${escapeHTML(t.id)}" ${t.id === defaultTaskId ? "selected" : ""}>${escapeHTML(t.title)} (${escapeHTML(t.assigned_name || "未指派")})</option>`).join("")}
    </select>
    <label for="replaceFromSelect">被替换的原成员</label>
    <select id="replaceFromSelect" required></select>
    <label for="replaceToSelect">替换为新成员</label>
    <select id="replaceToSelect" required>${activeAgents.map(a => `<option value="${escapeHTML(a.id)}" ${a.id === preselectedToId ? "selected" : ""}>${escapeHTML(a.name)} (${escapeHTML(a.vendor)} · ${escapeHTML(a.floor)})</option>`).join("")}</select>
    <label id="replaceManagerConfirmWrap" class="hidden" style="display:flex;align-items:center;gap:8px;">
      <input type="checkbox" id="replaceManagerConfirm" /> <span>确认替换经理/圆桌席位（二次确认）</span>
    </label>
    <p id="replaceAgentError" role="alert"></p>
    <div style="display:flex;gap:10px;justify-content:flex-end;">
      <button type="button" class="btn" id="replaceCancelBtn">取消</button>
      <button type="submit" class="btn btn-primary">确认替换</button>
    </div>
  </form>`;
  document.body.appendChild(dialog);
  const taskSel = dialog.querySelector("#replaceTaskSelect");
  const fromSel = dialog.querySelector("#replaceFromSelect");
  const mgrWrap = dialog.querySelector("#replaceManagerConfirmWrap");
  const mgrChk = dialog.querySelector("#replaceManagerConfirm");
  const syncFromOptions = () => {
    const task = candidates.find(t => t.id === taskSel.value);
    const ids = [];
    if (task) {
      if (task.assigned_to) ids.push(task.assigned_to);
      if (task.manager_id && !ids.includes(task.manager_id)) ids.push(task.manager_id);
      Object.values(task.roundtable_state?.seats || {}).forEach(s => { if (s?.id && !ids.includes(s.id)) ids.push(s.id); });
    }
    fromSel.innerHTML = ids.map(id => {
      const a = APP_STATE.agents.find(x => x.id === id);
      return `<option value="${escapeHTML(id)}">${escapeHTML(a ? `${a.name} (${a.floor})` : id)}</option>`;
    }).join("") || '<option value="">-- 请先选任务 --</option>';
    const fromAgent = APP_STATE.agents.find(x => x.id === fromSel.value);
    const isMgr = Boolean(fromAgent && fromAgent.floor === "manager");
    mgrWrap.classList.toggle("hidden", !isMgr);
    if (!isMgr) mgrChk.checked = false;
  };
  taskSel.addEventListener("change", syncFromOptions);
  fromSel.addEventListener("change", () => {
    const fromAgent = APP_STATE.agents.find(x => x.id === fromSel.value);
    const isMgr = Boolean(fromAgent && fromAgent.floor === "manager");
    mgrWrap.classList.toggle("hidden", !isMgr);
    if (!isMgr) mgrChk.checked = false;
  });
  syncFromOptions();
  dialog.querySelector("#replaceCancelBtn").addEventListener("click", () => { dialog.close(); dialog.remove(); });
  dialog.querySelector("#replaceAgentForm").addEventListener("submit", async ev => {
    ev.preventDefault();
    const fromAgent = APP_STATE.agents.find(x => x.id === fromSel.value);
    const isMgr = Boolean(fromAgent && fromAgent.floor === "manager");
    if (isMgr && !mgrChk.checked) {
      dialog.querySelector("#replaceAgentError").textContent = "替换经理必须勾选二次确认。";
      return;
    }
    try {
      await callOfficeAction("replaceagent", {
        task_id: taskSel.value, from_id: fromSel.value, to_id: dialog.querySelector("#replaceToSelect").value,
        confirm_manager: isMgr ? true : false,
      });
      dialog.close();
      dialog.remove();
      showToast("已替换任务成员");
    } catch (err) {
      dialog.querySelector("#replaceAgentError").textContent = err.message;
    }
  });
  dialog.showModal();
}

function switchMainView(view) {
  const showSkills = view === 'skills';
  document.getElementById('workspaceView').classList.toggle('hidden', showSkills);
  document.getElementById('skillsView').classList.toggle('hidden', !showSkills);
}

function switchWorkspaceTab(tab) {
  const activity = tab === 'activity';
  const stream = document.getElementById('groupChatStream');
  if (activity && stream) stream.scrollTop = stream.scrollHeight;
}

function toggleWorkspaceOverview() {
  const panel = document.getElementById('workspaceOverview');
  const hidden = panel.classList.toggle('hidden');
  document.getElementById('overviewToggle').setAttribute('aria-expanded', String(!hidden));
}

function openDetailPanel() {
  if (document.getElementById('workspaceView').classList.contains('hidden')) switchMainView('workspace');
}

function closeDetailPanel() {
  // 右侧当前任务对话区在桌面端常驻，不遮挡主区
}

function switchRightTab(tab) {
  document.getElementById("rTabProfile").classList.toggle("active", tab === "profile");
  document.getElementById("rTabThread").classList.toggle("active", tab === "thread");
  document.getElementById("panelProfile").classList.toggle("active", tab === "profile");
  document.getElementById("panelThread").classList.toggle("active", tab === "thread");
}

function switchMobilePane(pane) {
  if (pane === 'roster') switchMainView('team');
  else if (pane === 'chat') {
    switchMainView('workspace');
    switchWorkspaceTab('activity');
  } else if (pane === 'detail') {
    switchMainView('workspace');
    openDetailPanel();
  }
}

function showToast(msg, isError = false) {
  const c = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = isError ? "toast toast-error" : "toast";
  el.setAttribute("role", isError ? "alert" : "status");
  el.innerHTML = `${icon(isError ? 'alert' : 'check')}<span>${escapeHTML(stripEmoji(msg))}</span>`;
  c.appendChild(el);
  while (c.children.length > 2) c.firstElementChild.remove();
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
