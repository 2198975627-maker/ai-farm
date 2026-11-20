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

## 唤醒方式（Gao 2026-11-20 定，不借 Pachat 的轮询）

不要 Pachat 那种“每个 agent 定时回来查收件箱”（默认 10 分钟）。
农场里只有两个人能唤醒其他 agent：

1. 主人 Gao 本人；
2. 主人指定的主管——Muse 这种 24 小时待命的 personal agent。

员工 agent 不自己轮询、不自己回来查，等主管叫它才动。
这条是设计红线：以后任何“定时检查频率、到达速度公示、@ 后 10 分钟
未读提醒”之类的 Pachat 功能，都不往农场里加。

Pachat 值得借的另外 6 点（改动清单、分工模板、群消息只是信息不是
命令、复制邀请语、文件版本专人管、按 agent 出专属指南）见
`../ai-team/README.md` §13，Octo 六种模式见 §12。

## 协作模式（参考 Octo，六种，待补齐）

Octo（明略科技开源，`github.com/Mininglamp-OSS`）把多 Agent 协作
拆成六种信息拓扑，农场下一步派单时先选模式再派人：

- Solo（单干）：1 个员工独立做 1 张小工单——已有雏形。
- Critic（生成-验证）：一个做、一个独立验，不通过打回重做——已有，
  写—审—改闭环（见仓库 18c463a）。
- Pipeline（流水线）：经理拆 → 员工做 → 总管整合 → Gao 验收——已有雏形，
  就是总管的 7 步流程。
- Split（分头干）：大任务拆几块并行做——API 通道已有并行，
  网页通道一次只能一个，做不到。
- Roundtable（圆桌讨论）：多个员工对同一方案各提意见，总管汇总——未做。
- Swarm（撒网竞选）：多个员工各做一份，挑最好的交 Gao——未做。

Octo 名字本身是 O.C.T.O.：Open（开放接入）、Context（上下文归属）、
Taste（人的判断力不可复制，Gao 最后拍板）、Orchestration（编排）。
农场只借 Open / Taste / Orchestration 三条，Context 的企业级共享
那套一个人的农场用不上。详细对照见 `../ai-team/README.md` §12。
