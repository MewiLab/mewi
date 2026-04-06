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
    
    if provider in ("openai", "anthrophic"):
        return _make_langchain_provider(settings)
    
    if provider == "ollama":
        return _make_ollama_provider(settings)
    
    if provider == "openrouter":
        return _make_openrouter_provider(settings)
    
    
# builders    
def _make_langchain_provider(settings) -> LLMProvider:
    if settings.provider == "openai":
        from langchain_openai import ChatOpenAI
        kwargs: dict[str, Any] = dict(
            api_key=settings.api_key,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
        )
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        return ChatOpenAI(**kwargs)
    
    if settings.provider == "anthrophic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            api_key=settings.api_key,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )
        
    raise ValueError(settings.provider)

    
def _make_ollama_provider(settings) -> LLMProvider:
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        api_key="ollama",           # Ollama ignores the key but the field is required
        base_url=f"{settings.base_url}",
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout=settings.timeout,
    )
    
def _make_openrouter_provider(settings) -> LLMProvider:
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        api_key=settings.api_key,
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