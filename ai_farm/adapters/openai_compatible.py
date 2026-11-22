"""API channel: any OpenAI-compatible /chat/completions endpoint.

Covers DeepSeek, K-EXAONE, Qwen, GLM and any other vendor that speaks
the same wire format. Only the standard library is used, so there is
nothing to install.

Security: the key is read from an environment variable named by
``key_env`` (e.g. ``DEEPSEEK_API_KEY``). It is never written to a file,
never logged, and never accepted as a constructor argument that could
end up in a config file. If the env var is missing, chat() raises
before any network call.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import AgentAdapter, AgentReply, Quota


class OpenAICompatibleAdapter:
    access_kind = "api"

    def __init__(self, vendor: str, model_id: str, base_url: str, key_env: str,
                 balance_url: str | None = None, paid: bool = False):
        self.vendor = vendor
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.key_env = key_env
        self.balance_url = balance_url
        self.paid = paid

    def _key(self) -> str:
        key = os.environ.get(self.key_env, "").strip()
        if not key:
            raise RuntimeError(
                f"{self.key_env} is not set. Export it in your shell, "
                "do not put the key in any file."
            )
        return key

    def chat(self, prompt: str, max_tokens: int = 4096) -> AgentReply:
        body = json.dumps({
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key()}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                remaining = {k: v for k, v in resp.headers.items()
                             if "rate-limit-remaining" in k.lower()}
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"{self.vendor} HTTP {e.code}: "
                f"{e.read().decode('utf-8', errors='ignore')[:300]}"
            ) from e
        choices = data.get("choices") or []
        text = (choices[0].get("message") or {}).get("content", "") if choices else ""
        return AgentReply(text=text, model=self.model_id,
                          usage=data.get("usage") or {},
                          rate_limit_remaining=remaining)

    def list_models(self) -> list[str]:
        """Fetch live available model IDs from GET /models (returns [] on unsupported/error)."""
        if not os.environ.get(self.key_env, "").strip():
            return []
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self._key()}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items = data.get("data") or []
            return [str(m.get("id")) for m in items if isinstance(m, dict) and m.get("id")]
        except Exception:  # noqa: BLE001
            return []

    def check_quota(self) -> Quota:
        # Only vendors with a real balance endpoint can be auto-read.
        # Also query /models alongside quota so API accounts show both balance & models.
        models = self.list_models()
        tier_label = "付费·API" if self.paid else "免费·API"
        if not self.balance_url:
            return Quota(kind="unknown",
                         note="no balance API; check the vendor usage page",
                         tier=tier_label,
                         available_models=models)
        if not os.environ.get(self.key_env, "").strip():
            return Quota(kind="unknown",
                         note=f"环境变量 {self.key_env} 未设置，额度未填",
                         tier=tier_label)
        req = urllib.request.Request(
            self.balance_url,
            headers={"Authorization": f"Bearer {self._key()}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            return Quota(kind="unknown", note=f"读取余额失败: {e}",
                         tier=tier_label, available_models=models)
        # DeepSeek-style: {"is_available": true, "balance_infos": [...]}
        infos = data.get("balance_infos") or []
        if infos:
            total = float(infos[0].get("total_balance", 0))
            currency = infos[0].get("currency", "CNY")
            if total <= 0 or data.get("is_available") is False:
                return Quota(kind="api", percent_remaining=0.0,
                             note=f"实查余额 {total} {currency}，is_available={data.get('is_available')}（已停用，等充值）",
                             tier=tier_label, available_models=models)
            # Without a known starting balance we cannot turn a balance
            # into a percent honestly; report the raw balance in the note.
            return Quota(kind="api", note=f"实查余额 {total} {currency}",
                         tier=tier_label, available_models=models)
        return Quota(kind="unknown", note="balance endpoint returned no data",
                     tier=tier_label, available_models=models)


# Convenience constructors for well-known vendors. Model IDs are the
# vendor's own IDs; verify them against the vendor docs before use.
def deepseek(model_id: str = "deepseek-v4-flash") -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        vendor="DeepSeek", model_id=model_id,
        base_url="https://api.deepseek.com/v1",
        key_env="DEEPSEEK_API_KEY",
        balance_url="https://api.deepseek.com/user/balance",
        paid=False,
    )


def deepseek_pro(model_id: str = "deepseek-v4-pro") -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        vendor="DeepSeek", model_id=model_id,
        base_url="https://api.deepseek.com/v1",
        key_env="DEEPSEEK_API_KEY",
        balance_url="https://api.deepseek.com/user/balance",
        paid=True,
    )


def kexaone() -> OpenAICompatibleAdapter:
    # K-EXAONE 2.5: free, non-commercial, Korean/English only, 30-day key.
    # No total-quota API; remaining is only visible in per-call headers.
    return OpenAICompatibleAdapter(
        vendor="K-EXAONE", model_id="k-exaone_v2.5",
        base_url="https://api.exaone.ai/v1",
        key_env="KEXAONE_API_KEY",
        paid=False,
    )


def qwen_api(model_id: str = "qwen-turbo") -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        vendor="Qwen", model_id=model_id,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        key_env="QWEN_API_KEY",
        paid=True,
    )


def glm_api(model_id: str = "glm-5.3-flash") -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        vendor="GLM", model_id=model_id,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        key_env="GLM_API_KEY",
        paid=False,
    )
