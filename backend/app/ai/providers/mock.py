from .base import BaseProvider
from typing import Optional

class MockProvider(BaseProvider):
    def __init__(self, model: str = "mock-mini"):
        self.model = model
    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000, json_mode: bool = False) -> str:
        prefix = f"[MOCK {self.model}] "
        if system:
            return prefix + f"System: {system[:60]}... | User: {prompt[:400]}... (Mock - set LLM_API_KEY for real output)"
        return prefix + f"Echo: {prompt[:500]} (Mock LLM)"
