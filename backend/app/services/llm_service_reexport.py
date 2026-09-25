"""
Provider-independent LLMService - NEW location per spec (app/ai).
Re-exports with provider adapters isolated.
"""
import os
from typing import Optional
from app.core.config import get_settings
from app.core.errors import LLMNotConfiguredError

# Thin wrapper that delegates to providers/
class LLMService:
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None):
        s = get_settings()
        self.provider = (provider or s.LLM_PROVIDER).lower()
        self.model = model or s.LLM_MODEL
        if api_key:
            self.api_key = api_key
        else:
            pk = os.getenv(f"{self.provider.upper()}_API_KEY", "")
            self.api_key = pk or s.LLM_API_KEY or ""
        self.configured = self.provider == "mock" or bool(self.api_key)

    def _get_provider(self):
        if self.provider == "mock":
            from .providers.mock import MockProvider
            return MockProvider(self.model)
        elif self.provider == "openai":
            from .providers.openai import OpenAIProvider
            return OpenAIProvider(self.api_key, self.model)
        elif self.provider == "groq":
            from .providers.groq import GroqProvider
            return GroqProvider(self.api_key, self.model)
        elif self.provider == "gemini":
            from .providers.gemini import GeminiProvider
            return GeminiProvider(self.api_key, self.model)
        elif self.provider == "anthropic":
            from .providers.anthropic import AnthropicProvider
            return AnthropicProvider(self.api_key, self.model)
        else:
            from .providers.mock import MockProvider
            return MockProvider(self.model)

    def ensure_configured(self):
        if not self.configured:
            raise LLMNotConfiguredError(self.provider)

    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        if self.provider != "mock":
            self.ensure_configured()
        provider = self._get_provider()
        return await provider.generate(prompt, system, temperature, max_tokens)
