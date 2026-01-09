import io
import json
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple

import streamlit as st
from pypdf import PdfReader
import docx  # python-docx

from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")


# =========================
# PDF/DOCX/TXT Extraction
# =========================

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()

def extract_text_from_docx(file_bytes: bytes) -> str:
    document = docx.Document(io.BytesIO(file_bytes))
    return "\n".join([p.text for p in document.paragraphs if p.text]).strip()

def read_uploaded_file(uploaded_file) -> str:
    if not uploaded_file:
        return ""
    name = uploaded_file.name.lower()
    data = uploaded_file.read()

    if name.endswith(".pdf"):
        return extract_text_from_pdf(data)
    if name.endswith(".docx"):
        return extract_text_from_docx(data)

    try:
        return data.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


# =========================
# RFP Intelligence (starter)
# =========================

FORM_PATTERNS = [
    (r"\bSF[-\s]?1449\b", "SF 1449 (Commercial Items)"),
    (r"\bSF[-\s]?33\b", "SF 33 (Solicitation/Offer and Award)"),
    (r"\bSF[-\s]?30\b", "SF 30 (Amendment/Modification)"),
    (r"\bSF[-\s]?18\b", "SF 18 (RFQ)"),
    (r"\bDD[-\s]?1155\b", "DD 1155 (Order for Supplies or Services)"),
    (r"\bDD[-\s]?254\b", "DD 254 (Security Classification Spec)"),
]

ATTACHMENT_KEYWORDS = [
    "attachment", "appendix", "exhibit", "annex", "enclosure", "addendum",
    "amendment", "amendments", "modification", "mods",
    "pricing", "price schedule", "cost proposal", "rate sheet", "spreadsheet", "xlsx", "excel",
    "reps and certs", "representations and certifications",
    "sf-1449", "sf 1449", "sf-33", "sf 33", "sf-30", "sf 30", "sf-18", "sf 18",
]

SUBMISSION_RULE_PATTERNS = [
    (r"\bpage limit\b|\bnot exceed\s+\d+\s+pages\b|\bpages maximum\b", "Page Limit"),
    (r"\bfont\b|\b12[-\s]?point\b|\b11[-\s]?point\b|\bTimes New Roman\b|\bArial\b|\bCalibri\b", "Font Requirement"),
    (r"\bmargins?\b|\b1 inch\b|\bone inch\b|\b0\.?\d+\s*inch\b|\b1\"\b", "Margin Requirement"),
    (r"\bdue\b|\bdue date\b|\bdeadline\b|\bno later than\b|\boffers?\s+are\s+due\b", "Due Date/Deadline"),
    (r"\bsubmit\b|\bsubmission\b|\be-?mail\b|\bemailed\b|\bportal\b|\bupload\b|\bsam\.gov\b|\bebuy\b|\bpiee\b|\bfedconnect\b", "Submission Method"),
    (r"\bsection\s+l\b|\bsection\s+m\b", "Sections L/M referenced"),
    (r"\bvolume\s+(?:i|ii|iii|iv|v|vi|1|2|3|4|5|6)\b", "Volumes (if found)"),
]

AMENDMENT_PATTERN = r"\bamendment\b|\bamendments\b|\ba0{2,}\d+\b|\bmodification\b|\bmod\b"

SEPARATE_SUBMIT_HINTS = [
    r"\bsigned\b",
    r"\bsignature\b",
    r"\bcomplete and return\b",
    r"\bfill(?:ed)? out\b",
    r"\bsubmit separately\b",
    r"\bseparate file\b",
    r"\binclude as an attachment\b",
    r"\bexcel\b|\bspreadsheet\b|\bxlsx\b",
]

CERT_KEYWORDS = [
    ("SDVOSB", r"\bservice[-\s]?disabled veteran[-\s]?owned\b|\bsdv?osb\b"),
    ("VOSB", r"\bveteran[-\s]?owned\b|\bvosb\b"),
    ("8(a)", r"\b8\(a\)\b|\b8a\b"),
    ("WOSB/EDWOSB", r"\bwosb\b|\bedwosb\b|\bwoman[-\s]?owned\b"),
    ("HUBZone", r"\bhubzone\b"),
]

def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()

def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

