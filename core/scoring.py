from __future__ import annotations

from typing import Dict, List, Tuple

from core.state import get_company, get_rfp


def _grade(pct: int) -> str:
    if pct >= 95:
        return "A+"
    if pct >= 90:
        return "A"
    if pct >= 85:
        return "A-"
    if pct >= 80:
        return "B+"
    if pct >= 75:
        return "B"
    if pct >= 70:
        return "B-"
    if pct >= 65:
        return "C+"
    if pct >= 60:
        return "C"
    if pct >= 50:
        return "D"
    return "F"


def _clamp(x: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(x)))


def compute_scores() -> Dict[str, object]:
    """
    Returns:
      compliance_pct (0-100)
      compliance_grade (A-F)
      win_probability_pct (0-100)
      progress_pct (0-100)
      diagnostics {counts, evaluator_items}
      eligibility {is_eligible, reasons[]}
    """
    rfp = get_rfp()
    company = get_company()

    # --- Progress heuristic (sell-ready: simple, consistent)
    progress = 0
    if rfp.filename:
        progress += 20
    if rfp.extracted and (rfp.text or "").strip():
        progress += 25
    if (company.name or "").strip():
        progress += 15
    if (company.uei or "").strip() or (company.cage or "").strip():
        progress += 10
    if (company.past_performance or "").strip():
        progress += 15
    if (company.differentiators or "").strip():
        progress += 15
    progress_pct = _clamp(progress)

    # --- Compliance checklist (evaluator-style)
    items: List[Dict[str, str]] = []

    def add(label: str, ok: bool, hint_ok: str, hint_bad: str) -> None:
        items.append(
            {
                "status": "green" if ok else "red",
                "label": label,
                "hint": hint_ok if ok else hint_bad,
            }
        )

    def add_yellow(label: str, hint: str) -> None:
        items.append({"status": "yellow", "label": label, "hint": hint})

    # RFP extraction
    has_text = bool(rfp.extracted and (rfp.text or "").strip())
    add(
        "RFP text extracted",
        has_text,
        "RFP text is available for tailoring and diagnostics.",
        "RFP text is missing. Try a different PDF or use the paste-text fallback on Upload.",
    )

    # Page count
    add(
        "Page count detected",
        rfp.pages > 0,
        f"Detected {rfp.pages} pages.",
        "Page count is 0. Upload failed or PDF could not be read.",
    )

    # Due date & submission method
    if (rfp.due_date or "").strip():
        add("Due date detected", True, f"Due date found: {rfp.due_date}", "")
    else:
        add_yellow("Due date missing", "No due date detected. Add it manually in Draft if needed.")

    if (rfp.submission_email or "").strip():
        add("Submission method detected", True, f"Submission email found: {rfp.submission_email}", "")
    else:
        add_yellow("Submission email missing", "No submission email detected. Confirm in the RFP.")

    # Company basics
    add(
        "Company name entered",
        bool((company.name or "").strip()),
        "Company name set. Branding and tailoring will be more accurate.",
        "Enter your company info for maximum accuracy.",
    )
    add(
        "UEI or CAGE entered",
        bool((company.uei or "").strip() or (company.cage or "").strip()),
        "UEI/CAGE present.",
        "UEI/CAGE missing. Add at least one for evaluator confidence.",
    )
    add(
        "Past performance entered",
        bool((company.past_performance or "").strip()),
        "Past performance present.",
        "Past performance missing. This usually lowers evaluator confidence.",
    )
    add(
        "Differentiators entered",
        bool((company.differentiators or "").strip()),
        "Differentiators present.",
        "Differentiators missing. Add specific value props and proof.",
    )

    # Certifications alignment (soft eligibility)
    required = [c.upper() for c in (rfp.certifications_required or [])]
    have = [c.upper() for c in (company.certifications or [])]
    missing_required = [c for c in required if c not in have]

    # Eligibility logic: warn, don’t block
    reasons = []
    is_eligible = True
    if required and missing_required:
        is_eligible = False
        reasons.append(f"RFP references certifications you did not select: {', '.join(missing_required)}")

    # NAICS soft check
    if (rfp.naics or "").strip() and (company.naics or "").strip():
        if rfp.naics.strip() != company.naics.strip():
            reasons.append(f"NAICS mismatch (RFP: {rfp.naics}, Company: {company.naics})")
            # Do not hard fail; many primes/subs still bid
            is_eligible = False

    if required and not missing_required:
        add("Certification alignment", True, "Certifications appear aligned.", "")
    elif required and missing_required:
        add_yellow("Certification alignment", f"Missing: {', '.join(missing_required)} (warning, not a block).")
    else:
        add_yellow("Certifications not detected", "No certification requirements detected in the RFP text sample.")

    # --- Compute compliance %
    green = sum(1 for it in items if it["status"] == "green")
    yellow = sum(1 for it in items if it["status"] == "yellow")
    red = sum(1 for it in items if it["status"] == "red")

    total = max(1, len(items))
    compliance_pct = _clamp(int((green / total) * 100))

    # --- Win probability heuristic (sell-ready: interpretable)
    # Start from compliance and adjust
    win = compliance_pct
    if not is_eligible:
        win -= 18
    if (company.past_performance or "").strip():
        win += 7
    if (company.differentiators or "").strip():
        win += 5
    if has_text:
        win += 3
    win_probability_pct = _clamp(win)

    return {
        "progress_pct": progress_pct,
        "compliance_pct": compliance_pct,
        "compliance_grade": _grade(compliance_pct),
        "win_probability_pct": win_probability_pct,
        "diagnostics": {
            "counts": {"green": green, "yellow": yellow, "red": red},
            "evaluator_items": items,
        },
        "eligibility": {"is_eligible": is_eligible, "reasons": reasons},
    }