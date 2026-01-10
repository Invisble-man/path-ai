from __future__ import annotations

import re
from typing import Dict, Any, List


CERT_KEYWORDS = {
    "SDVOSB": ["service-disabled veteran", "sdvosb"],
    "VOSB": ["veteran-owned", "vosb"],
    "WOSB": ["women-owned", "wosb"],
    "EDWOSB": ["economically disadvantaged women-owned", "edwosb"],
    "8(a)": ["8(a)", "eight(a)"],
    "HUBZone": ["hubzone", "historically underutilized business zone"],
    "SDB": ["small disadvantaged business", "sdb"],
}


def _simple_requirements_from_text(text: str) -> List[Dict[str, str]]:
    """
    Lightweight extraction to avoid memory blowups.
    You can replace later with AI extraction.
    """
    reqs = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines[:2500]):  # cap
        if re.search(r"\bshall\b|\bmust\b|\brequired\b", line, re.I):
            reqs.append(
                {
                    "requirement_id": f"REQ-{len(reqs)+1:03d}",
                    "requirement": line[:400],
                    "status": "Unknown",
                    "notes": "",
                }
            )
        if len(reqs) >= 120:
            break
    return reqs


def _find_due_date(text: str) -> str:
    # super basic pattern
    m = re.search(r"(due|deadline)\s*[:\-]?\s*(.+)", text, re.I)
    if not m:
        return ""
    return m.group(2)[:80].strip()


def _find_submit_email(text: str) -> str:
    m = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)
    return m.group(0) if m else ""


def analyze_rfp(text: str, company: Dict[str, Any]) -> Dict[str, Any]:
    reqs = _simple_requirements_from_text(text)
    due_date = _find_due_date(text)
    submit_email = _find_submit_email(text)

    # Eligibility check: if RFP mentions a cert but company doesn't have it
    company_certs = set(company.get("certifications", []) or [])
    warnings = []
    for cert, keywords in CERT_KEYWORDS.items():
        if any(k.lower() in text.lower() for k in keywords):
            if cert not in company_certs:
                warnings.append(f"RFP references {cert}, but your Company Info does not include it.")
    eligibility_ok = len(warnings) == 0

    # Scores (starter heuristic)
    company_score = 0
    if company.get("legal_name"): company_score += 15
    if company.get("uei") or company.get("duns"): company_score += 10
    if company.get("cage"): company_score += 10
    if company.get("naics"): company_score += 10
    if company.get("address"): company_score += 10
    if company.get("capabilities"): company_score += 10
    if company.get("past_performance"): company_score += 15
    if company.get("certifications"): company_score += 10

    compliance_score = 0 if not reqs else min(100, int(20 + (len(reqs) / 120) * 80))
    win_score = 35
    if eligibility_ok:
        win_score += 10
    if company_score >= 60:
        win_score += 10
    win_score = min(100, win_score)

    overall = int((0.45 * compliance_score) + (0.35 * company_score) + (0.20 * win_score))

    suggestions = []
    if company_score < 60:
        suggestions.append("Add stronger Company Info (capabilities, past performance, differentiators).")
    if not eligibility_ok:
        suggestions.append("Eligibility warning: add required certifications or proceed with caution.")
    if compliance_score < 60:
        suggestions.append("Run AI extraction (or refine the RFP text) to capture more requirements.")

    return {
        "requirements": reqs,
        "compat_rows": reqs,  # same shape for XLSX export
        "diagnostics": {"due_date": due_date, "submit_email": submit_email, "notes": ""},
        "scores": {"compliance": compliance_score, "company": company_score, "win": win_score, "overall": overall},
        "suggestions": suggestions,
        "eligibility": {"ok": eligibility_ok, "warnings": warnings},
    }