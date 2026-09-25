from .base import BaseProvider
from typing import Optional

class AnthropicProvider(BaseProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self.api_key)
        r = await client.messages.create(model=self.model, system=system or "", max_tokens=max_tokens, temperature=temperature, messages=[{"role":"user","content":prompt}])
        return "".join([b.text for b in r.content if hasattr(b, "text")])
