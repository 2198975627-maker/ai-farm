# AI Farm 开源与桌面应用端演进路线 (Roadmap)

> 目标：在 GitHub 开源后，让任意新用户下载即可用，并支持本地桌面客户端直接调度 WorkBuddy、Codex 等本地工具。

## 1. 账号识别与使用前自动同步规范
- **网页 / 订阅制账号**：
  - 用户在桌面端内置浏览器登录各厂商官网后，每次农场启动或使用前，自动同步一次账号资料：
    - 识别并展示 **会员等级**（例如：Gemini `Plus` / `Pro`、ChatGPT/Codex `Free` / `Plus` / `Pro`）
    - 识别并展示 **会员到期时间**（例如 `2026-12-15`；若厂商页未提供或未登录，诚实标为 `未核实/待同步`，绝不编造）
  - 对应字段：`Agent.tier`、`Agent.expires_at`、`Agent.last_synced_at`（通过 `syncprofiles` 动作统一触发）。
- **API 账号**：
  - 不需要识别会员等级或到期日，只查两件事：**可用余额/额度** 与 **可用模型列表（`GET /models`）**。
  - 在 `OpenAICompatibleAdapter.check_quota()` 查余额时顺便拉取 `/models` 写入 `Quota.available_models`。

## 2. 演进阶段
1. **当前阶段（Python + 本地网页办公室）**：已完成核心接口（`AgentAdapter`）、26+ 办公室交互、两路招募弹窗、安全环境变量机制、PILOT-001 试点 C 验收。
2. **下一步（桌面应用端打包，如 Electron / Tauri / PyWebView）**：
   - 统一托管浏览器本地登录态（Session 存本地，不入库）；
   - 启动时静默访问各订阅账单页同步会员等级与到期时间；
   - 直接调用本机桌面/CLI 工具（如 WorkBuddy、Codex）读写本地工程目录。

## 3. 已完成与待跟进
- [x] **Dola 海外版 & 豆包国内版双招募**：已分别以独立图标、独立适配器（`dola-web` / `doubao-web`）接入 1 楼员工层并写入 `examples/agents.example.yaml`。
