from __future__ import annotations

import io
from typing import Dict, Any, Optional

from pypdf import PdfReader


def extract_rfp_text(uploaded_file) -> Dict[str, Any]:
    """
    Standard signature: takes ONLY the Streamlit uploaded_file and returns:
      {"text": str, "pages": int, "filename": str|None}
    """
    if uploaded_file is None:
        return {"text": "", "pages": 0, "filename": None}

    filename = getattr(uploaded_file, "name", None)

    # Read bytes once
    file_bytes = uploaded_file.read()
    if not file_bytes:
        return {"text": "", "pages": 0, "filename": filename}

    # Try PDF first
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = len(reader.pages)
        parts = []
        for p in reader.pages[:250]:  # hard cap to protect memory on cheap tiers
            t = p.extract_text() or ""
            if t.strip():
                parts.append(t)
        text = "\n\n".join(parts).strip()
        return {"text": text, "pages": pages, "filename": filename}
    except Exception:
        pass

    # Fallback: treat as text
    try:
        text = file_bytes.decode("utf-8", errors="ignore")
    except Exception:
        text = ""
    page_est = max(1, len(text) // 1800) if text else 0
    return {"text": text, "pages": page_est, "filename": filename}