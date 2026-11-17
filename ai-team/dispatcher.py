"""
AI Team Dispatcher — v2 真接版（只用 Python 标准库，不用装 openai 库）
用途：真正调用 OpenAI 兼容 API（员工层），把工单批量派出去，并把每次调用的用量写回结果。
只做 API 模型。网页模型（Gemini 网页 / ChatGPT 网页）不在这里，由 Muse 用浏览器跑。

三点关键问题的第 1 点就靠它解决：第 2 点靠 tasks/inbox 里的真实工单，第 3 点靠 quota-check.py。

安全规则：
- Key 一律走环境变量，绝不写进代码、工单、Git。
- 需要的 Key：DEEPSEEK_API_KEY, KEXAONE_API_KEY, QWEN_API_KEY（按需）
- 默认 DRY_RUN=True，只演练不花钱；要真调必须加 --live。
- K-EXAONE 仅限非商业、仅韩语/英语，密钥 2026-12-10 到期；别拿它做商业活。

模型 ID（2026-11-16 核查后修正）：
- deepseek-v4-pro：经理/代码实现，Codex 里在用的就是它
- deepseek-v4-flash：便宜员工，替代已停用的 deepseek-chat / deepseek-reasoner
  （deepseek-chat / deepseek-reasoner 已于 2026-07-24 停用，别再用）
- k-exaone_v2.5：K-EXAONE 2.5，免费到 2026-12-10
- qwen-turbo：千问 Turbo，待 Gao 确认有没有 Key

用法：
  python3 dispatcher.py --check-balance            # 只查 DeepSeek 余额，不调模型，不花钱（要 Key）
  python3 dispatcher.py --task tasks/inbox/X.md     # 默认演练，不调 API
  python3 dispatcher.py --task tasks/inbox/X.md --live --provider kexaone --prompt "你好"
  python3 dispatcher.py --live --provider deepseek_pro --prompt "用一句话介绍自己"
"""

import os
import sys
import json
import urllib.request
import urllib.error
import argparse

DRY_RUN_DEFAULT = True

PROVIDERS = {
    "deepseek_pro": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "env_key": "DEEPSEEK_API_KEY",
        "role": "manager",
        "note": "代码实现经理；和 Codex、DeepSeek Flash 共用同一个 DeepSeek 余额",
    },
    "deepseek_flash": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "env_key": "DEEPSEEK_API_KEY",
        "role": "worker",
        "note": "便宜员工；替代已停用的 deepseek-chat",
    },
    "kexaone": {
        "base_url": "https://api.exaone.ai/v1",
        "model": "k-exaone_v2.5",
        "env_key": "KEXAONE_API_KEY",
        "role": "worker",
        "note": "免费到 2026-12-10，仅非商业、仅韩语英语；高峰 429，要有备用；剩余额度只能从每次返回的响应头 x-day-rate-limit-remaining 看，没有总额度接口",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-turbo",
        "env_key": "QWEN_API_KEY",
        "role": "worker",
        "note": "待确认有没有 Key",
    },
}

# 失败先降级，不升级：员工做砸了先换另一个员工，两次都砸才升级给经理
FALLBACK_CHAIN = {
    "kexaone": ["deepseek_flash", "qwen"],
    "deepseek_flash": ["kexaone", "qwen"],
    "qwen": ["deepseek_flash", "kexaone"],
    "deepseek_pro": ["deepseek_flash"],
}


def _post_chat(base_url, api_key, model, prompt, max_tokens=800, timeout=60):
    """调一次 OpenAI 兼容的 /chat/completions，返回 (text, usage, headers)。只用标准库。"""
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            headers = dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")[:500]
        raise RuntimeError(f"HTTP {e.code}: {raw}")
    choices = data.get("choices") or []
    text = ""
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""
    return text, data.get("usage") or {}, headers


