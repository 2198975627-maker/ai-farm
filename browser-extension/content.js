/* Task-scoped courier; credentials remain in extension session storage. */

(function () {
  if (window.__AI_FARM_BRIDGE_LOADED__) return;
  window.__AI_FARM_BRIDGE_LOADED__ = true;

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
    return { ok: false, error: "请使用已安装的传令兵扩展；不允许匿名网页直连办公室。" };
  }

  function detectCaptcha() {
    const captchaSelectors = [
      'iframe[src*="captcha"]', 'iframe[src*="recaptcha"]', 'iframe[src*="hcaptcha"]',
      'iframe[title*="captcha" i]', 'iframe[title*="验证"]',
      '.g-recaptcha', '.h-captcha', '#cf-chl-running', '#challenge-running',
      '[class*="captcha"]', '[id*="captcha"]', '[class*="verify-wrap"]',
    ];
    for (const sel of captchaSelectors) {
      const el = document.querySelector(sel);
      if (el && !el.closest("#ai-farm-floating-bridge")) {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) return "检测到验证码 / 风控组件";
      }
    }
    const bodyText = (document.body?.innerText || "").slice(0, 4000);
    const riskPhrases = [
      "请完成安全验证", "人机验证", "拖动滑块", "访问验证", "异常流量",
      "verify you are human", "unusual traffic", "are you a robot",
      "complete the security check", "press and hold",
    ];
    for (const phrase of riskPhrases) {
      if (bodyText.toLowerCase().includes(phrase.toLowerCase())) return `页面提示：${phrase}`;
    }
    return "";
  }

  async function reportCourier(status, detail) {
    try {
      await callOfficeBridge("COURIER_STATUS", {
        taskId: (currentTask && currentTask.task_id) || parseTaskIdFromUrl() || "",
        agentId: (currentTask && currentTask.assigned_to) || "",
        status,
        detail: detail || "",
        url: window.location.href,
      });
    } catch (_) {
      /* self-check reporting must never break the page */
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

  function triggerSend(inputEl, retries = 5) {
    const btnSelectors = [
      'button[data-testid="send-button"]',
      'button[aria-label*="发送"]',
      'button[aria-label*="Send"]',
      'div[role="button"][aria-label*="发送"]',
      'button[type="submit"]',
    ];
    for (const sel of btnSelectors) {
      const btn = document.querySelector(sel);
      if (btn && !btn.closest("#ai-farm-floating-bridge")) {
        if (!btn.disabled && btn.getAttribute("aria-disabled") !== "true") {
          btn.click();
          return true;
        }
        if (retries > 0) {
          setTimeout(() => triggerSend(inputEl, retries - 1), 120);
          return true;
        }
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
    // Prefer explicit assistant-only selectors first so we never accidentally grab the user's own prompt
    const strictAssistantSelectors = [
      '[data-message-author-role="assistant"]',
      "model-response",
      '[class*="assistant-message"]',
      '[class*="answer-content"]',
    ];
    const fallbackSelectors = [
      ".segment-content-box",
      ".markdown-body",
      '[class*="markdown"]',
    ];
    const isValidReply = (node, txt) => {
      if (!txt || txt.length < 15) return false;
      if (node.closest("#ai-farm-floating-bridge")) return false;
      if (node.closest('[data-message-author-role="user"], [class*="user-message"], [class*="question"]')) return false;
      // Guard against capturing our own templated task prompt when the AI hasn't replied yet
      if (txt.includes("你是执行员工，只做下面这件事，不要做决定。") && txt.includes("红线：不确定的写“未核实”")) {
        return false;
      }
      return true;
    };

    for (const sel of [...strictAssistantSelectors, ...fallbackSelectors]) {
      const nodes = Array.from(document.querySelectorAll(sel)).filter((n) =>
        isValidReply(n, (n.innerText || "").trim())
      );
      if (nodes.length > 0) {
        return nodes[nodes.length - 1].innerText.trim();
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

  async function handleAutoFillAndSend(autoSend = true) {
    if (currentTask?.dispatch_allowed === false) {
      setStatus("此子单已派发、状态未知或已回收，不可重复发送；请主人核查回执。", true);
      return;
    }
    if (!currentTask || !currentTask.prompt) {
      setStatus("尚未加载到工单，请先点「同步工单」", true);
      return;
    }
    const captcha = detectCaptcha();
    if (captcha) {
      setStatus(`卡住了：${captcha}，等主人处理（不自动发送）`, true);
      reportCourier("captcha", captcha);
      return;
    }
    const inputEl = findChatInputElement();
    if (!inputEl) {
      setStatus("选择器失效：未找到聊天输入框（网页可能改版或未登录）", true);
      reportCourier("selector_failed", "未找到聊天输入框，可能网页改版或未登录");
      return;
    }
    const reservation = await callOfficeBridge("CLAIM_WORKER_SEND", { taskId: currentTask.task_id });
    if (!reservation.ok || !reservation.result?.claimed) {
      setStatus(reservation.error || "工单派发状态未确认，停止重复发送", true);
      return;
    }
    fillPromptIntoElement(inputEl, currentTask.prompt);
    if (autoSend) {
      setTimeout(() => {
        const sent = triggerSend(inputEl);
        if (sent) {
          setStatus(`已自动填入并触发发送：${currentTask.task_id}`);
          reportCourier("ok", "已自动填入并触发发送");
        } else {
          setStatus("选择器失效：找不到发送按钮，无法自动发送", true);
          reportCourier("send_failed", "找不到可用的发送按钮");
        }
      }, 350);
    } else {
      setStatus(`已填入输入框：${currentTask.task_id}（请按回车发送）`);
    }
  }

  async function handleSendReplyToOffice() {
    if (!currentTask) {
      setStatus("尚未绑定工单，请先点「同步工单」", true);
      return;
    }
    const captcha = detectCaptcha();
    if (captcha) {
      setStatus(`卡住了：${captcha}，等主人处理`, true);
      reportCourier("captcha", captcha);
      return;
    }
    let text = extractLatestReplyText();
    if (!text) {
      // retry once after a short delay (one-shot, not polling)
      setStatus("未检测到回复，自动重试一次...");
      reportCourier("retry", "首次未抓到回复，重试一次");
      await new Promise((r) => setTimeout(r, 1200));
      text = extractLatestReplyText();
    }
    if (!text) {
      setStatus("重试后仍抓不到回复（选择器可能失效），已上报，等主人处理或换员工", true);
      reportCourier("stuck", "重试一次后仍未检测到回复内容，可能网页改版");
      return;
    }
    setStatus("正在交回农场私聊窗...");
    const resp = await callOfficeBridge("SUBMIT_WORKER_REPORT", {
      taskId: currentTask.task_id,
      workerId: currentTask.assigned_to || "",
      text,
    });
    if (resp && resp.ok) {
      setStatus(`已交回农场私聊窗 (${text.length} 字，大群已留提示)！`);
      reportCourier("delivered", `已交回结论 ${text.length} 字`);
    } else {
      setStatus(`交回失败: ${(resp && resp.error) || "请确认 127.0.0.1:8765 已启动"}`, true);
      reportCourier("send_failed", `交回办公室失败：${(resp && resp.error) || "office unreachable"}`);
    }
  }

  function runSelfCheck() {
    const captcha = detectCaptcha();
    if (captcha) {
      setStatus(`自检：${captcha} — 已上报，等主人处理`, true);
      reportCourier("captcha", captcha);
      return;
    }
    const inputEl = findChatInputElement();
    if (!inputEl) {
      setStatus("自检：选择器失效（找不到输入框），已上报", true);
      reportCourier("selector_failed", "自检找不到聊天输入框");
      return;
    }
    const reply = extractLatestReplyText();
    setStatus(`自检通过：输入框正常${reply ? "，已检测到回复" : "，暂无回复"}，登录态正常`);
    reportCourier("login_ok", "自检通过：输入框可用，无验证码");
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
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;gap:6px;">
        <strong style="color:#38bdf8;font-size:12px;">AI 农场传令兵</strong>
        <span style="display:flex;gap:4px;">
          <button id="ai-farm-btn-bind" style="background:#1e293b;color:#cbd5e1;border:1px solid #334155;border-radius:4px;padding:2px 6px;font-size:11px;cursor:pointer;">绑定工单</button>
          <button id="ai-farm-btn-check" style="background:#1e293b;color:#cbd5e1;border:1px solid #334155;border-radius:4px;padding:2px 6px;font-size:11px;cursor:pointer;">自检</button>
          <button id="ai-farm-btn-sync" style="background:#1e293b;color:#cbd5e1;border:1px solid #334155;border-radius:4px;padding:2px 6px;font-size:11px;cursor:pointer;">同步工单</button>
        </span>
      </div>
      <div id="ai-farm-bridge-task" style="font-weight:700;font-size:11px;color:#e2e8f0;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
        正在连接 127.0.0.1:8765...
      </div>
      <div id="ai-farm-bridge-status" style="font-size:11px;color:#bae6fd;margin-bottom:8px;line-height:1.35;">
        等待读取工单...
      </div>
      <div style="display:flex;gap:6px;margin-bottom:6px;">
        <button id="ai-farm-btn-fill" style="flex:1;background:#0284c7;color:#fff;border:none;border-radius:6px;padding:6px 8px;font-size:11px;font-weight:600;cursor:pointer;">
          自动填入并发送
        </button>
      </div>
      <div>
        <button id="ai-farm-btn-report" style="width:100%;background:#10b981;color:#052e16;border:none;border-radius:6px;padding:6px 8px;font-size:11px;font-weight:700;cursor:pointer;">
          抓最新回复交回农场私聊窗
        </button>
      </div>
    `;
    document.body.appendChild(box);

    document.getElementById("ai-farm-btn-bind").addEventListener("click", async event => {
      if (!event.isTrusted) return;
      const taskId = window.prompt("工单编号", parseTaskIdFromUrl());
      if (!taskId) return;
      let token = window.prompt("粘贴此工单的传令兵凭据（不是主人配对码或 API Key）");
      if (!token) return;
      const response = await callOfficeBridge("BIND_TASK", { taskId: taskId.trim(), token: token.trim() });
      token = "";
      if (!response.ok) return setStatus(response.error, true);
      currentTask = response.result;
      document.getElementById("ai-farm-bridge-task").textContent = `${currentTask.task_id} · ${currentTask.title}`;
      setStatus("工单已绑定；请核对后点击自动填入并发送。");
    });
    document.getElementById("ai-farm-btn-check").addEventListener("click", event => { if (event.isTrusted) runSelfCheck(); });
    document.getElementById("ai-farm-btn-sync").addEventListener("click", event => { if (event.isTrusted) loadTaskFromOffice(false); });
    document.getElementById("ai-farm-btn-fill").addEventListener("click", event => { if (event.isTrusted) handleAutoFillAndSend(true); });
    document.getElementById("ai-farm-btn-report").addEventListener("click", event => { if (event.isTrusted) handleSendReplyToOffice(); });
  }

  mountFloatingWidget();
  loadTaskFromOffice(false);
  // one-shot self-check on load (event-driven, no polling): surface captcha /
  // selector failure immediately so the office knows the web channel is stuck.
  setTimeout(runSelfCheck, 1500);
})();
