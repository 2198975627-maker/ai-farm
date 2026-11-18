# AI Farm 农场传令兵 — 浏览器扩展 (Browser Extension)

这个轻量级 Chrome / Edge 扩展用于把你日常使用的浏览器和本地 **AI 农场办公室 (`http://127.0.0.1:8765`)** 打通，让**免费网页端 AI（Kimi、豆包、千问、Dola、ChatGPT、Gemini、Grok）**无需人工来回 `Ctrl+C / Ctrl+V`：

1. **自动填入并发送**：在农场办公室点击 **`🌐 打开网页 + 复制指令`** 时，网址会带上 `?ai_farm_task=TASK-xxx`。插件检测到后，自动从本地 `127.0.0.1:8765` 拉取该工单的模板化指令，**自动填入网页聊天框并点击发送**。
2. **一键交差回农场**：等网页 AI 生成完毕后，点击页面右下角悬浮框里的 **`📤 抓最新回复交回农场私聊窗`**（也可以用鼠标选中特定回复段落后再点），结果会直接 POST 回办公室该任务的**私聊汇报窗**（大群自动留一条 `🔒` 折叠提示，不刷屏）。
3. **不触发自动化风控**：因为它直接运行在你本人真实的 Chrome / Edge 浏览器和已登录会话里，不依赖无头爬虫（WebDriver），几乎不会触发滑块或人机验证。

---

## 30 秒安装步骤（Chrome / Edge 通用）

1. 打开浏览器地址栏，输入：
   - **Edge 浏览器**：`edge://extensions`
   - **Chrome 浏览器**：`chrome://extensions`
2. 打开右上角（或左侧）的 **「开发者模式 (Developer mode)」** 开关。
3. 点击 **「加载已解压的扩展程序 (Load unpacked)」**。
4. 选择本项目下的 **`browser-extension`** 文件夹（即 `C:\Users\HP\.gemini\antigravity\scratch\ai-farm\browser-extension`）。
5. 安装完成！现在只要本地运行着 `python -m ai_farm office --port 8765`，打开任意支持的 AI 聊天网页，右下角就会出现 **「🌾 AI 农场传令兵」** 悬浮小助手。
