"""Utilities for processing raw LLM output before delivery."""

from __future__ import annotations

NO_REPLY_SENTINEL = "[NO_REPLY_TO_HUMAN]"


def strip_no_reply_sentinel(text: str) -> tuple[str, bool]:
    """Strip the no-reply sentinel from LLM output.

    Returns (cleaned_text, should_deliver).  When the sentinel is present
    the text is cleaned and should_deliver is False.
    """
    if NO_REPLY_SENTINEL not in text:
        return text, True

    cleaned = text.replace(NO_REPLY_SENTINEL, "").strip()
    return cleaned, False
