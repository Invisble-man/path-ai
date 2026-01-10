import io
import json
import re
import base64
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional, Any

import streamlit as st
from pypdf import PdfReader
import docx  # python-docx
import requests

from docx.shared import Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# ============================================================
# Path.ai — Federal Proposal Prep
# Guided flow + AI gating + DOCX export
# ============================================================

APP_NAME = "Path.ai"
BUILD_VERSION = "v1.0.1"
BUILD_DATE = "Jan 9, 2026"

st.set_page_config(page_title=f"{APP_NAME} – Proposal Prep", layout="wide")


# ============================================================
# Styling
# ============================================================
def inject_css():
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.0rem; padding-bottom: 2.5rem; max-width: 1200px; }
        header[data-testid="stHeader"] { background: rgba(255,255,255,0.85); backdrop-filter: blur(6px); }

        .brandbar {
            display:flex; align-items:center; justify-content:space-between;
            padding: 14px 16px; border-radius: 16px;
            border: 1px solid rgba(49,51,63,0.14);
            background: linear-gradient(135deg, rgba(92, 124, 250, 0.10), rgba(34, 197, 94, 0.08));
            margin-bottom: 12px;
        }
        .brand-left { display:flex; align-items:center; gap: 10px; }
        .brand-dot {
            width: 14px; height: 14px; border-radius: 999px;
            background: radial-gradient(circle at 30% 30%, #22c55e, #5c7cfa);
        }
        .brand-title { font-weight: 800; font-size: 1.05rem; }
        .brand-sub { color: rgba(49,51,63,0.72); font-size: 0.90rem; margin-top: 2px; }

        .card {
            border: 1px solid rgba(49,51,63,0.14);
            border-radius: 16px;
            padding: 14px 14px 12px 14px;
            margin-bottom: 12px;
            background: rgba(255,255,255,0.92);
        }
        .card h4 { margin: 0 0 6px 0; font-size: 0.98rem; }
        .muted { color: rgba(49,51,63,0.65); font-size: 0.90rem; }
        .divider { height: 1px; background: rgba(49,51,63,0.10); margin: 10px 0; }

        .pill {
            display: inline-block;
            padding: 7px 11px;
            border-radius: 999px;
            font-size: 0.86rem;
            font-weight: 700;
            border: 1px solid rgba(49,51,63,0.14);
            margin-right: 8px;
            margin-bottom: 8px;
        }
        .pill-green { background: rgba(34, 197, 94, 0.13); }
        .pill-yellow { background: rgba(234, 179, 8, 0.16); }
        .pill-red { background: rgba(239, 68, 68, 0.14); }
        .pill-blue { background: rgba(92, 124, 250, 0.12); }

        .notice {
            border-radius: 16px;
            padding: 12px 14px;
            border: 1px solid rgba(49,51,63,0.14);
            background: rgba(255,255,255,0.92);
            margin: 10px 0 12px 0;
        }
        .notice-title { font-weight: 800; margin: 0 0 4px 0; font-size: 0.96rem; }
        .notice-body { margin: 0; font-size: 0.93rem; color: rgba(49,51,63,0.86); }
        .tone-good { background: rgba(34,197,94,0.10); }
        .tone-warn { background: rgba(234,179,8,0.12); }
        .tone-bad  { background: rgba(239,68,68,0.12); }
        .tone-neutral { background: rgba(92,124,250,0.08); }

        .stButton>button {
            border-radius: 14px !important;
            padding: 0.70rem 0.95rem !important;
            font-weight: 800 !important;
        }

        div[data-testid="stExpander"] details summary p { font-size: 0.96rem; font-weight: 700; }
        div[data-testid="stCheckbox"] label p { font-size: 0.95rem; }
        </style>
        """,
        unsafe_allow_html=True
    )


def ui_notice(title: str, body: str, tone: str = "neutral"):
    tone_class = {
        "neutral": "tone-neutral",
        "good": "tone-good",
        "warn": "tone-warn",
        "bad": "tone-bad",
    }.get(tone, "tone-neutral")

    st.markdown(
        f"""
        <div class="notice {tone_class}">
            <div class="notice-title">{title}</div>
            <p class="notice-body">{body}</p>
        </div>
        """,
        unsafe_allow_html=True
    )


inject_css()

# ============================================================
# Data model
# ============================================================
GATING_LABELS = ["ACTIONABLE", "INFORMATIONAL", "IRRELEVANT", "AUTO_RESOLVED"]


@dataclass
class ProposalItem:
    id: str
    kind: str
    text: str
    source: str
    bucket: str
    gating_label: str
    confidence: float
    status: str = "Unknown"
    notes: str = ""
    mapped_section: str = ""


# ============================================================
# Helpers
# ============================================================
def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "")).strip()


def scan_lines(text: str, max_lines: int = 12000) -> List[str]:
    out = []
    for raw in (text or "").splitlines():
        s = normalize_line(raw)
        if s:
            out.append(s)
        if len(out) >= max_lines:
            break
    return out


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        k = (x or "").lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def score_to_confidence(score: int, max_score: int = 10) -> float:
    if max_score <= 0:
        return 0.0
    v = max(0, min(max_score, score))
    return round(v / max_score, 2)


# ============================================================
# Text extraction
# ============================================================
def extract_text_from_pdf(file_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
    diag = {"file_type": "pdf", "pages_total": 0, "pages_with_text": 0, "chars_extracted": 0, "likely_scanned": False}
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    diag["pages_total"] = len(reader.pages)

    for page in reader.pages:
        t = page.extract_text() or ""
        if t.strip():
            diag["pages_with_text"] += 1
        parts.append(t)

    out = "\n".join(parts).strip()
    diag["chars_extracted"] = len(out)

    ratio = 0.0
    if diag["pages_total"] > 0:
        ratio = diag["pages_with_text"] / max(1, diag["pages_total"])
    if ratio < 0.25 or diag["chars_extracted"] < 800:
        diag["likely_scanned"] = True

    return out, diag


def extract_text_from_docx(file_bytes: bytes) -> str:
    document = docx.Document(io.BytesIO(file_bytes))
    return "\n".join([p.text for p in document.paragraphs if p.text]).strip()


def read_uploaded_file(uploaded_file) -> Tuple[str, Dict[str, Any]]:
    if not uploaded_file:
        return "", {}

    name = uploaded_file.name.lower()
    data = uploaded_file.read()

    if name.endswith(".pdf"):
        return extract_text_from_pdf(data)

    if name.endswith(".docx"):
        text = extract_text_from_docx(data)
        diag = {"file_type": "docx", "pages_total": None, "pages_with_text": None, "chars_extracted": len(text), "likely_scanned": False}
        return text, diag

    try:
        text = data.decode("utf-8", errors="ignore").strip()
    except Exception:
        text = ""

    diag = {"file_type": "text", "pages_total": None, "pages_with_text": None, "chars_extracted": len(text), "likely_scanned": False}
    return text, diag


# ============================================================
# Detection heuristics
# ============================================================
FORM_PATTERNS = [
    (r"\bSF[-\s]?1449\b", "SF 1449 (Commercial Items)"),
    (r"\bSF[-\s]?33\b", "SF 33 (Solicitation/Offer and Award)"),
    (r"\bSF[-\s]?30\b", "SF 30 (Amendment/Modification)"),
    (r"\bSF[-\s]?18\b", "SF 18 (RFQ)"),
    (r"\bDD[-\s]?1155\b", "DD 1155 (Order for Supplies or Services)"),
]

ATTACHMENT_KEYWORDS = [
    "attachment", "appendix", "exhibit", "annex", "enclosure", "addendum",
    "amendment", "modification", "pricing", "price schedule", "rate sheet",
    "spreadsheet", "xlsx", "excel",
]

SUBMISSION_RULE_PATTERNS = [
    (r"\bpage limit\b|\bnot exceed\s+\d+\s+pages\b|\bpages maximum\b", "Page Limit"),
    (r"\bfont\b|\b12[-\s]?point\b|\b11[-\s]?point\b|\bTimes New Roman\b|\bArial\b|\bCalibri\b", "Font Requirement"),
    (r"\bmargins?\b|\b1 inch\b|\bone inch\b|\b0\.?\d+\s*inch\b|\b1\"\b", "Margin Requirement"),
    (r"\bdue\b|\bdue date\b|\bdeadline\b|\bno later than\b|\boffers?\s+are\s+due\b|\bproposal\s+is\s+due\b", "Due Date/Deadline"),
    (r"\bsubmit\b|\bsubmission\b|\be-?mail\b|\bportal\b|\bupload\b|\bsam\.gov\b|\bebuy\b|\bpiee\b|\bfedconnect\b", "Submission Method"),
    (r"\bfile format\b|\bpdf\b|\bdocx\b|\bexcel\b|\bxlsx\b|\bzip\b|\bencrypt\b|\bpassword\b", "File Format Rules"),
    (r"\bsection\s+l\b|\bsection\s+m\b", "Sections L/M referenced"),
]

AMENDMENT_PATTERN = r"\bamendment\b|\bamendments\b|\ba0{2,}\d+\b|\bmodification\b|\bmod\b"
REQ_TRIGGER = re.compile(r"\b(shall|must|will)\b", re.IGNORECASE)
REQ_NUMBERED = re.compile(r"^(\(?[a-z0-9]{1,4}\)?[\.\)]|\d{1,3}\.)\s+", re.IGNORECASE)

DEFAULT_SECTIONS = ["Cover Letter", "Executive Summary", "Technical Approach", "Management Plan", "Past Performance", "Compliance Snapshot"]


def find_forms(text: str) -> List[str]:
    found = []
    for pat, label in FORM_PATTERNS:
        if re.search(pat, text or "", re.IGNORECASE):
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


def extract_requirements_best_effort(rfp_text: str, max_reqs: int = 70) -> List[str]:
    lines = scan_lines(rfp_text, max_lines=12000)
    reqs = []
    seen = set()

    for line in lines:
        if len(line) < 25:
            continue
        is_numbered = bool(REQ_NUMBERED.search(line))
        has_trigger = bool(REQ_TRIGGER.search(line))
        if has_trigger and (is_numbered or "offeror" in line.lower() or "proposal" in line.lower() or "submit" in line.lower()):
            norm = line.lower()
            if norm in seen:
                continue
            seen.add(norm)
            reqs.append(line)
            if len(reqs) >= max_reqs:
                break
    return reqs


def auto_map_section(req_text: str) -> str:
    t = (req_text or "").lower()
    if "past performance" in t or "cpars" in t:
        return "Past Performance"
    if "management" in t or "key personnel" in t or "resume" in t:
        return "Management Plan"
    if "technical" in t or "approach" in t or "solution" in t:
        return "Technical Approach"
    if "executive summary" in t or "summary" in t:
        return "Executive Summary"
    if "cover letter" in t or "signed" in t or "signature" in t:
        return "Cover Letter"
    return "Technical Approach"


# ============================================================
# Company info
# ============================================================
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
    website: str = ""
    certifications: List[str] = None
    capabilities: str = ""
    differentiators: str = ""
    past_performance: str = ""

    proposal_title: str = ""
    solicitation_number: str = ""
    agency_customer: str = ""

    signer_name: str = ""
    signer_title: str = ""
    signer_company: str = ""
    signer_phone: str = ""
    signer_email: str = ""

    def to_dict(self):
        d = asdict(self)
        if d["certifications"] is None:
            d["certifications"] = []
        return d


def missing_info_alerts(company: CompanyInfo) -> Tuple[List[str], List[str]]:
    critical = []
    recommended = []

    if not company.legal_name.strip():
        critical.append("Company legal name is missing.")
    if not company.uei.strip():
        critical.append("UEI is missing.")
    if not company.poc_name.strip():
        critical.append("Point of contact name is missing.")
    if not company.poc_email.strip():
        critical.append("Point of contact email is missing.")

    if not company.address.strip():
        recommended.append("Business address is missing.")
    if not company.capabilities.strip():
        recommended.append("Capabilities section is empty.")
    if not company.differentiators.strip():
        recommended.append("Differentiators section is empty.")
    if not company.proposal_title.strip():
        recommended.append("Proposal/Contract title is blank.")
    if not company.solicitation_number.strip():
        recommended.append("Solicitation number is blank.")
    if not company.agency_customer.strip():
        recommended.append("Agency/Customer is blank.")

    return critical, recommended


# ============================================================
# AI (OpenAI)
# ============================================================
def get_openai_key() -> Optional[str]:
    try:
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass
    import os
    return os.environ.get("OPENAI_API_KEY")


def openai_chat(messages: List[Dict[str, str]], model: str = "gpt-4.1-mini", temperature: float = 0.2, max_tokens: int = 450) -> Optional[str]:
    api_key = get_openai_key()
    if not api_key:
        return None

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=25)
        if r.status_code >= 300:
            return None
        data = r.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    except Exception:
        return None


def heuristic_gate_item(text: str, kind: str) -> Tuple[str, float, str]:
    low = (text or "").lower()

    bucket = "Other"
    if kind == "rule":
        bucket = "Submission & Format"
    elif kind == "form":
        bucket = "Required Forms"
    elif kind == "attachment":
        bucket = "Attachments/Exhibits"
    elif kind == "amendment":
        bucket = "Amendments"
    elif kind == "requirement":
        bucket = "Compliance Requirements"
    elif kind == "field_missing":
        bucket = "Company Profile"

    actionable_hits = 0
    if any(k in low for k in ["due date", "deadline", "no later than", "offers are due", "proposal is due"]):
        actionable_hits += 4
    if any(k in low for k in ["submit", "submission", "portal", "email", "upload", "fedconnect", "ebuy", "piee", "sam.gov"]):
        actionable_hits += 3
    if any(k in low for k in ["page limit", "not exceed", "font", "margins", "file format", "pdf", "docx", "xlsx", "excel", "zip"]):
        actionable_hits += 3
    if kind in ["form", "attachment", "amendment", "field_missing"]:
        actionable_hits += 3
    if kind == "requirement" and any(k in low for k in ["shall", "must", "will"]):
        actionable_hits += 2

    if len(text) < 20:
        return "IRRELEVANT", 0.70, bucket

    if actionable_hits >= 4:
        return "ACTIONABLE", score_to_confidence(min(10, actionable_hits), 10), bucket

    if kind in ["form", "attachment", "amendment", "field_missing", "requirement"]:
        return "ACTIONABLE", 0.68, bucket

    return "INFORMATIONAL", 0.60, bucket


def ai_gate_item(text: str, kind: str, context_hint: str = "") -> Tuple[str, float, str]:
    h_label, h_conf, h_bucket = heuristic_gate_item(text, kind)

    if not st.session_state.get("ai_enabled", False):
        return h_label, h_conf, h_bucket

    prompt = f"""
Classify proposal item into one gating label:
ACTIONABLE, INFORMATIONAL, IRRELEVANT, AUTO_RESOLVED
Also return confidence 0.00–1.00 and bucket:
Submission & Format, Required Forms, Attachments/Exhibits, Amendments,
Compliance Requirements, Company Profile, Other
Return ONLY JSON: {{ "gating_label": "...", "confidence": 0.0, "bucket": "..." }}

kind: {kind}
context: {context_hint}
text: {text}
""".strip()

    out = openai_chat(
        [{"role": "system", "content": "Return only JSON."}, {"role": "user", "content": prompt}],
        model=st.session_state.get("ai_model", "gpt-4.1-mini"),
        temperature=0.1,
        max_tokens=220
    )
    if not out:
        return h_label, h_conf, h_bucket

    try:
        j = json.loads(out)
        gl = (j.get("gating_label") or "").strip().upper()
        cf = float(j.get("confidence", h_conf))
        bk = (j.get("bucket") or h_bucket).strip()
        if gl not in GATING_LABELS:
            return h_label, h_conf, h_bucket
        cf = max(0.0, min(1.0, cf))
        return gl, cf, (bk or h_bucket)
    except Exception:
        return h_label, h_conf, h_bucket


def ai_write_drafts(company: CompanyInfo, rfp_text: str) -> Optional[Dict[str, str]]:
    if not st.session_state.get("ai_enabled", False):
        return None

    company_block = json.dumps(company.to_dict(), indent=2)[:2500]
    rfp_excerpt = (rfp_text or "")[:6000]

    prompt = f"""
Write a concise, professional federal proposal draft with these sections:
Executive Summary, Technical Approach, Management Plan, Past Performance.
Do NOT invent certifications or past performance.

Return ONLY JSON with those keys.

Company JSON:
{company_block}

RFP excerpt:
{rfp_excerpt}
""".strip()

    out = openai_chat(
        [{"role": "system", "content": "Return only JSON."}, {"role": "user", "content": prompt}],
        model=st.session_state.get("ai_model", "gpt-4.1-mini"),
        temperature=0.25,
        max_tokens=1200
    )
    if not out:
        return None

    try:
        j = json.loads(out)
        if not isinstance(j, dict):
            return None
        for k in ["Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]:
            if k not in j:
                return None
        return {k: str(j[k]).strip() for k in ["Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]}
    except Exception:
        return None


# ============================================================
# Build items
# ============================================================
def build_items_from_analysis(
    rfp_text: str,
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    amendments: List[str],
    requirements: List[str],
    company: CompanyInfo
) -> List[ProposalItem]:
    items: List[ProposalItem] = []
    seq = 1

    def add(kind: str, text: str, source: str, context_hint: str = ""):
        nonlocal seq
        gl, cf, bucket = ai_gate_item(text=text, kind=kind, context_hint=context_hint)
        items.append(
            ProposalItem(
                id=f"I{seq:04d}",
                kind=kind,
                text=text,
                source=source,
                bucket=bucket,
                gating_label=gl,
                confidence=cf
            )
        )
        seq += 1

    for label, lines in (rules or {}).items():
        for ln in lines:
            add("rule", f"{label}: {ln}", "Submission Rules", "Submission compliance rules")

    for f in (forms or []):
        add("form", f, "Forms", "Required government forms")

    for a in (attachments or []):
        add("attachment", a, "Attachments", "Attachment/exhibit mention")

    for a in (amendments or []):
        add("amendment", a, "Amendments", "Amendment/mod mention")

    for req in (requirements or []):
        add("requirement", req, "RFP", "Compliance requirement")

    # Missing critical company fields as tasks
    critical, _ = missing_info_alerts(company)
    for c in critical:
        add("field_missing", c, "Company Profile", "Missing critical company field")

    # De-dupe by text
    out = []
    seen = set()
    for it in items:
        k = (it.kind + "|" + it.text.strip().lower())
        if k not in seen:
            seen.add(k)
            out.append(it)

    # Map requirement sections
    for it in out:
        if it.kind == "requirement":
            it.mapped_section = auto_map_section(it.text)
            it.status = "Unknown"

    return out


def get_actionable_items(items: List[ProposalItem]) -> List[ProposalItem]:
    return [i for i in (items or []) if i.gating_label == "ACTIONABLE"]


def get_informational_items(items: List[ProposalItem]) -> List[ProposalItem]:
    return [i for i in (items or []) if i.gating_label == "INFORMATIONAL"]


def completion_stats(items: List[ProposalItem], checks: Dict[str, bool]) -> Tuple[int, int, int]:
    act = get_actionable_items(items)
    total = len(act)
    done = sum(1 for i in act if checks.get(i.id, False))
    remaining = max(0, total - done)
    return total, done, remaining


def kpi_color(level: str) -> str:
    return {"good": "pill-green", "warn": "pill-yellow", "bad": "pill-red"}.get(level, "pill-blue")


# ============================================================
# DOCX export
# ============================================================
def add_field(paragraph, field_code: str):
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
    section = doc.sections[0]
    footer = section.footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("Page ")
    add_field(p, "PAGE")
    p.add_run(" of ")
    add_field(p, "NUMPAGES")


def add_table_of_contents(doc: docx.Document):
    doc.add_page_break()
    doc.add_heading("Table of Contents", level=1)
    p = doc.add_paragraph()
    add_field(p, r'TOC \o "1-3" \z \u')
    doc.add_page_break()


def add_title_page(doc: docx.Document, company: CompanyInfo, logo_bytes: Optional[bytes]):
    doc.add_paragraph("")
    doc.add_paragraph("")

    if logo_bytes:
        try:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(io.BytesIO(logo_bytes), width=Inches(2.2))
            doc.add_paragraph("")
        except Exception:
            pass

    title = company.proposal_title.strip() or "Proposal"
    company_name = company.legal_name.strip() or "[Company Name]"
    sol = company.solicitation_number.strip() or "[Solicitation #]"
    agency = company.agency_customer.strip() or "[Agency/Customer]"

    p1 = doc.add_paragraph(); p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p1.add_run(company_name); r1.bold = True

    p2 = doc.add_paragraph(); p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run(title); r2.bold = True

    doc.add_paragraph("")
    p3 = doc.add_paragraph(); p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p3.add_run(f"Solicitation: {sol}")

    p4 = doc.add_paragraph(); p4.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p4.add_run(f"Agency/Customer: {agency}")

    doc.add_paragraph("")
    p5 = doc.add_paragraph(); p5.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p5.add_run(f"UEI: {company.uei or '[UEI]'}    CAGE: {company.cage or '[CAGE]'}")

    doc.add_page_break()


def signature_block(company: CompanyInfo) -> str:
    signer_name = (company.signer_name.strip() or company.poc_name.strip())
    signer_title = company.signer_title.strip()
    signer_company = (company.signer_company.strip() or company.legal_name.strip())
    signer_phone = (company.signer_phone.strip() or company.poc_phone.strip())
    signer_email = (company.signer_email.strip() or company.poc_email.strip())

    lines = ["Respectfully,", "", "", ""]
    if signer_name: lines.append(signer_name)
    if signer_title: lines.append(signer_title)
    if signer_company: lines.append(signer_company)
    if signer_phone: lines.append(signer_phone)
    if signer_email: lines.append(signer_email)
    return "\n".join(lines).strip()


def add_paragraph_lines(doc: docx.Document, text: str):
    for line in (text or "").splitlines():
        doc.add_paragraph(line)


def build_docx_package(company: CompanyInfo, logo_bytes: Optional[bytes], diag: Dict[str, Any],
                       items: List[ProposalItem], drafts: Dict[str, str], rules: Dict[str, List[str]],
                       task_checks: Dict[str, bool]) -> bytes:
    doc = docx.Document()
    add_page_numbers(doc)
    add_title_page(doc, company, logo_bytes)
    add_table_of_contents(doc)

    doc.add_heading("Diagnostics Summary", level=1)
    if diag:
        doc.add_paragraph(f"File Type: {diag.get('file_type','—')}")
        if diag.get("pages_total") is not None:
            doc.add_paragraph(f"Pages: {diag.get('pages_total','—')}")
        if diag.get("pages_with_text") is not None:
            doc.add_paragraph(f"Pages with text: {diag.get('pages_with_text','—')}")
        doc.add_paragraph(f"Characters extracted: {diag.get('chars_extracted','—')}")
        doc.add_paragraph(f"Likely scanned: {'Yes' if diag.get('likely_scanned') else 'No'}")
    doc.add_page_break()

    doc.add_heading("Submission Essentials", level=1)
    if rules:
        for k, lines in rules.items():
            doc.add_paragraph(k, style="List Bullet")
            for ln in (lines or [])[:6]:
                doc.add_paragraph(ln, style="List Bullet 2")
    else:
        doc.add_paragraph("No submission rules detected.", style="List Bullet")

    doc.add_page_break()

    doc.add_heading("Actionable Task Checklist", level=1)
    act = get_actionable_items(items)
    if act:
        for it in act:
            checked = task_checks.get(it.id, False)
            mark = "☑" if checked else "☐"
            doc.add_paragraph(f"{mark} [{it.bucket}] {it.text}", style="List Bullet")
    else:
        doc.add_paragraph("No actionable tasks detected.", style="List Bullet")
    doc.add_page_break()

    doc.add_heading("Draft Proposal Sections", level=1)

    doc.add_heading("Cover Letter", level=2)
    cover = f"""COVER LETTER

{company.legal_name or "[Company Name]"}
{company.address or "[Address]"}
UEI: {company.uei or "[UEI]"} | CAGE: {company.cage or "[CAGE]"}
POC: {company.poc_name or "[POC]"} | {company.poc_email or "[email]"} | {company.poc_phone or "[phone]"}

Subject: {company.proposal_title or "Proposal Submission"}

Dear Contracting Officer,

{company.legal_name or "[Company Name]"} submits this proposal in response to the solicitation and will execute with a low-risk approach aligned to schedule, quality, reporting, and risk management.

{signature_block(company)}
"""
    add_paragraph_lines(doc, cover)

    for title in ["Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]:
        if title in drafts:
            doc.add_heading(title, level=2)
            add_paragraph_lines(doc, drafts[title])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_matrix_csv(items: List[ProposalItem]) -> str:
    rows = ["id,kind,bucket,gating_label,confidence,status,mapped_section,text,notes"]
    for it in items:
        if it.kind != "requirement":
            continue
        row = [
            it.id, it.kind, it.bucket, it.gating_label, str(it.confidence),
            it.status, (it.mapped_section or ""),
            '"' + (it.text or "").replace('"', '""') + '"',
            '"' + (it.notes or "").replace('"', '""') + '"'
        ]
        rows.append(",".join(row))
    return "\n".join(rows)


# ============================================================
# Persistence (FIXED: uses st.session_state["items"] not .items)
# ============================================================
def b64_from_bytes(b: Optional[bytes]) -> Optional[str]:
    if not b:
        return None
    return base64.b64encode(b).decode("utf-8")


def bytes_from_b64(s: Optional[str]) -> Optional[bytes]:
    if not s:
        return None
    try:
        return base64.b64decode(s.encode("utf-8"))
    except Exception:
        return None


def export_project_json() -> str:
    c: CompanyInfo = st.session_state["company"]
    payload = {
        "build": {"version": BUILD_VERSION, "date": BUILD_DATE},
        "rfp_text": st.session_state["rfp_text"],
        "rfp_diag": st.session_state["rfp_diag"],
        "rules": st.session_state["rules"],
        "forms": st.session_state["forms"],
        "attachments": st.session_state["attachments"],
        "amendments": st.session_state["amendments"],
        "company": c.to_dict(),
        "logo_b64": b64_from_bytes(st.session_state["logo_bytes"]),
        "items": [asdict(i) for i in (st.session_state["items"] or [])],
        "task_checks": st.session_state["task_checks"],
        "drafts": st.session_state["drafts"],
        "analysis_done": st.session_state["analysis_done"],
        "ai_enabled": st.session_state["ai_enabled"],
        "ai_model": st.session_state["ai_model"],
        "step": st.session_state["step"],
    }
    return json.dumps(payload, indent=2)


def import_project_json(s: str) -> Tuple[bool, str]:
    try:
        payload = json.loads(s)
        if not isinstance(payload, dict):
            return False, "Invalid project file."

        st.session_state["rfp_text"] = payload.get("rfp_text", "") or ""
        st.session_state["rfp_diag"] = payload.get("rfp_diag", {}) or {}
        st.session_state["rules"] = payload.get("rules", {}) or {}
        st.session_state["forms"] = payload.get("forms", []) or []
        st.session_state["attachments"] = payload.get("attachments", []) or []
        st.session_state["amendments"] = payload.get("amendments", []) or []

        company_dict = payload.get("company", {}) or {}
        c = CompanyInfo(certifications=[])
        for k, v in company_dict.items():
            if hasattr(c, k):
                setattr(c, k, v)
        if c.certifications is None:
            c.certifications = []
        st.session_state["company"] = c

        st.session_state["logo_bytes"] = bytes_from_b64(payload.get("logo_b64"))

        st.session_state["items"] = [ProposalItem(**i) for i in (payload.get("items") or [])]
        st.session_state["task_checks"] = payload.get("task_checks", {}) or {}
        st.session_state["drafts"] = payload.get("drafts", {}) or {}
        st.session_state["analysis_done"] = bool(payload.get("analysis_done", False))
        st.session_state["ai_enabled"] = bool(payload.get("ai_enabled", False))
        st.session_state["ai_model"] = payload.get("ai_model", "gpt-4.1-mini")
        st.session_state["step"] = payload.get("step", 0)

        return True, "Project loaded."
    except Exception as e:
        return False, f"Could not load project: {e}"


# ============================================================
# Session init (BRACKET STYLE)
# ============================================================
def ss_init(key: str, value):
    if key not in st.session_state:
        st.session_state[key] = value


ss_init("rfp_text", "")
ss_init("rfp_diag", {})
ss_init("rules", {})
ss_init("forms", [])
ss_init("attachments", [])
ss_init("amendments", [])
ss_init("company", CompanyInfo(certifications=[]))
ss_init("logo_bytes", None)
ss_init("items", [])
ss_init("task_checks", {})
ss_init("drafts", {})
ss_init("analysis_done", False)
ss_init("ai_enabled", False)
ss_init("ai_model", "gpt-4.1-mini")
ss_init("step", 0)

# ============================================================
# UI Header
# ============================================================
st.markdown(
    f"""
    <div class="brandbar">
      <div class="brand-left">
        <div class="brand-dot"></div>
        <div>
          <div class="brand-title">{APP_NAME}</div>
          <div class="brand-sub">{BUILD_VERSION} • {BUILD_DATE}</div>
        </div>
      </div>
      <div class="muted">Proposal prep — guided and focused</div>
    </div>
    """,
    unsafe_allow_html=True
)

# ============================================================
# Sidebar
# ============================================================
st.sidebar.title(APP_NAME)

with st.sidebar.expander("AI Settings", expanded=False):
    key_present = bool(get_openai_key())
    st.session_state["ai_enabled"] = st.toggle("Enable AI (gating + drafts)", value=st.session_state["ai_enabled"], disabled=not key_present)
    st.session_state["ai_model"] = st.selectbox("AI model", options=["gpt-4.1-mini", "gpt-4.1"], index=0)
    if not key_present:
        ui_notice("AI off", "Add OPENAI_API_KEY in Render → Environment to enable AI.", tone="warn")

with st.sidebar.expander("Project Save / Load", expanded=False):
    st.download_button(
        "Download Project (.json)",
        data=export_project_json(),
        file_name="path_ai_project.json",
        mime="application/json"
    )
    up_proj = st.file_uploader("Upload Project (.json)", type=["json"], key="proj_uploader")
    if up_proj:
        ok, msg = import_project_json(up_proj.read().decode("utf-8", errors="ignore"))
        if ok:
            ui_notice("Loaded", "Project restored.", tone="good")
        else:
            ui_notice("Load failed", msg, tone="bad")

steps = ["Intake", "Company", "Compliance", "Draft", "Export"]
chosen = st.sidebar.radio("Navigate", options=list(range(len(steps))), format_func=lambda i: steps[i], index=st.session_state["step"])


def can_enter_step(target_step: int) -> Tuple[bool, str]:
    if target_step <= 0:
        return True, ""
    if target_step >= 1:
        if not st.session_state["rfp_text"].strip() or not st.session_state["analysis_done"]:
            return False, "Complete Intake and run Analyze first."
    if target_step >= 2:
        crit, _ = missing_info_alerts(st.session_state["company"])
        if crit:
            return False, "Complete critical Company fields first."
    if target_step >= 3:
        crit, _ = missing_info_alerts(st.session_state["company"])
        if crit:
            return False, "Complete critical Company fields first."
        if not st.session_state["items"]:
            return False, "Run Analyze in Intake first."
    if target_step >= 4:
        if not (st.session_state["drafts"] or {}):
            return False, "Generate drafts first."
    return True, ""


allowed, why = can_enter_step(chosen)
if not allowed:
    ui_notice("Not yet", why, tone="warn")
    chosen = st.session_state["step"]
else:
    st.session_state["step"] = chosen

# Top progress
items_now = st.session_state["items"] or []
total_tasks, done_tasks, remaining_tasks = completion_stats(items_now, st.session_state["task_checks"] or {})
pct = int(round((done_tasks / max(1, total_tasks)) * 100)) if total_tasks else 0
st.progress(pct / 100.0)

crit, _ = missing_info_alerts(st.session_state["company"])
gate_css = kpi_color("warn" if (not st.session_state["analysis_done"] or crit) else "good")
gate_label = "In Progress" if (not st.session_state["analysis_done"] or crit) else "Ready"

st.markdown(
    f"""
    <div class="card">
      <h4>Progress</h4>
      <div class="muted">Actionable tasks drive progress. Informational items stay tucked away in Reference.</div>
      <div class="divider"></div>
      <span class="pill pill-blue">Tasks: {total_tasks}</span>
      <span class="pill pill-green">Done: {done_tasks}</span>
      <span class="pill pill-yellow">Remaining: {remaining_tasks}</span>
      <span class="pill {gate_css}">Gate: {gate_label}</span>
      <span class="pill pill-red">Missing critical fields: {len(crit)}</span>
    </div>
    """,
    unsafe_allow_html=True
)

# Nav buttons
col_nav1, col_nav2, col_nav3 = st.columns([1, 1, 6])
with col_nav1:
    if st.button("⬅ Back", use_container_width=True, disabled=(st.session_state["step"] == 0)):
        st.session_state["step"] = max(0, st.session_state["step"] - 1)
        st.rerun()
with col_nav2:
    nxt = min(len(steps) - 1, st.session_state["step"] + 1)
    ok_next, why_next = can_enter_step(nxt)
    if st.button("Next ➜", use_container_width=True, disabled=not ok_next):
        st.session_state["step"] = nxt
        st.rerun()
with col_nav3:
    if not ok_next and st.session_state["step"] < len(steps) - 1:
        st.caption(f"To continue: {why_next}")


# ============================================================
# Pages
# ============================================================
def page_intake():
    st.subheader("Intake")

    left, right = st.columns([1.1, 0.9], gap="large")

    with left:
        uploaded = st.file_uploader("Upload RFP (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"])
        pasted = st.text_area("Or paste text", value=st.session_state["rfp_text"], height=260)

        if st.button("Analyze", use_container_width=True):
            text = ""
            diag = {}

            if uploaded:
                text, diag = read_uploaded_file(uploaded)
                st.session_state["rfp_diag"] = diag

            if pasted.strip():
                text = pasted.strip()

            if not text.strip():
                ui_notice("Missing input", "Upload a readable file or paste text to continue.", tone="bad")
                return

            st.session_state["rfp_text"] = text

            rules = detect_submission_rules(text)
            forms = find_forms(text)
            attachments = find_attachment_lines(text)
            amendments = detect_amendment_lines(text)
            reqs = extract_requirements_best_effort(text)

            st.session_state["rules"] = rules
            st.session_state["forms"] = forms
            st.session_state["attachments"] = attachments
            st.session_state["amendments"] = amendments

            st.session_state["items"] = build_items_from_analysis(
                rfp_text=text,
                rules=rules,
                forms=forms,
                attachments=attachments,
                amendments=amendments,
                requirements=reqs,
                company=st.session_state["company"]
            )

            checks = st.session_state["task_checks"] or {}
            for it in get_actionable_items(st.session_state["items"]):
                if it.id not in checks:
                    checks[it.id] = False
            st.session_state["task_checks"] = checks

            st.session_state["analysis_done"] = True
            ui_notice("Analysis complete", "Next: fill Company info.", tone="good")

    with right:
        diag = st.session_state["rfp_diag"] or {}
        if diag:
            scanned = "Yes" if diag.get("likely_scanned") else "No"
            st.markdown(
                f"""
                <div class="card">
                  <h4>File readability</h4>
                  <div class="divider"></div>
                  <div class="muted"><b>Type:</b> {diag.get('file_type','—')}</div>
                  <div class="muted"><b>Pages:</b> {diag.get('pages_total','—')} • <b>Pages w/ text:</b> {diag.get('pages_with_text','—')}</div>
                  <div class="muted"><b>Chars extracted:</b> {diag.get('chars_extracted','—')}</div>
                  <div class="muted"><b>Likely scanned:</b> {scanned}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            if diag.get("likely_scanned"):
                ui_notice("Scanned PDF", "Text extraction can miss requirements. If possible, paste the solicitation text.", tone="warn")
        else:
            ui_notice("No file diagnostics", "Upload a file to see readability stats.", tone="neutral")


def page_company():
    st.subheader("Company")
    c: CompanyInfo = st.session_state["company"]

    logo = st.file_uploader("Upload logo (PNG/JPG) (optional)", type=["png", "jpg", "jpeg"])
    if logo:
        st.session_state["logo_bytes"] = logo.read()
        ui_notice("Saved", "Logo will appear on the export.", tone="good")
        st.image(st.session_state["logo_bytes"], width=180)

    colA, colB, colC = st.columns(3)
    with colA:
        c.proposal_title = st.text_input("Proposal/Contract Title", value=c.proposal_title)
    with colB:
        c.solicitation_number = st.text_input("Solicitation Number", value=c.solicitation_number)
    with colC:
        c.agency_customer = st.text_input("Agency/Customer", value=c.agency_customer)

    col1, col2 = st.columns(2)
    with col1:
        c.legal_name = st.text_input("Legal Company Name", value=c.legal_name)
        c.uei = st.text_input("UEI", value=c.uei)
        c.cage = st.text_input("CAGE (optional)", value=c.cage)
        c.naics = st.text_input("Primary NAICS (optional)", value=c.naics)
    with col2:
        c.address = st.text_area("Business Address", value=c.address, height=120)
        c.poc_name = st.text_input("Point of Contact Name", value=c.poc_name)
        c.poc_email = st.text_input("Point of Contact Email", value=c.poc_email)
        c.poc_phone = st.text_input("Point of Contact Phone", value=c.poc_phone)

    c.capabilities = st.text_area("Capabilities", value=c.capabilities, height=100)
    c.differentiators = st.text_area("Differentiators", value=c.differentiators, height=90)
    c.past_performance = st.text_area("Past performance (optional)", value=c.past_performance, height=120)

    st.session_state["company"] = c

    crit, rec = missing_info_alerts(c)
    if crit:
        ui_notice("Missing critical fields", "Complete these before moving forward: " + " • ".join(crit), tone="warn")
    else:
        ui_notice("Looks good", "Critical fields are complete.", tone="good")

    if st.button("Refresh tasks (company changes)", use_container_width=True):
        if st.session_state["rfp_text"].strip() and st.session_state["analysis_done"]:
            reqs = [it.text for it in (st.session_state["items"] or []) if it.kind == "requirement"]
            st.session_state["items"] = build_items_from_analysis(
                rfp_text=st.session_state["rfp_text"],
                rules=st.session_state["rules"],
                forms=st.session_state["forms"],
                attachments=st.session_state["attachments"],
                amendments=st.session_state["amendments"],
                requirements=reqs,
                company=st.session_state["company"]
            )
            checks = st.session_state["task_checks"] or {}
            for it in get_actionable_items(st.session_state["items"]):
                checks.setdefault(it.id, False)
            st.session_state["task_checks"] = checks
            ui_notice("Updated", "Tasks refreshed.", tone="good")


def page_compliance():
    st.subheader("Compliance")

    items = st.session_state["items"] or []
    if not items:
        ui_notice("Nothing to review yet", "Go back to Intake and run Analyze.", tone="warn")
        return

    checks = st.session_state["task_checks"] or {}
    actionable = get_actionable_items(items)
    info = get_informational_items(items)

    buckets_order = [
        "Submission & Format",
        "Required Forms",
        "Attachments/Exhibits",
        "Amendments",
        "Company Profile",
        "Compliance Requirements",
        "Other",
    ]

    st.markdown("### Tasks")
    if not actionable:
        ui_notice("No tasks found", "No actionable items detected from current text.", tone="neutral")
    else:
        for bucket in buckets_order:
            bucket_items = [i for i in actionable if i.bucket == bucket]
            if not bucket_items:
                continue
            with st.expander(bucket, expanded=(bucket in ["Submission & Format", "Company Profile"])):
                for it in bucket_items:
                    checks.setdefault(it.id, False)
                    checks[it.id] = st.checkbox(it.text, value=checks[it.id], key=f"task_{it.id}")

                    if it.kind == "requirement":
                        cols = st.columns([1, 1.2, 2])
                        with cols[0]:
                            it.status = st.selectbox(
                                "Status",
                                options=["Pass", "Fail", "Unknown"],
                                index=["Pass", "Fail", "Unknown"].index(it.status if it.status in ["Pass", "Fail", "Unknown"] else "Unknown"),
                                key=f"status_{it.id}"
                            )
                        with cols[1]:
                            it.mapped_section = st.selectbox(
                                "Mapped section",
                                options=DEFAULT_SECTIONS,
                                index=DEFAULT_SECTIONS.index(it.mapped_section) if it.mapped_section in DEFAULT_SECTIONS else 2,
                                key=f"map_{it.id}"
                            )
                        with cols[2]:
                            it.notes = st.text_input("Notes (optional)", value=it.notes, key=f"notes_{it.id}")

    st.session_state["task_checks"] = checks

    st.markdown("---")
    st.markdown("### Reference (collapsed)")
    with st.expander("Open Reference", expanded=False):
        if not info:
            st.write("No informational items.")
        else:
            q = st.text_input("Search reference", value="", placeholder="type to filter")
            filt = (q or "").strip().lower()
            show = info if not filt else [i for i in info if filt in i.text.lower() or filt in i.source.lower() or filt in i.bucket.lower()]
            for i in show[:120]:
                st.markdown(
                    f"""
                    <div class="card">
                      <h4>{i.bucket}</h4>
                      <div class="muted">{i.source} • confidence {i.confidence}</div>
                      <div class="divider"></div>
                      <div>{i.text}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )


def page_draft():
    st.subheader("Draft")

    c: CompanyInfo = st.session_state["company"]
    crit, _ = missing_info_alerts(c)
    if crit:
        ui_notice("Company info needed", "Finish critical company fields in Company step.", tone="warn")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Generate AI Drafts", use_container_width=True, disabled=not st.session_state["ai_enabled"]):
            d = ai_write_drafts(company=c, rfp_text=st.session_state["rfp_text"])
            if d:
                st.session_state["drafts"] = d
                ui_notice("Drafts created", "Review and adjust anything you want.", tone="good")
            else:
                ui_notice("AI draft failed", "AI did not return valid output. Check API key or try again.", tone="bad")
    with col2:
        if st.button("Clear drafts", use_container_width=True):
            st.session_state["drafts"] = {}
            ui_notice("Cleared", "Drafts removed.", tone="neutral")

    drafts = st.session_state["drafts"] or {}
    if not drafts:
        ui_notice("No drafts yet", "Enable AI in sidebar and generate drafts.", tone="neutral")
        return

    for k in ["Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]:
        if k in drafts:
            with st.expander(k, expanded=(k == "Executive Summary")):
                drafts[k] = st.text_area(k, value=drafts[k], height=260)
    st.session_state["drafts"] = drafts


def page_export():
    st.subheader("Export")

    if not (st.session_state["drafts"] or {}):
        ui_notice("Drafts needed", "Go to Draft and generate drafts before export.", tone="warn")
        return

    c: CompanyInfo = st.session_state["company"]
    doc_bytes = build_docx_package(
        company=c,
        logo_bytes=st.session_state["logo_bytes"],
        diag=st.session_state["rfp_diag"],
        items=st.session_state["items"],
        drafts=st.session_state["drafts"],
        rules=st.session_state["rules"],
        task_checks=st.session_state["task_checks"] or {}
    )

    st.download_button(
        "Download Proposal Package (.docx)",
        data=doc_bytes,
        file_name="PathAI_Proposal_Package.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True
    )

    csv_text = build_matrix_csv(st.session_state["items"] or [])
    st.download_button(
        "Download Compliance Matrix (.csv)",
        data=csv_text.encode("utf-8"),
        file_name="PathAI_Compliance_Matrix.csv",
        mime="text/csv",
        use_container_width=True
    )


# ============================================================
# Render current step
# ============================================================
step = st.session_state["step"]
if step == 0:
    page_intake()
elif step == 1:
    page_company()
elif step == 2:
    page_compliance()
elif step == 3:
    page_draft()
else:
    page_export()