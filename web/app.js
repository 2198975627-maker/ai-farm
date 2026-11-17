/* AI 农场办公室前端控制器 (支持 Python 后端 API + 本地离线双模运行) */

let APP_STATE = {
  backendOnline: false,
  agents: [],
  tasks: [],
  taskSummary: { total: 0, claimed: 0, reported: 0, delivered: 0, accepted: 0 },
  groupMessages: [],
  taskMessages: {},
  skills: [],
  equippedBy: {},
  byFloor: { manager: [], worker: [], rest: [] },
  selectedAgentId: "muse",
  selectedTaskId: null,
  recruitLoggedInClicked: false,
  latestRecommendations: [],
  exampleCursor: 0,
};

// =========================================================================
// 离线后备种子数据（当直接双击 index.html 未开后端时，保持100%同样功能）
// =========================================================================
const SEED_AGENTS = [
  {
    id: "muse", name: "Muse（总管）", brand: "Meta (Muse)", vendor: "Meta",
    model: "Muse 总管（唯一入口）", verified_version: true, access_kind: "chief", paid: false,
    floor: "manager", role_label: "第1层 总管 / 第2层 统筹经理", badge: "总管·唯一入口", badge_color: "blue",
    status: "ready", account_status: "✅ 已核实有号（当前总管，持全量上下文）",
    specialty: "听任务、拆单、派单、记账、质检、整合、汇报、中文理解",
    quota_kind: "none", quota_percent: null, quota_note: "总管唯一对接口，无独立查额度链接",
    usage_url: "", login_url: "", key_env: "", base_url: "",
    fallback_note: "降级后：常驻总管，经理缺席时顶上", attached_tools: [], skills: ["doc-drafting-frame"], icon_kind: "muse"
  },
  {
    id: "gemini-4-argon", name: "Gemini 4 Argon", brand: "Google Gemini", vendor: "Gemini",
    model: "gemini-4-argon", verified_version: true, access_kind: "subscription", paid: true,
    floor: "manager", role_label: "2楼 经理层 · 前端/长代码/文档", badge: "付费·订阅", badge_color: "orange",
    status: "ready", account_status: "✅ 已核实有号（新加坡区，2026-12-15到期/订阅页写12-14，已取消自动续费）",
    specialty: "前端、大块长代码、Canvas文档、架构设计",
    quota_kind: "subscription", quota_percent: 82.0,
    quota_note: "2026-11-16 22:21实查：5小时周期已用18%（剩约82%，2:39重置）；每周已用9%（剩约91%，11月22日0:39重置）",
    usage_url: "https://gemini.google.com/usage", login_url: "https://gemini.google.com/", key_env: "", base_url: "",
    fallback_note: "降级后：Gemini Flash-Lite（订阅制到限额不真停，降级后只能干小活）",
    attached_tools: [], skills: ["doc-drafting-frame", "code-review-checklist"], icon_kind: "text"
  },
  {
    id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", brand: "DeepSeek", vendor: "DeepSeek",
    model: "deepseek-v4-pro", verified_version: true, access_kind: "api", paid: true,
    floor: "manager", role_label: "2楼 经理层 · 代码实现/审查", badge: "付费·API", badge_color: "orange",
    status: "ready", account_status: "✅ 已核实有号（API直连；与 DeepSeek V4 Flash、工具 Codex 共用同一余额）",
    specialty: "中文代码实现、代码审查、架构落地、高性价比推理",
    quota_kind: "api", quota_percent: null,
    quota_note: "额度未填（2026-11-16网页登录受阻；设好 DEEPSEEK_API_KEY 后可调 GET /user/balance 实时读余额）",
    usage_url: "https://platform.deepseek.com/usage", login_url: "", key_env: "DEEPSEEK_API_KEY", base_url: "https://api.deepseek.com/v1",
    fallback_note: "降级后：API余额归0或402真停（先换免费员工，不硬烧）",
    attached_tools: ["🔧 工具 Codex CLI（非模型，不占独立图标，共用本账号 DeepSeek 余额）"],
    skills: ["code-review-checklist"], icon_kind: "text"
  },
  {
    id: "gpt-plus", name: "GPT Plus", brand: "OpenAI ChatGPT", vendor: "ChatGPT",
    model: "待核实具体版本", verified_version: false, access_kind: "subscription", paid: true,
    floor: "manager", role_label: "2楼 经理层 · 架构/复杂推理", badge: "付费·订阅", badge_color: "orange",
    status: "pending", account_status: "❓ 待确认（Gao 已确认没有订 Plus，目前只有 ChatGPT 免费版）",
    specialty: "复杂推理、架构对比、代码审查",
    quota_kind: "subscription", quota_percent: null, quota_note: "额度未填（未开通 Plus，不编造数字）",
    usage_url: "https://chatgpt.com/#settings/Usage", login_url: "https://chatgpt.com/", key_env: "", base_url: "",
    fallback_note: "降级后：mini（订阅制到周期限额切 mini，不真停）", attached_tools: [], skills: [], icon_kind: "text"
  },
  {
    id: "grok-paid", name: "Grok 付费版", brand: "xAI Grok", vendor: "Grok",
    model: "待核实具体版本", verified_version: false, access_kind: "subscription", paid: true,
    floor: "manager", role_label: "2楼 经理层 · 实时情报/舆情", badge: "付费·订阅", badge_color: "orange",
    status: "pending", account_status: "❓ 待确认（Gao 已确认使用的是 Grok 免费版，未确认付费版）",
    specialty: "X 实时热点、舆情分析、快速情报检索",
    quota_kind: "subscription", quota_percent: null, quota_note: "额度未填（待确认是否付费）",
    usage_url: "https://grok.com/", login_url: "https://grok.com/", key_env: "", base_url: "",
    fallback_note: "降级后：待核实具体降级档位", attached_tools: [], skills: [], icon_kind: "text"
  },
  {
    id: "qwen-max", name: "千问 Max", brand: "阿里千问 Qwen", vendor: "Qwen",
    model: "待核实具体版本", verified_version: false, access_kind: "api", paid: true,
    floor: "manager", role_label: "2楼 经理层 · 中文长文/总结", badge: "付费·API", badge_color: "orange",
    status: "pending", account_status: "❓ 待确认（只提过千问名字，尚未确认是否有 Max API Key）",
    specialty: "中文长文统筹、深度总结、专业翻译审校",
    quota_kind: "api", quota_percent: null, quota_note: "额度未填（去阿里百炼控制台查看）",
    usage_url: "https://bailian.console.aliyun.com/", login_url: "", key_env: "QWEN_API_KEY", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    fallback_note: "降级后：API余额归0真停", attached_tools: [], skills: [], icon_kind: "text"
  },
  {
    id: "k-exaone-2-5", name: "K-EXAONE 2.5", brand: "LG EXAONE", vendor: "K-EXAONE",
    model: "k-exaone_v2.5", verified_version: true, access_kind: "api", paid: false,
    floor: "worker", role_label: "1楼 员工层 · 批量初稿/英韩处理", badge: "免费·API", badge_color: "green",
    status: "ready", account_status: "⚠️ 已核实有号（免费至2026-12-10；仅非商业、仅韩/英；2026-11-17早3次真调401/403 Access denied，需在EXAONE控制台核对模型权限）",
    specialty: "512k长上下文、英文/韩语批量初稿、批量分类打标、批量翻译",
    quota_kind: "api", quota_percent: null,
    quota_note: "额度未填（无总额度API，仅靠每次响应头 x-day-rate-limit-remaining 读取）",
    usage_url: "https://docs.exaone.ai/en/my-profile/api-key", login_url: "", key_env: "KEXAONE_API_KEY", base_url: "https://api.exaone.ai/v1",
    fallback_note: "降级后：API报429/403真停（立即换 DeepSeek Flash 或其他免费员工）",
    attached_tools: [], skills: ["batch-translate", "batch-classify", "english-writing"], icon_kind: "text"
  },
  {
    id: "deepseek-v4-flash", name: "DeepSeek V4 Flash", brand: "DeepSeek", vendor: "DeepSeek",
    model: "deepseek-v4-flash（含V3.2）", verified_version: true, access_kind: "api", paid: false,
    floor: "worker", role_label: "1楼 员工层 · 写测试/便宜代码", badge: "免费·API", badge_color: "green",
    status: "ready", account_status: "✅ 已核实有号（替代2026-07-24停用的 deepseek-chat；与 DeepSeek V4 Pro 共用同一余额）",
    specialty: "写单元测试、便宜代码小活、批量翻译、格式化",
    quota_kind: "api", quota_percent: null, quota_note: "额度未填（与 DeepSeek V4 Pro 共用同一 API 余额）",
    usage_url: "https://platform.deepseek.com/usage", login_url: "", key_env: "DEEPSEEK_API_KEY", base_url: "https://api.deepseek.com/v1",
    fallback_note: "降级后：API余额归0真停（换 ChatGPT 免费或千问免费网页）",
    attached_tools: [], skills: ["test-cases", "cheap-code-jobs", "batch-translate"], icon_kind: "text"
  },
  {
    id: "qwen-free-web", name: "千问 免费网页", brand: "阿里通义千问", vendor: "Qwen",
    model: "待核实具体版本", verified_version: false, access_kind: "web", paid: false,
    floor: "worker", role_label: "1楼 员工层 · 中文整理/翻译", badge: "免费·网页", badge_color: "green",
    status: "pending", account_status: "❓ 待确认（待点「登录一次」确认是否有通义千问免费网页号）",
    specialty: "中文批量翻译、名单整理成表格、中文润色、批量分类",
    quota_kind: "unknown", quota_percent: null, quota_note: "额度未填（去通义千问网页端查看）",
    usage_url: "https://tongyi.aliyun.com/", login_url: "https://tongyi.aliyun.com/", key_env: "", base_url: "",
    fallback_note: "降级后：今日限流则休息到明天，轮换给豆包/Kimi",
    attached_tools: [], skills: ["table-cleanup", "chinese-polish", "batch-translate"], icon_kind: "text"
  },
  {
    id: "qwen-paid-api", name: "千问 付费 API", brand: "阿里百炼 Qwen", vendor: "Qwen",
    model: "待核实具体版本", verified_version: false, access_kind: "api", paid: true,
    floor: "worker", role_label: "1楼 员工层 · API批量格式化/摘要", badge: "付费·API", badge_color: "orange",
    status: "pending", account_status: "❓ 待确认（与千问免费网页拆成两个独立图标；待确认百炼 API Key）",
    specialty: "API并行批量摘要、分类打标、表格格式化",
    quota_kind: "api", quota_percent: null, quota_note: "额度未填（去阿里百炼控制台查看）",
    usage_url: "https://bailian.console.aliyun.com/", login_url: "", key_env: "QWEN_API_KEY", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    fallback_note: "降级后：API余额归0真停", attached_tools: [], skills: ["table-cleanup", "batch-classify"], icon_kind: "text"
  },
  {
    id: "gemini-flash-lite", name: "Gemini Flash-Lite", brand: "Google Gemini", vendor: "Gemini",
    model: "待核实具体版本", verified_version: false, access_kind: "web", paid: false,
    floor: "worker", role_label: "1楼 员工层 · 长上下文小活/Pro降级形态", badge: "免费·网页", badge_color: "green",
    status: "ready", account_status: "✅ 已核实有号（Gemini 免费档 / Pro 额度用尽后的自动降级形态）",
    specialty: "长上下文速读、轻量问答、小批量摘要",
    quota_kind: "subscription", quota_percent: null, quota_note: "额度未填（见 gemini.google.com/usage 实时页面）",
    usage_url: "https://gemini.google.com/usage", login_url: "https://gemini.google.com/", key_env: "", base_url: "",
    fallback_note: "降级后：本身即为降级轻量模型，只接边角小任务",
    attached_tools: [], skills: ["long-text-speed-read"], icon_kind: "text"
  },
  {
    id: "chatgpt-free", name: "ChatGPT 免费", brand: "OpenAI ChatGPT", vendor: "ChatGPT",
    model: "待核实具体版本", verified_version: false, access_kind: "web", paid: false,
    floor: "worker", role_label: "1楼 员工层 · 英文写作/小代码", badge: "免费·网页", badge_color: "green",
    status: "ready", account_status: "✅ 已核实有号（Gao 本人确认有免费版账号，与 GPT Plus 拆开独立计算）",
    specialty: "英文写作小活、简单代码、单元测试草稿",
    quota_kind: "subscription", quota_percent: null, quota_note: "额度未填（去 ChatGPT Settings -> Usage 查看）",
    usage_url: "https://chatgpt.com/#settings/Usage", login_url: "https://chatgpt.com/", key_env: "", base_url: "",
    fallback_note: "降级后：mini（免费档达到周期限额后自动降级为 mini，不真停）",
    attached_tools: [], skills: ["english-writing", "cheap-code-jobs"], icon_kind: "text"
  },
  {
    id: "grok-free", name: "Grok 免费", brand: "xAI Grok", vendor: "Grok",
    model: "待核实具体版本", verified_version: false, access_kind: "web", paid: false,
    floor: "worker", role_label: "1楼 员工层 · 网页问答/宣传口号", badge: "免费·网页", badge_color: "green",
    status: "ready", account_status: "✅ 已核实有号（Gao 确认免费版，网页 grok.com 可用，手机 GBox App 暂打不开）",
    specialty: "宣传口号、英文/中文短平快问答、热点摘要",
    quota_kind: "subscription", quota_percent: null, quota_note: "额度未填（去 Grok Settings -> Usage 查看）",
    usage_url: "https://grok.com/", login_url: "https://grok.com/", key_env: "", base_url: "",
    fallback_note: "降级后：触发冷却休息到明天，轮换给其他免费员工",
    attached_tools: [], skills: ["promo-slogans"], icon_kind: "text"
  },
  {
    id: "kimi-free", name: "Kimi 免费", brand: "Moonshot Kimi", vendor: "Kimi",
    model: "待核实具体版本", verified_version: false, access_kind: "web", paid: false,
    floor: "worker", role_label: "1楼 员工层 · 长文三档摘要/速读", badge: "免费·网页", badge_color: "green",
    status: "pending", account_status: "❓ 待确认（待点「登录一次」看看是否有号，无号可当场免费注册）",
    specialty: "长文三档摘要、长文速读、资料归纳",
    quota_kind: "subscription", quota_percent: null, quota_note: "额度未填（去 kimi.com 设置 -> 订阅 查看）",
    usage_url: "https://kimi.com/", login_url: "https://kimi.com/", key_env: "", base_url: "",
    fallback_note: "降级后：今日累了休息，轮换给豆包/Gemini Flash-Lite",
    attached_tools: [], skills: ["three-tier-summary", "long-text-speed-read"], icon_kind: "text"
  },
  {
    id: "doubao-free", name: "豆包 免费", brand: "字节豆包 Doubao", vendor: "Doubao",
    model: "待核实具体版本", verified_version: false, access_kind: "web", paid: false,
    floor: "worker", role_label: "1楼 员工层 · 中文日常问答/润色", badge: "免费·网页", badge_color: "green",
    status: "pending", account_status: "❓ 待确认（待点「登录一次」确认是否有号；简单问答不限，重活有限额）",
    specialty: "中文润色、三档摘要、名单整理成表格、宣传口号",
    quota_kind: "unknown", quota_percent: null, quota_note: "额度未填（官方不给固定数字，无独立查额度页）",
    usage_url: "", login_url: "https://www.doubao.com/", key_env: "", base_url: "",
    fallback_note: "降级后：重活排队时轮换给千问/Kimi",
    attached_tools: [], skills: ["three-tier-summary", "chinese-polish", "table-cleanup"], icon_kind: "text"
  },
  {
    id: "glm-5-3-flash", name: "GLM-5.3-Flash", brand: "智谱 / 国家超算 scnet", vendor: "GLM",
    model: "glm-5.3-flash", verified_version: true, access_kind: "api", paid: false,
    floor: "rest", role_label: "院子休息 · 额度已耗尽 (0%)", badge: "已耗尽·API", badge_color: "red",
    status: "exhausted", account_status: "⛔ 已核实有号（10M免费额度4天已用完，2026-11-15实查剩0%，休息等新额度）",
    specialty: "批量小任务（当前已停用休息）",
    quota_kind: "api", quota_percent: 0.0,
    quota_note: "剩 0%（实查已耗尽，≤10%红条闪烁告警，API归0真停，在院子休息）",
    usage_url: "https://www.scnet.cn/", login_url: "", key_env: "GLM_API_KEY", base_url: "https://open.bigmodel.cn/api/paas/v4",
    fallback_note: "降级后：API余额 0% 真停（等新活动额度再拖回1楼）", attached_tools: [], skills: [], icon_kind: "text"
  },
  {
    id: "workbuddy", name: "Workbuddy", brand: "Workbuddy（待确认）", vendor: "Workbuddy",
    model: "待核实具体版本", verified_version: false, access_kind: "web", paid: false,
    floor: "rest", role_label: "院子休息 · 身份与通道待确认", badge: "待核实·未知", badge_color: "grey",
    status: "pending", account_status: "❓ 待确认（是App、网页还是机器人尚未确认，排在最后核查）",
    specialty: "待 Gao 确认具体形态与用途后再排班",
    quota_kind: "unknown", quota_percent: null, quota_note: "额度未填（无链接，不编造）",
    usage_url: "", login_url: "", key_env: "", base_url: "",
    fallback_note: "降级后：待确认", attached_tools: [], skills: [], icon_kind: "text"
  }
];

