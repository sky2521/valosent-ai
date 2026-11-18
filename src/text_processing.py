"""Shared text normalization for training and request-time sentiment analysis."""

from __future__ import annotations

import html
import re


def clean_review(text: str | None) -> str:
    """Normalize review text consistently before feature extraction."""
    if text is None:
        return ""
    value = html.unescape(str(text)).lower()
    value = re.sub(r"<.*?>", " ", value)
    value = re.sub(r"https?://\S+|www\.\S+", " ", value)
    value = re.sub(r"[^a-z\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()
