from __future__ import annotations

import os
from typing import Optional, Dict, Any

from tenacity import retry, stop_after_attempt, wait_exponential


def has_openai_key() -> bool:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return bool(key)


def _safe_trim(text: str, max_chars: int = 14000) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[TRUNCATED]"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=6))
def _call_openai(prompt: str, system: str = "") -> str:
    """
    Uses OpenAI if available. Designed to fail gracefully.
    NOTE: We keep imports inside to prevent import errors / optional dependency issues.
    """
    if not has_openai_key():
        raise RuntimeError("OPENAI_API_KEY not set.")

    from openai import OpenAI  # local import to avoid hard crash if package/version mismatch

    client = OpenAI()

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()


def generate_proposal_draft(
    rfp_text: str,
    company: Dict[str, Any],
    max_chars: int = 14000,
) -> Dict[str, str]:
    """
    Returns a dict with keys: cover_letter, proposal_body.
    If no key, returns a solid non-AI fallback template.
    """
    rfp_text = _safe_trim(rfp_text, max_chars=max_chars)

    company_name = (company.get("name") or "").strip() or "YOUR COMPANY"
    uei = (company.get("uei") or "").strip()
    cage = (company.get("cage") or "").strip()
    address = (company.get("address") or "").strip()
    naics = (company.get("naics") or "").strip()
    certs = company.get("certifications") or []
    differentiators = (company.get("differentiators") or "").strip()
    past_perf = (company.get("past_performance") or "").strip()

    # Fallback draft (works without AI)
    fallback_cover = f"""[COVER LETTER]

{company_name}
{address}

Subject: Proposal Submission – Response to Solicitation

Dear Contracting Officer,

{company_name} is pleased to submit this proposal in response to the referenced solicitation. Our team is prepared to deliver high-quality outcomes while meeting all schedule, compliance, and reporting requirements.

Company Identifiers:
- UEI: {uei or "N/A"}
- CAGE: {cage or "N/A"}
- NAICS: {naics or "N/A"}
- Certifications: {", ".join(certs) if certs else "N/A"}

We appreciate the opportunity to compete and look forward to supporting your mission.

Respectfully,
{company_name}
"""

    fallback_body = f"""[PROPOSAL BODY]

1. Executive Summary
{company_name} will deliver the required scope with disciplined execution, clear communication, and measurable outcomes.

2. Understanding of Requirements
We reviewed the solicitation and will address all requirements, deliverables, and submission instructions.

3. Technical Approach
- Delivery plan aligned to the statement of work
- Quality control checkpoints
- Risk management and mitigation

4. Management Plan
- Dedicated program leadership
- Clear roles and responsibilities
- Weekly status reporting and milestone tracking

5. Differentiators
{differentiators or "- Veteran-led execution\n- Compliance-first documentation\n- Fast turnaround with strong QA"}

6. Past Performance
{past_perf or "Relevant past performance available upon request; references can be provided."}

7. Compliance & Attachments
We will submit all required forms, representations, and certifications as specified.
"""

    # If no AI key, return fallback immediately
    if not has_openai_key():
        return {"cover_letter": fallback_cover, "proposal_body": fallback_body}

    system = (
        "You are an expert federal proposal writer. "
        "Write clear, compliant, professional text. "
        "Avoid fluff. Use headings and bullet points. "
        "Do NOT invent certifications or past performance—use what's provided."
    )

    prompt = f"""
Company info:
- Name: {company_name}
- UEI: {uei or "N/A"}
- CAGE: {cage or "N/A"}
- Address: {address or "N/A"}
- NAICS: {naics or "N/A"}
- Certifications: {", ".join(certs) if certs else "N/A"}
- Differentiators: {differentiators or "N/A"}
- Past performance: {past_perf or "N/A"}

RFP text (may be truncated):
{rfp_text}

Task:
1) Create a one-page cover letter tailored to this RFP.
2) Create a proposal body that includes: Executive Summary, Understanding of Requirements, Technical Approach, Management Plan, Staffing, Quality Control, Risk Management, Past Performance, and Compliance.
Return ONLY two sections with labels:
[COVER LETTER]
...
[PROPOSAL BODY]
...
""".strip()

    try:
        text = _call_openai(prompt, system=system)
        # Split into sections if possible
        cover = fallback_cover
        body = fallback_body

        if "[COVER LETTER]" in text and "[PROPOSAL BODY]" in text:
            cover = text.split("[PROPOSAL BODY]")[0].replace("[COVER LETTER]", "").strip()
            body = text.split("[PROPOSAL BODY]")[1].strip()
            cover = "[COVER LETTER]\n\n" + cover
            body = "[PROPOSAL BODY]\n\n" + body
        else:
            # If model didn't follow format, just put it in body
            body = "[PROPOSAL BODY]\n\n" + text

        return {"cover_letter": cover, "proposal_body": body}
    except Exception:
        # AI failed: fall back safely
        return {"cover_letter": fallback_cover, "proposal_body": fallback_body}