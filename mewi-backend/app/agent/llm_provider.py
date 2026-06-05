from __future__ import annotations

import logging
from typing import Any, Protocol
from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


class LLMProvider(Protocol):
    """
    LLM provider abstraction. Support multiple llm api
    """
    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> BaseMessage: ...
    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> BaseMessage: ...


def describe_llm_provider(settings=None) -> dict[str, Any]:
    """
    Return a safe, loggable description of the active LLM provider.

    This intentionally never returns the raw API key.
    """
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings().llm

    api_key_status = "set" if settings.api_key else "missing"
    if settings.provider == "ollama" and settings.api_key == "ollama":
        api_key_status = "placeholder"

    return {
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url or "<provider default>",
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "timeout": settings.timeout,
        "api_key": api_key_status,
    }


def log_llm_provider_selection(settings=None, target_logger: logging.Logger | None = None) -> dict[str, Any]:
    """
    Log the active LLM provider and return the same safe summary for callers
    that want to expose it via app.state or diagnostics.
    """
    summary = describe_llm_provider(settings)
    log = target_logger or logger
    log.info(
        "LLM provider selected: provider=%s model=%s base_url=%s api_key=%s temperature=%s max_tokens=%s timeout=%s",
        summary["provider"],
        summary["model"],
        summary["base_url"],
        summary["api_key"],
        summary["temperature"],
        summary["max_tokens"],
        summary["timeout"],
    )
    return summary

    
def create_llm_provider(settings=None) -> LLMProvider:
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings().llm
    
    provider = settings.provider
    logger.info(
        "Creating LLM provider: provider=%s model=%s base_url=%s",
        provider,
        settings.model,
        settings.base_url or "<provider default>",
    )
    
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
        kwargs: dict[str, Any] = dict(
            api_key=settings.api_key or None,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        return ChatAnthropic(**kwargs)
        
    raise ValueError(settings.provider)

    
def _make_ollama_provider(settings) -> LLMProvider:
    from langchain_openai import ChatOpenAI
    # Config already normalizes the base_url to Ollama's OpenAI-compatible /v1 path.
    base = settings.base_url.rstrip("/")
    logger.info("Ollama base_url resolved to: %s", base)
    return ChatOpenAI(
        api_key=settings.api_key or "ollama",
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
            "X-Title": "CreatureRuntime",
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
