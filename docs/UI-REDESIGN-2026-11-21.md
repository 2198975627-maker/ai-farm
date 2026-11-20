# UI 重做说明（2026-11-21）

对照需求 `ai-farm-qoder-ui-redesign-2026-11-21.md` §六 完成。原则：**先审计再动手；一个功能都不删**；
零构建、零第三方依赖（原生 HTML/CSS/JS + Python stdlib 后端）。

## 一、按钮 / 入口 / 弹窗 / Tab / 开关 审计表

处置类型：keep=保留；merge=合并进别的入口；collapse=默认收起（hover/展开/步骤/折叠可见）；
delete=删除原位置但功能迁移到别处（不丢功能）；add=新增；fix=修复。

| 原入口 | 处置 | 去向 / 理由 |
| --- | --- | --- |
| 顶栏品牌 🌾 + 副标题 | collapse | 保留品牌名 + 线性 SVG 麦穗图标；副标题删除（信息已在 README/指南），顶栏瘦身 |
| connModeBadge（后端连接态） | keep / collapse | 桌面保留；<960px 收起（窄屏空间让给主按钮） |
| 主视图 Tab（群聊/技能） | keep | 改为图标+文字分段控件；<400px 仅图标，横向不折行 |
| 顶栏 4 个统计 chip（认领/汇报/交付/验收） | merge | 合并为中部单条进度条 + 一行紧凑 label，减少视觉噪音 |
| statLowQuota 低额度告警 | keep | 保留为进度区内的告警 chip，点击定位低额度成员 |
| autoExecuteToggleBtn 自动执行开关 | merge | 收进「更多 ▾」菜单（低频但重要，不删） |
| 示例任务 按钮 | merge | 收进「更多 ▾」菜单 |
| 拆大任务 按钮 | keep | 保留为「派新任务」旁的次级 ghost 按钮（需求指定） |
| 派新任务 按钮 | keep | 唯一主强调色按钮 |
| 工具与指南 ▾（指南/示例团队/同步/重置） | merge | 更名「更多 ▾」，原有 4 项全保留 + 并入自动执行开关、示例任务 |
| 内联 approvalBanner 审批条 | delete→drawer | 功能迁移到右上角盾牌徽章 + 侧滑抽屉（含超时与一键回滚），不再占群聊上方横条 |
| （新增）审批徽章按钮 | add | 显示待授权计数，点击开抽屉 |
| 左栏搜索框 / 拖拽提示 / 楼层标题 / 招募按钮 | keep | 去 emoji，文案不变 |
| 成员卡：名字+徽章+额度条+状态点 | keep | 默认只露这四样（卡片瘦身硬规则） |
| 成员卡：模型/等级/到期/降级规则/工具/Token/会话 | collapse | 默认隐藏；hover / 选中 / 点眼睛展开才显示 |
| （新增）成员卡登录态徽章 + 展开眼睛 | add | 登录一次可见性（已登录/未登录/会话过期），不显示任何密钥明文 |
| 中栏独立厂商池 ▾ | keep | 保留折叠 details |
| activeTaskStrip 任务切换条 | keep | 不变 |
| hudFlightStrip ✈ emoji 飞线条 | merge→SVG | 替换为 SVG 弧线节点图（谁→谁、摘要、blocked 红色虚线+中途坠落） |
| groupChatStream 气泡 | keep(restyle) | 统一结论卡风格：细边框+软阴影；汇报/交付卡左侧功能色边；告警卡红边 |
| 群聊发言舱（身份/@/输入/发送） | keep | 去 emoji |
| 右栏 Tab（档案/私聊） | keep | 去 emoji；窄屏不折行 |
| teamOverviewBox 账本总览 | keep + add | 保留人数/就绪；新增近 7 日省钱柱状图（只统计真实 Token） |
| 技能中心：裁判选择/让它判断一次/新增技能/楼层装配/12 技能卡 | keep | 去 emoji、中性化；布局不变 |
| 招募弹窗 4 通道按钮 | keep→step1 | 成为三步向导第 1 步「选通道」 |
| 招募弹窗各通道字段 | collapse→step2 | 第 2 步「填资料」才显示 |
| （新增）招募第 3 步确认 + 上一步/下一步 | add | 确认页汇总名字/厂商/模型/通道/楼层；提交按钮仅第 3 步出现 |
| 派单弹窗 6 个下拉（经理/员工/技能/类型/审查） | collapse | 收进「高级派单选项」折叠；默认只露必填项 |
| 派单弹窗 标题/目标/输入/格式/验收 | keep | 默认露出的必填项（格式/验收带默认值） |
| （新增）派单协作模式选择器（6 模式） | add | Solo/Critic/Roundtable/Pipeline/Split/Swarm，写入 task.mode |
| 大任务 / 新技能 / 自动化指南 弹窗 | keep | 去 emoji、中性化 |
| 移动端 mobile-nav 3 Tab | fix | 360/390px 不折行、横向滚动；顶栏紧凑两行保证主按钮可达 |
| （新增）审批抽屉 | add | 待授权允许一次/总是允许低风险/拒绝 + 超时退回提示 + 已执行操作一键回滚 |

