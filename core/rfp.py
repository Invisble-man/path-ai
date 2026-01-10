from __future__ import annotations
import io
from typing import Dict, Any
from pypdf import PdfReader

MAX_PDF_PAGES = 250
MAX_TEXT_CHARS = 350_000  # protect 512MB tiers

def extract_rfp_text(uploaded_file) -> Dict[str, Any]:
    """
    Standard signature: takes ONLY Streamlit uploaded_file.
    Returns:
      {"text": str, "pages": int, "filename": str|None}
    """
    if uploaded_file is None:
        return {"text": "", "pages": 0, "filename": None}

    filename = getattr(uploaded_file, "name", None)

    file_bytes = uploaded_file.read()
    if not file_bytes:
        return {"text": "", "pages": 0, "filename": filename}

    # Try PDF
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = len(reader.pages)
        parts = []
        for p in reader.pages[:MAX_PDF_PAGES]:
            t = p.extract_text() or ""
            if t.strip():
                parts.append(t)
        text = "\n\n".join(parts).strip()
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]
        return {"text": text, "pages": pages, "filename": filename}
    except Exception:
        pass

    # Fallback: treat as text
    try:
        text = file_bytes.decode("utf-8", errors="ignore")
    except Exception:
        text = ""

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]

    page_est = max(1, len(text) // 1800) if text else 0
    return {"text": text, "pages": page_est, "filename": filename}