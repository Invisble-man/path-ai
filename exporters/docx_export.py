from __future__ import annotations

import io
from typing import Dict, Any, Optional

from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _add_page_numbers(doc: Document):
    section = doc.sections[0]
    footer = section.footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Page ")
    _add_field(run, "PAGE")
    p.add_run(" of ")
    _add_field(p.add_run(), "NUMPAGES")


def _add_field(run, field_code: str):
    r = run._r
    fldChar1 = OxmlElement('w:fldChar')
    fldChar1.set(qn('w:fldCharType'), 'begin')

    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = field_code

    fldChar2 = OxmlElement('w:fldChar')
    fldChar2.set(qn('w:fldCharType'), 'end')

    r.append(fldChar1)
    r.append(instrText)
    r.append(fldChar2)


def _add_toc(doc: Document):
    doc.add_page_break()
    doc.add_heading("Table of Contents", level=1)
    p = doc.add_paragraph()
    run = p.add_run()
    fldChar1 = OxmlElement('w:fldChar')
    fldChar1.set(qn('w:fldCharType'), 'begin')
    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = 'TOC \\o "1-3" \\z \\u'
    fldChar2 = OxmlElement('w:fldChar')
    fldChar2.set(qn('w:fldCharType'), 'end')
    run._r.append(fldChar1)
    run._r.append(instrText)
    run._r.append(fldChar2)
    doc.add_page_break()


def _add_cover_page(doc: Document, company: Dict[str, Any], logo_bytes: Optional[bytes]):
    doc.add_paragraph("\n\n")

    if logo_bytes:
        try:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(io.BytesIO(logo_bytes), width=Inches(2.5))
        except Exception:
            pass

    def center_bold(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.bold = True

    center_bold(company.get("legal_name") or "Company Name")
    center_bold(company.get("proposal_title") or "Proposal Title")

    doc.add_paragraph("")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f"Solicitation: {company.get('solicitation_number') or '—'}")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f"Agency: {company.get('agency_customer') or '—'}")

    doc.add_page_break()


def _add_section(doc: Document, title: str, body: str):
    doc.add_heading(title, level=1)
    for line in (body or "").splitlines():
        doc.add_paragraph(line)


def build_proposal_docx(
    company: Dict[str, Any],
    drafts: Dict[str, str],
    logo_bytes: Optional[bytes] = None,
) -> bytes:
    doc = Document()

    _add_page_numbers(doc)
    _add_cover_page(doc, company, logo_bytes)
    _add_toc(doc)

    sections = [
        "Cover Letter",
        "Executive Summary",
        "Technical Approach",
        "Management Plan",
        "Past Performance",
    ]

    for sec in sections:
        body = drafts.get(sec, "")
        if body.strip():
            _add_section(doc, sec, body)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()