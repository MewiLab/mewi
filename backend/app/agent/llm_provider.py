"""
LLM provider abstraction.

The graph depends on LLMProvider (a Protocol).
Concrete implementations are created once in lifespan.py and injected.

Provider quick-reference (set via env vars):
  LLM_PROVIDER=openai      LLM_API_KEY=sk-...        LLM_MODEL=gpt-4o
  LLM_PROVIDER=groq         LLM_API_KEY=gsk_...       LLM_MODEL=llama-3.3-70b-versatile
  LLM_PROVIDER=openrouter  LLM_API_KEY=sk-or-...     LLM_MODEL=anthropic/claude-sonnet-4-5
  LLM_PROVIDER=ollama      LLM_BASE_URL=https://xxxx.ngrok.io  LLM_MODEL=gemma3:4b
  LLM_PROVIDER=anthropic   LLM_API_KEY=sk-ant-...    LLM_MODEL=claude-3-5-sonnet-20241022
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> BaseMessage: ...
    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> BaseMessage: ...


def create_llm_provider(settings=None) -> LLMProvider:
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings().llm

    provider = settings.provider
    base_url_display = settings.base_url or "(default)"
    logger.info(
        "LLM provider: %s | model: %s | base_url: %s | timeout: %ss",
        provider,
        settings.model,
        base_url_display,
        settings.timeout,
    )

    if provider in ("openai", "anthropic"):
        return _make_langchain_provider(settings)
    if provider == "ollama":
        return _make_ollama_provider(settings)
    if provider == "openrouter":
        return _make_openrouter_provider(settings)
    if provider == "groq":
        return _make_groq_provider(settings)

    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        "Valid options: openai, anthropic, ollama, openrouter, groq"
    )


# ── builders ────────────────────────────────────────────────────────────────

def _make_langchain_provider(settings) -> LLMProvider:
    if settings.provider == "openai":
        from langchain_openai import ChatOpenAI
        kwargs: dict[str, Any] = dict(
            api_key=settings.api_key or None,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
        )
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        return ChatOpenAI(**kwargs)

    if settings.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            api_key=settings.api_key or None,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )

    raise ValueError(settings.provider)


def _make_ollama_provider(settings) -> LLMProvider:
    from langchain_openai import ChatOpenAI

    # Ollama's OpenAI-compatible endpoint lives at /v1.
    # Append it automatically so LLM_BASE_URL=https://xxxx.ngrok.io just works.
    base = settings.base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"

    return ChatOpenAI(
        api_key="ollama",   # Ollama ignores the key; field is required by LangChain
        base_url=base,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout=settings.timeout,
    )


def _make_openrouter_provider(settings) -> LLMProvider:
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        api_key=settings.api_key or None,
        base_url=settings.base_url,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout=settings.timeout,
        default_headers={
            "HTTP-Referer": "https://your-app.example.com",
            "X-Title": "CreatureAgent",
        },
    )


def _make_groq_provider(settings) -> LLMProvider:
    """
    Groq is OpenAI-compatible and IP-agnostic — no VPN / campus network needed.
    Get a free key at console.groq.com.  Fast inference, generous free tier.
    Recommended model: llama-3.3-70b-versatile
    """
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        api_key=settings.api_key or None,
        base_url=settings.base_url,   # defaults to https://api.groq.com/openai/v1
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout=settings.timeout,
    )
