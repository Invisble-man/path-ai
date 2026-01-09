import io
import json
import re
import base64
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional, Any

import streamlit as st
from pypdf import PdfReader
import docx  # python-docx

from docx.shared import Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# =========================
# App Config
# =========================
st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")

BUILD_VERSION = "v0.12.0"
BUILD_DATE = "Jan 9, 2026"

# =========================
# UI Styling (website look)
# =========================
def inject_css():
    st.markdown(
        """
        <style>
        /* General page spacing */
        .block-container { padding-top: 1.0rem; padding-bottom: 2.5rem; }

        /* Sticky KPI header */
        .kpi-wrap {
            position: sticky;
            top: 0.5rem;
            z-index: 999;
            background: rgba(255,255,255,0.92);
            backdrop-filter: blur(6px);
            border: 1px solid rgba(49,51,63,0.15);
            border-radius: 14px;
            padding: 12px 14px;
            margin-bottom: 12px;
        }
        .kpi-title {
            font-weight: 700;
            font-size: 0.95rem;
            margin: 0 0 6px 0;
        }
        .pill {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 0.85rem;
            font-weight: 600;
            border: 1px solid rgba(49,51,63,0.15);
            margin-right: 8px;
            margin-bottom: 6px;
        }
        .pill-good { background: rgba(46, 204, 113, 0.12); }
        .pill-warn { background: rgba(241, 196, 15, 0.14); }
        .pill-bad  { background: rgba(231, 76, 60, 0.14); }

        /* Card UI */
        .card {
            border: 1px solid rgba(49,51,63,0.15);
            border-radius: 14px;
            padding: 14px 14px 12px 14px;
            margin-bottom: 12px;
            background: rgba(255,255,255,0.90);
        }
        .card h4 { margin: 0 0 6px 0; font-size: 0.95rem; }
        .muted { color: rgba(49,51,63,0.65); font-size: 0.88rem; }
        .small { font-size: 0.86rem; }
        .divider { height: 1px; background: rgba(49,51,63,0.10); margin: 10px 0; }

        /* Website-style notices (replaces st.info blue boxes) */
        .notice {
            border-radius: 14px;
            padding: 12px 14px;
            border: 1px solid rgba(49,51,63,0.15);
            background: rgba(255,255,255,0.88);
            margin: 10px 0 12px 0;
        }
        .notice-title { font-weight: 700; margin: 0 0 4px 0; font-size: 0.95rem; }
        .notice-body { margin: 0; font-size: 0.92rem; color: rgba(49,51,63,0.85); }
        .notice-neutral { background: rgba(52, 73, 94, 0.06); }
        .notice-good    { background: rgba(46, 204, 113, 0.10); }
        .notice-warn    { background: rgba(241, 196, 15, 0.12); }
        .notice-bad     { background: rgba(231, 76, 60, 0.12); }

        /* Make checkboxes more compact */
        div[data-testid="stCheckbox"] label p { font-size: 0.92rem; }

        /* Tighten expanders */
        div[data-testid="stExpander"] details summary p { font-size: 0.95rem; }

        /* Slightly larger primary headers */
        h1, h2, h3 { letter-spacing: -0.2px; }
        </style>
        """,
        unsafe_allow_html=True
    )

inject_css()

def ui_notice(title: str, body: str, tone: str = "neutral"):
    tone_class = {
        "neutral": "notice-neutral",
        "good": "notice-good",
        "warn": "notice-warn",
        "bad": "notice-bad",
    }.get(tone, "notice-neutral")

    st.markdown(
        f"""
        <div class="notice {tone_class}">
            <div class="notice-title">{title}</div>
            <p class="notice-body">{body}</p>
        </div>
        """,
        unsafe_allow_html=True
    )

# =========================
# Label cleaning (TurboTax-like UI)
# =========================
def label_clean(title: str) -> str:
    """
    Cleans UI labels:
    - Removes leading "A) ", "D) ", "1) ", "3) ", etc.
    - Removes suffixes like "(starter)" and "(Detected)"
    """
    t = (title or "").strip()
    # leading enumerations
    t = re.sub(r"^\s*[A-Za-z]\)\s+", "", t)         # D) Something
    t = re.sub(r"^\s*\d+\)\s+", "", t)              # 3) Something
    t = re.sub(r"^\s*\d+\.\s+", "", t)              # 3. Something
    # trailing noise
    t = re.sub(r"\s*\(starter\)\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\(detected(?:-only)?\)\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\(detected\)\s*$", "", t, flags=re.IGNORECASE)
    return t.strip()

# =========================
# Helpers
# =========================
def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()

def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        k = (x or "").lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

def scan_lines(text: str, max_lines: int = 10000) -> List[str]:
    lines = []
    for raw in (text or "").splitlines():
        s = normalize_line(raw)
        if s:
            lines.append(s)
        if len(lines) >= max_lines:
            break
    return lines

def _contains_any(text: str, keywords: List[str]) -> bool:
    low = (text or "").lower()
    return any(k in low for k in keywords)

