from typing import Dict, Any, List
from core.openai_client import get_openai_client

MODEL = "gpt-4.1-mini"

def _safe_text(text: str, limit: int = 35_000) -> str:
    if not text:
        return ""
    return text[:limit]

def ai_extract_requirements(rfp_text: str) -> List[Dict[str, Any]]:
    """
    AI extraction into structured requirements for the compatibility matrix.
    """
    client = get_openai_client()
    if client is None:
        return []

    rfp_text = _safe_text(rfp_text)

    prompt = f"""
You are extracting proposal compliance requirements from an RFP.

Return ONLY JSON array. Each item must have:
- requirement_id (string like REQ-001)
- requirement (short clear requirement statement)
- status (default "Not started")
- notes (default "")
- owner (default "")
- evidence (default "")

Extract 20-40 most important requirements.
RFP TEXT:
{rfp_text}
""".strip()

    resp = client.responses.create(
        model=MODEL,
        input=prompt,
    )

    # responses output_text is the safest helper
    raw = getattr(resp, "output_text", None)
    if not raw:
        # fallback: try to pull text chunks
        raw = ""
        try:
            for item in resp.output:
                if getattr(item, "type", "") == "output_text":
                    for c in item.content:
                        if getattr(c, "type", "") == "output_text":
                            raw += c.text
        except Exception:
            pass

    import json
    try:
        data = json.loads(raw)
        # normalize IDs
        out = []
        for i, r in enumerate(data, start=1):
            out.append({
                "requirement_id": r.get("requirement_id") or f"REQ-{i:03d}",
                "requirement": r.get("requirement") or "",
                "status": r.get("status") or "Not started",
                "notes": r.get("notes") or "",
                "owner": r.get("owner") or "",
                "evidence": r.get("evidence") or "",
            })
        return out
    except Exception:
        return []

def ai_draft_sections(rfp_text: str, company: Dict[str, Any]) -> Dict[str, str]:
    """
    Creates outline + narrative draft using RFP + Company info.
    """
    client = get_openai_client()
    if client is None:
        return {"outline": "", "narrative": ""}

    rfp_text = _safe_text(rfp_text)
    company_blob = _safe_text(str(company), 8_000)

    prompt = f"""
You are writing a federal proposal draft. Use the RFP and company profile.

Return ONLY JSON:
{{
  "outline": "...",
  "narrative": "..."
}}

RFP TEXT:
{rfp_text}

COMPANY PROFILE:
{company_blob}
""".strip()

    resp = client.responses.create(model=MODEL, input=prompt)
    raw = getattr(resp, "output_text", "") or ""

    import json
    try:
        obj = json.loads(raw)
        return {"outline": obj.get("outline",""), "narrative": obj.get("narrative","")}
    except Exception:
        # fallback: just dump into narrative
        return {"outline": "", "narrative": raw}

def ai_suggest_fixes(rfp_text: str, draft: Dict[str, Any], company: Dict[str, Any]) -> List[str]:
    """
    Returns bullet suggestions. Used inline (no Fixes tab).
    """
    client = get_openai_client()
    if client is None:
        return []

    rfp_text = _safe_text(rfp_text)
    draft_blob = _safe_text(str(draft), 10_000)
    company_blob = _safe_text(str(company), 8_000)

    prompt = f"""
You are a proposal compliance coach.
Given the RFP, company profile, and current draft, return 8-15 concise fix suggestions as a JSON array of strings.
Focus on missing sections, compliance gaps, eligibility issues, and clarity.

RFP TEXT:
{rfp_text}

COMPANY:
{company_blob}

DRAFT:
{draft_blob}
""".strip()

    resp = client.responses.create(model=MODEL, input=prompt)
    raw = getattr(resp, "output_text", "") or ""

    import json
    try:
        arr = json.loads(raw)
        return [str(x) for x in arr][:20]
    except Exception:
        # fallback: split lines
        return [l.strip("-• ").strip() for l in raw.splitlines() if l.strip()][:20]