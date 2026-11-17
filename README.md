# AI Farm — 多级 AI 协同工作台（开源版）

> One icon = one model. Managers think, workers do, the chief integrates.
> 一个图标 = 一个模型。经理动脑，员工动手，总管整合。

AI Farm 是一个多级 AI 协同开源工作台（MIT 协议）。**本项目只提供“AI 农场办公室”的协作场地、调度规则与四大标准接入接口，不预设或捆绑任何私人账号与模型**——下载后用什么网页端 AI、接什么 API、还是挂载什么本地 CLI / 桌面端 Agent，全部由使用者自己按需自由招募。

通过整合分工，把简单、重复、计算量大的**边角工作交给多家免费资源（员工层）轮换执行**，把规划、架构、审查、最终整合留给**强推理模型（经理层/总管）**，从而大幅节省付费模型的 Token 与额度开销，同时避开免费模型分析深度与决断力不足的短板。

---

## 核心规则（Hard Rules）

1. **一个图标 = 一个模型。** 同一家既有付费又有免费，就分开两个图标，角标标 `免费/付费` + `网页/API/订阅`。Codex 这类跑代码的 CLI 工具不是模型，不占独立模型图标，与底层模型共用余额。
2. **一厂商一免费号（免费农场轮换制）。** 不靠多开同一家小号绕额度，不做同款复制/孵化；招募多家不同厂商的免费档轮换，转交任务只允许转给不同厂商。
3. **经理动脑，员工动手。** 小活不请经理；经理只看 diff / 摘要，不重读全文；指令強制模板化（目标 + 输入 + 强制输出格式 + 验收标准 + “不许自由发挥”）；失败先换另一个免费员工，连续两次失败才升级给经理。
4. **额度必须是真的。** 订阅制只显示当前刷新周期（到限额降级为轻量模型，如 `Flash-Lite` / `mini`，不真停）；API 制显示到余额归零（到 0 或 429 真停）；`≤10%` 变红闪烁告警；查不到就写 `额度未填`，绝不编造百分比。
5. **密钥不进仓库。** API Key 只放系统环境变量，网页登录会话只存本地 `~/.ai-farm/sessions/`，永远不写进配置文件、工单、聊天记录或 Git。

## 快速开始

```bash
# 1. 启动「AI 农场办公室」全栈网页工作台（含全员群聊、两路招募弹窗、法力值蓝条、技能中心）
python -m ai_farm office --port 8765
# 浏览器打开 http://127.0.0.1:8765 （或直接双击打开 web/index.html）

# 2. 命令行交互式招募新 Agent（API 只问环境变量名，网页引导点登录一次）
python -m ai_farm recruit

# 3. 干跑测试（不调真实接口、不花一分钱额度）
python tests/test_farm.py
python -m ai_farm run examples/tasks/example-task.md --dry-run

# 4. 核查各模型真实额度状态
python -m ai_farm quota

# 5. 真跑一次（需先在自己的终端设置好环境变量 Key，并加 --live）
export DEEPSEEK_API_KEY="<你的 Key>"   # Windows PowerShell: $env:DEEPSEEK_API_KEY="<你的 Key>"
python -m ai_farm run examples/tasks/example-task.md --live
```

## 无 CLI 桌面应用端（WorkBuddy / 豆包电脑版）半自动调用法

对于**没有开放 HTTP API 或 CLI 命令行**、但能直接读写本地电脑目录的桌面应用（例如 WorkBuddy、豆包 PC 端），农场采用零封号风险的**「工作空间文件信箱 + `@工单.md` 触发」半自动协同**：

1. **绑定同一工作空间**：在 WorkBuddy / 豆包电脑版左下角点击「选择工作空间」，选定本项目的工程目录。
2. **导出工单并复制触发句**：在办公室网页（`http://127.0.0.1:8765`）打开任意任务的私聊汇报窗，点击 **`📂 导出 .md + 复制 @触发句`**。系统会自动在 `ai-team/tasks/inbox/` 生成标准工单 `.md`（自动注明优先切换 `0.00x` 限时免费子模型），并复制触发句。
3. **一键投喂与交差**：切到桌面端输入框直接 `Ctrl+V` 粘贴并回车（如 `@ai-team/tasks/inbox/TASK-xxx.md 严格按此工单要求执行...`）。桌面端读完文件并修改本地代码/文档后，回到农场直接审阅 `git diff` 并验收即可。

## 项目结构

```text
ai-farm/
  ai_farm/
    adapters/base.py               # AgentAdapter 统一接口 (chat + check_quota)
    adapters/openai_compatible.py  # API 通道：标准库直连 /chat/completions，Key 仅读环境变量
    adapters/web.py                # 网页/订阅通道：厂商官网登录一次 + 本地会话
    adapters/registry.py           # 按 slug 注册适配器（30行内即可接入新厂商）
    roster.py                      # 花名册校验：一图标一模型、拦截 Key 明文
    dispatcher.py                  # 派单器：员工优先、失败换员工、两次失败升经理
    quota.py                       # 额度状态：订阅降级 vs API 归零停用、<=10% 告警
    skills.py                      # 技能中心：12 个固定流程种子技能 + 高级模型裁判打分
    office_store.py                # 办公室状态引擎：完整实现 26 个 Office Actions
    office_server.py               # 办公室本地 HTTP 服务端（纯 Python 标准库）
    cli.py                         # 命令行入口：office / recruit / run / quota
  web/
    index.html                     # AI 农场办公室前端页面（三栏布局 + 技能中心 + 两路招募弹窗）
    styles.css                     # 样式表（含 <=10% 红条闪烁告警与响应式布局）
    app.js                         # 前端交互逻辑（支持连接 Python 后端或离线双击打开）
  ai-team/                         # 协作系统设计文档、花名册账本、dispatcher v2、PILOT-001 试点工单
  exaone-connector/                # K-EXAONE 连接脚本
  office/                          # 办公室规格说明 (office-spec.md) 与 26 动作定义 (office-actions.json)
  examples/
    agents.example.yaml            # 示例花名册（仅含环境变量名占位符，无真实 Key）
    tasks/example-task.md          # 通用示例工单
  tests/
    test_farm.py                   # 9 项完整干跑测试（零网络请求、零额度消耗）
```

## License

MIT — 见 `LICENSE`。
