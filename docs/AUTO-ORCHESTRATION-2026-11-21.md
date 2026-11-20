# 自动编排闭环说明（2026-11-21）

对照需求 §一/§四（P0–P4）与 Agent HUD（jazzenchen/agent-hud-open, Apache-2.0）理念落地。
目标：主人只做三件事 —— **登录一次、发布任务、看结果 + 一键验收**；从发布到交付**零复制粘贴**。

## 一、闭环流程

```
发布(createtask / createbigtask / autorun)
  → 拆单（规则拆 或 真实经理模型 DAG，_plan_with_manager；无模型则规则拆并诚实标注）
  → 按模式派单（solo/critic/roundtable/pipeline/split/swarm）
  → 员工执行（API/CLI 真调；网页走传令兵；桌面走 @工单.md + outbox 回执）
  → 结论回私聊（postmessage，结论-only：【结论】【改动文件】【测试结果】；拒收整段对话粘贴）
  → 经理审查（submitcodereview / runautocodereview，只审 diff/摘要）
  → 经理互相讨论批判一轮（startdiscussion/postdiscussionmessage；真实模型调用，不伪造）
  → 汇总（aggregatebigtask / deliverfinalresult）
  → 交付卡（final_delivery_card）
  → 主人一键验收 / 打回（reviewfinalresult verified/rejected）
```

`autorun` 为单入口编排：一次调用串起 拆→派→执行→收→审→讨论→汇总→交付；
桌面端回执在 execute 阶段自动收取（`checkdesktopreceipt`），无需主人手动搬运。

## 二、六种协作模式

| 模式 | 行为 | 诚实停止条件 |
| --- | --- | --- |
| solo | 一员工执行、经理审 | 无可用员工模型 |
| critic | 写-审-改闭环（独立审查者与写者分离） | 无审查模型 |
| roundtable | ≥2 经理各抒己见 + 批判一轮 + 收敛采纳 | 经理<2 或无真实模型 |
| pipeline | 多步串行交接（depends_on DAG 波次） | 上游失败即停 |
| split | 大需求拆子单跨厂商并行 | 子单全失败 |
| swarm | 多员工并行草稿、总管择优 | 员工<2 或总管无模型 |

## 三、安全熔断与并发（P0）

- 全局 `threading.RLock` + `os.replace` 原子写；慢 I/O（adapter.chat / 并行池 / git subprocess）**不持锁**。
- 幂等回执：同一任务重复汇报/重复 autorun 不重复计账、不重复派单。
- 三道熔断：单链 pass ≤ `MAX_CHAIN_PASS=10`；讨论轮数 ≤ `MAX_DISCUSSION_ROUNDS`；失败两次升级经理。
- **红线：不加定时轮询、不加到达速度公示、不加 @ 未读提醒**；只有主人/指定主管能唤醒他人。

## 四、消息总线与 MCP Relay（P1）

- 总线只接 **API / CLI / 桌面** 三类本地可直连 agent；**网页免费员工永远走传令兵扩展，不进 MCP**。
- Relay 只对齐协议（"a message, not the conversation"）；状态/账本由 Core 计算。
- 总线失败在群聊明示（bus_error），不静默吞掉。

## 五、省钱账本（P2）

- 只统计**真实记录**的 Token；干跑计 0；按日/按周聚合（`savingsledger`）。
- 免费员工(1F)替付费经理(2F)执行的次数/Token 单独列示；UI 近 7 日柱状图。
- 查不到额度一律显示「额度未填」，绝不编造数字。

## 六、通道加固（P3）

- 传令兵扩展自检（`runSelfCheck`，事件驱动 + 一次性 setTimeout，**无轮询**）：
  验证码/选择器失效/卡住/发送失败 → `courierstatus` 上报 → 群聊 courier_alert + 飞线 blocked，不伪造成功。
- 登录一次可见性：`syncprofiles` 产出 `login_state`（已登录/未登录/会话过期），只读环境变量名，不泄露明文。
- 桌面回执：`exporttaskmd` 写明写回 `tasks/outbox/<id>.md`；`checkdesktopreceipt` 自动收取并结论-only 校验。