def scan_lines(text: str, max_lines: int = 8000) -> List[str]:
    lines = []
    for raw in text.splitlines():
        s = normalize_line(raw)
        if s:
            lines.append(s)
        if len(lines) >= max_lines:
            break
    return lines

def find_forms(text: str) -> List[str]:
    found = []
    for pat, label in FORM_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            found.append(label)
    return unique_keep_order(found)

def find_attachment_lines(text: str) -> List[str]:
    lines = scan_lines(text)
    hits = []
    for line in lines:
        low = line.lower()
        if any(k in low for k in ATTACHMENT_KEYWORDS):
            if len(line) <= 320:
                hits.append(line)
    return unique_keep_order(hits)

def detect_submission_rules(text: str) -> Dict[str, List[str]]:
    lines = scan_lines(text)
    grouped: Dict[str, List[str]] = {}
    for line in lines:
        for pat, label in SUBMISSION_RULE_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                grouped.setdefault(label, []).append(line)
    for k in list(grouped.keys()):
        grouped[k] = unique_keep_order(grouped[k])[:12]
    return grouped

def detect_amendment_lines(text: str) -> List[str]:
    lines = scan_lines(text)
    hits = [l for l in lines if re.search(AMENDMENT_PATTERN, l, re.IGNORECASE)]
    return unique_keep_order(hits)

def detect_separate_submit_lines(text: str) -> List[str]:
    lines = scan_lines(text)
    hits = []
    for l in lines:
        low = l.lower()
        if any(re.search(h, low, re.IGNORECASE) for h in SEPARATE_SUBMIT_HINTS):
            if ("attachment" in low or "appendix" in low or "exhibit" in low or
                "sf " in low or "sf-" in low or "amendment" in low or
                "pricing" in low or "spreadsheet" in low or "excel" in low):
                hits.append(l)
    return unique_keep_order(hits)

def extract_sow_snippets(text: str, max_snips: int = 6) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    key = re.compile(r"\b(statement of work|scope of work|sow|pws|performance work statement|tasks?|requirements?)\b", re.IGNORECASE)
    cands = []
    for p in paras:
        if key.search(p):
            cands.append(p[:900])
    if not cands:
        cands = paras[:max_snips]
    out, seen = [], set()
    for c in cands:
        k = c.lower()
        if k not in seen:
            seen.add(k)
            out.append(c)
        if len(out) >= max_snips:
            break
    return out

def derive_tailor_keywords(snips: List[str]) -> List[str]:
    text = " ".join(snips).lower()
    stop = set("""
        the a an and or to of for in on with by from as at is are be shall will may must
        offer proposal contractor government agency work statement performance requirement requirements
        services service task tasks provide providing include including
        section submission submit due date deadline pages page limit font margin margins
    """.split())
    words = re.findall(r"[a-z]{4,}", text)
    freq: Dict[str, int] = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:12]
    return [w for w, _ in top]

def detect_required_certifications(text: str) -> List[str]:
    found = []
    for label, pat in CERT_KEYWORDS:
        if re.search(pat, text, re.IGNORECASE):
            found.append(label)
    return unique_keep_order(found)

def compliance_warnings(rules: Dict[str, List[str]], forms: List[str], amendments: List[str], separate: List[str]) -> List[str]:
    warnings = []
    if not rules:
        warnings.append("No submission rules detected. If you pasted partial text, upload the full text-based solicitation.")
    else:
        if "Due Date/Deadline" not in rules:
            warnings.append("Due date/deadline not clearly detected. Verify cover page + Section L.")
        if "Submission Method" not in rules:
            warnings.append("Submission method not clearly detected (email/portal). Verify exactly where/how to submit.")
        if any(k in rules for k in ["Page Limit", "Font Requirement", "Margin Requirement"]):
            warnings.append("Formatting rules detected (page/font/margins). Violations can cause rejection as non-compliant.")
    if forms:
        warnings.append("SF/DD forms detected. Confirm each required form is completed and signed where required.")
    if amendments:
        warnings.append("Amendments/modifications referenced. Confirm all amendments acknowledged and instructions incorporated.")
    if separate:
        warnings.append("Items may require separate files/submissions (signed forms, spreadsheets, attachments). Review the list below.")
    if not warnings:
        warnings.append("No major issues detected by starter logic. Still verify Section L/M and all attachments manually.")
    return warnings


# =========================
# Company Info + Drafts
# =========================

