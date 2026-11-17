# 贡献指南

欢迎加新模型、新技能、新通道。

## 加一个新模型（30 行左右）

1. API：继承 `ai_farm/adapters/openai_compatible.py` 的
   `OpenAICompatibleAdapter`，填 Base URL、模型 ID、环境变量名。
   网页：继承 `ai_farm/adapters/web.py` 的 `WebAdapter`，实现 `chat()`，
   登录只走厂商自己的页面。
2. 在 `ai_farm/adapters/registry.py` 注册一个 slug。
3. 在 `examples/agents.example.yaml` 加一个占位示例（无真 Key）。
4. 在 `tests/test_farm.py` 加一个干跑测试，不调真接口。

## 规则

- 不提交任何真实 Key、密码、会话、个人账号信息。
- 额度查不到就返回 `Quota(kind="unknown")`，不编数字。
- 失败先降级换员工，两次失败才升经理，别一上来就烧经理。
- 文档和代码一起改，示例配置里的模型 ID 以厂商文档为准。
