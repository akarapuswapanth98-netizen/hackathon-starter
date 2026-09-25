from abc import ABC, abstractmethod
from typing import Optional

class BaseProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        pass
