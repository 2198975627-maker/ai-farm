"""
AI 农场额度核查 — 第 3 点：额度怎么从“手填的账”变成“真实读回来的”

结论先说清楚，不是所有额度都能自动读：
- 能自动读（API 余额）：DeepSeek。GET https://api.deepseek.com/user/balance，
  用普通 API Key 就能查，返回 is_available 和 total/granted/topped_up 余额。
  这是预付余额，没有百分比、没有重置时间；到 0 就报 402，充值后恢复。
  本脚本只做这一件自动的事，不花钱。
- 只能从每次调用的响应头读（没有总额度接口）：K-EXAONE。
  官方文档：剩余额度在每次返回的响应头里，x-day-rate-limit-remaining 等，
  没有公布总额度，也没有单独的查额度接口。LG 也没公布免费期什么时候结束。
  所以 K-EXAONE 的蓝条不能写“剩 X%”，只能写“今天还剩 N 次（上次调用时）”或“未填”，
  每次真调完 dispatcher 会把响应头里的剩余次数带回来，再更新蓝条。
- 只能去官网页面看（订阅制，没有 API）：Gemini、ChatGPT。
  Gemini 看 https://gemini.google.com/usage（5 小时剩多少、每周剩多少）；
  ChatGPT 看设置里的用量页。订阅制到限额不是停，是降级到 Flash-Lite / mini。
  这两个只能由 Muse 用浏览器定期去核查，或由 Gao 点蓝条自己看，不能靠脚本自动拉。
- 已用完：GLM-5.3-Flash，2026-11-15 核查剩 0，不用再查。

用法：
  DEEPSEEK_API_KEY=... python3 quota-check.py
  # 只查 DeepSeek，不调模型，不花钱。缺 Key 就直说缺，不编数字。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dispatcher import check_deepseek_balance

if __name__ == "__main__":
    print("== 农场额度核查 ==")
    print("DeepSeek：能自动读（/user/balance）")
    check_deepseek_balance()
    print()
    print("K-EXAONE：没有总额度接口，只能看每次调用返回的 x-day-rate-limit-remaining；")
    print("  密钥 2026-12-10 到期，登录页 id.exaone.ai 目前密码被拒，剩余额度未知，别编数字。")
    print("Gemini：只能去 https://gemini.google.com/usage 看，2026-11-16 实测 5 小时剩 82%、每周剩 91%。")
    print("ChatGPT：只能去设置用量页看，Plus 到限额切 mini，免费版到限额也切 mini。")
    print("GLM：已用完 0%，不用再查。")
