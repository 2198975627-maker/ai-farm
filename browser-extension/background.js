const DEFAULT_OFFICE_URL = "http://127.0.0.1:8765";
const WORKER_HOSTS = ["kimi.com", "moonshot.cn", "doubao.com", "dola.com", "qianwen.com", "aliyun.com", "chat.qwen.ai", "chatgpt.com", "gemini.google.com", "grok.com"];

function workerContext(sender) {
  if (sender.id !== chrome.runtime.id || !Number.isInteger(sender.tab?.id)) throw new Error("只接受受信扩展的网页标签页消息");
  const url = new URL(sender.url);
  if (url.protocol !== "https:" || !WORKER_HOSTS.some(host => url.hostname === host || url.hostname.endsWith(`.${host}`))) throw new Error("网页来源未获准");
  return { key: `farm-tab-${sender.tab.id}`, origin: url.origin };
}

async function callOfficeApi(token, action, payload) {
  const response = await fetch(`${DEFAULT_OFFICE_URL}/api/action`, {
    method: "POST", redirect: "error", credentials: "omit",
    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
    body: JSON.stringify({ action, payload }),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data.result;
}

async function handleMessage(message, sender) {
  const context = workerContext(sender);
  if (message.type === "BIND_TASK") {
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(message.taskId || "") || !/^[A-Za-z0-9_-]{40,128}$/.test(message.token || "")) throw new Error("请输入工单编号及对应的任务范围凭据");
    const result = await callOfficeApi(message.token, "gettaskprompt", { task_id: message.taskId });
    await chrome.storage.session.set({ [context.key]: { token: message.token, taskId: message.taskId, origin: context.origin, workerId: result.assigned_to } });
    return result;
  }
  const binding = (await chrome.storage.session.get(context.key))[context.key];
  if (!binding || binding.origin !== context.origin || (message.taskId && message.taskId !== binding.taskId)) throw new Error("请先绑定此标签页的工单及任务凭据");
  const common = { task_id: binding.taskId };
  if (message.type === "GET_TASK_PROMPT") return callOfficeApi(binding.token, "gettaskprompt", common);
  if (message.type === "CLAIM_WORKER_SEND") return callOfficeApi(binding.token, "courierclaim", common);
  if (message.type === "SUBMIT_WORKER_REPORT") return callOfficeApi(binding.token, "postmessage", { ...common, sender_id: binding.workerId, text: message.text, is_delivery: true });
  if (message.type === "COURIER_STATUS") return callOfficeApi(binding.token, "courierstatus", { ...common, agent_id: binding.workerId, status: message.status, detail: message.detail || "" });
  throw new Error("未知传令兵操作");
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then(result => sendResponse({ ok: true, result }))
    .catch(error => sendResponse({ ok: false, error: error.message }));
  return true;
});

chrome.tabs.onRemoved.addListener(tabId => chrome.storage.session.remove(`farm-tab-${tabId}`));
