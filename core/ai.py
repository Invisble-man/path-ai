from __future__ import annotations

from typing import Dict, Any

from core.openai_client import get_client


def draft_sections_with_ai(rfp_text: str, company: Dict[str, Any]) -> Dict[str, str]:
    """
    Returns dict with: cover, outline, narrative
    """
    client = get_client()
    if client is None:
        return {"cover": "", "outline": "", "narrative": ""}

    company_block = "\n".join(
        [
            f"Legal name: {company.get('legal_name','')}",
            f"DBA: {company.get('dba','')}",
            f"UEI: {company.get('uei','')}",
            f"CAGE: {company.get('cage','')}",
            f"NAICS: {company.get('naics','')}",
            f"Certifications: {', '.join(company.get('certifications', []) or [])}",
            f"Capabilities: {company.get('capabilities','')}",
            f"Past performance: {company.get('past_performance','')}",
            f"Differentiators: {company.get('differentiators','')}",
        ]
    ).strip()

    prompt = f"""
You are an expert federal proposal writer.

Use the RFP text + company info to produce:
1) Cover Letter (1 page max, professional)
2) Proposal Outline (section headings only)
3) Draft Narrative (starter, structured, compliant tone)

RFP TEXT (trimmed):
{rfp_text[:18000]}

COMPANY INFO:
{company_block}
""".strip()

    # Use Chat Completions (most stable)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Write in a clean, federal-compliant proposal style. Be specific. No fluff."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    text = resp.choices[0].message.content or ""

    # Simple split markers (you can improve later)
    cover = ""
    outline = ""
    narrative = ""

    lower = text.lower()
    if "cover letter" in lower and "proposal outline" in lower and "draft narrative" in lower:
        # naive parsing by headings
        def chunk(after: str, before: str) -> str:
            a = lower.find(after)
            b = lower.find(before)
            if a == -1:
                return ""
            a2 = a + len(after)
            if b == -1 or b <= a2:
                return text[a2:].strip()
            return text[a2:b].strip()

        cover = chunk("cover letter", "proposal outline")
        outline = chunk("proposal outline", "draft narrative")
        narrative = chunk("draft narrative", "end")
    else:
        # fallback: dump all into narrative
        narrative = text.strip()

    return {"cover": cover.strip(), "outline": outline.strip(), "narrative": narrative.strip()}