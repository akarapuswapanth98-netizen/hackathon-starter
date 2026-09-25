"""
Provider-agnostic LLM service.
Switch via env: LLM_PROVIDER=mock|openai|groq|gemini|anthropic
               LLM_MODEL=...
               LLM_API_KEY=...
No hard-coded keys. All providers return same interface.
"""
import os
import logging
from typing import Optional
from app.core.config import get_settings
from app.core.errors import LLMNotConfiguredError

logger = logging.getLogger("hackathon.llm")
settings = get_settings()

# --- Provider interface ---

class LLMService:
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None):
        s = get_settings()
        self.provider = (provider or s.LLM_PROVIDER).lower()
        self.model = model or s.LLM_MODEL
        # Resolve API key: explicit -> provider-specific -> generic
        if api_key:
            self.api_key = api_key
        else:
            provider_key = os.getenv(f"{self.provider.upper()}_API_KEY", "")
            self.api_key = provider_key or s.LLM_API_KEY or ""

        self.configured = self._is_configured()
        logger.info(f"LLM init provider={self.provider} model={self.model} configured={self.configured}")

    def _is_configured(self) -> bool:
        if self.provider == "mock":
            return True
        return bool(self.api_key)

    def ensure_configured(self):
        if not self.configured:
            raise LLMNotConfiguredError(self.provider)

    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        """Generate text. Provider-agnostic entrypoint."""
        if self.provider == "mock":
            return self._mock_generate(prompt, system)

        self.ensure_configured()

        # Dispatch to provider
        if self.provider == "openai":
            return await self._openai_generate(prompt, system, temperature, max_tokens)
        elif self.provider == "groq":
            return await self._groq_generate(prompt, system, temperature, max_tokens)
        elif self.provider == "gemini":
            return await self._gemini_generate(prompt, system, temperature, max_tokens)
        elif self.provider == "anthropic":
            return await self._anthropic_generate(prompt, system, temperature, max_tokens)
        else:
            logger.warning(f"Unknown provider {self.provider}, falling back to mock")
            return self._mock_generate(prompt, system)

    def _mock_generate(self, prompt: str, system: Optional[str]) -> str:
        # Deterministic mock for hackathon without keys - demo-safe
        prefix = f"[MOCK {self.model}] "
        if system:
            return prefix + f"System: {system[:80]}...\nUser: {prompt[:300]}...\n(Mock response: Configure LLM_PROVIDER and LLM_API_KEY in .env to get real LLM output. This mock proves workflow wiring works.)"
        return prefix + f"Echo: {prompt[:500]} (Mock LLM - set LLM_API_KEY to enable real provider '{self.provider}')"

    async def _openai_generate(self, prompt, system, temperature, max_tokens):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise AppError("openai package not installed. Run pip install openai")
        client = AsyncOpenAI(api_key=self.api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.chat.completions.create(model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        return resp.choices[0].message.content

    async def _groq_generate(self, prompt, system, temperature, max_tokens):
        try:
            from groq import AsyncGroq
        except ImportError:
            # Fallback to openai-compatible client
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=self.api_key, base_url="https://api.groq.com/openai/v1")
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})
                resp = await client.chat.completions.create(model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens)
                return resp.choices[0].message.content
            except ImportError:
                raise AppError("groq or openai package not installed. Run pip install groq")
        client = AsyncGroq(api_key=self.api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await client.chat.completions.create(model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        return resp.choices[0].message.content

    async def _gemini_generate(self, prompt, system, temperature, max_tokens):
        try:
            import google.generativeai as genai
        except ImportError:
            raise AppError("google-generativeai not installed. Run pip install google-generativeai")
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model, system_instruction=system)
        resp = await model.generate_content_async(prompt, generation_config={"temperature": temperature, "max_output_tokens": max_tokens})
        return resp.text

    async def _anthropic_generate(self, prompt, system, temperature, max_tokens):
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise AppError("anthropic not installed. Run pip install anthropic")
        client = AsyncAnthropic(api_key=self.api_key)
        resp = await client.messages.create(model=self.model, system=system or "", max_tokens=max_tokens, temperature=temperature, messages=[{"role": "user", "content": prompt}])
        return "".join([b.text for b in resp.content if hasattr(b, 'text')])

# Re-export for convenience
from app.core.errors import AppError
