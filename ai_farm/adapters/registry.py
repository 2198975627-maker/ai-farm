"""Adapter registry: recruit any vendor by slug.

Add a new model in two steps, no dispatcher changes needed:
  1. Write a factory that returns an AgentAdapter (see
     openai_compatible.py / web.py).
  2. Register it here with a short slug, e.g. ``register("my-model", factory)``.
The roster then refers to the slug, and the office shows one icon per slug.
"""
from __future__ import annotations

from typing import Callable

_FACTORIES: dict[str, Callable[..., object]] = {}


def register(slug: str, factory: Callable[..., object]) -> None:
    _FACTORY_SLUG = slug.strip().lower()
    if _FACTORY_SLUG in _FACTORIES:
        raise ValueError(f"adapter slug already registered: {slug}")
    _FACTORIES[_FACTORY_SLUG] = factory


def get_adapter(slug: str, **kwargs):
    factory = _FACTORIES.get(slug.strip().lower())
    if factory is None:
        raise KeyError(
            f"unknown adapter slug: {slug}. Registered: {sorted(_FACTORIES)}"
        )
    return factory(**kwargs)


def registered_slugs() -> list[str]:
    return sorted(_FACTORIES)


# Built-in API adapters.
from .openai_compatible import (  # noqa: E402
    OpenAICompatibleAdapter,
    deepseek,
    deepseek_pro,
    glm_api,
    kexaone,
    qwen_api,
)
from .web import (  # noqa: E402
    ChatGPTFreeWebAdapter,
    ChatGPTPlusWebAdapter,
    DolaFreeWebAdapter,
    DoubaoFreeWebAdapter,
    GeminiArgonSubscriptionAdapter,
    GeminiFlashWebAdapter,
    GrokFreeWebAdapter,
    KimiFreeWebAdapter,
    QwenChatIntlWebAdapter,
    QwenFreeWebAdapter,
    WebAdapter,
)

register("deepseek-flash", deepseek)
register("deepseek-pro", deepseek_pro)
register("kexaone", kexaone)
register("qwen-api", qwen_api)
register("glm-flash", glm_api)
register("custom-api", OpenAICompatibleAdapter)

# Built-in Web / Subscription adapters.
register("gemini-web", GeminiArgonSubscriptionAdapter)
register("gemini-flash-web", GeminiFlashWebAdapter)
register("chatgpt-web", ChatGPTFreeWebAdapter)
register("chatgpt-plus-web", ChatGPTPlusWebAdapter)
register("grok-web", GrokFreeWebAdapter)
register("kimi-web", KimiFreeWebAdapter)
register("doubao-web", DoubaoFreeWebAdapter)
register("dola-web", DolaFreeWebAdapter)
register("qwen-web", QwenFreeWebAdapter)
register("qwen-intl-web", QwenChatIntlWebAdapter)
register("custom-web", WebAdapter)
