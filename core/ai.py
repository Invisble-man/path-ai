from __future__ import annotations

import os
from typing import Any, Dict


def ai_enabled() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


def _model() -> str:
    return (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()


def _local_cleanup(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    out = []
    blank = 0
    for ln in lines:
        if ln.strip() == "":
            blank += 1
            if blank <= 1:
                out.append("")
        else:
            blank = 0
            out.append(ln)
    return "\n".join(out).strip()


def _call_openai(messages: list[dict], temperature: float = 0.2) -> str:
    api_key = os.getenv("OPENAI_API_KEY") or ""
    model = _model()

    try:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        import openai  # type: ignore

        openai.api_key = api_key
        resp = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return (resp["choices"][0]["message"]["content"] or "").strip()


def polish_for_submission(
    *,
    rfp_text: str,
    company: Dict[str, Any],
    cover_letter: str,
    proposal_body: str,
) -> Dict[str, str]:
    cover_letter = cover_letter or ""
    proposal_body = proposal_body or ""

    if not ai_enabled():
        qa = []
        if not (rfp_text or "").strip():
            qa.append("- RFP text is empty; tailoring will be limited.")
        if not (company.get("name") or "").strip():
            qa.append("- Company name missing; enter company info for maximum accuracy.")
        if len((proposal_body or "").strip()) < 200:
            qa.append("- Proposal body is short; generate more content before export.")
        return {
            "polished_cover_letter": _local_cleanup(cover_letter),
            "polished_proposal_body": _local_cleanup(proposal_body),
            "qa_findings": "\n".join(qa) if qa else "AI not enabled. Basic cleanup applied.",
        }

    company_block = f"""
Company Info (source of truth):
- Name: {company.get("name","")}
- UEI: {company.get("uei","")}
- CAGE: {company.get("cage","")}
- Address: {company.get("address","")}
- NAICS: {company.get("naics","")}
- Certifications: {", ".join(company.get("certifications") or [])}
- Differentiators: {company.get("differentiators","")}
- Past Performance: {company.get("past_performance","")}
""".strip()

    system = (
        "You are a federal proposal editor. Improve grammar and formatting and align to the solicitation. "
        "Use clear headings, bullets, short paragraphs, and a crisp federal tone. "
        "Do NOT invent certifications, past performance, contract numbers, dates, or compliance claims. "
        "If something is missing, insert a bracket placeholder like [ADD UEI]."
    )

    user = f"""
SOLICITATION TEXT (partial sample):
{(rfp_text or "")[:14000]}

{company_block}

CURRENT COVER LETTER:
{(cover_letter or "")[:7000]}

CURRENT PROPOSAL BODY:
{(proposal_body or "")[:14000]}

OUTPUT FORMAT (STRICT):
<COVER_LETTER>
...
</COVER_LETTER>

<PROPOSAL_BODY>
...
</PROPOSAL_BODY>

<QA_FINDINGS>
- ...
</QA_FINDINGS>
""".strip()

    text = _call_openai(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
    )

    def _extract(tag: str) -> str:
        s = f"<{tag}>"
        e = f"</{tag}>"
        if s in text and e in text:
            return text.split(s, 1)[1].split(e, 1)[0].strip()
        return ""

    return {
        "polished_cover_letter": _extract("COVER_LETTER") or cover_letter,
        "polished_proposal_body": _extract("PROPOSAL_BODY") or proposal_body,
        "qa_findings": _extract("QA_FINDINGS") or "QA not returned.",
    }