@dataclass
class CompanyInfo:
    legal_name: str = ""
    address: str = ""
    uei: str = ""
    cage: str = ""
    naics: str = ""
    psc: str = ""
    poc_name: str = ""
    poc_email: str = ""
    poc_phone: str = ""
    certifications: List[str] = None
    capabilities: str = ""
    differentiators: str = ""
    past_performance: str = ""
    website: str = ""

    # Proposal title info
    proposal_title: str = ""        # e.g., "Proposal for XYZ Services"
    solicitation_number: str = ""   # e.g., "W91XXX-26-R-0001"
    agency_customer: str = ""       # e.g., "Department of X / Agency Y"

    def to_dict(self):
        d = asdict(self)
        if d["certifications"] is None:
            d["certifications"] = []
        return d


def generate_drafts(
    sow_snips: List[str],
    keywords: List[str],
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    company: CompanyInfo
) -> Dict[str, str]:
    kw = ", ".join(keywords[:8]) if keywords else "quality, schedule, reporting, risk"
    due = rules.get("Due Date/Deadline", ["Not detected"])[0] if rules.get("Due Date/Deadline") else "Not detected"
    method = rules.get("Submission Method", ["Not detected"])[0] if rules.get("Submission Method") else "Not detected"
    vols = rules.get("Volumes (if found)", [])
    certs = ", ".join(company.certifications or []) if company.certifications else "—"

    sow_block = "\n".join([f"- {s}" for s in sow_snips[:3]]) if sow_snips else "- [No SOW snippets detected]"

    cover = f"""COVER LETTER (DRAFT)

{company.legal_name or "[Company Name]"}
{company.address or "[Address]"}
UEI: {company.uei or "[UEI]"} | CAGE: {company.cage or "[CAGE]"}
POC: {company.poc_name or "[POC]"} | {company.poc_email or "[email]"} | {company.poc_phone or "[phone]"}
Certifications: {certs}

Subject: {company.proposal_title or "Proposal Submission"}

Dear Contracting Officer,

{company.legal_name or "[Company Name]"} submits this proposal in response to the solicitation. We understand the Government’s requirement and will execute with a low-risk approach aligned to: {kw}.

Submission (best-effort detected):
- Deadline: {due}
- Submission Method: {method}

Sincerely,
{company.poc_name or "[POC Name]"}
{company.legal_name or "[Company Name]"}
"""

    exec_summary = f"""EXECUTIVE SUMMARY (DRAFT)

{company.legal_name or "[Company Name]"} will deliver the required scope with disciplined execution, clear communication, and measurable outcomes.

Tailoring keywords (auto-extracted from SOW text):
{kw}

Capabilities:
{company.capabilities or "[Add capabilities]"}
"""

    tech = f"""TECHNICAL APPROACH (DRAFT)

Understanding of Requirement (SOW/PWS excerpts – starter):
{sow_block}

Approach:
- Requirements-to-Deliverables Mapping: map each requirement to a deliverable, owner, schedule, and acceptance criteria.
- Execution Plan: controlled phases with weekly status, quality checks, and documented approvals.
- Quality Control: peer review, checklists, and objective evidence to confirm compliance.

Designed around:
{kw}
"""

    mgmt = f"""MANAGEMENT PLAN (DRAFT)

Program Management:
- Single accountable Program Manager and clear escalation path.
- Weekly status reporting, risk log, action tracker, and stakeholder communications.

Staffing:
- Roles aligned to SOW tasks; surge support available.
- Controlled onboarding, SOPs, and oversight.

Risk Management:
- Identify risks early, mitigate, and communicate impacts with options.
"""

    if company.past_performance.strip():
        pp = f"""PAST PERFORMANCE (DRAFT)

Provided Past Performance:
{company.past_performance}

Relevance:
- Demonstrates delivery of similar scope and disciplined execution.
"""
    else:
        pp = f"""PAST PERFORMANCE (CAPABILITY-BASED – DRAFT)

No direct past performance provided. {company.legal_name or "[Company Name]"} will demonstrate responsibility and capability through:
- Strong management controls and reporting cadence
- Defined QC checks and documented processes
- Staffing aligned to the requirement
- Risk mitigation and escalation procedures
"""

    forms_block = "\n".join([f"- {f}" for f in forms]) if forms else "- None detected"
    att_block = "\n".join([f"- {a}" for a in attachments[:10]]) if attachments else "- None detected"
    vol_block = "; ".join(vols) if vols else "Not detected"

    compliance = f"""COMPLIANCE SNAPSHOT (STARTER)

Submission Rules (best-effort):
- Deadline: {due}
- Method: {method}
- Volumes: {vol_block}

Forms detected:
{forms_block}

Attachment/Appendix/Exhibit mentions:
{att_block}

Next step: build a true compliance matrix aligned to Section L/M.
"""

    return {
        "Cover Letter": cover,
        "Executive Summary": exec_summary,
        "Technical Approach": tech,
        "Management Plan": mgmt,
        "Past Performance": pp,
        "Compliance Snapshot": compliance,
    }


