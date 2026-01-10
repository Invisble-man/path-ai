import os
from typing import Optional, Any

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

def get_openai_client() -> Optional[Any]:
    """
    Returns OpenAI client if OPENAI_API_KEY exists and SDK is installed.
    """
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or OpenAI is None:
        return None
    return OpenAI(api_key=key)