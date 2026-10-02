"""
Provider-independent LLMService with timeout, retries, logging, token estimates.
Mock mode works offline. Real providers need API key + pip package.
"""
import asyncio
import logging
import os
import time
from typing import Optional
from app.core.config import get_settings
from app.core.errors import LLMNotConfiguredError

logger = logging.getLogger("hackathon.llm")


def estimate_tokens(text: str) -> int:
    # Rough: ~4 chars per token. Used when API doesn't return usage.
    return max(1, len(text or "") // 4)


class LLMService:
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None,
                 timeout: Optional[float] = None, max_retries: int = 2):
        s = get_settings()
        self.provider = (provider or s.LLM_PROVIDER).lower()
        self.model = model or s.LLM_MODEL
        if api_key:
            self.api_key = api_key
        else:
            pk = os.getenv(f"{self.provider.upper()}_API_KEY", "")
            self.api_key = pk or s.LLM_API_KEY or ""
        self.configured = self.provider == "mock" or bool(self.api_key)
        self.timeout = timeout if timeout is not None else float(getattr(s, "API_TIMEOUT", 30))
        self.max_retries = max_retries
        self.last_latency_ms: float = 0.0
        self.last_prompt_tokens: int = 0
        self.last_output_tokens: int = 0

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

    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000, json_mode: bool = False) -> str:
        if self.provider != "mock":
            self.ensure_configured()
        provider = self._get_provider()
        prompt_tokens = estimate_tokens((system or "") + prompt)
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    provider.generate(prompt, system, temperature, max_tokens, json_mode=json_mode),
                    timeout=self.timeout,
                )
                latency_ms = (time.perf_counter() - start) * 1000
                out_tokens = estimate_tokens(result)
                self.last_latency_ms = latency_ms
                self.last_prompt_tokens = prompt_tokens
                self.last_output_tokens = out_tokens
                logger.info(
                    "llm provider=%s model=%s latency_ms=%.1f prompt_tokens~%d output_tokens~%d attempt=%d",
                    self.provider, self.model, latency_ms, prompt_tokens, out_tokens, attempt,
                )
                return result
            except LLMNotConfiguredError:
                raise
            except Exception as e:
                last_err = e
                latency_ms = (time.perf_counter() - start) * 1000
                logger.warning("llm attempt=%d failed provider=%s model=%s latency_ms=%.1f err=%s",
                               attempt, self.provider, self.model, latency_ms, e)
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))  # 0.5s, 1.0s backoff
                continue
        assert last_err is not None
        raise last_err