def call_provider(provider_name, prompt, max_tokens=800):
    """真调一次指定模型。返回 dict：text / usage / rate_limit_remaining。缺 Key 就报错，不编结果。"""
    cfg = PROVIDERS[provider_name]
    api_key = os.environ.get(cfg["env_key"])
    if not api_key:
        raise RuntimeError(f"缺 Key：{cfg['env_key']} 没设，没法调 {provider_name}（{cfg['model']}）")
    text, usage, headers = _post_chat(cfg["base_url"], api_key, cfg["model"], prompt, max_tokens=max_tokens)
    remaining = {}
    for k, v in headers.items():
        lk = k.lower()
        if "rate-limit-remaining" in lk:
            remaining[k] = v
    return {"provider": provider_name, "model": cfg["model"], "text": text,
            "usage": usage, "rate_limit_remaining": remaining}


def dispatch_one(provider_name, prompt, max_tokens=800):
    """派一个活：先调指定的，429/失败就按降级链换另一个员工；都失败才报给经理。"""
    tried = [provider_name] + FALLBACK_CHAIN.get(provider_name, [])
    last_err = None
    for name in tried:
        try:
            out = call_provider(name, prompt, max_tokens=max_tokens)
            out["tried"] = tried[:tried.index(name) + 1]
            return out
        except Exception as e:
            last_err = e
            print(f"  {name} 失败：{e}，换下一个员工…")
    raise RuntimeError(f"都失败了，最后一个错误：{last_err}。这时才升级给经理，别再硬试。")


def check_keys():
    print("== 检查 Key（只检查有没有，不打印值） ==")
    for name, cfg in PROVIDERS.items():
        has = bool(os.environ.get(cfg["env_key"]))
        print(f"  {name:16} {cfg['model']:20} key: {'有' if has else '缺'}  {cfg.get('note','')}")
    print()


def check_deepseek_balance():
    """第 3 点：DeepSeek 余额能自动读。GET https://api.deepseek.com/user/balance，返回总额/赠送/充值余额。"""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("缺 Key：DEEPSEEK_API_KEY 没设，查不了余额。")
        return None
    req = urllib.request.Request(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"查余额失败：HTTP {e.code}：{e.read().decode('utf-8', errors='ignore')[:300]}")
        return None
    print("DeepSeek 余额（官方 /user/balance 返回）：")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("说明：这是预付余额，不是百分比；到 0 时调用会报 402，没法再调，直到充值。")
    return data


def main():
    ap = argparse.ArgumentParser(description="AI 农场 API 派单器 v2")
    ap.add_argument("--task", default="")
    ap.add_argument("--provider", default="kexaone", choices=list(PROVIDERS))
    ap.add_argument("--prompt", default="")
    ap.add_argument("--live", action="store_true", help="真调 API，会花钱/花额度；不加就是演练")
    ap.add_argument("--check-balance", action="store_true")
    args = ap.parse_args()

    check_keys()
    if args.check_balance:
        check_deepseek_balance()
        return 0

    if args.task:
        print(f"== 派单计划：{args.task} ==")
        print("  1. 总管 Muse 已拆单（人工）")
        print("  2. 员工并行：kexaone 做初稿，deepseek_flash 做代码，qwen 做格式化")
        print("  3. 经理只审 diff，不重读全文")
        print("  4. 结果写回 tasks/review/，等 Muse 整合")
        print()

    if not args.live:
        print("[DRY_RUN] 本次只演练，未调用任何 API，未花钱。加 --live 才会真调。")
        print("真调前确认：Key 已设在环境变量里，工单是真实任务，不是通用示例。")
        return 0

    if not args.prompt:
        print("加了 --live 但没给 --prompt，不知道调什么。先给一个真实的小任务再跑。")
        return 2
    out = dispatch_one(args.provider, args.prompt)
    print(f"== 真调结果：{out['provider']} / {out['model']}，试过：{out['tried']} ==")
    print(f"用量：{json.dumps(out['usage'], ensure_ascii=False)}")
    if out["rate_limit_remaining"]:
        print(f"剩余额度（响应头）：{json.dumps(out['rate_limit_remaining'], ensure_ascii=False)}")
    print("--- 回复 ---")
    print(out["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
