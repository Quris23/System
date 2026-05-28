from config import AI_PROVIDER
from .base import BaseProvider


def get_provider() -> BaseProvider:
    if AI_PROVIDER == "groq":
        from .groq_provider import GroqProvider
        return GroqProvider()
    elif AI_PROVIDER == "claude":
        from .claude_provider import ClaudeProvider
        return ClaudeProvider()
    else:
        raise ValueError(f"Unknown AI_PROVIDER={AI_PROVIDER!r}. Use 'groq' or 'claude'.")
