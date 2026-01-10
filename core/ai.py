from __future__ import annotations
import os
import json
from typing import Optional, Dict, Any
from openai import OpenAI


def get_client() -> Optional[OpenAI]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    return OpenAI(api_key=key)


def ai_build_draft_package(rfp_text: str, rfp_meta: Dict[str, Any], company: Dict[str, Any]) -> Dict[str, Any]:
    client = get_client()
    if not client:
        raise RuntimeError("OPENAI_API_KEY is missing on the server.")

    payload = {
        "rfp_meta": rfp_meta,
        "company": {
            "legal_name": company.get("legal_name", ""),
            "uei": company.get("uei", ""),
            "cage": company.get("cage", ""),
            "address": f"{company.get('address_line1','')} {company.get('city','')}, {company.get('state','')} {company.get('zip','')}",
            "poc_name": company.get("primary_poc_name", ""),
            "poc_email": company.get("primary_poc_email", ""),
            "poc_phone": company.get("primary_poc_phone", ""),
            "certifications": company.get("certifications", []),
            "capability_statement": company.get("capability_statement", ""),
        },
        "rfp_text_excerpt": rfp_text[:14000],
    }

    prompt = f"""
You are a federal proposal writer.
Using the RFP meta + company info, generate a JSON object with:
- cover_page fields (contract_title, solicitation_number, agency, due_date, offeror_name, poc_name, poc_email, poc_phone)
- cover_letter (1 page, professional, compliant tone)
- outline (clear proposal outline headings)

Return ONLY valid JSON.
INPUT:
{json.dumps(payload, ensure_ascii=False)}
"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Return only JSON. No markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    text = resp.choices[0].message.content.strip()
    try:
        return json.loads(text)
    except Exception:
        # If the model returns slightly messy output, attempt salvage
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
        raise RuntimeError("AI returned non-JSON output.")


def ai_recommend_fixes(rfp_text: str, matrix: list, draft_text: str) -> str:
    client = get_client()
    if not client:
        raise RuntimeError("OPENAI_API_KEY is missing on the server.")

    prompt = f"""
You are a compliance reviewer.
Given the RFP and current draft, provide the top missing items and fixes.
Keep it tight. Bullet list. Include exact missing info.

RFP (excerpt):
{rfp_text[:12000]}

MATRIX (first 35 rows):
{json.dumps(matrix[:35], ensure_ascii=False)}

DRAFT (excerpt):
{draft_text[:12000]}
"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()