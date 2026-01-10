from __future__ import annotations
from io import BytesIO
from typing import Dict, Optional
from docx import Document
from docx.shared import Inches


def build_proposal_docx(company: Dict, draft: Dict) -> bytes:
    doc = Document()

    cp = draft.get("cover_page", {})
    logo_bytes: Optional[bytes] = company.get("logo_bytes")

    # --- Cover Page ---
    if logo_bytes:
        try:
            doc.add_picture(BytesIO(logo_bytes), width=Inches(1.6))
        except Exception:
            pass

    doc.add_heading(cp.get("contract_title") or "Proposal", level=0)
    doc.add_paragraph(f"Solicitation: {cp.get('solicitation_number','')}")
    doc.add_paragraph(f"Agency: {cp.get('agency','')}")
    doc.add_paragraph(f"Due Date: {cp.get('due_date','')}")
    doc.add_paragraph("")
    doc.add_paragraph(f"Offeror: {cp.get('offeror_name','')}")
    doc.add_paragraph(f"POC: {cp.get('poc_name','')} • {cp.get('poc_email','')} • {cp.get('poc_phone','')}")
    doc.add_page_break()

    # --- Cover Letter ---
    doc.add_heading("Cover Letter", level=1)
    doc.add_paragraph(draft.get("cover_letter", "") or "")
    doc.add_page_break()

    # --- Proposal Body ---
    doc.add_heading("Outline", level=1)
    doc.add_paragraph(draft.get("outline", "") or "")

    doc.add_heading("Narrative", level=1)
    doc.add_paragraph(draft.get("narrative", "") or "")

    doc.add_heading("AI Recommendations / Fixes", level=1)
    doc.add_paragraph(draft.get("notes", "") or "")

    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()