from __future__ import annotations

import hashlib
from typing import Tuple

import streamlit as st

from core.rfp import parse_rfp_from_pdf_bytes, ParsedRFP


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@st.cache_data(show_spinner=False)
def cached_parse(pdf_hash: str, pdf_bytes: bytes, max_pages_to_read: int) -> ParsedRFP:
    # pdf_hash is included so cache invalidates when file changes
    return parse_rfp_from_pdf_bytes(pdf_bytes, max_pages_to_read=max_pages_to_read)


def analyze_pdf(pdf_bytes: bytes, max_pages_to_read: int) -> Tuple[ParsedRFP, str]:
    h = _hash_bytes(pdf_bytes)
    parsed = cached_parse(h, pdf_bytes, max_pages_to_read)
    return parsed, h