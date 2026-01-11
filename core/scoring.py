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


def compute_compliance_pct(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    score = 0.0
    for row in rows:
        status = _normalize_status(row.get("status", "missing"))
        if status == "met":
            score += 1.0
        elif status == "partial":
            score += 0.5
    pct = int(round((score / max(1, len(rows))) * 100))
    return max(0, min(100, pct))


def grade_from_pct(pct: int) -> str:
    if pct >= 90:
        return "A"
    if pct >= 80:
        return "B"
    if pct >= 70:
        return "C"
    if pct >= 60:
        return "D"
    return "F"


def compute_eligibility_flags(rfp: Dict[str, Any], company: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    rfp_certs = rfp.get("certifications_required") or []
    company_certs = company.get("certifications") or []

    if rfp_certs:
        overlap = {c.lower() for c in company_certs} & {c.lower() for c in rfp_certs}
        if not overlap:
            flags.append("Eligibility warning: RFP mentions certifications; your profile doesn’t show a matching certification.")

    if not (company.get("uei") or company.get("cage")):
        flags.append("Company profile warning: UEI or CAGE is missing (not blocking).")

    if not company.get("name"):
        flags.append("Company profile warning: Company name is missing (not blocking).")

    return flags


def build_diagnostics(rfp: Dict[str, Any], company: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    issues: List[str] = []
    wins: List[str] = []

    # RFP diagnostics
    if rfp.get("filename"):
        wins.append("RFP uploaded.")
    else:
        issues.append("Upload an RFP PDF.")

    if (rfp.get("text") or "").strip():
        wins.append("RFP text extracted.")
    else:
        issues.append("RFP text extraction failed (scanned/protected PDF or parsing issue).")

    if rfp.get("due_date"):
        wins.append("Due date detected.")
    else:
        issues.append("Due date not detected (you can still proceed).")

    if rfp.get("submission_email"):
        wins.append("Submission email detected.")
    else:
        issues.append("Submission email not detected (you can still proceed).")

    # Company diagnostics
    if company.get("name"):
        wins.append("Company name provided.")
    else:
        issues.append("Add company name for maximum accuracy.")

    if company.get("uei") or company.get("cage"):
        wins.append("UEI/CAGE provided.")
    else:
        issues.append("Add UEI or CAGE for a complete cover page (not blocking).")

    # Compatibility diagnostics
    if rows:
        wins.append(f"Compatibility Matrix created ({len(rows)} rows).")
        missing = sum(1 for r in rows if (r.get("status","").lower() == "missing"))
        if missing > 0:
            issues.append(f"{missing} requirements are still marked Missing in the Compatibility Matrix.")
    else:
        issues.append("Generate or add requirements to the Compatibility Matrix to increase compliance.")

    return {"wins": wins, "issues": issues}


def compute_win_probability_pct(compliance_pct: int, completion_pct: int, eligibility_flags: List[str]) -> int:
    base = 10
    base += int(compliance_pct * 0.55)
    base += int(completion_pct * 0.25)
    if eligibility_flags:
        base -= min(20, 8 * len(eligibility_flags))
    return max(1, min(95, base))


def compute_all_scores() -> Dict[str, Any]:
    rfp = st.session_state.get("rfp", {}) or {}
    company = st.session_state.get("company", {}) or {}
    rows = st.session_state.get("compatibility_rows", []) or []

    completion_pct = compute_completion_pct()
    compliance_pct = compute_compliance_pct(rows)
    eligibility_flags = compute_eligibility_flags(rfp, company)
    win_probability_pct = compute_win_probability_pct(compliance_pct, completion_pct, eligibility_flags)

    grade = grade_from_pct(compliance_pct)
    diagnostics = build_diagnostics(rfp, company, rows)

    scores = {
        "completion_pct": completion_pct,
        "compliance_pct": compliance_pct,
        "win_probability_pct": win_probability_pct,
        "grade": grade,
    }
    st.session_state.scores = scores
    st.session_state.eligibility_flags = eligibility_flags
    st.session_state.diagnostics = diagnostics
    return scores