# =========================
# Missing Info Alerts
# =========================

def missing_info_alerts(company: CompanyInfo) -> Tuple[List[str], List[str]]:
    """
    Returns (critical, recommended)
    """
    critical = []
    recommended = []

    if not company.legal_name.strip():
        critical.append("Company legal name is missing.")
    if not company.uei.strip():
        critical.append("UEI is missing (commonly required).")
    if not company.poc_name.strip():
        critical.append("POC name is missing.")
    if not company.poc_email.strip():
        critical.append("POC email is missing.")
    if not company.address.strip():
        recommended.append("Business address is missing (often used on cover letter).")

    if not company.certifications or (len(company.certifications) == 1 and company.certifications[0] == "None"):
        recommended.append("Certifications/set-asides not selected (if applicable).")
    if not company.capabilities.strip():
        recommended.append("Capabilities section is empty (hurts competitiveness).")
    if not company.differentiators.strip():
        recommended.append("Differentiators section is empty (hurts competitiveness).")
    if not company.past_performance.strip():
        recommended.append("Past performance is blank (app will use capability-based language).")

    if not company.proposal_title.strip():
        recommended.append("Proposal/Contract title is blank (recommended for title page).")
    if not company.solicitation_number.strip():
        recommended.append("Solicitation number is blank (recommended for title page).")
    if not company.agency_customer.strip():
        recommended.append("Agency/Customer is blank (recommended for title page).")

    return critical, recommended


# =========================
# Compliance Checklist v1
# =========================

def build_checklist_items(
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    amendments: List[str],
    separate: List[str],
    required_certs: List[str]
) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []

    # Core rules buckets
    for key in ["Due Date/Deadline", "Submission Method", "Page Limit", "Font Requirement", "Margin Requirement", "Volumes (if found)"]:
        if key in rules and rules[key]:
            items.append({"item": f"Verify: {key}", "source": "Submission Rules", "status": "Needs Review"})
        else:
            items.append({"item": f"Find & confirm: {key}", "source": "Submission Rules", "status": "Missing/Unknown"})

    # Forms
    if forms:
        for f in forms:
            items.append({"item": f"Complete/attach required form: {f}", "source": "Forms", "status": "Needs Review"})
    else:
        items.append({"item": "Confirm whether SF/DD forms are required", "source": "Forms", "status": "Missing/Unknown"})

    # Attachments mentions
    if attachments:
        items.append({"item": "Review every attachment/appendix/exhibit mention and ensure included", "source": "Attachments", "status": "Needs Review"})
    else:
        items.append({"item": "Confirm required attachments/appendices/exhibits", "source": "Attachments", "status": "Missing/Unknown"})

    # Amendments
    if amendments:
        items.append({"item": "Acknowledge all amendments and incorporate revised instructions", "source": "Amendments", "status": "Needs Review"})
    else:
        items.append({"item": "Confirm whether any amendments exist", "source": "Amendments", "status": "Needs Review"})

    # Separate submissions
    if separate:
        items.append({"item": "Prepare separate submission items (spreadsheets/signed forms/etc.)", "source": "Separate Submissions", "status": "Needs Review"})

    # Required certs
    if required_certs:
        items.append({"item": f"Confirm eligibility/documentation for: {', '.join(required_certs)}", "source": "Certifications", "status": "Needs Review"})

    # Dedup
    uniq = []
    seen = set()
    for it in items:
        k = (it["item"] + "|" + it["source"]).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    return uniq


# =========================
# DOCX Export Helpers: TOC + Page numbers + Title Page + Logo
# =========================

