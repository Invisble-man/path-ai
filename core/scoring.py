from __future__ import annotations

import re
from typing import Dict, Any, List, Tuple


CERT_ALIASES = {
    # normalize common ways people write certs in RFP text
    "sdvosb": "Service-Disabled Veteran-Owned Small Business (SDVOSB)",
    "vosb": "Veteran-Owned Small Business (VOSB)",
    "wosb": "Women-Owned Small Business (WOSB)",
    "edwosb": "Economically Disadvantaged WOSB (EDWOSB)",
    "hubzone": "HUBZone",
    "8(a)": "8(a)",
    "8a": "8(a)",
}


def _safe_lower(s: str) -> str:
    return (s or "").lower()


def _pct(numer: float, denom: float) -> float:
    if denom <= 0:
        return 0.0
    return max(0.0, min(100.0, (numer / denom) * 100.0))


def _has_any_company_data(company: Dict[str, Any]) -> bool:
    if not company:
        return False
    for k, v in company.items():
        if v not in (None, "", [], {}):
            return True
    return False


def _company_completeness(company: Dict[str, Any]) -> Tuple[float, List[str]]:
    """
    Returns (% complete, missing_fields list)
    """
    required = [
        ("legal_name", "Legal company name"),
        ("uei", "UEI"),
        ("address", "Street address"),
        ("city", "City"),
        ("state", "State"),
        ("zip", "ZIP"),
        ("website", "Website"),
        ("phone", "Main phone"),
        ("email", "Main email"),
        ("poc_name", "POC name"),
        ("poc_title", "POC title"),
        ("poc_email", "POC email"),
        ("poc_phone", "POC phone"),
        ("naics", "Primary NAICS"),
        ("capability_summary", "Capability summary"),
        ("past_performance", "Past performance"),
    ]
    total = len(required)
    missing = []
    have = 0
    for key, label in required:
        if str(company.get(key, "")).strip():
            have += 1
        else:
            missing.append(label)

    return _pct(have, total), missing


def _rfp_readiness(ss) -> Tuple[float, List[str]]:
    """
    Returns (% complete, missing list)
    """
    missing = []
    text_ok = bool(ss.get("rfp_text"))
    if not text_ok:
        missing.append("RFP text (upload and analyze)")

    pages_ok = (ss.get("rfp_pages") or 0) > 0
    if not pages_ok:
        missing.append("RFP page count")

    meta = ss.get("rfp_meta", {}) or {}
    if not str(meta.get("title", "")).strip():
        missing.append("Opportunity title")
    if not str(meta.get("solicitation", "")).strip():
        missing.append("Solicitation number")
    if not str(meta.get("due_date", "")).strip():
        missing.append("Due date")
    if not str(meta.get("submit_email", "")).strip():
        missing.append("Submission email")

    total_checks = 1 + 1 + 4
    have = 0
    have += 1 if text_ok else 0
    have += 1 if pages_ok else 0
    have += 1 if str(meta.get("title", "")).strip() else 0
    have += 1 if str(meta.get("solicitation", "")).strip() else 0
    have += 1 if str(meta.get("due_date", "")).strip() else 0
    have += 1 if str(meta.get("submit_email", "")).strip() else 0

    return _pct(have, total_checks), missing


def _draft_completeness(draft: Dict[str, Any]) -> Tuple[float, List[str]]:
    """
    Draft is considered complete-ish when cover info + outline + narrative exist.
    """
    missing = []
    checks = [
        ("cover_title", "Cover title"),
        ("cover_contract", "Contract/opportunity name"),
        ("cover_solicitation", "Solicitation #"),
        ("cover_agency", "Agency"),
        ("cover_due_date", "Due date"),
        ("outline", "Outline"),
        ("narrative", "Narrative body"),
    ]
    total = len(checks)
    have = 0
    for k, label in checks:
        if str(draft.get(k, "")).strip():
            have += 1
        else:
            missing.append(label)

    return _pct(have, total), missing


def _requirements_health(reqs: List[Dict[str, Any]]) -> Tuple[float, Dict[str, int]]:
    """
    Scores how "worked" the requirements are.
    - Not started = 0 points
    - In progress = 1 point
    - Complete = 2 points
    """
    if not reqs:
        return 0.0, {"total": 0, "not_started": 0, "in_progress": 0, "complete": 0}

    scoring = {"not started": 0, "not_started": 0, "in progress": 1, "in_progress": 1, "complete": 2, "done": 2}
    total = len(reqs)
    points = 0
    counts = {"total": total, "not_started": 0, "in_progress": 0, "complete": 0}

    for r in reqs:
        status = _safe_lower(r.get("status", "not started")).strip()
        if "complete" in status or "done" in status:
            counts["complete"] += 1
            points += 2
        elif "progress" in status:
            counts["in_progress"] += 1
            points += 1
        else:
            counts["not_started"] += 1
            points += 0

    # max points = total * 2
    pct = _pct(points, total * 2)
    return pct, counts


