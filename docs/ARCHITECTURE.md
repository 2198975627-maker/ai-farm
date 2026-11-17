# 架构

## 分层

```
你（发任务、拍板、验收、填密钥/付钱）
  ↓
总管（唯一对接口：拆单、派单、记账、质检、整合、汇报）
  ↓
经理层（付费/强推理，动脑：方案、架构、审查、最终整合）
  ↓
员工层（免费/便宜，动手：翻译、测试、格式化、分类、摘要）
```

## 接口：经理位和员工位都是一样的槽

一个槽 = 一个 `AgentAdapter`。不管填哪个厂商、API 还是网页，
派单器只认三个方法：`chat()`、`check_quota()`，外加三个属性
`vendor / model_id / access_kind`。

```
AgentAdapter (ai_farm/adapters/base.py)
  ├─ OpenAICompatibleAdapter  # API 通道，/chat/completions，标准库实现
  ├─ WebAdapter               # 网页/订阅通道，登录一次，浏览器代管
  └─ CLIAdapter               # 命令行 Agent 通道，本地读写工作区 + 收 diff
```

加新模型 = 写一个适配器 + 在 `registry.py` 注册一个 slug。
不用改派单器，不用改办公室，不用改花名册格式。

## 四种通道的本质区别（别混了）

| | API | 网页 / 订阅 | CLI 工具 (如 Codex) | 桌面应用端 (如 WorkBuddy/豆包PC) |
|---|---|---|---|---|
| 真整合？ | 是，并行 | 半整合，一次一个 | 是，subprocess 自动跑 | 文件信箱联动（`@工单.md` 触发） |
| 认证 | 环境变量里的 Key | 浏览器里登一次自己的号 | 复用本地 CLI 登录/Key | 客户端内独立免费积分池 |
| 本地读写 | 无（纯文本） | 无（纯文本） | 直接读写工程目录 | 直接读写选择的工作空间 |
| 到限额 | API：真停 | 订阅：降级到 lite 模型 | 随底层 API/账号 | 切 0.00x 限时免费模型或休息 |

### 无 CLI 桌面应用端半自动协同 SOP（3 步法）
1. **代码实现位置**：`ai_farm/office_store.py` 中的 `exporttaskmd` 动作 + `web/app.js` 中的 `handleExportTaskMd()` 按钮。
2. **标准执行流**：
   - 桌面端选定同一工程目录作为工作空间；
   - 办公室导出 `ai-team/tasks/inbox/<TASK_ID>.md`（内含目标、输入、格式、验收标准与建议切换的 `0.00x` 低倍率子模型），自动复制 `@ai-team/tasks/inbox/<TASK_ID>.md ...`；
   - 粘贴进桌面端触发执行，完成后经理只审本地 `git diff` 摘要进行统筹交付。

## 共享记忆

模型之间不直接对话。共享记忆 = 工单文件（`examples/tasks/`）
+ 花名册（`agents.yaml`）+ 交付记录。总管是唯一读全量的人，
经理只看 diff / 摘要。

## 办公室网页

见 `docs/OFFICE.md`：全员群聊、经理发任务、员工领任务、
私聊汇报、经理统筹交付。办公室只调适配器接口，不直连厂商。