def add_field(paragraph, field_code: str):
    """
    Insert a Word field code (e.g. TOC, PAGE, NUMPAGES).
    """
    run = paragraph.add_run()
    r = run._r

    fldChar1 = OxmlElement('w:fldChar')
    fldChar1.set(qn('w:fldCharType'), 'begin')

    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = field_code

    fldChar2 = OxmlElement('w:fldChar')
    fldChar2.set(qn('w:fldCharType'), 'separate')

    fldChar3 = OxmlElement('w:fldChar')
    fldChar3.set(qn('w:fldCharType'), 'end')

    r.append(fldChar1)
    r.append(instrText)
    r.append(fldChar2)
    r.append(fldChar3)

def add_page_numbers(doc: docx.Document):
    """
    Footer: Page X of Y
    """
    section = doc.sections[0]
    footer = section.footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    p.add_run("Page ")
    add_field(p, "PAGE")
    p.add_run(" of ")
    add_field(p, "NUMPAGES")

def add_table_of_contents(doc: docx.Document):
    """
    TOC field based on Heading 1-3
    """
    doc.add_page_break()
    doc.add_heading("Table of Contents", level=1)
    p = doc.add_paragraph()
    add_field(p, r'TOC \o "1-3" \h \z \u')
    doc.add_page_break()

def add_title_page(doc: docx.Document, company: CompanyInfo, logo_bytes: bytes | None):
    """
    Title page with centered logo and key identifiers.
    """
    # Big spacing to keep logo "middle-ish"
    doc.add_paragraph("")  # top padding
    doc.add_paragraph("")
    doc.add_paragraph("")

    if logo_bytes:
        try:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(io.BytesIO(logo_bytes), width=Inches(2.2))
            doc.add_paragraph("")
        except Exception:
            # If logo fails, just skip it (do not break export)
            pass

    title = company.proposal_title.strip() or "Proposal"
    company_name = company.legal_name.strip() or "[Company Name]"
    sol = company.solicitation_number.strip() or "[Solicitation #]"
    agency = company.agency_customer.strip() or "[Agency/Customer]"

    p1 = doc.add_paragraph()
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p1.add_run(company_name)
    r1.bold = True
    r1.font.size = docx.shared.Pt(20)

    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run(title)
    r2.bold = True
    r2.font.size = docx.shared.Pt(16)

    doc.add_paragraph("")
    p3 = doc.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p3.add_run(f"Solicitation: {sol}")

    p4 = doc.add_paragraph()
    p4.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p4.add_run(f"Agency/Customer: {agency}")

    doc.add_paragraph("")
    p5 = doc.add_paragraph()
    p5.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p5.add_run(f"UEI: {company.uei or '[UEI]'}    CAGE: {company.cage or '[CAGE]'}")

    # End title page
    doc.add_page_break()

def add_paragraph_lines(doc: docx.Document, text: str):
    for line in text.splitlines():
        doc.add_paragraph(line)

