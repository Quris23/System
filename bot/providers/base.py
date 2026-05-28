from abc import ABC, abstractmethod
from typing import List, Dict


class BaseProvider(ABC):
    @abstractmethod
    async def complete(self, messages: List[Dict], system_prompt: str) -> str:
        """Send messages to LLM, return response text."""
        pass
