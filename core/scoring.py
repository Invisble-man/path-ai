from typing import Dict, Any

def compute_progress(ss) -> Dict[str, Any]:
    rfp_ok = bool(ss.get("rfp_text"))
    company = ss.get("company", {})
    company_ok = bool(company.get("legal_name")) and bool(company.get("poc_email") or company.get("email"))
    draft = ss.get("draft", {})
    draft_ok = bool(draft.get("narrative")) or bool(draft.get("outline"))

    # simple scoring (you can upgrade later)
    compliance_pct = 0
    if rfp_ok:
        compliance_pct += 25
    if company_ok:
        compliance_pct += 25
    if draft_ok:
        compliance_pct += 25
    if ss.get("requirements"):
        compliance_pct +=
