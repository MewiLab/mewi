"""
LLM provider abstraction.

The graph depends on LLMProvider (a Protocol).
Concrete implementations are created once in lifespan.py and injected.
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
    logger.info("Creating LLM provider: %s / %s", provider, settings.model)
    
    if provider in ("openai", "anthropic"):
        return _make_langchain_provider(settings)

    if provider == "ollama":
        return _make_ollama_provider(settings)

    if provider == "openrouter":
        return _make_openrouter_provider(settings)

    if provider == "groq":
        return _make_groq_provider(settings)

    raise ValueError(f"Unknown LLM provider: {provider!r}")
    
    
# builders    
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
    # Ensure the base_url ends with /v1 (Ollama's OpenAI-compatible path).
    # LLM_BASE_URL (e.g. an ngrok tunnel) is used as-is when set; the config
    # validator already appended /v1 to the localhost default.
    base = settings.base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    logger.info("Ollama base_url resolved to: %s", base)
    return ChatOpenAI(
        api_key="ollama",           # Ollama ignores the key but the field is required
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
            "HTTP-Referer": "https://your-app.example.com",   # shows in OR dashboard
            "X-Title": "CreatureAgent",
        },
    )


def _make_groq_provider(settings) -> LLMProvider:
    """
    Groq Cloud — OpenAI-compatible, very fast, no IP restrictions.
    Set in .env:
        LLM_PROVIDER=groq
        LLM_API_KEY=gsk_...
        LLM_MODEL=llama3-70b-8192   # or mixtral-8x7b-32768, gemma2-9b-it, etc.
    """
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        api_key=settings.api_key or None,
        base_url=settings.base_url,   # auto-filled to https://api.groq.com/openai/v1
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout=settings.timeout,
    )