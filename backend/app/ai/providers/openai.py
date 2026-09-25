from .base import BaseProvider
from typing import Optional

class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("openai not installed: pip install openai")
        client = AsyncOpenAI(api_key=self.api_key)
        msgs = []
        if system: msgs.append({"role":"system","content":system})
        msgs.append({"role":"user","content":prompt})
        r = await client.chat.completions.create(model=self.model, messages=msgs, temperature=temperature, max_tokens=max_tokens)
        return r.choices[0].message.content