def _detect_required_certs_from_rfp(text: str) -> List[str]:
    """
    Heuristic: look for SDVOSB / HUBZone / 8(a) etc in RFP text.
    We only use this for WARNINGS (not hard blocking).
    """
    t = _safe_lower(text)
    found = set()

    # direct hits
    if "service-disabled veteran-owned" in t or "sdvosb" in t:
        found.add(CERT_ALIASES["sdvosb"])
    if "veteran-owned" in t or re.search(r"\bvosb\b", t):
        found.add(CERT_ALIASES["vosb"])
    if "hubzone" in t:
        found.add(CERT_ALIASES["hubzone"])
    if "wosb" in t or "women-owned" in t:
        found.add(CERT_ALIASES["wosb"])
    if "edwosb" in t:
        found.add(CERT_ALIASES["edwosb"])
    if "8(a)" in t or re.search(r"\b8a\b", t):
        found.add(CERT_ALIASES["8(a)"])

    return sorted(found)


def _eligibility_warnings(ss) -> List[str]:
    """
    Generates warnings like:
    - RFP references SDVOSB set-aside but company certs don't include SDVOSB
    - SAM not active
    """
    warnings = []
    company = ss.get("company", {}) or {}
    rfp_text = ss.get("rfp_text", "") or ""

    certs_have = set(company.get("certifications") or [])
    certs_required = _detect_required_certs_from_rfp(rfp_text)

    for req in certs_required:
        if req not in certs_have:
            warnings.append(
                f"Eligibility risk: RFP appears to reference **{req}**, but your Company Info does not include it."
            )

    sam = (company.get("sam_status") or "").strip().lower()
    if sam and sam != "active":
        warnings.append("Eligibility risk: SAM status is not Active (Company Info → SAM Status).")

    return warnings


def compute_scores(ss) -> Dict[str, Any]:
    """
    Master scoring engine powering:
    - compliance %
    - win strength %
    - overall progress %
    - step colors (green/orange/red)
    - warnings + missing fields lists

    Export is ALWAYS unlocked (per your requirement).
    Draft generation can be recommended at >=60% overall, but not gated here.
    """
    # --- Section completeness ---
    rfp_pct, rfp_missing = _rfp_readiness(ss)
    company_pct, company_missing = _company_completeness(ss.get("company", {}) or {})
    draft_pct, draft_missing = _draft_completeness(ss.get("draft", {}) or {})
    reqs_pct, req_counts = _requirements_health(ss.get("requirements") or [])

    # --- Compliance: weighted toward RFP + requirements ---
    compliance_pct = (
        (rfp_pct * 0.30) +
        (reqs_pct * 0.35) +
        (company_pct * 0.20) +
        (draft_pct * 0.15)
    )

    # --- Win strength: compliance + quality signals ---
    quality_bonus = 0.0

    # More requirements worked = stronger
    if req_counts["total"] >= 20 and req_counts["complete"] >= 5:
        quality_bonus += 5.0
    if req_counts["complete"] >= max(3, int(0.25 * max(1, req_counts["total"]))):
        quality_bonus += 7.0

    # If company has a strong capability summary and past performance, bump
    company = ss.get("company", {}) or {}
    if len((company.get("capability_summary") or "").strip()) >= 250:
        quality_bonus += 4.0
    if len((company.get("past_performance") or "").strip()) >= 200:
        quality_bonus += 4.0

    # AI enabled can help execution speed, slight bump
    if ss.get("ai_enabled"):
        quality_bonus += 2.0

    # Eligibility warnings reduce win strength (not compliance)
    warnings = _eligibility_warnings(ss)
    penalty = min(20.0, 6.0 * len(warnings))

    win_strength_pct = max(1.0, min(100.0, compliance_pct + quality_bonus - penalty))

    # --- Overall progress: user experience progress ---
    overall_progress_pct = (
        (rfp_pct * 0.25) +
        (company_pct * 0.25) +
        (draft_pct * 0.25) +
        (reqs_pct * 0.25)
    )

    # --- Step statuses for sidebar “path” ---
    def step_color(pct: float, started: bool) -> str:
        if pct >= 90:
            return "green"
        if started:
            return "orange"
        return "red"

    # started flags
    rfp_started = bool(ss.get("rfp_text"))
    company_started = _has_any_company_data(company)
    draft_started = bool((ss.get("draft", {}) or {}).get("outline") or (ss.get("draft", {}) or {}).get("narrative"))
    reqs_started = bool(ss.get("requirements"))

    steps = {
        "home": {"pct": rfp_pct, "color": step_color(rfp_pct, rfp_started)},
        "company": {"pct": company_pct, "color": step_color(company_pct, company_started)},
        "draft": {"pct": draft_pct, "color": step_color(draft_pct, draft_started)},
        "requirements": {"pct": reqs_pct, "color": step_color(reqs_pct, reqs_started)},
        # Export ALWAYS “available”, so keep it orange/green based on readiness, but never block UI.
        "export": {"pct": min(100.0, (rfp_pct + company_pct + draft_pct) / 3.0), "color": "orange" if overall_progress_pct < 90 else "green"},
    }

    return {
        "rfp": {"pct": rfp_pct, "missing": rfp_missing},
        "company": {"pct": company_pct, "missing": company_missing},
        "draft": {"pct": draft_pct, "missing": draft_missing},
        "requirements": {"pct": reqs_pct, "counts": req_counts},
        "compliance_pct": float(max(0.0, min(100.0, compliance_pct))),
        "win_strength_pct": float(win_strength_pct),
        "overall_progress_pct": float(max(0.0, min(100.0, overall_progress_pct))),
        "warnings": warnings,
        "steps": steps,
        # convenience flags
        "recommended_to_generate_draft": overall_progress_pct >= 60.0,
    }