**结论：没有任何功能被删除。** 原内联审批条、顶栏统计、自动执行开关、示例任务等均迁移而非移除。

## 二、设计 token（统一，移除散落 inline 颜色）

- 背景 3 级：`--bg-app #0b0d10` / `--bg-panel #12151a` / `--bg-card #171b21`（+elevated/hover）。
- 文字 3 级：`--text-main #e8eaed` / `--text-secondary #9aa9b2` / `--text-muted #6b7280`。
- 强调色仅 2 个：`--accent #4f8cff`（主）、`--danger #ef4444`（危险）。
  额度绿/黄/红与状态点为**功能色**（quota-green/yellow/red），非装饰强调色。
- 字号 3 级：`--fs-sm 12.5` / `--fs-md 14` / `--fs-lg 17`（+`--fs-xs 11` 元信息）。
- 间距刻度：4/8/12/16/24；圆角 6/10/14；阴影 2 级（软）；边框细 `rgba(255,255,255,.08/.16)`。
- 分层灰暗色 + 细边框 + 软阴影，非死黑。
- 散落 inline 颜色（#0f172a/#334155/#38bdf8/#94a3b8…）由 `neutralizeHTML()` 在渲染期映射到 token；
  emoji 图标由 `stripEmoji()/neutralizeHTML()` 去除，改用文本 + 线性 SVG（`icon()`）。

## 三、对比截图（干净演示态，不含个人数据）

见 `docs/ui-shots/`：
- 桌面 1440：`before-desktop-1440.png` → `after-desktop-1440.png`（首页/含任务群聊）
- 桌面 1440 技能中心：`after-desktop-skills-1440.png`
- 桌面 1440 招募向导：`after-desktop-recruit-1440.png`
- 移动 390：`before-mobile-390.png` → `after-mobile-390.png`（首页）、`after-mobile-group-390.png`（群聊）

移动 390 截图用 CDP `Emulation.setDeviceMetricsOverride` 取真实 390 视口
（headless `--window-size` 在窄屏会被钳制，不能代表真实手机宽度）。

## 四、回归与实测

- `python tests/test_farm.py`：**41 通过**（基线 39 + 新增 2：已执行授权携带回滚元数据；静态路径越界/请求体上限安全回归）。
- 本地 8765 端到端（HTTP）：publish→claim→结论私聊→deliver→accept 全通；
  招募 API（仅环境变量名）→syncprofiles 登录态→switch model→delete 全通；
  明文 Key（sk-…）被安全拦截；圆桌在经理不足 2 人时**诚实停下**而非伪造讨论。
- 自我大筛查加固（已落地+回归）：静态文件守卫由 `startswith` 改 `is_relative_to`（挡 `../` 越界到 web 前缀同级目录，实测 403）；
  `/api/action` 请求体上限 1 MiB（实测 413）；Windows 启动打印去 emoji（避免重定向 stdout 的 GBK 崩溃）。

## 五、诚实说明（UI 侧不能完全自动化的部分）

- 模式选择器只记录 `task.mode`；Roundtable/Swarm 的真实多模型讨论/抢单仍需 ≥2 名总线合格经理/员工
  且配置了可用模型（环境变量 Key / CLI / 桌面回执），否则 autorun 诚实停下并说明原因。
- 网页/订阅免费员工不进 MCP 总线，仍走传令兵扩展；其「登录一次」需主人在厂商页手动完成一次。
- 桌面端回执需桌面 Agent 真实写回 `tasks/outbox/<id>.md`，农场只做自动收取，不代写结论。
- 关键操作（合并/删代码/部署）永远先人工授权；超时原样退回、不默认放行；回滚仅到 `backup/` 备份。