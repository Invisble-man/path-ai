from __future__ import annotations

import os
from typing import Optional

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


def get_client() -> Optional["OpenAI"]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or OpenAI is None:
        return None
    return OpenAI(api_key=key)