const SEED_SKILLS = [
  { slug: "batch-translate", name: "批量翻译", category: "语言与翻译", steps: "1. 逐条翻译，不增不减 2. 术语统一 3. 输出双语对照表，不许自由发挥", best_for: "K-EXAONE / Qwen / ChatGPT Free", savings_note: "10条合成1次员工调用，经理只审表格不重读原文，省80%经理Token" },
  { slug: "table-cleanup", name: "名单整理成表格", category: "数据格式化", steps: "1. 去重 2. 按列对齐为Markdown表格 3. 空值统一标[缺失]，不编造数据", best_for: "Qwen / Doubao", savings_note: "纯格式体力活交免费中文员工，零经理算力消耗" },
  { slug: "three-tier-summary", name: "三档摘要", category: "阅读与摘要", steps: "1. 一句话结论(≤50字) 2. 300字核心摘要 3. 要点清单；数字、人名、日期严格照原文", best_for: "Kimi / Doubao", savings_note: "让免费长文模型先压成300字，经理只读摘要不读万字原文" },
  { slug: "long-text-speed-read", name: "长文速读", category: "阅读与摘要", steps: "1. 提取章节骨架 2. 列出所有数字/日期/专有名词原句定位 3. 标注存疑处", best_for: "Kimi / Gemini Flash-Lite", savings_note: "用512k/长窗口免费档做预筛，避免付费主模型一次性吞入数万Token" },
  { slug: "code-review-checklist", name: "代码审查清单", category: "代码与研发", steps: "1. 逐项核对安全/边界/类型/密钥泄露 2. 只报问题+文件行号+简短原因，不重写全文件", best_for: "DeepSeek Pro / GPT", savings_note: "只看git diff不看全仓，输出限定行号清单，大幅压缩输出Token" },
  { slug: "test-cases", name: "测试用例生成", category: "代码与研发", steps: "1. 覆盖正常/边界/异常三类输入 2. 只写测试文件代码，绝不修改业务源码", best_for: "DeepSeek Flash / ChatGPT Free", savings_note: "测试样板代码由便宜/免费代码员工生成，本地跑通后再交经理核验" },
  { slug: "cheap-code-jobs", name: "便宜代码小活", category: "代码与研发", steps: "1. 单文件小函数/类型补齐/注释规范化 2. 仅输出改动片段或完整单文件，不讲原理", best_for: "DeepSeek Flash / ChatGPT Free", savings_note: "边角代码不唤醒Gemini Argon或DeepSeek Pro，直接省下主力额度" },
  { slug: "chinese-polish", name: "中文润色", category: "语言与翻译", steps: "1. 修正语病与生硬翻译腔 2. 保持原意与全部事实数字不变 3. 给修改前后对比", best_for: "Qwen / Doubao", savings_note: "用免费国产网页模型润色中文段落，不耗付费订阅周期" },
  { slug: "promo-slogans", name: "宣传口号", category: "创意与文案", steps: "1. 按目标受众生成5条不同风格备选 2. 每条≤20字 3. 附一句适用场景说明", best_for: "Doubao / Qwen / Grok Free", savings_note: "发散型短文案由免费员工批量出备选，Gao直接挑" },
  { slug: "english-writing", name: "英文写作小活", category: "语言与翻译", steps: "1. 语法与地道表达检查 2. 按指定语气输出 3. 不增删核心信息", best_for: "ChatGPT Free / K-EXAONE", savings_note: "英文短文交给免费GPT网页或K-EXAONE，无需动用付费经理" },
  { slug: "batch-classify", name: "批量分类打标", category: "数据格式化", steps: "1. 严格按给定标签集合分类 2. 每条输出[编号 -> 标签] 3. 不确定的标unknown，绝不乱猜", best_for: "K-EXAONE / Qwen", savings_note: "分类输出仅几个词，极省completion tokens，适合免费API批量跑" },
  { slug: "doc-drafting-frame", name: "文档起草框架", category: "规划与架构", steps: "1. 先列二级目录大纲与验收点 2. 标记哪些小节由哪个员工填内容 3. 经理审完大纲再填正文", best_for: "Muse / Gemini Argon / Qwen Max", savings_note: "经理只写200字骨架，几千字正文拆给免费员工填，彻底告别Canvas长输出卡死" },
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
      document.getElementById("connModeBadge").textContent = "🟢 Python 后端已连接 (26 Actions + AgentAdapter)";
      applySnapshot(data);
      return;
    }
  } catch (_) {
    // 离线文件模式
  }
  APP_STATE.backendOnline = false;
  document.getElementById("connModeBadge").textContent = "🔵 本地演示模式 (运行 python -m ai_farm office 可连后端)";
  APP_STATE.agents = JSON.parse(JSON.stringify(SEED_AGENTS));
  APP_STATE.skills = JSON.parse(JSON.stringify(SEED_SKILLS));
  APP_STATE.groupMessages = [
    {
      id: "msg-welcome-1",
      sender_id: "muse",
      sender_name: "Muse（总管）",
      kind: "system_welcome",
      text: "👋 欢迎来到 **AI 农场办公室**！我是总管 **Muse**。\n• 左侧 **17 个模型图标**严格按「一个图标 = 一个模型」拆分；Codex 是工具（挂在 DeepSeek V4 Pro 下共用同一余额，不单占模型图标）。\n• 真实法力值：**Gemini 4 Argon**（5小时剩 82% / 每周剩 91%）、**GLM-5.3-Flash**（0% 红条闪烁告警）；未核实的一律标「**额度未填**」。",
      created_at: new Date().toLocaleTimeString(),
    }
  ];
  renderAll();
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
  renderGroupChat();
  renderSelectedAgentProfile();
  renderSelectedTaskThread();
  renderTeamOverview();
  renderSkillCenter();
}

