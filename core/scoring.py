from __future__ import annotations

from typing import List, Dict, Any

import streamlit as st

from core.state import compute_completion_pct, get_rfp, get_company


def _normalize_status(s: str) -> str:
    s = (s or "").strip().lower()
    if s in ("met", "complete", "yes"):
        return "met"
    if s in ("partial", "incomplete"):
        return "partial"
    return "missing"


def compute_compliance_pct(compatibility_rows: List[Dict[str, Any]]) -> int:
    """
    Met = 1.0, Partial = 0.5, Missing = 0.0
    """
    if not compatibility_rows:
        return 0

    score = 0.0
    for row in compatibility_rows:
        status = _normalize_status(row.get("status", "missing"))
        if status == "met":
            score += 1.0
        elif status == "partial":
            score += 0.5

    pct = int(round((score / max(1, len(compatibility_rows))) * 100))
    return max(0, min(100, pct))


def compute_eligibility_flags(rfp: Dict[str, Any], company: Dict[str, Any]) -> List[str]:
    """
    Warnings only (no blocking).
    """
    flags: List[str] = []

    rfp_certs = rfp.get("certifications_required") or []
    company_certs = company.get("certifications") or []

    # If RFP mentions certifications, warn if company doesn't have any overlap
    if rfp_certs:
        overlap = {c.lower() for c in company_certs} & {c.lower() for c in rfp_certs}
        if not overlap:
            flags.append(
                "Eligibility warning: RFP references certifications, but your company profile does not show a matching certification."
            )

    # Basic identity completeness signals
    if not (company.get("uei") or company.get("cage")):
        flags.append("Company profile warning: UEI or CAGE is missing (not blocking).")

    if not company.get("name"):
        flags.append("Company profile warning: Company name is missing (not blocking).")

    return flags


def compute_win_probability_pct(
    compliance_pct: int,
    completion_pct: int,
    eligibility_flags: List[str],
) -> int:
    """
    A conservative heuristic (not a promise).
    """
    base = 10

    # Weight compliance most heavily
    base += int(compliance_pct * 0.55)
    base += int(completion_pct * 0.25)

    # Penalize eligibility warnings
    if eligibility_flags:
        base -= min(20, 8 * len(eligibility_flags))

    # Clamp
    return max(1, min(95, base))


def compute_all_scores() -> Dict[str, int]:
    """
    Stores scores in session_state and returns them.
    """
    rfp = st.session_state.get("rfp", {}) or {}
    company = st.session_state.get("company", {}) or {}
    compatibility_rows = st.session_state.get("compatibility_rows", []) or []

    completion_pct = compute_completion_pct()
    compliance_pct = compute_compliance_pct(compatibility_rows)
    eligibility_flags = compute_eligibility_flags(rfp, company)
    win_probability_pct = compute_win_probability_pct(compliance_pct, completion_pct, eligibility_flags)

    scores = {
        "completion_pct": completion_pct,
        "compliance_pct": compliance_pct,
        "win_probability_pct": win_probability_pct,
    }
    st.session_state.scores = scores
    st.session_state.eligibility_flags = eligibility_flags
    return scores