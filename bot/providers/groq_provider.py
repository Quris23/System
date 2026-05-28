from groq import AsyncGroq
from .base import BaseProvider
from config import GROQ_API_KEY


class GroqProvider(BaseProvider):
    MODEL = "llama-3.3-70b-versatile"

    def __init__(self):
        self.client = AsyncGroq(api_key=GROQ_API_KEY)

    async def complete(self, messages, system_prompt: str) -> str:
        payload = [{"role": "system", "content": system_prompt}] + messages
        resp = await self.client.chat.completions.create(
            model=self.MODEL,
            messages=payload,
            max_tokens=1500,
            temperature=0.7,
        )
        return resp.choices[0].message.content
