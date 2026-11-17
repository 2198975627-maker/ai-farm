"""Skill Center: small fixed playbooks for workers.

A skill is a fixed procedure, not free thinking: it cuts the worker's
reasoning, makes output predictable, and saves quota. Skills live in a
dedicated module; which skill goes to which model is a manager's call.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Skill:
    slug: str
    name: str
    steps: str
    best_for: str
    category: str = "通用"
    description: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)
    savings_note: str = "固定步骤减少员工自由思考，降低废稿率与重跑次数"


SKILLS: list[Skill] = [
    Skill(
        "batch-translate",
        "批量翻译",
        "1. 逐条翻译，不增不减 2. 术语统一 3. 输出双语对照表，不许自由发挥",
        "K-EXAONE / Qwen / ChatGPT Free",
        category="语言与翻译",
        description="将批量短句或产品文案按固定格式翻成双语对照表，10条合1次调用。",
        keywords=("translate", "翻译", "英文", "韩语", "双语", "batch"),
        savings_note="10条合成1次员工调用，经理只审表格不重读原文，省80%经理Token",
    ),
    Skill(
        "table-cleanup",
        "名单整理成表格",
        "1. 去重 2. 按列对齐为Markdown表格 3. 空值统一标[缺失]，不编造数据",
        "Qwen / Doubao",
        category="数据格式化",
        description="把杂乱文本、名单、配置项清洗并整理为规范的Markdown或CSV表格。",
        keywords=("table", "表格", "名单", "中文", "格式化", "整理"),
        savings_note="纯格式体力活交免费中文员工，零经理算力消耗",
    ),
    Skill(
        "three-tier-summary",
        "三档摘要",
        "1. 一句话结论(≤50字) 2. 300字核心摘要 3. 要点清单；数字、人名、日期严格照原文；字数按去空白后全部字符计",
        "Kimi / Doubao",
        category="阅读与摘要",
        description="把长文章或报告压缩成一句话、300字、要点清单三档，供经理快速审阅。",
        keywords=("summary", "摘要", "长文", "总结", "长上下文"),
        savings_note="让免费长文模型先压成300字，经理只读摘要不读万字原文",
    ),
    Skill(
        "long-text-speed-read",
        "长文速读",
        "1. 提取章节骨架 2. 列出所有数字/日期/专有名词原句定位 3. 标注存疑处",
        "Kimi / Gemini Flash-Lite",
        category="阅读与摘要",
        description="针对超长文档快速提取结构与关键事实索引，避免主模型吞入巨量上下文。",
        keywords=("long", "长文", "长上下文", "速读", "检索"),
        savings_note="用512k/长窗口免费档做预筛，避免付费主模型一次性吞入数万Token",
    ),
    Skill(
        "code-review-checklist",
        "代码审查清单",
        "1. 逐项核对安全/边界/类型/密钥泄露 2. 只报问题+文件行号+简短原因，不重写全文件",
        "DeepSeek Pro / GPT",
        category="代码与研发",
        description="按固定清单对diff进行快速排雷，只输出问题行号与修复建议。",
        keywords=("code", "review", "审查", "代码", "架构", "diff"),
        savings_note="只看git diff不看全仓，输出限定行号清单，大幅压缩输出Token",
    ),
    Skill(
        "test-cases",
        "测试用例生成",
        "1. 覆盖正常/边界/异常三类输入 2. 只写测试文件代码，绝不修改业务源码",
        "DeepSeek Flash / ChatGPT Free",
        category="代码与研发",
        description="根据函数签名或模块接口批量补充单元测试用例。",
        keywords=("test", "测试", "代码", "单元测试", "边界"),
        savings_note="测试样板代码由便宜/免费代码员工生成，本地跑通后再交经理核验",
    ),
    Skill(
        "cheap-code-jobs",
        "便宜代码小活",
        "1. 单文件小函数/类型补齐/注释规范化 2. 仅输出改动片段或完整单文件，不讲原理",
        "DeepSeek Flash / ChatGPT Free",
        category="代码与研发",
        description="处理单文件内的简单样板代码、类型声明、格式转换等边角编程活。",
        keywords=("code", "代码", "小任务", "函数", "实现"),
        savings_note="边角代码不唤醒Gemini Argon或DeepSeek Pro，直接省下主力额度",
    ),
    Skill(
        "chinese-polish",
        "中文润色",
        "1. 修正语病与生硬翻译腔 2. 保持原意与全部事实数字不变 3. 给修改前后对比",
        "Qwen / Doubao",
        category="语言与翻译",
        description="对中文报告草稿、参赛文档语句进行顺滑润色，不改变任何事实与数据。",
        keywords=("中文", "润色", "文档", "报告", "写作"),
        savings_note="用免费国产网页模型润色中文段落，不耗付费订阅周期",
    ),
    Skill(
        "promo-slogans",
        "宣传口号",
        "1. 按目标受众生成5条不同风格备选 2. 每条≤20字 3. 附一句适用场景说明",
        "Doubao / Qwen / Grok Free",
        category="创意与文案",
        description="批量产出简短宣传语、标题备选方案供人工拍板。",
        keywords=("口号", "宣传", "文案", "标题", "中文", "热点"),
        savings_note="发散型短文案由免费员工批量出备选，Gao直接挑",
    ),
    Skill(
        "english-writing",
        "英文写作小活",
        "1. 语法与地道表达检查 2. 按指定语气(学术/商务/日常)输出 3. 不增删核心信息",
        "ChatGPT Free / K-EXAONE",
        category="语言与翻译",
        description="处理英文邮件、CET-4练习短文、英文README段落起草与纠错。",
        keywords=("english", "英文", "英语", "写作", "初稿"),
        savings_note="英文短文交给免费GPT网页或K-EXAONE，无需动用付费经理",
    ),
    Skill(
        "batch-classify",
        "批量分类打标",
        "1. 严格按给定标签集合分类 2. 每条输出[编号 -> 标签] 3. 不确定的标unknown，绝不乱猜",
        "K-EXAONE / Qwen",
        category="数据格式化",
        description="对大批量文本、工单、评论按预设枚举标签进行快速归类。",
        keywords=("classify", "分类", "打标", "批量", "初稿"),
        savings_note="分类输出仅几个词，极省completion tokens，适合免费API批量跑",
    ),
    Skill(
        "doc-drafting-frame",
        "文档起草框架",
        "1. 先列二级目录大纲与验收点 2. 标记哪些小节由哪个员工填内容 3. 经理审完大纲再填正文",
        "Muse / Gemini Argon / Qwen Max",
        category="规划与架构",
        description="由经理/总管先定文档骨架与分包清单，再拆给免费员工填各节初稿。",
        keywords=("文档", "报告", "架构", "计划", "大纲", "Canvas"),
        savings_note="经理只写200字骨架，几千字正文拆给免费员工填，彻底告别Canvas长输出卡死",
    ),
]


def get_skill(slug: str) -> Skill:
    for s in SKILLS:
        if s.slug == slug:
            return s
    raise KeyError(f"unknown skill: {slug}")


def analyze_skill_assignments(agents: list[dict], skills: list[dict], judge: str = "Muse") -> list[dict]:
    """Senior model (default Muse) scores and recommends which agent should carry which skill."""
    recommendations = []
    for agent in agents:
        floor = agent.get("floor", "worker")
        status = agent.get("status", "ready")
        if floor == "rest" or status == "exhausted" or agent.get("is_tool"):
            continue
        specialty = (agent.get("specialty", "") + " " + agent.get("name", "") + " " + agent.get("vendor", "")).lower()
        current_skills = set(agent.get("skills") or [])

        for sk in skills:
            slug = sk["slug"]
            cat = sk.get("category", "")
            # Managers only get planning/review skills; workers get execution skills
            if floor == "manager" and cat not in ("规划与架构", "代码与研发"):
                continue
            if floor == "worker" and slug in ("code-review-checklist", "doc-drafting-frame"):
                continue

            score = 60
            matched_kw = []
            for kw in sk.get("keywords", []):
                if kw.lower() in specialty:
                    score += 14
                    matched_kw.append(kw)
            if agent.get("vendor", "").lower() in sk.get("best_for", "").lower():
                score += 18
                matched_kw.append(f"官方推荐契合({sk.get('best_for')})")

            score = min(score, 98)
            if score >= 74 and slug not in current_skills:
                reason = (
                    f"[{judge} 裁判分析] {agent['name']}（{agent.get('badge', '')}）特长含 "
                    f"{'、'.join(matched_kw) if matched_kw else agent.get('specialty', '通用执行')}，"
                    f"装配「{sk['name']}」可固定输出步骤、{sk.get('savings_note', '节省额度')}。"
                )
                recommendations.append({
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "agent_floor": floor,
                    "skill_slug": slug,
                    "skill_name": sk["name"],
                    "score": score,
                    "reason": reason,
                    "approved": True,
                })
    recommendations.sort(key=lambda r: (-r["score"], r["agent_name"]))
    return recommendations
