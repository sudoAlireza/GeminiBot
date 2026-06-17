"""Provider API key format helpers."""

from __future__ import annotations

import re


_GEMINI_KEY_PATTERNS = (
    re.compile(r"^AIza[A-Za-z0-9_-]{35,}$"),
    re.compile(r"^AQ\.[A-Za-z0-9._-]{8,}$"),
)


def is_valid_gemini_key_format(api_key: str) -> bool:
    """Return whether a Gemini key matches a known AI Studio key prefix."""
    return any(pattern.fullmatch(api_key) for pattern in _GEMINI_KEY_PATTERNS)