function renderTopBar() {
  // 厂商条
  const vendors = [...new Set(APP_STATE.agents.map(a => `${a.vendor}`))];
  const strip = document.getElementById("vendorStrip");
  strip.innerHTML = `<span style="font-size:10px;color:#94a3b8;">独立厂商池 (${vendors.length}家，各走各号)：</span>` +
    vendors.map(v => `<span class="vendor-chip">${escapeHTML(v)}</span>`).join("");

  // 顶部任务统计
  const s = APP_STATE.taskSummary;
  document.getElementById("statClaimed").textContent = `${s.claimed}/${s.total}`;
  document.getElementById("statReported").textContent = `${s.reported}/${s.total}`;
  document.getElementById("statDelivered").textContent = `${s.delivered}`;
  document.getElementById("statAccepted").textContent = `${s.accepted}`;

  // 低额度告警 (≤10%)
  const lowAgents = APP_STATE.agents.filter(a => a.quota_percent !== null && a.quota_percent !== undefined && Number(a.quota_percent) <= 10);
  const lowEl = document.getElementById("statLowQuota");
  if (lowAgents.length > 0) {
    lowEl.classList.remove("hidden");
    lowEl.textContent = `🚨 低额度告警 (≤10%): ` + lowAgents.map(a => `${a.name} (${a.quota_percent}%)`).join(", ");
    lowEl.onclick = () => selectAgent(lowAgents[0].id);
  } else {
    lowEl.classList.add("hidden");
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
  document.getElementById("rosterTotalBadge").textContent = `${APP_STATE.agents.length} 模型图标 + Codex工具`;

  ["manager", "worker", "rest"].forEach(fl => {
    const container = document.getElementById(
      fl === "manager" ? "listManager" : fl === "worker" ? "listWorker" : "listRest"
    );
    container.innerHTML = floors[fl].map(agent => renderAgentCardHTML(agent)).join("");
  });
}

function renderAgentCardHTML(agent) {
  const isSelected = agent.id === APP_STATE.selectedAgentId ? "selected" : "";
  const hasPct = agent.quota_percent !== null && agent.quota_percent !== undefined;
  const pct = hasPct ? Number(agent.quota_percent) : null;
  const isLow = hasPct && pct <= 10;
  const fillClass = !hasPct ? "unknown" : isLow ? "low-red" : "";
  const labelText = !hasPct ? "额度未填" : isLow ? `⚠️ 剩 ${pct}%` : `剩 ${pct}%`;
  const widthPct = !hasPct ? 100 : Math.max(4, pct);

  const toolsHTML = (agent.attached_tools || []).map(t =>
    `<div class="tool-attachment-pill">${escapeHTML(t)}</div>`
  ).join("");

  return `
    <div class="agent-card ${isSelected}" draggable="true"
         ondragstart="onAgentDragStart(event, '${agent.id}')"
         onclick="selectAgent('${agent.id}')">
      <div class="agent-row-top">
        ${renderAvatarHTML(agent)}
        <div class="agent-meta">
          <div class="agent-name-line">
            <span class="agent-name">${escapeHTML(agent.name)}</span>
            <span class="access-badge ${agent.badge_color || 'green'}">${escapeHTML(agent.badge)}</span>
          </div>
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
        </div>
      </div>
      ${toolsHTML}
      <div class="mana-bar-wrap" onclick="handleManaBarClick(event, '${agent.id}')"
           title="${escapeHTML(agent.quota_note || '')}${agent.usage_url ? '（点击跳转官方实时查额度页）' : '（无独立查额度链接）'}">
        <div class="mana-track">
          <div class="mana-fill ${fillClass}" style="width:${widthPct}%"></div>
        </div>
        <span class="mana-label ${fillClass}">${labelText} ${agent.usage_url ? '↗' : ''}</span>
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

function renderTaskStepFlow(status) {
  const order = ["assigned", "accepted", "working", "delivered", "accepted_done"];
  const labels = [
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
  }).join("<span>→</span>") + (status === "rejected" ? ` <span style="color:#f87171;font-weight:700;">(↩已打回重做)</span>` : "") + `</div>`;
}

function renderGroupChat() {
  // 顶部快速切换任务条
  const strip = document.getElementById("activeTaskStrip");
  if (APP_STATE.tasks.length === 0) {
    strip.innerHTML = `<span style="font-size:11px;color:#64748b;">当前暂无派单，可点右上角「🧪 一键塞入通用示例任务」测试完整流程</span>`;
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
    const isGao = msg.sender_id === "gao";
    const task = msg.task_id ? APP_STATE.tasks.find(t => t.id === msg.task_id) : null;
    let actionBarHTML = "";

    if (task && msg.kind === "task_card") {
      actionBarHTML = `
        <div class="card-actions-bar">
          ${renderTaskStepFlow(task.status)}
          ${task.status === "assigned" ? `
            <button class="btn btn-example" onclick="handleClaimTask('${task.id}', '${task.assigned_to || ''}')">
              ✋ 员工点击领取 (${escapeHTML(task.assigned_name)})
            </button>
          ` : ""}
          <button class="btn btn-ghost" onclick="openTaskPrivateThread('${task.id}')">
            🔒 打开私聊汇报窗 (${task.worker_reported ? '已汇报' : '待汇报'})
          </button>
          ${task.status !== "accepted_done" ? `
            <button class="btn btn-primary" onclick="handleDeliverFinalResult('${task.id}')">
              📦 经理统筹交付总结果
            </button>
          ` : ""}
        </div>
      `;
    } else if (task && msg.kind === "private_report_lock") {
      actionBarHTML = `
        <div class="card-actions-bar">
          <button class="btn btn-ghost" onclick="openTaskPrivateThread('${task.id}')">
            🔍 经理点此审阅私聊摘要/diff
          </button>
          <button class="btn btn-primary" onclick="handleDeliverFinalResult('${task.id}')">
            📦 经理统筹交付给 Gao
          </button>
        </div>
      `;
    } else if (task && msg.kind === "final_delivery_card") {
      actionBarHTML = `
        <div class="card-actions-bar">
          ${renderTaskStepFlow(task.status)}
          <button class="btn btn-success" onclick="handleReviewFinalResult('${task.id}', 'verified')">
            ✅ 验收通过
          </button>
          <button class="btn btn-danger" onclick="handleReviewFinalResult('${task.id}', 'rejected')">
            ↩ 打回重做
          </button>
        </div>
      `;
    }

    return `
      <div class="chat-bubble ${isGao ? 'from-gao' : ''} kind-${msg.kind || 'chat'}">
        <div class="bubble-header">
          <span class="bubble-sender">${escapeHTML(msg.sender_name)}</span>
          <span>${escapeHTML(msg.created_at || '')}</span>
        </div>
        <div class="bubble-body">${formatChatTextWithMentions(msg.text)}</div>
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

  container.innerHTML = `
    <div class="profile-box">
      <div class="identity-block">
        <h4>🔒 私聊专线：${escapeHTML(task.assigned_name)} ⇄ 经理 ${escapeHTML(task.manager_name)}</h4>
        <div style="font-size:12px;font-weight:700;margin-bottom:4px;">${escapeHTML(task.id)} · ${escapeHTML(task.title)}</div>
        ${renderTaskStepFlow(task.status)}
        <div style="font-size:11px;color:#94a3b8;margin-top:6px;">
          • <strong>当前执行员工</strong>：${escapeHTML(task.assigned_name)}（厂商：${escapeHTML(task.assigned_vendor || '待认领')}）<br/>
          • <strong>省 Token 规则</strong>：员工汇报正文只留在本私聊窗，大群里仅发一条 🔒 提示；经理核验后再点「统筹交付」发回大群给 Gao。
        </div>
      </div>

      <!-- 快捷操作栏：干跑 Adapter / 提交私聊汇报 / 跨厂商转交 / 经理统筹交付 -->
      <div class="identity-block">
        <h4>⚡ 员工执行与汇报操作</h4>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
          <button class="btn btn-example" onclick="handleRunAdapterTask('${task.id}', false)">
            🧪 调 AgentAdapter 干跑 (0消耗)
          </button>
          <button class="btn btn-ghost" onclick="handleCopyWorkerPrompt('${task.id}')" title="一键复制标准指令，直接粘贴给 WorkBuddy 桌面端或网页端执行">
            📋 复制工单指令 (给桌面/网页跑)
          </button>
          <button class="btn btn-ghost" onclick="handleExportTaskMd('${task.id}')" title="生成工单 .md 文件并复制 @文件 触发句，可直接贴进 WorkBuddy @引用文件执行">
            📂 导出 .md + 复制 @触发句
          </button>
          <button class="btn btn-primary" onclick="handleDeliverFinalResult('${task.id}')">
            📦 经理统筹交付总结果给 Gao
          </button>
        </div>

        <form onsubmit="handleWorkerPrivateReport(event, '${task.id}')" style="margin-bottom:10px;">
          <label style="font-size:11px;color:#cbd5e1;display:block;margin-bottom:4px;">📤 员工在私聊提交产出汇报（群里只留 🔒 提示）：</label>
          <textarea id="privateReportInput" rows="3" placeholder="输入员工按模板完成的表格/测试/摘要产出..."
                    style="width:100%;background:#0f172a;border:1px solid #334155;color:#fff;padding:6px;border-radius:6px;font-size:12px;margin-bottom:6px;" required>| 序号 | 英文原句 | 中文翻译 |\n|---|---|---|\n| 1 | Insulated stainless steel water bottle... | 保温不锈钢水壶，保冷24小时。 |\n| ... | (共10条已按模板全部译完，无自由发挥) | ... |</textarea>
          <button type="submit" class="btn btn-ghost" style="width:100%;">🔒 发送私聊汇报（不刷大群）</button>
        </form>

        <div style="border-top:1px dashed #334155;padding-top:8px;">
          <label style="font-size:11px;color:#cbd5e1;display:block;margin-bottom:4px;">↪ 跨厂商轮换转交（强制仅限不同厂商，禁止同家多开倒手）：</label>
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
            <div style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:7px 9px;font-size:12px;">
              <div style="display:flex;justify-content:space-between;color:#94a3b8;font-size:10px;margin-bottom:3px;">
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
function renderTeamOverview() {
  const managers = APP_STATE.agents.filter(a => a.floor === "manager").length;
  const workers = APP_STATE.agents.filter(a => a.floor === "worker").length;
  const rest = APP_STATE.agents.filter(a => a.floor === "rest").length;
  const el = document.getElementById("teamOverviewBox");
  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
      <strong>📊 农场真实账本总览</strong>
      <span style="color:#38bdf8;">已真接模型：0（待选试点+配Key）</span>
    </div>
    <div>2楼经理 <strong>${managers}</strong> · 1楼免费员工 <strong>${workers}</strong> · 院子休息 <strong>${rest}</strong> · 工具 <strong>Codex</strong>(挂DeepSeek Pro)</div>
    <div style="color:#94a3b8;margin-top:2px;">已核实有号 7 家：Muse / Gemini Argon(82%) / DeepSeek Pro / K-EXAONE / GLM(0%) / ChatGPT免费 / Grok免费</div>
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
      <strong>🧠 高级模型裁判「${escapeHTML(res.judge)}」打分推荐清单（请 Gao 打勾批准后应用）：</strong>
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

async function handleWorkerPrivateReport(event, taskId) {
  event.preventDefault();
  const text = document.getElementById("privateReportInput").value.trim();
  if (!text) return;
  const task = APP_STATE.tasks.find(t => t.id === taskId);
  await callOfficeAction("postmessage", {
    task_id: taskId,
    sender_id: task ? task.assigned_to : "deepseek-v4-flash",
    text,
    is_delivery: true,
  });
  await openTaskPrivateThread(taskId);
  showToast("🔒 私聊汇报已发给经理（大群仅留折叠提示，未刷屏）！");
}

async function handleRunAdapterTask(taskId, live = false) {
  const res = await callOfficeAction("runadaptertask", { task_id: taskId, live });
  await openTaskPrivateThread(taskId);
  if (res) {
    showToast(`🔌 ${res.mode === 'dry_run' ? 'AgentAdapter 干跑完成 (0消耗)' : '真实调用完成'}`);
  }
}

async function handleCopyWorkerPrompt(taskId) {
  const task = APP_STATE.tasks.find(t => t.id === taskId);
  if (!task) return;
  const promptText =
    `你是执行员工，只做下面这件事，不要做决定。\n` +
    `任务目标：${task.goal}\n` +
    `输入内容：\n${task.input_text}\n` +
    `强制输出格式：${task.output_format}\n` +
    `验收标准：${task.acceptance}\n` +
    `红线：不确定的写“未核实”，不要猜。不许自由发挥。`;
  try {
    await navigator.clipboard.writeText(promptText);
    showToast("📋 已复制标准派单指令！直接切到 WorkBuddy 桌面端粘贴运行，完成后把结果贴回下方汇报框即可。");
  } catch (_) {
    showToast("复制失败，请手动从下方系统消息框复制指令", true);
  }
}

async function handleExportTaskMd(taskId) {
  const res = await callOfficeAction("exporttaskmd", { task_id: taskId });
  if (!res) return;
  try {
    await navigator.clipboard.writeText(res.trigger_text);
    showToast(`📂 已生成 ${res.rel_path} 并复制 @触发句！直接去 WorkBuddy 粘贴按回车即可。`);
  } catch (_) {
    showToast(`📂 已生成 ${res.rel_path}，触发句：${res.trigger_text}`);
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
  showToast("🏁 经理已将统筹最终结果发回大群，请 Gao 验收！");
}

async function handleReviewFinalResult(taskId, decision) {
  await callOfficeAction("reviewfinalresult", { task_id: taskId, decision });
  showToast(decision === "verified" ? "✅ Gao 已验收通过！" : "↩ 已打回重做！");
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
}

function closeRecruitModal() {
  document.getElementById("recruitModal").classList.add("hidden");
}

function switchRecruitPath(path) {
  document.getElementById("recPathInput").value = path;
  document.getElementById("pathBtnApi").classList.toggle("active", path === "api");
  document.getElementById("pathBtnWeb").classList.toggle("active", path === "web");
  document.getElementById("recApiFields").classList.toggle("hidden", path !== "api");
  document.getElementById("recWebFields").classList.toggle("hidden", path !== "web");
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

  document.getElementById("newTaskModal").classList.remove("hidden");
}

function closeNewTaskModal() {
  document.getElementById("newTaskModal").classList.add("hidden");
}

async function handleCreateTaskSubmit(event) {
  event.preventDefault();
  const payload = {
    title: document.getElementById("taskTitle").value.trim(),
    manager_id: document.getElementById("taskManagerSelect").value,
    assigned_to: document.getElementById("taskWorkerSelect").value,
    skill_slug: document.getElementById("taskSkillSelect").value,
    goal: document.getElementById("taskGoal").value.trim(),
    input_text: document.getElementById("taskInput").value.trim(),
    output_format: document.getElementById("taskFormat").value.trim(),
    acceptance: document.getElementById("taskAcceptance").value.trim(),
  };
  const task = await callOfficeAction("createtask", payload);
  closeNewTaskModal();
  if (task) {
    APP_STATE.selectedTaskId = task.id;
    showToast(`📌 已在大群发布任务：${task.title}`);
  }
}

function openNewSkillModal() {
  document.getElementById("newSkillModal").classList.remove("hidden");
}
function closeNewSkillModal() {
  document.getElementById("newSkillModal").classList.add("hidden");
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
