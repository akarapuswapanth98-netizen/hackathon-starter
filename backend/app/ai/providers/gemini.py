from .base import BaseProvider
from typing import Optional

class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
    async def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 1000, json_mode: bool = False) -> str:
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        m = genai.GenerativeModel(self.model, system_instruction=system)
        cfg = {"temperature": temperature, "max_output_tokens": max_tokens}
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        r = await m.generate_content_async(prompt, generation_config=cfg)
        return r.text
