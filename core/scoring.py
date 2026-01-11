from __future__ import annotations

from typing import Dict, Any, List, Tuple

import streamlit as st

from core.state import get_rfp, get_company


def _grade_from_pct(pct: int) -> str:
    if pct >= 90:
        return "A"
    if pct >= 80:
        return "B"
    if pct >= 70:
        return "C"
    if pct >= 60:
        return "D"
    return "F"


def _truthy(s: Any) -> bool:
    if s is None:
        return False
    if isinstance(s, str):
        return bool(s.strip())
    return bool(s)


def _build_checklist(rfp: Dict[str, Any], company: Dict[str, Any]) -> List[Tuple[str, bool, int, str]]:
    """
    Returns list of (label, passed, weight, hint)
    Weights total 100 for easy scoring.
    """
    cover = st.session_state.get("draft_cover_letter", "") or ""
    body = st.session_state.get("draft_body", "") or ""

    checks: List[Tuple[str, bool, int, str]] = []

    # RFP readiness (40)
    checks.append(("RFP uploaded", _truthy(rfp.get("filename")), 10, "Upload an RFP PDF on the first step."))
    checks.append(("Pages counted", (rfp.get("pages", 0) or 0) > 0, 8, "Ensure the PDF is readable (not corrupted)."))
    checks.append(("Text extracted", _truthy(rfp.get("text")), 12, "If text is empty, try a different PDF version."))
    checks.append(("Due date detected", _truthy(rfp.get("due_date")), 5, "If missing, you can still proceed; we’ll add manual entry later."))
    checks.append(("Submission email/method detected", _truthy(rfp.get("submission_email")), 5, "If missing, you can still proceed; we’ll add manual entry later."))

    # Company readiness (35)
    checks.append(("Company name provided", _truthy(company.get("name")), 8, "Enter your company name for maximum accuracy."))
    checks.append(("UEI or CAGE provided", _truthy(company.get("uei")) or _truthy(company.get("cage")), 10, "UEI/CAGE strengthens credibility and completeness."))
    checks.append(("NAICS provided", _truthy(company.get("naics")), 5, "Add NAICS to align with the solicitation."))
    checks.append(("Certifications selected", bool(company.get("certifications") or []), 6, "Select applicable certifications (SDVOSB, 8(a), etc.)."))
    checks.append(("Differentiators provided", _truthy(company.get("differentiators")), 3, "Add 3–5 differentiators that match the RFP."))
    checks.append(("Past performance provided", _truthy(company.get("past_performance")), 3, "Add 1–3 past performance bullets."))

    # Draft readiness (25)
    checks.append(("Cover letter generated", _truthy(cover) and len(cover.strip()) > 80, 10, "Generate a cover letter in Draft Proposal."))
    checks.append(("Proposal body generated", _truthy(body) and len(body.strip()) > 200, 15, "Generate a proposal body in Draft Proposal."))

    return checks


def _eligibility_flags(rfp: Dict[str, Any], company: Dict[str, Any]) -> List[str]:
    flags: List[str] = []

    rfp_certs = rfp.get("certifications_required") or []
    company_certs = company.get("certifications") or []

    if rfp_certs and company_certs:
        overlap = {c.lower() for c in company_certs} & {c.lower() for c in rfp_certs}
        if not overlap:
            flags.append("Eligibility warning: RFP mentions certifications that don’t match your selected certifications.")
    elif rfp_certs and not company_certs:
        flags.append("Eligibility warning: RFP mentions certifications, but none are selected in your company profile.")

    return flags


def compute_scores() -> Dict[str, Any]:
    rfp = (st.session_state.get("rfp") or {})
    company = (st.session_state.get("company") or {})

    checklist = _build_checklist(rfp, company)

    earned = sum(weight for _, passed, weight, _ in checklist if passed)
    total = sum(weight for _, _, weight, _ in checklist) or 1
    compliance_pct = int(round((earned / total) * 100))
    grade = _grade_from_pct(compliance_pct)

    # Progress = how many checks passed
    passed_count = sum(1 for _, passed, _, _ in checklist if passed)
    progress_pct = int(round((passed_count / len(checklist)) * 100)) if checklist else 0

    # Win probability = conservative heuristic based on compliance + penalties
    flags = _eligibility_flags(rfp, company)
    win = 10 + int(compliance_pct * 0.7)
    win -= min(20, 8 * len(flags))
    win_probability_pct = max(1, min(95, win))

    diagnostics = {
        "passed": [label for label, passed, _, _ in checklist if passed],
        "missing": [(label, hint) for label, passed, _, hint in checklist if not passed],
        "weights": [{"label": label, "passed": passed, "weight": weight} for label, passed, weight, _ in checklist],
    }

    scores = {
        "progress_pct": progress_pct,
        "compliance_pct": compliance_pct,
        "grade": grade,
        "win_probability_pct": win_probability_pct,
    }

    st.session_state.scores = scores
    st.session_state.eligibility_flags = flags
    st.session_state.diagnostics = diagnostics
    return scores