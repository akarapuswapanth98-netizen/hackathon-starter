from abc import ABC, abstractmethod
from typing import Optional

class BaseProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000, json_mode: bool = False) -> str:
        """Generate text. json_mode=True requests strict JSON output (enforced where the API supports it)."""
        pass
