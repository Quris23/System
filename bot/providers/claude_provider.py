"""
Claude API provider (stub — ready to enable).

To switch:
  1. pip install anthropic
  2. Set ANTHROPIC_API_KEY in .env
  3. Set AI_PROVIDER=claude in .env
"""
import os
from .base import BaseProvider


class ClaudeProvider(BaseProvider):
    MODEL = "claude-sonnet-4-5"

    def __init__(self):
        try:
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        except ImportError:
            raise ImportError("Run: pip install anthropic")

    async def complete(self, messages, system_prompt: str) -> str:
        resp = await self.client.messages.create(
            model=self.MODEL,
            max_tokens=1500,
            system=system_prompt,
            messages=messages,
        )
        return resp.content[0].text
