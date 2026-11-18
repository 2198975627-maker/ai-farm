/* AI Farm Browser Extension - Background Service Worker
 * Bridges content scripts on AI web chats with local AI Farm Office (http://127.0.0.1:8765).
 */

const DEFAULT_OFFICE_URL = "http://127.0.0.1:8765";

async function callOfficeApi(action, payload = {}) {
  const resp = await fetch(`${DEFAULT_OFFICE_URL}/api/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, payload }),
  });
  const data = await resp.json();
  if (!resp.ok || !data.ok) {
    throw new Error(data.error || `HTTP ${resp.status}`);
  }
  return data.result;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "GET_TASK_PROMPT") {
    callOfficeApi("gettaskprompt", { task_id: msg.taskId || "" })
      .then((res) => sendResponse({ ok: true, result: res }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // async response
  }

  if (msg.type === "SUBMIT_WORKER_REPORT") {
    callOfficeApi("postmessage", {
      task_id: msg.taskId,
      sender_id: msg.workerId || "",
      text: msg.text,
      is_delivery: true,
    })
      .then((res) => sendResponse({ ok: true, result: res }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // async response
  }
});
