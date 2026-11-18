/* AI Farm Browser Extension & Universal Web Bridge - Content Script
 * Runs on free AI web chat pages (Kimi, Doubao, Qwen, Dola, ChatGPT, Gemini, Grok).
 * Works both as a Chrome/Edge Manifest V3 Extension (via background service worker)
 * and as a direct injected bridge script (via direct CORS fetch to http://127.0.0.1:8765).
 */

(function () {
  if (window.__AI_FARM_BRIDGE_LOADED__) return;
  window.__AI_FARM_BRIDGE_LOADED__ = true;

  const OFFICE_ORIGIN = "http://127.0.0.1:8765";
  let currentTask = null;
  let autoFilledOnce = false;

  function hasExtensionRuntime() {
    return (
      typeof chrome !== "undefined" &&
      chrome.runtime &&
      typeof chrome.runtime.sendMessage === "function" &&
      Boolean(chrome.runtime.id)
    );
  }

  async function callOfficeBridge(type, payload) {
    if (hasExtensionRuntime()) {
      return new Promise((resolve) => {
        chrome.runtime.sendMessage({ type, ...payload }, (resp) => {
          resolve(resp || { ok: false, error: "Extension background did not respond" });
        });
      });
    }
    // Direct fetch fallback when loaded via /bridge.js or bookmarklet
    try {
      const action = type === "GET_TASK_PROMPT" ? "gettaskprompt" : "postmessage";
      const bodyPayload =
        type === "GET_TASK_PROMPT"
          ? { task_id: payload.taskId || "" }
          : {
              task_id: payload.taskId,
              sender_id: payload.workerId || "",
              text: payload.text,
              is_delivery: true,
            };
      const resp = await fetch(`${OFFICE_ORIGIN}/api/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, payload: bodyPayload }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        return { ok: false, error: data.error || `HTTP ${resp.status}` };
      }
      return { ok: true, result: data.result };
    } catch (err) {
      return { ok: false, error: err.message || String(err) };
    }
  }

  function parseTaskIdFromUrl() {
    try {
      const url = new URL(window.location.href);
      const fromQuery = url.searchParams.get("ai_farm_task");
      if (fromQuery) return fromQuery;
      const hashMatch = (window.location.hash || "").match(/ai_farm_task=([A-Za-z0-9_-]+)/);
      if (hashMatch) return hashMatch[1];
    } catch (_) {}
    return "";
  }

  function findChatInputElement() {
    const selectors = [
      "#prompt-textarea",
      "textarea[placeholder]",
      "textarea",
      'div[contenteditable="true"][role="textbox"]',
      'div[contenteditable="true"].ProseMirror',
      'div[contenteditable="true"]',
    ];
    for (const sel of selectors) {
      const els = Array.from(document.querySelectorAll(sel));
      const visible = els.find((el) => {
        const rect = el.getBoundingClientRect();
        return rect.width > 80 && rect.height > 18 && !el.closest("#ai-farm-floating-bridge");
      });
      if (visible) return visible;
    }
    return null;
  }

  function fillPromptIntoElement(el, text) {
    el.focus();
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const proto =
        el.tagName === "TEXTAREA"
          ? window.HTMLTextAreaElement.prototype
          : window.HTMLInputElement.prototype;
      const nativeSetter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (nativeSetter) {
        nativeSetter.call(el, text);
      } else {
        el.value = text;
      }
      el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }

    if (el.isContentEditable) {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(el);
      selection.removeAllRanges();
      selection.addRange(range);
      const ok = document.execCommand && document.execCommand("insertText", false, text);
      if (!ok) {
        el.textContent = text;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
      }
      return true;
    }
    return false;
  }

  function triggerSend(inputEl) {
    const btnSelectors = [
      'button[data-testid="send-button"]',
      'button[aria-label*="发送"]',
      'button[aria-label*="Send"]',
      'div[role="button"][aria-label*="发送"]',
      'button[type="submit"]',
    ];
    for (const sel of btnSelectors) {
      const btn = document.querySelector(sel);
      if (btn && !btn.disabled && !btn.closest("#ai-farm-floating-bridge")) {
        btn.click();
        return true;
      }
    }
    if (inputEl) {
      inputEl.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          code: "Enter",
          keyCode: 13,
          which: 13,
          bubbles: true,
          cancelable: true,
        })
      );
      return true;
    }
    return false;
  }

  function extractLatestReplyText() {
    const selected = (window.getSelection()?.toString() || "").trim();
    if (selected.length >= 10) {
      return selected;
    }
    const replySelectors = [
      '[data-message-author-role="assistant"]',
      "model-response",
      ".segment-content-box",
      ".markdown-body",
      '[class*="assistant-message"]',
      '[class*="answer-content"]',
      '[class*="markdown"]',
    ];
    for (const sel of replySelectors) {
      const nodes = Array.from(document.querySelectorAll(sel)).filter(
        (n) => !n.closest("#ai-farm-floating-bridge") && (n.innerText || "").trim().length >= 15
      );
      if (nodes.length > 0) {
        const last = nodes[nodes.length - 1];
        return last.innerText.trim();
      }
    }
    return "";
  }

  function setStatus(text, isError = false) {
    const el = document.getElementById("ai-farm-bridge-status");
    if (!el) return;
    el.textContent = text;
    el.style.color = isError ? "#fca5a5" : "#bae6fd";
  }

  function handleAutoFillAndSend(autoSend = true) {
    if (!currentTask || !currentTask.prompt) {
      setStatus("尚未加载到工单，请先点「🔄 同步工单」", true);
      return;
    }
    const inputEl = findChatInputElement();
    if (!inputEl) {
      setStatus("未找到聊天输入框（请确认已登录当前网站）", true);
      return;
    }
    fillPromptIntoElement(inputEl, currentTask.prompt);
    if (autoSend) {
      setTimeout(() => {
        triggerSend(inputEl);
        setStatus(`✅ 已自动填入并触发发送：${currentTask.task_id}`);
      }, 350);
    } else {
      setStatus(`📥 已填入输入框：${currentTask.task_id}（请按回车发送）`);
    }
  }

  async function handleSendReplyToOffice() {
    if (!currentTask) {
      setStatus("尚未绑定工单，请先点「🔄 同步工单」", true);
      return;
    }
    const text = extractLatestReplyText();
    if (!text) {
      setStatus("未检测到回复内容（也可鼠标选中回复文字后再点此按钮）", true);
      return;
    }
    setStatus("⏳ 正在交回农场私聊窗...");
    const resp = await callOfficeBridge("SUBMIT_WORKER_REPORT", {
      taskId: currentTask.task_id,
      workerId: currentTask.assigned_to || "",
      text,
    });
    if (resp && resp.ok) {
      setStatus(`🎉 已交回农场私聊窗 (${text.length} 字，大群已留 🔒 提示)！`);
    } else {
      setStatus(`❌ 交回失败: ${(resp && resp.error) || "请确认 127.0.0.1:8765 已启动"}`, true);
    }
  }

  async function loadTaskFromOffice(autoTrigger = false) {
    const urlTaskId = parseTaskIdFromUrl();
    const resp = await callOfficeBridge("GET_TASK_PROMPT", { taskId: urlTaskId });
    const titleEl = document.getElementById("ai-farm-bridge-task");
    if (!resp || !resp.ok || !resp.result) {
      if (titleEl) titleEl.textContent = "未连接本地办公室 (127.0.0.1:8765)";
      setStatus((resp && resp.error) || "请先在办公室派发一张工单", true);
      return;
    }
    currentTask = resp.result;
    if (titleEl) {
      titleEl.textContent = `${currentTask.task_id} · ${currentTask.title.slice(0, 18)}`;
    }
    setStatus(`已就绪：执行者 ${currentTask.assigned_name}`);

    if (autoTrigger && urlTaskId && !autoFilledOnce) {
      autoFilledOnce = true;
      setTimeout(() => handleAutoFillAndSend(true), 900);
    }
  }

  function mountFloatingWidget() {
    if (document.getElementById("ai-farm-floating-bridge")) return;
    const box = document.createElement("div");
    box.id = "ai-farm-floating-bridge";
    box.style.cssText = [
      "position:fixed",
      "right:16px",
      "bottom:16px",
      "z-index:2147483647",
      "width:270px",
      "background:#0f172a",
      "color:#f8fafc",
      "border:1.5px solid #38bdf8",
      "border-radius:10px",
      "padding:10px 12px",
      "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif",
      "font-size:12px",
      "box-shadow:0 8px 24px rgba(0,0,0,0.45)",
    ].join(";");

    box.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <strong style="color:#38bdf8;font-size:12px;">🌾 AI 农场传令兵</strong>
        <button id="ai-farm-btn-sync" style="background:#1e293b;color:#cbd5e1;border:1px solid #334155;border-radius:4px;padding:2px 6px;font-size:11px;cursor:pointer;">🔄 同步工单</button>
      </div>
      <div id="ai-farm-bridge-task" style="font-weight:700;font-size:11px;color:#e2e8f0;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
        正在连接 127.0.0.1:8765...
      </div>
      <div id="ai-farm-bridge-status" style="font-size:11px;color:#bae6fd;margin-bottom:8px;line-height:1.35;">
        等待读取工单...
      </div>
      <div style="display:flex;gap:6px;margin-bottom:6px;">
        <button id="ai-farm-btn-fill" style="flex:1;background:#0284c7;color:#fff;border:none;border-radius:6px;padding:6px 8px;font-size:11px;font-weight:600;cursor:pointer;">
          📥 自动填入并发送
        </button>
      </div>
      <div>
        <button id="ai-farm-btn-report" style="width:100%;background:#10b981;color:#052e16;border:none;border-radius:6px;padding:6px 8px;font-size:11px;font-weight:700;cursor:pointer;">
          📤 抓最新回复交回农场私聊窗
        </button>
      </div>
    `;
    document.body.appendChild(box);

    document.getElementById("ai-farm-btn-sync").addEventListener("click", () => loadTaskFromOffice(false));
    document.getElementById("ai-farm-btn-fill").addEventListener("click", () => handleAutoFillAndSend(true));
    document.getElementById("ai-farm-btn-report").addEventListener("click", handleSendReplyToOffice);
  }

  mountFloatingWidget();
  loadTaskFromOffice(true);
})();
