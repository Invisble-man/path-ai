from __future__ import annotations

from io import BytesIO
from typing import Dict, Any, List

from docx import Document
from docx.shared import Inches


def build_docx(
    rfp: Dict[str, Any],
    company: Dict[str, Any],
    draft_cover_letter: str,
    draft_body: str,
    compatibility_rows: List[Dict[str, Any]],
) -> bytes:
    doc = Document()

    # Cover page (simple, professional)
    doc.add_heading(company.get("name") or "Proposal", level=0)

    # Logo if present
    logo_bytes = company.get("logo_bytes", None)
    if logo_bytes:
        try:
            bio = BytesIO(logo_bytes)
            doc.add_picture(bio, width=Inches(2.0))
        except Exception:
            pass

    doc.add_paragraph(company.get("address") or "")
    doc.add_paragraph(f"UEI: {company.get('uei') or 'N/A'}   |   CAGE: {company.get('cage') or 'N/A'}")
    doc.add_paragraph(f"NAICS: {company.get('naics') or 'N/A'}")
    certs = company.get("certifications") or []
    doc.add_paragraph(f"Certifications: {', '.join(certs) if certs else 'N/A'}")

    doc.add_page_break()

    doc.add_heading("Cover Letter", level=1)
    doc.add_paragraph(draft_cover_letter or "")

    doc.add_page_break()

    doc.add_heading("Proposal Body", level=1)
    doc.add_paragraph(draft_body or "")

    doc.add_page_break()

    doc.add_heading("Compatibility Matrix", level=1)
    table = doc.add_table(rows=1, cols=3)
    hdr = table.rows[0].cells
    hdr[0].text = "RFP Requirement"
    hdr[1].text = "Response"
    hdr[2].text = "Status"

    for row in compatibility_rows or []:
        cells = table.add_row().cells
        cells[0].text = str(row.get("requirement", "") or "")
        cells[1].text = str(row.get("response", "") or "")
        cells[2].text = str(row.get("status", "") or "")

    out = BytesIO()
    doc.save(out)
    return out.getvalue()