# =========================
# Extraction (PDF/DOCX/TXT)
# =========================
def extract_text_from_pdf(file_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
    diag = {
        "file_type": "pdf",
        "pages_total": 0,
        "pages_with_text": 0,
        "chars_extracted": 0,
        "likely_scanned": False,
    }

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
        diag = {
            "file_type": "docx",
            "pages_total": None,
            "pages_with_text": None,
            "chars_extracted": len(text),
            "likely_scanned": False,
        }
        return text, diag

    try:
        text = data.decode("utf-8", errors="ignore").strip()
    except Exception:
        text = ""

    diag = {
        "file_type": "text",
        "pages_total": None,
        "pages_with_text": None,
        "chars_extracted": len(text),
        "likely_scanned": False,
    }
    return text, diag

# =========================
# RFP Intelligence
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
    (r"\bdue\b|\bdue date\b|\bdeadline\b|\bno later than\b|\boffers?\s+are\s+due\b|\bproposal\s+is\s+due\b", "Due Date/Deadline"),
    (r"\bsubmit\b|\bsubmission\b|\be-?mail\b|\bemailed\b|\bportal\b|\bupload\b|\bsam\.gov\b|\bebuy\b|\bpiee\b|\bfedconnect\b", "Submission Method"),
    (r"\bfile format\b|\bpdf\b|\bdocx\b|\bexcel\b|\bxlsx\b|\bzip\b|\bencrypt\b|\bpassword\b", "File Format Rules"),
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

PRICE_HINTS = [
    "price", "pricing", "cost", "rates", "rate", "labor category", "labor categories",
    "excel", "xlsx", "spreadsheet", "price schedule", "cost proposal", "fee"
]

PAST_PERF_HINTS = [
    "past performance", "cpars", "references", "experience", "relevant experience", "prior contracts"
]

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

DATE_PATTERNS = [
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
]
TIME_PATTERNS = [
    r"\b\d{1,2}:\d{2}\s*(?:am|pm)\b",
    r"\b\d{1,2}\s*(?:am|pm)\b",
    r"\b\d{1,2}:\d{2}\b",
]
TZ_PATTERNS = [
    r"\b(?:et|ct|mt|pt|est|edt|cst|cdt|mst|mdt|pst|pdt|utc|zulu)\b",
]
DUE_KEYWORDS = [
    "offer due", "offers are due", "proposal due", "proposal is due", "submission due",
    "deadline", "no later than", "due date", "closing date", "response due"
]

def refine_due_date_rule(text: str, rules: Dict[str, List[str]]) -> Dict[str, List[str]]:
    lines = scan_lines(text, max_lines=14000)

    best = None
    best_score = -1

    for line in lines:
        low = line.lower()

        if not any(k in low for k in DUE_KEYWORDS) and "due" not in low:
            continue

        if "invoice" in low or "invoices" in low or "payment" in low:
            continue

        has_date = any(re.search(p, line, re.IGNORECASE) for p in DATE_PATTERNS)
        has_time = any(re.search(p, line, re.IGNORECASE) for p in TIME_PATTERNS)
        has_tz = any(re.search(p, line, re.IGNORECASE) for p in TZ_PATTERNS)

        score = 0
        if any(k in low for k in DUE_KEYWORDS): score += 3
        if "no later than" in low: score += 2
        if "deadline" in low: score += 2
        if has_date: score += 4
        if has_time: score += 2
        if has_tz: score += 1
        if "section l" in low or "instructions" in low: score += 1
        if len(line) > 220: score -= 1

        if score > best_score:
            best_score = score
            best = line

    if best and best_score >= 6:
        rules = dict(rules or {})
        rules["Due Date/Deadline"] = [best]
    return rules

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
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
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
    text = " ".join(snips or []).lower()
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
        if re.search(pat, text or "", re.IGNORECASE):
            found.append(label)
    return unique_keep_order(found)

def compliance_warnings(
    rules: Dict[str, List[str]],
    forms: List[str],
    amendments: List[str],
    separate: List[str]
) -> List[str]:
    warnings = []
    if not rules:
        warnings.append("No clear submission rules detected. If you pasted partial text, upload/paste Section L/M and the cover page.")
    else:
        if "Due Date/Deadline" not in rules:
            warnings.append("Due date/deadline not clearly detected. Verify cover page + Section L.")
        if "Submission Method" not in rules:
            warnings.append("Submission method not clearly detected (email/portal). Verify exactly where/how to submit.")
        if "File Format Rules" not in rules:
            warnings.append("File format rules not clearly detected. Confirm required formats (PDF/Excel/ZIP) and naming rules.")
        if any(k in rules for k in ["Page Limit", "Font Requirement", "Margin Requirement"]):
            warnings.append("Formatting rules detected (page/font/margins). Violations can cause rejection as non-compliant.")
    if forms:
        warnings.append("SF/DD forms detected. Confirm each required form is completed and signed where required.")
    if amendments:
        warnings.append("Amendments/modifications referenced. Confirm all amendments acknowledged and instructions incorporated.")
    if separate:
        warnings.append("Items may require separate files/submissions (signed forms, spreadsheets, attachments). Review 'Separate submission indicators'.")
    if not warnings:
        warnings.append("No major issues detected by starter logic. Still verify Section L/M and all attachments manually.")
    return warnings

# =========================
# Company Info
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
        critical.append("UEI is missing (commonly required).")
    if not company.poc_name.strip():
        critical.append("POC name is missing.")
    if not company.poc_email.strip():
        critical.append("POC email is missing.")

    if not company.address.strip():
        recommended.append("Business address is missing (often used on cover letter/title page).")
    if not company.certifications or (len(company.certifications) == 1 and company.certifications[0] == "None"):
        recommended.append("Certifications/set-asides not selected (if applicable).")
    if not company.capabilities.strip():
        recommended.append("Capabilities section is empty (hurts competitiveness).")
    if not company.differentiators.strip():
        recommended.append("Differentiators section is empty (hurts competitiveness).")
    if not company.past_performance.strip():
        recommended.append("Past performance is blank (draft uses capability-based language).")

    if not company.proposal_title.strip():
        recommended.append("Proposal/Contract title is blank (recommended for title page).")
    if not company.solicitation_number.strip():
        recommended.append("Solicitation number is blank (recommended for title page).")
    if not company.agency_customer.strip():
        recommended.append("Agency/Customer is blank (recommended for title page).")

    return critical, recommended

# =========================
# Draft Generator (CLEAN signature)
# =========================
def _signature_block(company: CompanyInfo) -> str:
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

def generate_drafts(
    sow_snips: List[str],
    keywords: List[str],
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    company: CompanyInfo
) -> Dict[str, str]:
    kw = ", ".join((keywords or [])[:8]) if keywords else "quality, schedule, reporting, risk"
    due = rules.get("Due Date/Deadline", ["Not detected"])[0] if rules.get("Due Date/Deadline") else "Not detected"
    method = rules.get("Submission Method", ["Not detected"])[0] if rules.get("Submission Method") else "Not detected"
    vols = rules.get("Volumes (if found)", [])
    certs = ", ".join(company.certifications or []) if company.certifications else "—"

    sow_block = "\n".join([f"- {s}" for s in (sow_snips or [])[:3]]) if sow_snips else "- [No SOW snippets detected]"
    vol_block = "; ".join(vols) if vols else "Not detected"

    cover = f"""COVER LETTER

{company.legal_name or "[Company Name]"}
{company.address or "[Address]"}
UEI: {company.uei or "[UEI]"} | CAGE: {company.cage or "[CAGE]"}
POC: {company.poc_name or "[POC]"} | {company.poc_email or "[email]"} | {company.poc_phone or "[phone]"}
Certifications: {certs}

Subject: {company.proposal_title or "Proposal Submission"}

Dear Contracting Officer,

{company.legal_name or "[Company Name]"} submits this proposal in response to the solicitation. We understand the Government’s requirement and will execute with a low-risk approach aligned to: {kw}.

Submission details (auto-detected — verify Section L and cover page):
- Deadline: {due}
- Submission Method: {method}

{_signature_block(company)}
"""

    exec_summary = f"""EXECUTIVE SUMMARY

{company.legal_name or "[Company Name]"} will deliver the required scope with disciplined execution, clear communication, and measurable outcomes.

Tailoring keywords (auto-extracted):
{kw}

Capabilities:
{company.capabilities or "[Add capabilities]"}
"""

    tech = f"""TECHNICAL APPROACH

Understanding of Requirement (excerpts — verify full SOW/PWS):
{sow_block}

Approach:
- Requirements-to-Deliverables Mapping: map each requirement to a deliverable, owner, schedule, and acceptance criteria.
- Execution Plan: controlled phases with weekly status, quality checks, and documented approvals.
- Quality Control: peer review, checklists, and objective evidence to confirm compliance.

Designed around:
{kw}
"""

    mgmt = f"""MANAGEMENT PLAN

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
        pp = f"""PAST PERFORMANCE

Provided Past Performance:
{company.past_performance}

Relevance:
- Demonstrates delivery of similar scope and disciplined execution.
"""
    else:
        pp = f"""PAST PERFORMANCE (CAPABILITY-BASED)

No direct past performance provided. {company.legal_name or "[Company Name]"} will demonstrate responsibility and capability through:
- Strong management controls and reporting cadence
- Defined QC checks and documented processes
- Staffing aligned to the requirement
- Risk mitigation and escalation procedures
"""

    forms_block = "\n".join([f"- {f}" for f in forms]) if forms else "- None detected"
    att_block = "\n".join([f"- {a}" for a in (attachments or [])[:10]]) if attachments else "- None detected"

    compliance = f"""COMPLIANCE SNAPSHOT

Submission Details (auto-detected — verify Section L/M):
- Deadline: {due}
- Method: {method}
- Volumes: {vol_block}

Forms detected:
{forms_block}

Attachment/Appendix/Exhibit mentions:
{att_block}

Next step: build a complete compliance matrix aligned to Section L/M.
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
# Checklist
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

    for key in ["Due Date/Deadline", "Submission Method", "File Format Rules", "Page Limit", "Font Requirement", "Margin Requirement", "Volumes (if found)"]:
        if key in rules and rules[key]:
            items.append({"item": f"Verify: {key}", "source": "Submission Rules", "status": "Needs Review"})
        else:
            items.append({"item": f"Find & confirm: {key}", "source": "Submission Rules", "status": "Missing/Unknown"})

    if forms:
        for f in forms:
            items.append({"item": f"Complete/attach required form: {f}", "source": "Forms", "status": "Needs Review"})
    else:
        items.append({"item": "Confirm whether SF/DD forms are required", "source": "Forms", "status": "Missing/Unknown"})

    if attachments:
        items.append({"item": "Review every attachment/appendix/exhibit mention and ensure included", "source": "Attachments", "status": "Needs Review"})
    else:
        items.append({"item": "Confirm required attachments/appendices/exhibits", "source": "Attachments", "status": "Missing/Unknown"})

    if amendments:
        items.append({"item": "Acknowledge all amendments and incorporate revised instructions", "source": "Amendments", "status": "Needs Review"})
    else:
        items.append({"item": "Confirm whether any amendments exist", "source": "Amendments", "status": "Needs Review"})

    if separate:
        items.append({"item": "Prepare separate submission items (spreadsheets/signed forms/etc.)", "source": "Separate Submissions", "status": "Needs Review"})

    if required_certs:
        items.append({"item": f"Confirm eligibility/documentation for: {', '.join(required_certs)}", "source": "Certifications", "status": "Needs Review"})

    uniq = []
    seen = set()
    for it in items:
        k = (it["item"] + "|" + it["source"]).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    return uniq

# =========================
# Compliance Matrix (best-effort)
# =========================
REQ_TRIGGER = re.compile(r"\b(shall|must|will)\b", re.IGNORECASE)
REQ_NUMBERED = re.compile(r"^(\(?[a-z0-9]{1,4}\)?[\.\)]|\d{1,3}\.)\s+", re.IGNORECASE)

def extract_requirements_v2(rfp_text: str, max_reqs: int = 60) -> List[Dict[str, str]]:
    lines = scan_lines(rfp_text, max_lines=12000)

    lm_indexes = []
    for i, line in enumerate(lines):
        if re.search(r"\bsection\s+l\b|\binstructions to offerors\b", line, re.IGNORECASE):
            lm_indexes.append(i)
        if re.search(r"\bsection\s+m\b|\bevaluation criteria\b", line, re.IGNORECASE):
            lm_indexes.append(i)

    windows = []
    for idx in lm_indexes[:10]:
        start = max(0, idx - 80)
        end = min(len(lines), idx + 260)
        windows.append((start, end))

    if not windows:
        windows = [(0, len(lines))]

    reqs = []
    seen = set()
    rid = 1

    for start, end in windows:
        for i in range(start, end):
            line = lines[i]
            if len(line) < 25:
                continue

            is_numbered = bool(REQ_NUMBERED.search(line))
            has_trigger = bool(REQ_TRIGGER.search(line))

            if has_trigger and (is_numbered or "offeror" in line.lower() or "proposal" in line.lower() or "submit" in line.lower()):
                norm = line.lower()
                if norm in seen:
                    continue
                seen.add(norm)

                reqs.append({
                    "id": f"R{rid:03d}",
                    "requirement": line,
                    "source": "Section L/M (best-effort)" if lm_indexes else "RFP (best-effort)"
                })
                rid += 1
                if len(reqs) >= max_reqs:
                    return reqs

    return reqs

DEFAULT_SECTIONS = [
    "Cover Letter",
    "Executive Summary",
    "Technical Approach",
    "Management Plan",
    "Past Performance",
    "Compliance Snapshot",
    "Other / Add New Section",
]

def auto_map_section(req_text: str) -> str:
    t = (req_text or "").lower()
    if "past performance" in t or "reference" in t or "experience" in t or "cpars" in t:
        return "Past Performance"
    if "management" in t or "staff" in t or "key personnel" in t or "organization" in t or "resume" in t:
        return "Management Plan"
    if "technical" in t or "approach" in t or "method" in t or "solution" in t or "work plan" in t:
        return "Technical Approach"
    if "executive summary" in t or "summary" in t:
        return "Executive Summary"
    if "cover letter" in t or "signed" in t or "signature" in t:
        return "Cover Letter"
    if "compliance" in t or "matrix" in t or "section l" in t or "section m" in t:
        return "Compliance Snapshot"
    return "Technical Approach"

# =========================
# Submission Package Checklist (Detected-only)
# (UI labels are cleaned at render time)
# =========================
def build_submission_package_detected(
    rfp_text: str,
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    separate: List[str],
    matrix_rows: List[Dict[str, str]],
    drafts: Dict[str, str],
    company: CompanyInfo
) -> Dict[str, List[str]]:
    pkg: Dict[str, List[str]] = {}

    has_forms = bool(forms)
    has_attachments = bool(attachments)
    has_separate = bool(separate)

    tech_evidence = False
    if drafts and any(k in drafts for k in ["Executive Summary", "Technical Approach", "Management Plan"]):
        tech_evidence = True
    if matrix_rows and any(r.get("section") in ["Technical Approach", "Management Plan", "Executive Summary"] for r in matrix_rows):
        tech_evidence = True

    if tech_evidence:
        items = []
        if drafts.get("Executive Summary"): items.append("Include: Executive Summary")
        if drafts.get("Technical Approach"): items.append("Include: Technical Approach")
        if drafts.get("Management Plan"): items.append("Include: Management Plan")

        base = {"Cover Letter","Executive Summary","Technical Approach","Management Plan","Past Performance","Compliance Snapshot"}
        for k in (drafts or {}).keys():
            if k not in base:
                items.append(f"Include: {k}")

        if "Page Limit" in rules: items.append("Verify page limit and stay within maximum pages")
        if "Font Requirement" in rules or "Margin Requirement" in rules:
            items.append("Verify font/margin formatting requirements")

        pkg["Volume I – Technical"] = unique_keep_order(items)

    pp_evidence = False
    if drafts.get("Past Performance"):
        if company.past_performance.strip():
            pp_evidence = True
        if _contains_any(rfp_text, PAST_PERF_HINTS):
            pp_evidence = True
        if any(_contains_any((r.get("requirement") or ""), PAST_PERF_HINTS) for r in (matrix_rows or [])):
            pp_evidence = True

    if pp_evidence:
        items = ["Include: Past Performance section"]
        if _contains_any(rfp_text, ["cpars"]):
            items.append("If required: attach CPARS or performance evaluations")
        if _contains_any(rfp_text, ["reference", "references"]):
            items.append("If required: include references/contact information")
        pkg["Volume II – Past Performance"] = unique_keep_order(items)

    price_evidence = False
    if has_attachments and any(_contains_any(a, PRICE_HINTS) for a in attachments):
        price_evidence = True
    if has_separate and any(_contains_any(s, PRICE_HINTS) for s in separate):
        price_evidence = True
    if _contains_any(rfp_text, PRICE_HINTS):
        if has_attachments or has_separate or ("File Format Rules" in rules):
            price_evidence = True

    if price_evidence:
        items = ["Prepare: Price/Cost volume (as instructed)"]
        if has_attachments:
            for a in attachments:
                if _contains_any(a, PRICE_HINTS):
                    items.append(f"Attachment mention: {a}")
        if "File Format Rules" in rules:
            items.append("Verify required pricing file format (Excel/PDF) and naming rules")
        pkg["Volume III – Price/Cost"] = unique_keep_order(items)

    if has_forms:
        pkg["Required Forms"] = unique_keep_order([f"Complete/attach: {f}" for f in forms])

    if has_attachments:
        pkg["Attachments / Exhibits"] = unique_keep_order(attachments[:20])

    if has_separate:
        pkg["Separate Submission Items"] = unique_keep_order(separate[:25])

    instr = []
    if rules.get("Due Date/Deadline"):
        instr.append(f"Deadline (detected): {rules['Due Date/Deadline'][0]}")
    if rules.get("Submission Method"):
        instr.append(f"Method (detected): {rules['Submission Method'][0]}")
    if rules.get("File Format Rules"):
        instr.append("File format rules detected — confirm each required format")
    if instr:
        pkg["Submission Instructions"] = unique_keep_order(instr)

    return pkg

# =========================
# Validation Lock (Pre-Submit Gate)
# =========================
def compute_matrix_kpis(matrix_rows: List[Dict[str, str]]) -> Dict[str, int]:
    total = len(matrix_rows or [])
    pass_ct = sum(1 for r in (matrix_rows or []) if (r.get("status") == "Pass"))
    fail_ct = sum(1 for r in (matrix_rows or []) if (r.get("status") == "Fail"))
    unk_ct = sum(1 for r in (matrix_rows or []) if (r.get("status") in [None, "", "Unknown"]))
    return {"total": total, "pass": pass_ct, "fail": fail_ct, "unknown": unk_ct}

def run_pre_submit_gate(
    company: CompanyInfo,
    rules: Dict[str, List[str]],
    matrix_rows: List[Dict[str, str]],
    deadline_acknowledged: bool
) -> Dict[str, Any]:
    crit, _ = missing_info_alerts(company)
    kpi = compute_matrix_kpis(matrix_rows)

    blocked = []
    risk = []

    if kpi["fail"] > 0:
        blocked.append(f"{kpi['fail']} requirements are marked FAIL in the compliance matrix.")
    if crit:
        blocked.append("Critical company info missing: " + "; ".join(crit))

    deadline_detected = bool(rules.get("Due Date/Deadline"))
    if deadline_detected and not deadline_acknowledged:
        blocked.append("Deadline detected but not acknowledged.")

    if kpi["unknown"] > 0:
        risk.append(f"{kpi['unknown']} requirements are still UNKNOWN (not evaluated).")
    if not rules.get("Submission Method"):
        risk.append("Submission method not detected. Verify email/portal details in Section L.")

    if blocked:
        return {"status": "NOT COMPLIANT", "level": "blocked", "blocked_reasons": blocked, "risk_reasons": risk, "kpi": kpi}
    if risk:
        return {"status": "AT RISK", "level": "risk", "blocked_reasons": [], "risk_reasons": risk, "kpi": kpi}
    return {"status": "READY", "level": "ready", "blocked_reasons": [], "risk_reasons": [], "kpi": kpi}

# =========================
# Word Export Helpers
# =========================
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

def set_word_styles_no_blue_links(doc: docx.Document):
    try:
        hl = doc.styles["Hyperlink"]
        hl.font.color.rgb = RGBColor(0, 0, 0)
        hl.font.underline = False
    except Exception:
        pass

def add_table_of_contents(doc: docx.Document):
    doc.add_page_break()
    doc.add_heading("Table of Contents", level=1)
    p = doc.add_paragraph()
    add_field(p, r'TOC \o "1-3" \z \u')
    doc.add_page_break()

def add_title_page(doc: docx.Document, company: CompanyInfo, logo_bytes: Optional[bytes]):
    doc.add_paragraph("")
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

    p1 = doc.add_paragraph()
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p1.add_run(company_name); r1.bold = True

    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
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

def add_paragraph_lines(doc: docx.Document, text: str):
    for line in (text or "").splitlines():
        doc.add_paragraph(line)

def build_proposal_docx_bytes(
    company: CompanyInfo,
    logo_bytes: Optional[bytes],
    rfp_diag: Dict[str, Any],
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    amendments: List[str],
    separate: List[str],
    warnings: List[str],
    checklist_items: List[Dict[str, str]],
    matrix_rows: List[Dict[str, str]],
    drafts: Dict[str, str],
    validation_result: Optional[Dict[str, Any]],
    submission_pkg: Dict[str, List[str]],
) -> bytes:
    doc = docx.Document()

    set_word_styles_no_blue_links(doc)
    add_page_numbers(doc)
    add_title_page(doc, company, logo_bytes)
    add_table_of_contents(doc)

    doc.add_heading("Diagnostics Summary", level=1)
    if rfp_diag:
        doc.add_paragraph(f"File Type: {rfp_diag.get('file_type','—')}")
        if rfp_diag.get("pages_total") is not None:
            doc.add_paragraph(f"Pages: {rfp_diag.get('pages_total','—')}")
        if rfp_diag.get("pages_with_text") is not None:
            doc.add_paragraph(f"Pages with text: {rfp_diag.get('pages_with_text','—')}")
        doc.add_paragraph(f"Characters extracted: {rfp_diag.get('chars_extracted','—')}")
        doc.add_paragraph(f"Likely scanned: {'Yes' if rfp_diag.get('likely_scanned') else 'No'}")
    else:
        doc.add_paragraph("No file diagnostics available (text may have been pasted).")
    doc.add_page_break()

    doc.add_heading("Pre-Submission Gate Result", level=1)
    if validation_result:
        doc.add_paragraph(f"Status: {validation_result.get('status','—')}")
        if validation_result.get("blocked_reasons"):
            doc.add_paragraph("Blocked Reasons:", style="List Bullet")
            for r in validation_result["blocked_reasons"]:
                doc.add_paragraph(r, style="List Bullet 2")
        if validation_result.get("risk_reasons"):
            doc.add_paragraph("Risk Reasons:", style="List Bullet")
            for r in validation_result["risk_reasons"]:
                doc.add_paragraph(r, style="List Bullet 2")
    else:
        doc.add_paragraph("Gate has not been run yet.")
    doc.add_page_break()

    doc.add_heading("Submission Package Checklist", level=1)
    if submission_pkg:
        for bucket, items in submission_pkg.items():
            doc.add_paragraph(label_clean(bucket), style="List Bullet")
            for it in items:
                doc.add_paragraph(f"☐ {it}", style="List Bullet 2")
    else:
        doc.add_paragraph("No submission package items detected yet.")
    doc.add_page_break()

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

    doc.add_heading("Compliance Checklist", level=1)
    for it in checklist_items:
        doc.add_paragraph(f"☐ {it['item']}  ({it['status']})", style="List Bullet")

    doc.add_heading("Compliance Matrix", level=1)
    if matrix_rows:
        table = doc.add_table(rows=1, cols=5)
        hdr = table.rows[0].cells
        hdr[0].text = "Req ID"
        hdr[1].text = "Requirement"
        hdr[2].text = "Mapped Section"
        hdr[3].text = "Status"
        hdr[4].text = "Notes"

        for row in matrix_rows[:80]:
            r = table.add_row().cells
            r[0].text = row.get("id", "")
            r[1].text = row.get("requirement", "")
            r[2].text = row.get("section", "")
            r[3].text = row.get("status", "Unknown")
            r[4].text = row.get("notes", "")
    else:
        doc.add_paragraph("No requirements extracted yet.", style="List Bullet")

    doc.add_heading("Submission Rules (Detected)", level=2)
    if rules:
        for k, lines in rules.items():
            doc.add_paragraph(label_clean(k), style="List Bullet")
            for ln in lines[:6]:
                doc.add_paragraph(ln, style="List Bullet 2")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Forms (Detected)", level=2)
    if forms:
        for f in forms:
            doc.add_paragraph(f, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Attachments / Exhibits (Detected)", level=2)
    if attachments:
        for a in attachments[:12]:
            doc.add_paragraph(a, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Amendments / Mods (Detected)", level=2)
    if amendments:
        for a in amendments[:12]:
            doc.add_paragraph(a, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Separate Submission Items (Detected)", level=2)
    if separate:
        for s in separate[:15]:
            doc.add_paragraph(s, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Warnings (Detected)", level=2)
    if warnings:
        for w in warnings:
            doc.add_paragraph(w, style="List Bullet")
    else:
        doc.add_paragraph("None.", style="List Bullet")

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
# Diagnostics UI
# =========================
def diagnostics_quality(diag: Dict[str, Any]) -> Tuple[str, str]:
    if not diag:
        return ("Extraction quality: Unknown (text pasted)", "warn")
    if diag.get("file_type") != "pdf":
        return ("Extraction quality: Good", "good")
    pages = diag.get("pages_total") or 0
    pages_text = diag.get("pages_with_text") or 0
    chars = diag.get("chars_extracted") or 0
    scanned = bool(diag.get("likely_scanned"))
    if scanned:
        return ("Extraction quality: Poor (likely scanned)", "bad")
    if pages > 0 and (pages_text / max(1, pages)) >= 0.6 and chars >= 2000:
        return ("Extraction quality: Excellent", "good")
    return ("Extraction quality: OK (verify Section L/M)", "warn")

def render_diagnostics_card(diag: Dict[str, Any]):
    label, level = diagnostics_quality(diag)
    badge_class = "pill-good" if level == "good" else ("pill-warn" if level == "warn" else "pill-bad")
    scanned = "Yes" if (diag or {}).get("likely_scanned") else "No"
    file_type = (diag or {}).get("file_type", "—")
    pages_total = (diag or {}).get("pages_total", "—")
    pages_text = (diag or {}).get("pages_with_text", "—")
    chars = (diag or {}).get("chars_extracted", "—")

    st.markdown(
        f"""
        <div class="card">
          <h4>Diagnostics</h4>
          <div class="muted">Confirms whether the PDF was readable as text.</div>
          <div class="divider"></div>
          <span class="pill {badge_class}">{label}</span>
          <div class="small" style="margin-top:8px;">
            <b>File Type:</b> {file_type}<br/>
            <b>Pages:</b> {pages_total} &nbsp;&nbsp; <b>Pages with Text:</b> {pages_text}<br/>
            <b>Characters Extracted:</b> {chars}<br/>
            <b>Likely Scanned:</b> {scanned}
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if diag and diag.get("likely_scanned"):
        ui_notice(
            "Scanned PDF detected",
            "This file looks image-based. Text extraction may miss requirements. If possible, paste the text or use a text-based version of the solicitation.",
            tone="warn"
        )

# =========================
# Project Save/Load (Full State)
# =========================
PROJECT_KEYS = [
    "rfp_text", "rfp_diag", "rules", "forms", "attachments", "amendments", "separate_submit",
    "required_certs", "sow_snips", "keywords", "drafts", "company", "logo_bytes",
    "checklist_done", "matrix_rows", "deadline_ack", "validation_last", "pkg_checks"
]

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
    c: CompanyInfo = st.session_state.company
    payload = {
        "build": {"version": BUILD_VERSION, "date": BUILD_DATE},
        "rfp_text": st.session_state.rfp_text,
        "rfp_diag": st.session_state.rfp_diag,
        "rules": st.session_state.rules,
        "forms": st.session_state.forms,
        "attachments": st.session_state.attachments,
        "amendments": st.session_state.amendments,
        "separate_submit": st.session_state.separate_submit,
        "required_certs": st.session_state.required_certs,
        "sow_snips": st.session_state.sow_snips,
        "keywords": st.session_state.keywords,
        "drafts": st.session_state.drafts,
        "company": c.to_dict(),
        "logo_b64": b64_from_bytes(st.session_state.logo_bytes),
        "checklist_done": st.session_state.checklist_done,
        "matrix_rows": st.session_state.matrix_rows,
        "deadline_ack": st.session_state.deadline_ack,
        "validation_last": st.session_state.validation_last,
        "pkg_checks": st.session_state.pkg_checks,
    }
    return json.dumps(payload, indent=2)

def import_project_json(s: str) -> Tuple[bool, str]:
    try:
        payload = json.loads(s)
        if not isinstance(payload, dict):
            return False, "Invalid project file."

        st.session_state.rfp_text = payload.get("rfp_text", "") or ""
        st.session_state.rfp_diag = payload.get("rfp_diag", {}) or {}
        st.session_state.rules = payload.get("rules", {}) or {}
        st.session_state.forms = payload.get("forms", []) or []
        st.session_state.attachments = payload.get("attachments", []) or []
        st.session_state.amendments = payload.get("amendments", []) or []
        st.session_state.separate_submit = payload.get("separate_submit", []) or []
        st.session_state.required_certs = payload.get("required_certs", []) or []
        st.session_state.sow_snips = payload.get("sow_snips", []) or []
        st.session_state.keywords = payload.get("keywords", []) or []
        st.session_state.drafts = payload.get("drafts", {}) or {}

        company_dict = payload.get("company", {}) or {}
        c = CompanyInfo(certifications=[])
        for k, v in company_dict.items():
            if hasattr(c, k):
                setattr(c, k, v)
        if c.certifications is None:
            c.certifications = []
        st.session_state.company = c

        st.session_state.logo_bytes = bytes_from_b64(payload.get("logo_b64"))

        st.session_state.checklist_done = payload.get("checklist_done", {}) or {}
        st.session_state.matrix_rows = payload.get("matrix_rows", []) or []
        st.session_state.deadline_ack = bool(payload.get("deadline_ack", False))
        st.session_state.validation_last = payload.get("validation_last", None)
        st.session_state.pkg_checks = payload.get("pkg_checks", {}) or {}

        return True, "Project loaded."
    except Exception as e:
        return False, f"Could not load project: {e}"

# =========================
# Session State Init
# =========================
if "rfp_text" not in st.session_state: st.session_state.rfp_text = ""
if "rfp_diag" not in st.session_state: st.session_state.rfp_diag = {}
if "rules" not in st.session_state: st.session_state.rules = {}
if "forms" not in st.session_state: st.session_state.forms = []
if "attachments" not in st.session_state: st.session_state.attachments = []
if "amendments" not in st.session_state: st.session_state.amendments = []
if "separate_submit" not in st.session_state: st.session_state.separate_submit = []
if "required_certs" not in st.session_state: st.session_state.required_certs = []
if "sow_snips" not in st.session_state: st.session_state.sow_snips = []
if "keywords" not in st.session_state: st.session_state.keywords = []
if "drafts" not in st.session_state: st.session_state.drafts = {}
if "company" not in st.session_state: st.session_state.company = CompanyInfo(certifications=[])
if "logo_bytes" not in st.session_state: st.session_state.logo_bytes = None
if "checklist_done" not in st.session_state: st.session_state.checklist_done = {}
if "matrix_rows" not in st.session_state: st.session_state.matrix_rows = []
if "deadline_ack" not in st.session_state: st.session_state.deadline_ack = False
if "validation_last" not in st.session_state: st.session_state.validation_last = None
if "pkg_checks" not in st.session_state: st.session_state.pkg_checks = {}

# =========================
# Sidebar Navigation + Project Save/Load
# =========================
st.sidebar.title("Path")
st.sidebar.caption(f"{BUILD_VERSION} • {BUILD_DATE}")

with st.sidebar.expander("Project Save / Load", expanded=False):
    st.download_button(
        "Download Project (.json)",
        data=export_project_json(),
        file_name="path_project.json",
        mime="application/json"
    )
    up_proj = st.file_uploader("Upload Project (.json)", type=["json"], key="proj_uploader")
    if up_proj:
        ok, msg = import_project_json(up_proj.read().decode("utf-8", errors="ignore"))
        if ok:
            ui_notice("Project loaded", "Your full session (RFP, matrix, drafts, company info) has been restored.", tone="good")
        else:
            ui_notice("Could not load project", msg, tone="bad")

page = st.sidebar.radio("Go to", ["RFP Intake", "Company Info", "Proposal Output"])
st.sidebar.caption("Upload/Paste → Analyze → Matrix → Drafts → Gate → Export")

# =========================
# Page 1: RFP Intake
# =========================
if page == "RFP Intake":
    st.title("RFP Intake")

    uploaded = st.file_uploader("Upload RFP (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"])
    pasted = st.text_area("Or paste RFP / RFI text", value=st.session_state.rfp_text, height=320)

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("Analyze", use_container_width=True):
            text = ""
            diag = {}

            if uploaded:
                text, diag = read_uploaded_file(uploaded)
                st.session_state.rfp_diag = diag

            if pasted.strip():
                text = pasted.strip()

            if not text.strip():
                ui_notice("Input required", "Upload a readable file OR paste text.", tone="bad")
            else:
                st.session_state.rfp_text = text

                rules = detect_submission_rules(text)
                rules = refine_due_date_rule(text, rules)
                st.session_state.rules = rules

                st.session_state.forms = find_forms(text)
                st.session_state.attachments = find_attachment_lines(text)
                st.session_state.amendments = detect_amendment_lines(text)
                st.session_state.separate_submit = detect_separate_submit_lines(text)
                st.session_state.sow_snips = extract_sow_snippets(text)
                st.session_state.keywords = derive_tailor_keywords(st.session_state.sow_snips)
                st.session_state.required_certs = detect_required_certifications(text)

                extracted = extract_requirements_v2(text)
                matrix_rows = []
                for r in extracted:
                    matrix_rows.append({
                        "id": r["id"],
                        "requirement": r["requirement"],
                        "section": auto_map_section(r["requirement"]),
                        "status": "Unknown",
                        "notes": "",
                    })
                st.session_state.matrix_rows = matrix_rows

                st.session_state.validation_last = None
                st.session_state.pkg_checks = {}

                ui_notice("Analysis saved", "Go to Proposal Output.", tone="good")

    with colB:
        ui_notice(
            "Tip",
            "If a PDF is image-based (scanned), text extraction may miss requirements. Use a text-based version or paste the relevant sections.",
            tone="neutral"
        )

    st.markdown("### Diagnostics")
    render_diagnostics_card(st.session_state.rfp_diag)

    st.markdown("### Preview")
    st.text_area("RFP Preview (first 1200 characters)", (st.session_state.rfp_text or "")[:1200], height=220)

# =========================
# Page 2: Company Info
# =========================
elif page == "Company Info":
    st.title("Company Info")
    st.caption("Fill this out once. It auto-fills drafts, export title page, and signature block.")

    c: CompanyInfo = st.session_state.company

    st.markdown("### Logo (optional)")
    logo = st.file_uploader("Upload company logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
    if logo:
        st.session_state.logo_bytes = logo.read()
        ui_notice("Logo saved", "It will be placed on the title page.", tone="good")
        st.image(st.session_state.logo_bytes, width=180)

    st.markdown("---")
    st.markdown("### Proposal / Contract Info")
    c.proposal_title = st.text_input("Proposal/Contract Title", value=c.proposal_title, placeholder="e.g., Proposal for IT Support Services")
    c.solicitation_number = st.text_input("Solicitation Number", value=c.solicitation_number, placeholder="e.g., W91XXX-26-R-0001")
    c.agency_customer = st.text_input("Agency/Customer", value=c.agency_customer, placeholder="e.g., Department of X / Agency Y")

    st.markdown("---")
    st.markdown("### Company Details")

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
    c.capabilities = st.text_area("Capabilities (short paragraph or bullets)", value=c.capabilities, height=120)
    c.differentiators = st.text_area("Differentiators (why you)", value=c.differentiators, height=100)

    st.markdown("### Past Performance (optional)")
    st.caption("If blank, the draft will use capability-based language.")
    c.past_performance = st.text_area("Paste past performance notes", value=c.past_performance, height=140)

    st.markdown("---")
    st.markdown("### Signature Block (Cover Letter)")
    st.caption("Blank fields fall back to POC/company. Signature is an implied blank space (no DocuSign / wet ink wording).")
    s1, s2 = st.columns(2)
    with s1:
        c.signer_name = st.text_input("Signer Name (optional)", value=c.signer_name, placeholder="If blank, uses POC name")
        c.signer_title = st.text_input("Signer Title (optional)", value=c.signer_title)
        c.signer_company = st.text_input("Signer Company (optional)", value=c.signer_company, placeholder="If blank, uses Legal Company Name")
    with s2:
        c.signer_phone = st.text_input("Signer Phone (optional)", value=c.signer_phone, placeholder="If blank, uses POC phone")
        c.signer_email = st.text_input("Signer Email (optional)", value=c.signer_email, placeholder="If blank, uses POC email")

    st.session_state.company = c

# =========================
# Page 3: Proposal Output (TurboTax-like)
# =========================
else:
    st.title("Proposal Output")

    if not st.session_state.rfp_text.strip():
        ui_notice("No RFP found", "Go to RFP Intake and click Analyze.", tone="warn")
        st.stop()

    rules = st.session_state.rules or {}
    forms = st.session_state.forms or []
    attachments = st.session_state.attachments or []
    amendments = st.session_state.amendments or []
    separate = st.session_state.separate_submit or []
    required_certs = st.session_state.required_certs or []
    c: CompanyInfo = st.session_state.company
    logo_bytes = st.session_state.logo_bytes
    matrix_rows = st.session_state.matrix_rows or []
    drafts = st.session_state.drafts or {}
    diag = st.session_state.rfp_diag or {}

    # Sticky KPI Header
    k = compute_matrix_kpis(matrix_rows)
    total = max(1, k["total"])
    compliance_pct = int(round((k["pass"] / total) * 100))

    gate = st.session_state.validation_last
    gate_label = gate["status"] if gate else "Gate not run"
    gate_level = gate["level"] if gate else "warn"
    gate_class = "pill-good" if gate_level == "ready" else ("pill-warn" if gate_level == "risk" else "pill-bad")

    crit, rec = missing_info_alerts(c)
    missing_crit_ct = len(crit)

    st.markdown(
        f"""
        <div class="kpi-wrap">
          <div class="kpi-title">Compliance KPI</div>
          <span class="pill pill-good">Compliance: {compliance_pct}%</span>
          <span class="pill pill-good">Pass: {k["pass"]}</span>
          <span class="pill pill-bad">Fail: {k["fail"]}</span>
          <span class="pill pill-warn">Unknown: {k["unknown"]}</span>
          <span class="pill {gate_class}">Gate: {gate_label}</span>
          <span class="pill pill-warn">Missing critical fields: {missing_crit_ct}</span>
          <div class="muted">Finish these sections top-to-bottom like TurboTax.</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Build these once
    warns = compliance_warnings(rules, forms, amendments, separate)
    checklist_items = build_checklist_items(rules, forms, attachments, amendments, separate, required_certs)
    submission_pkg = build_submission_package_detected(
        rfp_text=st.session_state.rfp_text,
        rules=rules,
        forms=forms,
        attachments=attachments,
        separate=separate,
        matrix_rows=matrix_rows,
        drafts=drafts,
        company=c
    )

    # ---------- TurboTax-style accordion ----------
    with st.expander("Diagnostics", expanded=False):
        render_diagnostics_card(diag)

    with st.expander("Missing Info Alerts", expanded=False):
        if crit:
            for x in crit:
                ui_notice("Missing critical field", x, tone="bad")
        else:
            ui_notice("Critical fields", "No critical company-info fields missing.", tone="good")

        if rec:
            ui_notice("Recommended improvements", "These improve competitiveness (not hard blockers).", tone="warn")
            for x in rec:
                st.write("•", x)

        if required_certs:
            ui_notice("Detected certification mentions", "RFP references: " + ", ".join(required_certs), tone="neutral")

    with st.expander("Submission Package Checklist", expanded=True):
        if not submission_pkg:
            ui_notice("Nothing detected yet", "Upload/paste more of Section L/M and re-run Analyze.", tone="warn")
        else:
            total_items = 0
            checked_items = 0
            for bucket, items in submission_pkg.items():
                if not items:
                    continue
                with st.expander(label_clean(bucket), expanded=False):
                    for it in items:
                        key = f"pkg::{bucket}::{it}"
                        if key not in st.session_state.pkg_checks:
                            st.session_state.pkg_checks[key] = False
                        st.session_state.pkg_checks[key] = st.checkbox(it, value=st.session_state.pkg_checks[key], key=key)

                        total_items += 1
                        if st.session_state.pkg_checks[key]:
                            checked_items += 1

            pct = int(round((checked_items / max(1, total_items)) * 100))
            st.markdown(
                f"""
                <div class="card">
                  <h4>Submission Package Completion</h4>
                  <div class="muted">Tracks checklist progress (not compliance).</div>
                  <div class="divider"></div>
                  <b>{pct}%</b> complete ({checked_items}/{total_items})
                </div>
                """,
                unsafe_allow_html=True
            )

    with st.expander("Compliance Matrix", expanded=False):
        if not matrix_rows:
            ui_notice("No requirements extracted", "Paste/upload Section L/M and re-run Analyze.", tone="warn")
        else:
            section_options = DEFAULT_SECTIONS.copy()
            for kname in (drafts or {}).keys():
                if kname not in section_options:
                    section_options.insert(-1, kname)

            for row in matrix_rows[:60]:
                with st.expander(f"{row['id']} — {row['requirement'][:90]}{'...' if len(row['requirement'])>90 else ''}", expanded=False):
                    st.write("**Requirement:**", row["requirement"])

                    col1, col2, col3 = st.columns([1.2, 1, 1.2])
                    with col1:
                        row["section"] = st.selectbox(
                            "Mapped Section",
                            options=section_options,
                            index=section_options.index(row.get("section") or "Technical Approach")
                            if (row.get("section") in section_options)
                            else section_options.index("Technical Approach"),
                            key=f"sec_{row['id']}"
                        )
                    with col2:
                        row["status"] = st.selectbox(
                            "Status",
                            options=["Pass", "Fail", "Unknown"],
                            index=["Pass", "Fail", "Unknown"].index(row.get("status", "Unknown")),
                            key=f"status_{row['id']}"
                        )
                    with col3:
                        row["notes"] = st.text_input("Notes", value=row.get("notes", ""), key=f"note_{row['id']}")

                    if row["section"] == "Other / Add New Section":
                        new_title_default = f"{row['id']} Requirement Response"
                        new_title = st.text_input("New section title", value=new_title_default, key=f"newtitle_{row['id']}")
                        if st.button("Add missing section to Drafts", key=f"addsection_{row['id']}"):
                            drafts_local = st.session_state.drafts or {}
                            if new_title not in drafts_local:
                                drafts_local[new_title] = f"{new_title}\n\n[Write your response here.]\n\nRequirement:\n{row['requirement']}\n"
                                st.session_state.drafts = drafts_local
                            row["section"] = new_title
                            ui_notice("Section added", f"Added section: {new_title}", tone="good")

            st.session_state.matrix_rows = matrix_rows

    with st.expander("Validation Lock (Pre-Submit Gate)", expanded=False):
        deadline_detected = bool(rules.get("Due Date/Deadline"))

        if deadline_detected:
            st.session_state.deadline_ack = st.checkbox(
                "I acknowledge the detected submission deadline is correct (verify Section L and cover page).",
                value=st.session_state.deadline_ack
            )
        else:
            st.caption("No deadline detected. Gate will not require deadline acknowledgement (still verify manually).")

        if st.button("Run Pre-Submission Check", use_container_width=True):
            st.session_state.validation_last = run_pre_submit_gate(
                company=c,
                rules=rules,
                matrix_rows=matrix_rows,
                deadline_acknowledged=st.session_state.deadline_ack
            )

        vr = st.session_state.validation_last
        if vr:
            if vr["level"] == "blocked":
                ui_notice("Status: NOT COMPLIANT", "Export is blocked until items are resolved.", tone="bad")
                for r in vr["blocked_reasons"]:
                    st.write("•", r)
                if vr["risk_reasons"]:
                    ui_notice("Additional risks", "These do not block export, but should be addressed.", tone="warn")
                    for r in vr["risk_reasons"]:
                        st.write("•", r)
            elif vr["level"] == "risk":
                ui_notice("Status: AT RISK", "Export is allowed once drafts exist, but risks remain.", tone="warn")
                for r in vr["risk_reasons"]:
                    st.write("•", r)
            else:
                ui_notice("Status: READY", "Gate passed. You can export once drafts are generated.", tone="good")

    with st.expander("Submission Rules / Forms / Attachments / Amendments", expanded=False):
        with st.expander("Submission Rules", expanded=False):
            if rules:
                for label, lines in rules.items():
                    with st.expander(label_clean(label), expanded=False):
                        for ln in lines:
                            st.write("•", ln)
            else:
                st.write("No obvious submission rules detected yet. Upload/paste more of Section L/M.")

        with st.expander("Forms / Attachments / Amendments", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Forms Found**")
                if forms:
                    for f in forms:
                        st.write("•", f)
                else:
                    st.write("None detected.")
            with col2:
                st.markdown("**Amendments / Mods referenced**")
                if amendments:
                    for a in amendments[:15]:
                        st.write("•", a)
                else:
                    st.write("None detected.")

            st.markdown("**Attachments / Exhibits**")
            if attachments:
                for a in attachments[:25]:
                    st.write("•", a)
            else:
                st.write("None detected.")

            if separate:
                st.markdown("**Separate submission indicators**")
                for ln in separate[:25]:
                    st.write("•", ln)

    with st.expander("Warnings", expanded=False):
        for w in warns:
            ui_notice("Warning", w, tone="warn")

    with st.expander("Compliance Checklist", expanded=False):
        for idx, it in enumerate(checklist_items):
            key = f"chk_{idx}_{it['source']}"
            if key not in st.session_state.checklist_done:
                st.session_state.checklist_done[key] = False
            label = f"{it['item']}  —  [{it['status']}]  ({it['source']})"
            st.session_state.checklist_done[key] = st.checkbox(label, value=st.session_state.checklist_done[key], key=key)

    with st.expander("Draft Proposal Sections", expanded=False):
        kws = st.session_state.keywords or []
        st.caption("Tailoring keywords (auto-extracted): " + (", ".join(kws[:10]) if kws else "None detected yet"))

        if st.button("Generate Draft Sections", use_container_width=True):
            st.session_state.drafts = generate_drafts(
                sow_snips=st.session_state.sow_snips or [],
                keywords=kws,
                rules=rules,
                forms=forms,
                attachments=attachments,
                company=c
            )
            ui_notice("Draft generated", "Expand sections below to review.", tone="good")

        drafts = st.session_state.drafts or {}
        if drafts:
            for title, body in drafts.items():
                with st.expander(title, expanded=False):
                    st.text_area(label="", value=body, height=260)
        else:
            ui_notice("Drafts not generated", "Generate drafts to enable export.", tone="neutral")

    with st.expander("Export (Word Proposal Package)", expanded=True):
        vr = st.session_state.validation_last
        export_blocked = False
        block_reason = ""

        if vr and vr.get("level") == "blocked":
            export_blocked = True
            block_reason = "Export is disabled because the Pre-Submission Gate is NOT COMPLIANT."
        elif not (st.session_state.drafts or {}):
            export_blocked = True
            block_reason = "Export is disabled until you generate draft sections."

        if export_blocked:
            ui_notice("Export locked", block_reason, tone="bad")
            st.caption("Fix the issues above, run the Gate again, then Export will unlock.")
        else:
            doc_bytes = build_proposal_docx_bytes(
                company=c,
                logo_bytes=logo_bytes,
                rfp_diag=diag,
                rules=rules,
                forms=forms,
                attachments=attachments,
                amendments=amendments,
                separate=separate,
                warnings=warns,
                checklist_items=checklist_items,
                matrix_rows=st.session_state.matrix_rows or [],
                drafts=st.session_state.drafts or {},
                validation_result=vr,
                submission_pkg=submission_pkg,
            )
            st.download_button(
                label="Download Proposal Package (.docx)",
                data=doc_bytes,
                file_name="proposal_package.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            st.caption("In Word: right-click the Table of Contents → Update Field → Update entire table.")

    with st.expander("RFP Preview", expanded=False):
        st.text_area("RFP Preview (first 1500 characters)", st.session_state.rfp_text[:1500], height=220)