def build_proposal_docx_bytes(
    company: CompanyInfo,
    logo_bytes: bytes | None,
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    amendments: List[str],
    separate: List[str],
    required_certs: List[str],
    warnings: List[str],
    checklist_items: List[Dict[str, str]],
    drafts: Dict[str, str]
) -> bytes:
    doc = docx.Document()

    # Page numbers (footer)
    add_page_numbers(doc)

    # Title page
    add_title_page(doc, company, logo_bytes)

    # TOC
    add_table_of_contents(doc)

    # Company profile
    doc.add_heading("Company Profile", level=1)
    certs = ", ".join(company.certifications or []) if company.certifications else "—"
    profile = f"""Company: {company.legal_name or "—"}
Address: {company.address or "—"}
UEI: {company.uei or "—"} | CAGE: {company.cage or "—"}
NAICS: {company.naics or "—"} | PSC: {company.psc or "—"}
POC: {company.poc_name or "—"} | {company.poc_email or "—"} | {company.poc_phone or "—"}
Certifications/Set-Asides: {certs}
Website: {company.website or "—"}
"""
    add_paragraph_lines(doc, profile)

    # Cleaner submission checklist
    doc.add_heading("Submission Checklist (Compliance Checklist v1)", level=1)

    # Checklist items
    for it in checklist_items:
        box = "☐"
        line = f"{box} {it['item']}  ({it['status']})"
        doc.add_paragraph(line, style="List Bullet")

    doc.add_paragraph("")

    # Evidence sections (short + clean)
    doc.add_heading("Detected Submission Rules (Starter)", level=2)
    if rules:
        for k, lines in rules.items():
            doc.add_paragraph(k, style="List Bullet")
            for ln in lines[:6]:
                doc.add_paragraph(ln, style="List Bullet 2")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Detected Forms", level=2)
    if forms:
        for f in forms:
            doc.add_paragraph(f, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Attachment/Appendix/Exhibit Mentions", level=2)
    if attachments:
        for a in attachments[:12]:
            doc.add_paragraph(a, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Amendments/Mods Referenced", level=2)
    if amendments:
        for a in amendments[:12]:
            doc.add_paragraph(a, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Separate Submission Indicators", level=2)
    if separate:
        for s in separate[:15]:
            doc.add_paragraph(s, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Compliance Warnings (Starter)", level=2)
    if warnings:
        for w in warnings:
            doc.add_paragraph(w, style="List Bullet")
    else:
        doc.add_paragraph("None.", style="List Bullet")

    # Draft sections
    doc.add_page_break()
    doc.add_heading("Draft Proposal Sections", level=1)
    if drafts:
        for title, body in drafts.items():
            doc.add_heading(title, level=2)
            add_paragraph_lines(doc, body)
    else:
        doc.add_paragraph("No draft sections generated yet.", style="List Bullet")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# =========================
# Session State Init
# =========================

if "rfp_text" not in st.session_state:
    st.session_state.rfp_text = ""

if "rules" not in st.session_state:
    st.session_state.rules = {}

if "forms" not in st.session_state:
    st.session_state.forms = []

if "attachments" not in st.session_state:
    st.session_state.attachments = []

if "amendments" not in st.session_state:
    st.session_state.amendments = []

if "separate_submit" not in st.session_state:
    st.session_state.separate_submit = []

if "required_certs" not in st.session_state:
    st.session_state.required_certs = []

if "sow_snips" not in st.session_state:
    st.session_state.sow_snips = []

if "keywords" not in st.session_state:
    st.session_state.keywords = []

if "drafts" not in st.session_state:
    st.session_state.drafts = {}

if "company" not in st.session_state:
    st.session_state.company = CompanyInfo(certifications=[])

if "logo_bytes" not in st.session_state:
    st.session_state.logo_bytes = None

if "checklist_done" not in st.session_state:
    st.session_state.checklist_done = {}  # key -> bool


# =========================
# UI Navigation
# =========================

st.sidebar.title("Path")
page = st.sidebar.radio("Go to", ["RFP Intake", "Company Info", "Proposal Output"])
st.sidebar.caption("Flow: Upload/Paste → Analyze → Generate Drafts → Download Word")


# =========================
# Page 1: RFP Intake
# =========================

if page == "RFP Intake":
    st.title("1) RFP Intake")

    uploaded = st.file_uploader("Upload RFP (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"])
    pasted = st.text_area("Or paste RFP / RFI text", value=st.session_state.rfp_text, height=300)

    if st.button("Analyze"):
        text = ""
        if uploaded:
            text = read_uploaded_file(uploaded)
            if not text.strip():
                st.warning("File uploaded, but no text could be extracted. If PDF is scanned, we’ll need OCR later.")
        if pasted.strip():
            text = pasted.strip()

        if not text.strip():
            st.error("Please upload a readable file OR paste text.")
        else:
            st.session_state.rfp_text = text
            st.session_state.rules = detect_submission_rules(text)
            st.session_state.forms = find_forms(text)
            st.session_state.attachments = find_attachment_lines(text)
            st.session_state.amendments = detect_amendment_lines(text)
            st.session_state.separate_submit = detect_separate_submit_lines(text)
            st.session_state.sow_snips = extract_sow_snippets(text)
            st.session_state.keywords = derive_tailor_keywords(st.session_state.sow_snips)
            st.session_state.required_certs = detect_required_certifications(text)
            st.success("Analysis saved. Go to Proposal Output.")

    st.markdown("---")
    st.subheader("Preview (first 1200 characters)")
    st.code((st.session_state.rfp_text or "")[:1200], language="text")


# =========================
# Page 2: Company Info
# =========================

elif page == "Company Info":
    st.title("2) Company Info")
    st.caption("Fill this out once. It auto-fills the proposal drafts and the export title page.")

    c: CompanyInfo = st.session_state.company

    st.subheader("Logo Upload (optional)")
    logo = st.file_uploader("Upload company logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
    if logo:
        st.session_state.logo_bytes = logo.read()
        st.success("Logo saved. It will be placed on the title page.")
        st.image(st.session_state.logo_bytes, width=180)

    st.markdown("---")

    st.subheader("Proposal / Contract Information (Title Page)")
    c.proposal_title = st.text_input("Proposal/Contract Title", value=c.proposal_title, placeholder="e.g., Proposal for IT Support Services")
    c.solicitation_number = st.text_input("Solicitation Number", value=c.solicitation_number, placeholder="e.g., W91XXX-26-R-0001")
    c.agency_customer = st.text_input("Agency/Customer", value=c.agency_customer, placeholder="e.g., Department of X / Agency Y")

    st.markdown("---")
    st.subheader("Company Information")

    col1, col2 = st.columns(2)
    with col1:
        c.legal_name = st.text_input("Legal Company Name", value=c.legal_name)
        c.uei = st.text_input("UEI", value=c.uei)
        c.cage = st.text_input("CAGE (optional)", value=c.cage)
        c.naics = st.text_input("Primary NAICS (optional)", value=c.naics)
        c.psc = st.text_input("PSC (optional)", value=c.psc)

    with col2:
        c.address = st.text_area("Business Address", value=c.address, height=110)
        c.poc_name = st.text_input("Point of Contact Name", value=c.poc_name)
        c.poc_email = st.text_input("Point of Contact Email", value=c.poc_email)
        c.poc_phone = st.text_input("Point of Contact Phone", value=c.poc_phone)
        c.website = st.text_input("Website (optional)", value=c.website)

    st.markdown("### Certifications / Set-Asides")
    options = ["SDVOSB", "VOSB", "8(a)", "WOSB/EDWOSB", "HUBZone", "SBA Small Business", "ISO 9001", "None"]
    c.certifications = st.multiselect("Select all that apply", options=options, default=c.certifications or [])

    st.markdown("### Capabilities & Differentiators")
    c.capabilities = st.text_area("Capabilities (short paragraph or bullets)", value=c.capabilities, height=130)
    c.differentiators = st.text_area("Differentiators (why you)", value=c.differentiators, height=110)

    st.markdown("### Past Performance (optional)")
    st.caption("If blank, the draft will use capability-based language.")
    c.past_performance = st.text_area("Paste past performance notes", value=c.past_performance, height=150)

    st.session_state.company = c

    st.markdown("---")
    colA, colB = st.columns(2)
    with colA:
        if st.button("Download Company Info (JSON backup)"):
            backup = json.dumps(c.to_dict(), indent=2)
            st.download_button(
                label="Click to download JSON",
                data=backup,
                file_name="company_profile.json",
                mime="application/json"
            )

    with colB:
        up = st.file_uploader("Upload Company Info (JSON)", type=["json"])
        if up:
            try:
                loaded = json.loads(up.read().decode("utf-8"))
                if isinstance(loaded, dict):
                    for k, v in loaded.items():
                        if hasattr(c, k):
                            setattr(c, k, v)
                    if c.certifications is None:
                        c.certifications = []
                    st.session_state.company = c
                    st.success("Company profile loaded.")
                else:
                    st.error("That JSON file isn't a valid company profile.")
            except Exception as e:
                st.error(f"Could not load JSON: {e}")


# =========================
# Page 3: Proposal Output
# =========================

else:
    st.title("3) Proposal Output")

    if not st.session_state.rfp_text.strip():
        st.warning("No RFP saved yet. Go to RFP Intake and click Analyze.")
        st.stop()

    rules = st.session_state.rules or {}
    forms = st.session_state.forms or []
    attachments = st.session_state.attachments or []
    amendments = st.session_state.amendments or []
    separate = st.session_state.separate_submit or []
    required_certs = st.session_state.required_certs or []
    c: CompanyInfo = st.session_state.company
    logo_bytes = st.session_state.logo_bytes

    # Missing Info Alerts
    st.subheader("A) Missing Info Alerts (fix these before you submit)")
    crit, rec = missing_info_alerts(c)
    if crit:
        for x in crit:
            st.error(x)
    else:
        st.success("No critical company-info fields missing.")

    if rec:
        for x in rec:
            st.warning(x)

    if required_certs:
        st.info("RFP mentions these certification types (starter detection): " + ", ".join(required_certs))

    st.markdown("---")

    # Submission Rules
    st.subheader("B) Submission Rules Found (starter)")
    if rules:
        for label, lines in rules.items():
            with st.expander(label, expanded=False):
                for ln in lines:
                    st.write("•", ln)
    else:
        st.write("No obvious submission rules detected yet. Upload the full solicitation or paste Section L/M.")

    st.markdown("---")

    # Forms & Attachments
    st.subheader("C) Forms & Attachments Detected (starter)")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Forms (SF/DD) Found**")
        if forms:
            for f in forms:
                st.write("•", f)
        else:
            st.write("No SF/DD forms detected.")
    with col2:
        st.markdown("**Amendments / Mods referenced**")
        if amendments:
            for a in amendments[:15]:
                st.write("•", a)
            if len(amendments) > 15:
                st.caption(f"Showing 15 of {len(amendments)}")
        else:
            st.write("No amendments detected.")

    st.markdown("**Attachment / Appendix / Exhibit lines**")
    if attachments:
        for a in attachments[:25]:
            st.write("•", a)
        if len(attachments) > 25:
            st.caption(f"Showing 25 of {len(attachments)}")
    else:
        st.write("No obvious attachment references detected.")

    st.markdown("---")

    # Compliance Warnings
    st.subheader("D) Compliance Warnings (starter)")
    warns = compliance_warnings(rules, forms, amendments, separate)
    for w in warns:
        st.warning(w)

    if separate:
        st.markdown("**Separate submission indicators**")
        for ln in separate[:25]:
            st.write("•", ln)

    st.markdown("---")

    # Compliance Checklist v1 (real checklist)
    st.subheader("E) Compliance Checklist v1 (check things off)")
    checklist_items = build_checklist_items(rules, forms, attachments, amendments, separate, required_certs)

    # Render checklist as interactive checkboxes (persisted in session)
    for idx, it in enumerate(checklist_items):
        key = f"chk_{idx}_{it['source']}"
        if key not in st.session_state.checklist_done:
            st.session_state.checklist_done[key] = False
        label = f"{it['item']}  —  [{it['status']}]  ({it['source']})"
        st.session_state.checklist_done[key] = st.checkbox(label, value=st.session_state.checklist_done[key], key=key)

    st.markdown("---")

    # Draft generator
    st.subheader("F) Draft Proposal Sections (starter, template-based)")
    kws = st.session_state.keywords or []
    if kws:
        st.caption("Tailoring keywords (auto-extracted): " + ", ".join(kws[:10]))
    else:
        st.caption("Tailoring keywords: (none detected yet)")

    if st.button("Generate Draft Sections"):
        st.session_state.drafts = generate_drafts(
            sow_snips=st.session_state.sow_snips or [],
            keywords=kws,
            rules=rules,
            forms=forms,
            attachments=attachments,
            company=c
        )
        st.success("Draft generated. Expand the sections below.")

    drafts = st.session_state.drafts or {}
    if drafts:
        for title, body in drafts.items():
            with st.expander(title, expanded=(title in ["Executive Summary", "Technical Approach"])):
                st.text_area(label="", value=body, height=260)
    else:
        st.info("Generate drafts to enable export.")

    st.markdown("---")

    # Export: Title page + TOC + page numbers + logo + checklist
    st.subheader("G) Export (Professional Word Proposal Package)")
    if drafts:
        doc_bytes = build_proposal_docx_bytes(
            company=c,
            logo_bytes=logo_bytes,
            rules=rules,
            forms=forms,
            attachments=attachments,
            amendments=amendments,
            separate=separate,
            required_certs=required_certs,
            warnings=warns,
            checklist_items=checklist_items,
            drafts=drafts
        )
        file_name = "proposal_package.docx"
        st.download_button(
            label="Download Proposal Package (.docx)",
            data=doc_bytes,
            file_name=file_name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        st.caption("Note: In Word, right-click the Table of Contents → Update Field → Update entire table.")
    else:
        st.write("Generate draft sections first, then export.")

    st.markdown("---")
    st.subheader("H) RFP Preview (first 1500 characters)")
    st.code(st.session_state.rfp_text[:1500], language="text")