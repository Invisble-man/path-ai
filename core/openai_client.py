import os
from typing import Optional

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def get_client() -> Optional["OpenAI"]:
    """
    Returns an OpenAI client if the SDK is installed and OPENAI_API_KEY exists.
    """
    key = os.getenv("OPENAI_API_KEY", "")
    if not key or not OpenAI:
        return None
    return OpenAI()


def ai_text(prompt: str, model: str = "gpt-4o-mini") -> str:
    """
    Minimal text helper using the current OpenAI Python SDK.
    """
    client = get_client()
    if not client:
        raise RuntimeError("OpenAI not configured. Missing OPENAI_API_KEY or openai package.")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful proposal-writing assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""