## 七、受控执行器与审批（P4）

- 关键操作（merge/delete_code/deploy）**默认只记录不执行**，界面明说；需主人单次授权后才真执行。
- 真执行前自动建 Git 备份分支 `backup/<op>-<ts>-<ms>`；merge 用 `--no-ff`、冲突 `--abort`；
  delete 走 `git rm`+commit、越界路径拦截；deploy 无主人配置命令时仅记录。
- 一键回滚 `rollbackcriticalop`：仅 `confirm=True` 且仅重置到 `backup/` 命名空间；非 Git/脏树安全退回。
- 审批超时（默认 1800s，可 `setapprovaltimeout`，0 关闭）：**读取时懒过期**，超时原样退回、不默认放行；无轮询。
- 已执行授权携带 `backup_ref/rollback_available/workspace_dir`，授权抽屉可一键回滚。

## 八、诚实说明（不能完全自动化的步骤）

1. **登录一次**：网页/订阅通道需主人在厂商官方页手动登录一次（扩展只代填代发，不索取密码）。
2. **真实模型讨论/审查/拆单**：必须配置可用模型（环境变量 Key / CLI / 桌面回执）；无模型时该步停下并明说原因，绝不写死套话假装讨论过。
3. **桌面端执行**：桌面 Agent 需真实读工单、改代码、写回 outbox；农场只自动收取与校验，不代写结论。
4. **关键操作**：合并/删代码/部署永远先问主人；超时不放行；回滚是破坏性操作需主人显式确认。
5. **额度/价格/省了多少**：只显示真实值或「额度未填」；干跑不产生省钱数字。

## 九、回归

`python tests/test_farm.py` → **41 通过**（P0 并发/幂等/熔断、P1 总线/讨论/roundtable/swarm、
P2 编排/账本、P3 传令兵/桌面回执/登录态、P4 受控执行/回滚/超时 + 回滚元数据 + 静态越界/请求体上限安全回归）。

## 十、自我大筛查结论（并发/安全/诚实/隔离）

- **并发**：`_LOCKED_METHODS` 仅包裹快状态写；所有 `adapter.chat`/`check_quota`/`subprocess`（git）调用点
  均落在被排除的慢编排器（runadaptertask/checklivequota/collectgitdiff/runautocodereview/runroundtable/runswarm/_plan_with_manager），
  锁内不做网络/子进程 I/O；`save()` 临时文件 + `os.replace` 原子写。无死锁/长持锁风险。
- **安全**：Python 无 `shell=True`/`os.system`/`eval`/`exec`/`pickle`/`yaml.load`；JS 无 `eval`/`document.write`/`new Function`；
  受控 git 用 `shlex.split`+`shell=False`；`escapeHTML` 先转义再加粗/码/@；CORS 仅放行 localhost/127.0.0.1 + 浏览器扩展 Origin；
  静态守卫 `is_relative_to`（挡 `../` 越界）；`/api/action` 体上限 1 MiB；工作空间挡系统敏感目录与盘符根。
- **诚实**：额度/价格/省钱只显示真实值或「额度未填」，干跑省钱=0；讨论/汇报/审查必须真实模型调用，无可用模型即诚实停下。
- **隔离**：Key 只存环境变量名（拒收 sk-/SK- 明文）；网页免费员工不进 MCP 总线；个人状态/私聊/本机绝对路径不进公开库
  （`.gitignore` 排除 roster/state/sessions；演示状态与截图均在仓库外或用干净演示数据）。
- **改良建议（未落地，供主人裁决）**：① 扩展 Origin 目前放行任意 `chrome-extension://`，可考虑钉到传令兵扩展 ID；
  ② 内联 `onclick` 插值的是服务端可控 id（slug/TASK-数字/backup-时间戳），实际安全，建议改 `data-*`+事件委托以彻底消除注入面；
  ③ 工作空间守卫可再加个人数据目录（`~/.ai-farm`、`ai-farm-private/`）黑名单。