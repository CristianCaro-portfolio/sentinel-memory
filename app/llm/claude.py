"""Thin wrapper around the Anthropic Messages API."""
import os
from typing import Optional

from anthropic import Anthropic

_client: Optional[Anthropic] = None
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def complete(system: str, messages: list[dict], max_tokens: int = 1024) -> str:
    resp = get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text")
