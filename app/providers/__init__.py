from __future__ import annotations

from ..config import Settings
from .anthropic import AnthropicProvider
from .base import ExtractionProvider, ProviderError
from .gemini import GeminiProvider
from .openai import OpenAIProvider

__all__ = ["ExtractionProvider", "ProviderError", "get_provider"]


def get_provider(settings: Settings) -> ExtractionProvider:
    chosen = settings.provider.lower()
    if chosen != "auto":
        return _explicit(settings, chosen)
    if settings.gemini_api_key:
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if settings.openai_api_key:
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    if settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    raise ProviderError(
        "no extraction provider configured: set GEMINI_API_KEY, OPENAI_API_KEY, "
        "or ANTHROPIC_API_KEY (or PROVIDER plus its key)"
    )


def _explicit(settings: Settings, name: str) -> ExtractionProvider:
    if name == "gemini":
        if not settings.gemini_api_key:
            raise ProviderError("PROVIDER=gemini but GEMINI_API_KEY is not set")
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if name == "openai":
        if not settings.openai_api_key:
            raise ProviderError("PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    if name == "anthropic":
        if not settings.anthropic_api_key:
            raise ProviderError("PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    raise ProviderError(f"unknown PROVIDER '{name}' (expected gemini, openai, or anthropic)")
