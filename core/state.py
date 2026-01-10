from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


# The required flow (but we still allow navigation with warnings)
step_order: List[Tuple[str, str]] = [
    ("home", "Upload RFP"),
    ("dashboard", "Dashboard"),
    ("company", "Company Info"),
    ("draft", "Draft Proposal"),
    ("compatibility", "Compatibility Matrix"),
    ("export", "Export"),
]


@dataclass
class RFPData:
    filename: str = ""
    pages: int = 0
    text: str = ""
    extracted: bool = False

    # Signals extracted by heuristics (and later AI)
    due_date: str = ""
    submission_email: str = ""
    certifications_required: List[str] = None
    eligibility_rules: List[str] = None
    past_performance_requirements: List[str] = None
    requirements: List[str] = None

    # Warnings from parsing
    flags: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # dataclass defaults for lists
        d["certifications_required"] = d["certifications_required"] or []
        d["eligibility_rules"] = d["eligibility_rules"] or []
        d["past_performance_requirements"] = d["past_performance_requirements"] or []
        d["requirements"] = d["requirements"] or []
        d["flags"] = d["flags"] or []
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RFPData":
        return RFPData(
            filename=d.get("filename", ""),
            pages=int(d.get("pages", 0) or 0),
            text=d.get("text", "") or "",
            extracted=bool(d.get("extracted", False)),
            due_date=d.get("due_date", "") or "",
            submission_email=d.get("submission_email", "") or "",
            certifications_required=list(d.get("certifications_required", []) or []),
            eligibility_rules=list(d.get("eligibility_rules", []) or []),
            past_performance_requirements=list(d.get("past_performance_requirements", []) or []),
            requirements=list(d.get("requirements", []) or []),
            flags=list(d.get("flags", []) or []),
        )


@dataclass
class CompanyProfile:
    name: str = ""
    uei: str = ""
    cage: str = ""
    address: str = ""
    naics: str = ""
    differentiators: str = ""
    past_performance: str = ""
    certifications: List[str] = None

    logo_bytes: Optional[bytes] = None
    logo_mime: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["certifications"] = d["certifications"] or []
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CompanyProfile":
        return CompanyProfile(
            name=d.get("name", "") or "",
            uei=d.get("uei", "") or "",
            cage=d.get("cage", "") or "",
            address=d.get("address", "") or "",
            naics=d.get("naics", "") or "",
            differentiators=d.get("differentiators", "") or "",
            past_performance=d.get("past_performance", "") or "",
            certifications=list(d.get("certifications", []) or []),
            logo_bytes=d.get("logo_bytes", None),
            logo_mime=d.get("logo_mime", "") or "",
        )


def init_app_state() -> None:
    """Initialize Streamlit session state safely (no crashes, no missing keys)."""
    if "current_step" not in st.session_state:
        st.session_state.current_step = "home"

    if "rfp" not in st.session_state:
        st.session_state.rfp = RFPData().to_dict()

    if "company" not in st.session_state:
        st.session_state.company = CompanyProfile().to_dict()

    if "compatibility_rows" not in st.session_state:
        # List[Dict]: requirement, response, status
        st.session_state.compatibility_rows = []

    if "scores" not in st.session_state:
        # Filled in later by core/scoring.py
        st.session_state.scores = {
            "compliance_pct": 0,
            "completion_pct": 0,
            "win_probability_pct": 0,
        }


def set_current_step(step_id: str) -> None:
    st.session_state.current_step = step_id


def get_rfp() -> RFPData:
    return RFPData.from_dict(st.session_state.get("rfp", {}) or {})


def set_rfp(rfp: RFPData) -> None:
    st.session_state.rfp = rfp.to_dict()


def get_company() -> CompanyProfile:
    return CompanyProfile.from_dict(st.session_state.get("company", {}) or {})


def set_company(profile: CompanyProfile) -> None:
    st.session_state.company = profile.to_dict()


def _is_rfp_uploaded() -> bool:
    rfp = get_rfp()
    return bool(rfp.extracted and rfp.text.strip())


def _is_company_started() -> bool:
    c = get_company()
    return bool(c.name.strip() or c.uei.strip() or c.cage.strip())


def _is_company_complete_minimum() -> bool:
    c = get_company()
    # "Minimum viable" to draft without blocking. Draft page will still warn if incomplete.
    return bool(c.name.strip() and (c.uei.strip() or c.cage.strip()))


def _has_compatibility() -> bool:
    rows = st.session_state.get("compatibility_rows", []) or []
    return len(rows) > 0


def get_step_status_map() -> Dict[str, str]:
    """
    done / in_progress / not_started
    Sidebar should be a guide, not a gate.
    """
    status = {sid: "not_started" for sid, _ in step_order}

    # Home (Upload RFP)
    if _is_rfp_uploaded():
        status["home"] = "done"
    else:
        status["home"] = "in_progress" if get_rfp().filename else "not_started"

    # Dashboard becomes meaningful after upload
    status["dashboard"] = "done" if _is_rfp_uploaded() else "not_started"

    # Company info
    if _is_company_complete_minimum():
        status["company"] = "done"
    elif _is_company_started():
        status["company"] = "in_progress"
    else:
        status["company"] = "not_started"

    # Draft
    # We'll mark in_progress if either upload or company exists, done later after we generate draft state (future)
    if _is_rfp_uploaded() and _is_company_started():
        status["draft"] = "in_progress"
    else:
        status["draft"] = "not_started"

    # Compatibility
    if _has_compatibility():
        status["compatibility"] = "in_progress"
    else:
        status["compatibility"] = "not_started"

    # Export is always accessible
    status["export"] = "not_started"

    return status


def compute_completion_pct() -> int:
    """
    Basic completion heuristic (0-100). We’ll refine later when scoring is fully implemented.
    """
    points = 0
    total = 4

    if _is_rfp_uploaded():
        points += 1
    if _is_company_complete_minimum():
        points += 1
    if _has_compatibility():
        points += 1
    # draft generation state will be added later; for now treat as 0
    # points += 1 when draft exists

    return int(round((points / total) * 100))