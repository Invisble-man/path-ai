from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import streamlit as st


@dataclass
class RFPState:
    filename: str = ""
    extracted: bool = False
    pages: int = 0
    text: str = ""
    # extracted fields
    due_date: str = ""
    submission_email: str = ""
    certifications_required: List[str] = field(default_factory=list)
    naics: str = ""
    # raw
    pdf_bytes: Optional[bytes] = None


@dataclass
class CompanyState:
    name: str = ""
    uei: str = ""
    cage: str = ""
    address: str = ""
    naics: str = ""
    certifications: List[str] = field(default_factory=list)
    past_performance: str = ""
    differentiators: str = ""


def ensure_state() -> None:
    st.session_state.setdefault("current_step", "home")
    st.session_state.setdefault("completion", {})  # step -> started/complete
    st.session_state.setdefault("rfp", RFPState())
    st.session_state.setdefault("company", CompanyState())
    st.session_state.setdefault("company_logo_bytes", None)

    # Draft lifecycle
    st.session_state.setdefault("draft_cover_letter", "")
    st.session_state.setdefault("draft_body", "")
    st.session_state.setdefault("final_cover_letter", "")
    st.session_state.setdefault("final_body", "")
    st.session_state.setdefault("qa_findings", "")


def get_current_step() -> str:
    return st.session_state.get("current_step", "home")


def set_current_step(step: str) -> None:
    st.session_state["current_step"] = step
    _mark_started(step)


def _mark_started(step: str) -> None:
    completion = st.session_state.get("completion", {})
    if completion.get(step) is None:
        completion[step] = "started"
    st.session_state["completion"] = completion


def mark_complete(step: str) -> None:
    completion = st.session_state.get("completion", {})
    completion[step] = "complete"
    st.session_state["completion"] = completion


def get_rfp() -> RFPState:
    return st.session_state["rfp"]


def set_rfp(rfp: RFPState) -> None:
    st.session_state["rfp"] = rfp


def get_company() -> CompanyState:
    return st.session_state["company"]


def set_company(company: CompanyState) -> None:
    st.session_state["company"] = company