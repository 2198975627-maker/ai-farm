# 招募手册：谁都可以随心所欲招募不同的 AI Agent

招募 = 在花名册里加一个图标。两种流程，按接入方式分：

## 1. API（付费或免费 API）

适用：DeepSeek、K-EXAONE、Qwen、GLM 等 OpenAI 兼容接口。

1. 去厂商后台领 Key（只在创建时显示一次，关掉就看不到，丢了重建）。
2. 在你自己的 shell 里：
   ```bash
   export DEEPSEEK_API_KEY="<你的 Key>"
   ```
   Key 别写进任何文件，别发聊天里，别截图。
3. 在 `agents.yaml` 里加一行，只填环境变量的**名字**：
   ```yaml
   - name: "DeepSeek V4 Flash"
     slug: "deepseek-flash"
     role: "worker"
     vendor: "DeepSeek"
     model_id: "deepseek-v4-flash"
     access_kind: "api"
     key_env: "DEEPSEEK_API_KEY"
     base_url: "https://api.deepseek.com/v1"
   ```
4. 干跑验证：`python -m ai_farm run examples/tasks/example-task.md --dry-run`

命令行交互版：`python -m ai_farm recruit`，选 `api`，它只会问你要
环境变量名，不会问你要 Key 本身。

## 2. 网页 / 订阅制（免费网页 + 付费订阅）

适用：Gemini 网页、ChatGPT 网页、Grok 网页等没有稳定 API 的。

1. 在 `agents.yaml` 里加一行，填厂商登录页：
   ```yaml
   - name: "ChatGPT Free"
     slug: "chatgpt-web"
     role: "worker"
     vendor: "ChatGPT"
     model_id: "gpt-5.3"
     access_kind: "web"
     login_url: "https://chatgpt.com/"
     usage_url: "https://chatgpt.com/#settings/Usage"
   ```
2. 点 **登录一次**：在厂商自己的页面登你自己的号。
   本项目永远不问你要密码，密码只交给厂商。
3. 会话只存在你本地浏览器 / `~/.ai-farm/sessions/`，不进仓库，
   换电脑要重新登一次。
4. 额度去厂商用量页看，办公室蓝条上挂的就是那个链接。

命令行交互版：`python -m ai_farm recruit`，选 `web` 或
`subscription`，它会打开登录页让你登。

## 规则

- 一个图标 = 一个模型；同一家付费+免费分开两个图标。
- 一厂商一免费号，不要多开小号绕额度。
- 工具（Codex 这类跑代码的 CLI）不是模型，不占图标，在档案里
  注明它接的是哪个模型的余额。
- 额度查不到就写“额度未填”，不编数字。
