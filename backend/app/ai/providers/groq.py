from .base import BaseProvider
from typing import Optional

class GroqProvider(BaseProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000, json_mode: bool = False) -> str:
        try:
            from groq import AsyncGroq
            client = AsyncGroq(api_key=self.api_key)
            msgs = []
            if system: msgs.append({"role":"system","content":system})
            msgs.append({"role":"user","content":prompt})
            kwargs = {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            r = await client.chat.completions.create(**kwargs)
            return r.choices[0].message.content
        except ImportError:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self.api_key, base_url="https://api.groq.com/openai/v1")
            msgs = []
            if system: msgs.append({"role":"system","content":system})
            msgs.append({"role":"user","content":prompt})
            kwargs = {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            r = await client.chat.completions.create(**kwargs)
            return r.choices[0].message.content
