import io
import json
import re
import base64
import math
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime

import streamlit as st
from pypdf import PdfReader
import docx  # python-docx
from docx.shared import Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from openpyxl import Workbook
from openpyxl.utils import get_column_letter


# ============================================================
# Path.ai — Federal Proposal Builder
# ============================================================
st.set_page_config(page_title="Path.ai — Proposal Builder", layout="wide")

BUILD_VERSION = "v1.3.0"
BUILD_DATE = "Jan 9, 2026"

APP_NAME = "Path.ai"
PRIMARY = "#5B7CFF"
ACCENT = "#25C2A0"
WARN = "#F5B700"
BAD = "#FF4D4D"
INK = "#0B1220"


# ============================================================
# UI / Branding
# ============================================================
def inject_css():
    st.markdown(
        f"""
        <style>
        /* Global */
        html, body, [class*="css"] {{
            font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
        }}
        .block-container {{
            padding-top: 0.9rem;
            padding-bottom: 2.5rem;
            max-width: 1200px;
        }}

        /* Hide Streamlit chrome bits */
        header {{ visibility: hidden; height: 0; }}
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}

        /* Hero */
        .hero {{
            border-radius: 22px;
            padding: 18px 18px 14px 18px;
            background: radial-gradient(1200px 500px at 20% 0%, rgba(91,124,255,0.25), rgba(37,194,160,0.12) 45%, rgba(255,255,255,0.0) 70%),
                        linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.82));
            border: 1px solid rgba(11,18,32,0.08);
            box-shadow: 0 12px 40px rgba(11,18,32,0.06);
            margin-bottom: 12px;
        }}
        .hero-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
        }}
        .brand {{
            display:flex;
            align-items:center;
            gap:10px;
        }}
        .logo-dot {{
            width: 12px; height: 12px; border-radius: 999px;
            background: {PRIMARY};
            box-shadow: 0 0 0 6px rgba(91,124,255,0.18);
        }}
        .brand-name {{
            font-weight: 800; letter-spacing: -0.02em;
            color: {INK};
            font-size: 1.1rem;
        }}
        .build {{
            color: rgba(11,18,32,0.55);
            font-size: 0.85rem;
            white-space: nowrap;
        }}

        .hero-grid {{
            display: grid;
            grid-template-columns: 1.3fr 0.7fr;
            gap: 14px;
            margin-top: 10px;
        }}
        .hero-title {{
            font-size: 1.45rem;
            font-weight: 820;
            letter-spacing: -0.03em;
            color: {INK};
            margin: 0 0 6px 0;
        }}
        .hero-sub {{
            margin: 0;
            color: rgba(11,18,32,0.68);
            font-size: 0.98rem;
            line-height: 1.35;
        }}

        /* "Walking path" loader (simple SVG + animation) */
        .walker {{
            border-radius: 18px;
            padding: 12px;
            border: 1px solid rgba(11,18,32,0.08);
            background: rgba(255,255,255,0.86);
            overflow:hidden;
            position:relative;
            min-height: 110px;
        }}
        .walker svg {{
            width: 100%;
            height: 110px;
        }}
        .walkman {{
            animation: walk 2.8s linear infinite;
        }}
        @keyframes walk {{
            0% {{ transform: translateX(-8%); opacity: 0.4; }}
            10% {{opacity:1;}}
            100% {{ transform: translateX(105%); opacity: 0.4; }}
        }}

        /* KPI chips */
        .kpi-wrap {{
            position: sticky;
            top: 0.6rem;
            z-index: 50;
            border-radius: 18px;
            padding: 12px 14px;
            background: rgba(255,255,255,0.90);
            border: 1px solid rgba(11,18,32,0.08);
            backdrop-filter: blur(8px);
            box-shadow: 0 10px 30px rgba(11,18,32,0.05);
            margin-bottom: 12px;
        }}
        .kpi-row {{
            display:flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items:center;
            justify-content: space-between;
        }}
        .chips {{
            display:flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items:center;
        }}
        .chip {{
            display:inline-flex;
            align-items:center;
            gap: 8px;
            padding: 7px 12px;
            border-radius: 999px;
            border: 1px solid rgba(11,18,32,0.10);
            font-weight: 700;
            font-size: 0.88rem;
            background: rgba(255,255,255,0.85);
        }}
        .dot {{
            width: 10px; height: 10px; border-radius: 999px;
        }}
        .dot-good {{ background: {ACCENT}; box-shadow: 0 0 0 5px rgba(37,194,160,0.16); }}
        .dot-warn {{ background: {WARN}; box-shadow: 0 0 0 5px rgba(245,183,0,0.18); }}
        .dot-bad  {{ background: {BAD}; box-shadow: 0 0 0 5px rgba(255,77,77,0.16); }}

        /* Progress bar */
        .progress-shell {{
            width: 240px;
            height: 10px;
            border-radius: 999px;
            background: rgba(11,18,32,0.10);
            overflow:hidden;
            border: 1px solid rgba(11,18,32,0.06);
        }}
        .progress-bar {{
            height: 100%;
            width: var(--w);
            background: linear-gradient(90deg, {PRIMARY}, {ACCENT});
        }}

        /* Cards */
        .card {{
            border: 1px solid rgba(11,18,32,0.08);
            border-radius: 18px;
            padding: 14px 14px 12px 14px;
            background: rgba(255,255,255,0.90);
            box-shadow: 0 10px 30px rgba(11,18,32,0.04);
            margin-bottom: 12px;
        }}
        .card h4 {{
            margin: 0 0 6px 0;
            font-size: 1.0rem;
        }}
        .muted {{
            color: rgba(11,18,32,0.62);
            font-size: 0.92rem;
        }}
        .divider {{
            height: 1px;
            background: rgba(11,18,32,0.08);
            margin: 10px 0;
        }}

        /* Notice */
        .notice {{
            border-radius: 18px;
            padding: 12px 14px;
            border: 1px solid rgba(11,18,32,0.08);
            background: rgba(255,255,255,0.88);
            margin: 10px 0 12px 0;
        }}
        .notice-title {{
            font-weight: 800;
            margin: 0 0 4px 0;
            font-size: 0.98rem;
            color: {INK};
        }}
        .notice-body {{
            margin: 0;
            font-size: 0.93rem;
            color: rgba(11,18,32,0.78);
            line-height: 1.35;
        }}
        .notice-neutral {{ background: rgba(91,124,255,0.06); }}
        .notice-good    {{ background: rgba(37,194,160,0.10); }}
        .notice-warn    {{ background: rgba(245,183,0,0.12); }}
        .notice-bad     {{ background: rgba(255,77,77,0.12); }}

        /* Bigger buttons */
        .stButton>button {{
            border-radius: 14px !important;
            padding: 0.72rem 1.0rem !important;
            font-weight: 800 !important;
            border: 1px solid rgba(11,18,32,0.10) !important;
        }}
        .stDownloadButton>button {{
            border-radius: 14px !important;
            padding: 0.72rem 1.0rem !important;
            font-weight: 800 !important;
        }}

        /* Tabs look */
        .stTabs [data-baseweb="tab"] {{
            padding-top: 14px;
            padding-bottom: 14px;
            font-weight: 800;
            border-radius: 14px;
        }}

        /* Checkboxes: slightly larger */
        div[data-testid="stCheckbox"] label p {{
            font-size: 0.95rem;
        }}

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


def render_hero():
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-top">
                <div class="brand">
                    <div class="logo-dot"></div>
                    <div class="brand-name">{APP_NAME}</div>
                </div>
                <div class="build">{BUILD_VERSION} • {BUILD_DATE}</div>
            </div>
            <div class="hero-grid">
                <div>
                    <div class="hero-title">Proposal prep that feels guided, not overwhelming.</div>
                    <p class="hero-sub">
                        Upload your solicitation, fill company info once, then follow a clean task list that only shows what matters for your situation.
                    </p>
                </div>
                <div class="walker">
                    <svg viewBox="0 0 600 120" xmlns="http://www.w3.org/2000/svg">
                        <path d="M20 90 C 120 20, 220 140, 320 70 C 420 0, 500 120, 590 50"
                              fill="none" stroke="rgba(91,124,255,0.35)" stroke-width="6" stroke-linecap="round"/>
                        <circle cx="20" cy="90" r="7" fill="{ACCENT}"/>
                        <circle cx="590" cy="50" r="7" fill="{PRIMARY}"/>
                        <g class="walkman">
                            <circle cx="0" cy="0" r="9" fill="{INK}" opacity="0.85"/>
                            <path d="M0 9 L0 36" stroke="{INK}" stroke-width="4" stroke-linecap="round" opacity="0.85"/>
                            <path d="M0 18 L-10 26" stroke="{INK}" stroke-width="4" stroke-linecap="round" opacity="0.85"/>
                            <path d="M0 18 L10 28" stroke="{INK}" stroke-width="4" stroke-linecap="round" opacity="0.85"/>
                            <path d="M0 36 L-10 54" stroke="{INK}" stroke-width="4" stroke-linecap="round" opacity="0.85"/>
                            <path d="M0 36 L10 52" stroke="{INK}" stroke-width="4" stroke-linecap="round" opacity="0.85"/>
                        </g>
                    </svg>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# Helpers
# ============================================================
def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "")).strip()


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items or []:
        k = (x or "").lower()
        if k not in seen and k.strip():
            seen.add(k)
            out.append(x)
    return out


def scan_lines(text: str, max_lines: int = 15000) -> List[str]:
    lines = []
    for raw in (text or "").splitlines():
        s = normalize_line(raw)
        if s:
            lines.append(s)
        if len(lines) >= max_lines:
            break
    return lines


def label_clean(title: str) -> str:
    return re.sub(r"\s*\(starter\)\s*$", "", title or "").strip()


# ============================================================
# Extraction (PDF/DOCX/TXT)
# ============================================================
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


# ============================================================
# RFP Intelligence (Detection)
# ============================================================
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
    "amendment", "amendments",
    "pricing", "price schedule", "cost proposal", "rate sheet", "spreadsheet", "xlsx", "excel",
    "representations and certifications", "reps and certs",
    "sf-1449", "sf 1449", "sf-33", "sf 33", "sf-30", "sf 30", "sf-18", "sf 18",
]

SUBMISSION_RULE_PATTERNS = [
    (r"\bpage limit\b|\bnot exceed\s+\d+\s+pages\b|\bpages maximum\b", "Page limit"),
    (r"\bfont\b|\b12[-\s]?point\b|\b11[-\s]?point\b|\bTimes New Roman\b|\bArial\b|\bCalibri\b", "Font requirement"),
    (r"\bmargins?\b|\b1 inch\b|\bone inch\b|\b0\.?\d+\s*inch\b|\b1\"\b", "Margin requirement"),
    (r"\bdue\b|\bdue date\b|\bdeadline\b|\bno later than\b|\boffers?\s+are\s+due\b|\bproposal\s+is\s+due\b", "Submission deadline"),
    (r"\bsubmit\b|\bsubmission\b|\be-?mail\b|\bemailed\b|\bportal\b|\bupload\b|\bebuy\b|\bpiee\b|\bfedconnect\b|\bsam\.gov\b", "Submission method"),
    (r"\bfile format\b|\bpdf\b|\bdocx\b|\bexcel\b|\bxlsx\b|\bzip\b|\bencrypt\b|\bpassword\b", "File format"),
    (r"\bsection\s+l\b|\bsection\s+m\b", "Sections L/M referenced"),
    (r"\bvolume\s+(?:i|ii|iii|iv|v|vi|1|2|3|4|5|6)\b", "Volumes referenced"),
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


def refine_deadline(text: str, rules: Dict[str, List[str]]) -> Dict[str, List[str]]:
    lines = scan_lines(text, max_lines=16000)
    best = None
    best_score = -1

    for line in lines:
        low = line.lower()

        if not any(k in low for k in DUE_KEYWORDS) and "due" not in low:
            continue
        if "invoice" in low or "payment" in low:
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
        rules["Submission deadline"] = [best]

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


# ============================================================
# Company Info
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
        critical.append("UEI is missing.")
    if not company.poc_name.strip():
        critical.append("Point of contact name is missing.")
    if not company.poc_email.strip():
        critical.append("Point of contact email is missing.")

    if not company.address.strip():
        recommended.append("Business address is missing.")
    if not company.certifications:
        recommended.append("Certifications / set-asides are not selected.")
    if not company.capabilities.strip():
        recommended.append("Capabilities are empty.")
    if not company.differentiators.strip():
        recommended.append("Differentiators are empty.")
    if not company.proposal_title.strip():
        recommended.append("Proposal/contract title is blank.")
    if not company.solicitation_number.strip():
        recommended.append("Solicitation number is blank.")
    if not company.agency_customer.strip():
        recommended.append("Agency/customer is blank.")

    return critical, recommended


# ============================================================
# Draft Generator
# ============================================================
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
    due = rules.get("Submission deadline", ["Not detected"])[0] if rules.get("Submission deadline") else "Not detected"
    method = rules.get("Submission method", ["Not detected"])[0] if rules.get("Submission method") else "Not detected"
    vols = rules.get("Volumes referenced", [])
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

{company.legal_name or "[Company Name]"} submits this proposal in response to the solicitation. We understand the requirement and will execute with a low-risk approach aligned to: {kw}.

Submission details (detected — verify Section L and the cover page):
- Deadline: {due}
- Method: {method}

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
- Execution Plan: phased delivery with weekly status, quality checks, and documented approvals.
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

Submission details (detected — verify Section L/M):
- Deadline: {due}
- Method: {method}
- Volumes: {vol_block}

Forms detected:
{forms_block}

Attachment/appendix/exhibit mentions:
{att_block}
"""

    return {
        "Cover Letter": cover,
        "Executive Summary": exec_summary,
        "Technical Approach": tech,
        "Management Plan": mgmt,
        "Past Performance": pp,
        "Compliance Snapshot": compliance,
    }


# ============================================================
# Compliance Matrix Extraction (best-effort)
# ============================================================
REQ_TRIGGER = re.compile(r"\b(shall|must|will)\b", re.IGNORECASE)
REQ_NUMBERED = re.compile(r"^(\(?[a-z0-9]{1,4}\)?[\.\)]|\d{1,3}\.)\s+", re.IGNORECASE)


def extract_requirements_v2(rfp_text: str, max_reqs: int = 80) -> List[Dict[str, str]]:
    lines = scan_lines(rfp_text, max_lines=14000)

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


# ============================================================
# Relevance Gating (the rule that fixes everything)
# ============================================================
G_ACTIONABLE = "ACTIONABLE"
G_INFO = "INFORMATIONAL"
G_IRRELEVANT = "IRRELEVANT"
G_AUTO = "AUTO_RESOLVED"


@dataclass
class ExtractedItem:
    item_id: str
    kind: str               # e.g., "deadline", "method", "form", "attachment", "amendment", "matrix_req"
    title: str              # human-friendly label
    detail: str             # source line / description
    bucket: str             # grouping
    gating_label: str       # ACTIONABLE / INFO / IRRELEVANT / AUTO
    confidence: float       # 0..1
    status: str             # "open" / "done"
    source: str             # where it came from


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def classify_item(kind: str, title: str, detail: str, context: Dict[str, Any]) -> Tuple[str, float]:
    """
    Rules (simple, strong defaults):
    - Missing criticals -> ACTIONABLE, high confidence
    - Detected facts -> INFO, medium/high confidence
    - Noisy/weak signals -> IRRELEVANT, low confidence
    - Auto-resolved -> AUTO, high confidence
    """
    detail_low = (detail or "").lower()

    # Some global signals
    has_rfp = bool((context.get("rfp_text") or "").strip())
    diag = context.get("rfp_diag") or {}
    likely_scanned = bool(diag.get("likely_scanned"))

    # Confidence base by kind
    base = {
        "deadline_missing": 0.95,
        "method_missing": 0.92,
        "format_missing": 0.88,
        "company_missing": 0.96,
        "matrix_fail": 0.98,
        "matrix_unknown": 0.82,
        "matrix_req": 0.70,
        "form": 0.85,
        "attachment": 0.72,
        "amendment": 0.78,
        "rule_line": 0.68,
        "diagnostic": 0.90,
    }.get(kind, 0.60)

    # Penalty if scanned (more uncertainty)
    if likely_scanned and kind in ["rule_line", "attachment", "matrix_req"]:
        base -= 0.18

    # If no rfp, almost everything irrelevant except "upload rfp"
    if not has_rfp and kind not in ["diagnostic", "company_missing"]:
        return (G_IRRELEVANT, 0.15)

    # Hard rules
    if kind.endswith("_missing"):
        return (G_ACTIONABLE, clamp01(base))

    if kind == "company_missing":
        return (G_ACTIONABLE, clamp01(base))

    if kind in ["matrix_fail"]:
        return (G_ACTIONABLE, clamp01(base))

    if kind in ["matrix_unknown"]:
        # Unknowns are actionable but slightly lower confidence
        return (G_ACTIONABLE, clamp01(base))

    # Detected lines that are not "to-do" become informational
    if kind in ["form", "amendment"]:
        return (G_INFO, clamp01(base))

    if kind in ["attachment", "rule_line", "matrix_req"]:
        # attachments can become actionable if they clearly say "must include"
        if "must" in detail_low or "shall" in detail_low or "required" in detail_low:
            return (G_ACTIONABLE, clamp01(base + 0.08))
        return (G_INFO, clamp01(base))

    if kind == "diagnostic":
        # show if scanned
        if likely_scanned:
            return (G_ACTIONABLE, clamp01(base))
        return (G_AUTO, clamp01(base))

    return (G_INFO, clamp01(base))


def build_items_from_analysis(context: Dict[str, Any]) -> List[ExtractedItem]:
    """
    Converts raw detections + state into gated items.
    """
    items: List[ExtractedItem] = []
    rid = 1

    rfp_text = context.get("rfp_text") or ""
    rules = context.get("rules") or {}
    forms = context.get("forms") or []
    attachments = context.get("attachments") or []
    amendments = context.get("amendments") or []
    diag = context.get("rfp_diag") or {}
    company: CompanyInfo = context.get("company")

    crit, rec = missing_info_alerts(company)

    # 1) Diagnostics
    diag_kind = "diagnostic"
    diag_title = "RFP extraction quality"
    diag_detail = f"Likely scanned PDF: {'Yes' if diag.get('likely_scanned') else 'No'}"
    gating, conf = classify_item(diag_kind, diag_title, diag_detail, context)
    items.append(ExtractedItem(
        item_id=f"I{rid:04d}", kind=diag_kind, title=diag_title, detail=diag_detail,
        bucket="Intake", gating_label=gating, confidence=conf,
        status="open" if gating == G_ACTIONABLE else "done",
        source="Diagnostics"
    ))
    rid += 1

    # 2) Missing criticals in company profile
    for x in crit:
        kind = "company_missing"
        title = "Complete company profile"
        detail = x
        gating, conf = classify_item(kind, title, detail, context)
        items.append(ExtractedItem(
            item_id=f"I{rid:04d}", kind=kind, title=title, detail=detail,
            bucket="Company", gating_label=gating, confidence=conf,
            status="open",
            source="Company Profile"
        ))
        rid += 1

    # Recommended fields -> informational (not to-do noise)
    for x in rec:
        kind = "rule_line"
        title = "Recommendation"
        detail = x
        gating, conf = (G_INFO, 0.55)
        items.append(ExtractedItem(
            item_id=f"I{rid:04d}", kind=kind, title=title, detail=detail,
            bucket="Reference", gating_label=gating, confidence=conf,
            status="done",
            source="Company Profile"
        ))
        rid += 1

    # 3) Missing submission criticals
    if rfp_text.strip():
        if not rules.get("Submission deadline"):
            kind = "deadline_missing"
            title = "Confirm submission deadline"
            detail = "Deadline not detected. Add/paste Section L or cover page and analyze again."
            gating, conf = classify_item(kind, title, detail, context)
            items.append(ExtractedItem(
                item_id=f"I{rid:04d}", kind=kind, title=title, detail=detail,
                bucket="Submission & format", gating_label=gating, confidence=conf,
                status="open", source="RFP"
            ))
            rid += 1

        if not rules.get("Submission method"):
            kind = "method_missing"
            title = "Confirm submission method"
            detail = "Method not detected (email vs portal). Add/paste Section L and analyze again."
            gating, conf = classify_item(kind, title, detail, context)
            items.append(ExtractedItem(
                item_id=f"I{rid:04d}", kind=kind, title=title, detail=detail,
                bucket="Submission & format", gating_label=gating, confidence=conf,
                status="open", source="RFP"
            ))
            rid += 1

        if not rules.get("File format"):
            kind = "format_missing"
            title = "Confirm file format rules"
            detail = "File format rules not detected (PDF/Excel/ZIP). Add/paste Section L and analyze again."
            gating, conf = classify_item(kind, title, detail, context)
            items.append(ExtractedItem(
                item_id=f"I{rid:04d}", kind=kind, title=title, detail=detail,
                bucket="Submission & format", gating_label=gating, confidence=conf,
                status="open", source="RFP"
            ))
            rid += 1

    # 4) Detected rules -> informational reference
    for label, lines in (rules or {}).items():
        for ln in lines:
            kind = "rule_line"
            title = label_clean(label)
            detail = ln
            gating, conf = classify_item(kind, title, detail, context)
            status = "done" if gating in [G_INFO, G_AUTO] else "open"
            items.append(ExtractedItem(
                item_id=f"I{rid:04d}", kind=kind, title=title, detail=detail,
                bucket="Reference", gating_label=gating, confidence=conf,
                status=status, source="RFP"
            ))
            rid += 1

    # 5) Forms / amendments -> informational
    for f in forms:
        kind = "form"
        title = "Form referenced"
        detail = f
        gating, conf = classify_item(kind, title, detail, context)
        items.append(ExtractedItem(
            item_id=f"I{rid:04d}", kind=kind, title=title, detail=detail,
            bucket="Reference", gating_label=gating, confidence=conf,
            status="done" if gating != G_ACTIONABLE else "open",
            source="RFP"
        ))
        rid += 1

    for a in amendments:
        kind = "amendment"
        title = "Amendment referenced"
        detail = a
        gating, conf = classify_item(kind, title, detail, context)
        items.append(ExtractedItem(
            item_id=f"I{rid:04d}", kind=kind, title=title, detail=detail,
            bucket="Reference", gating_label=gating, confidence=conf,
            status="done" if gating != G_ACTIONABLE else "open",
            source="RFP"
        ))
        rid += 1

    # 6) Attachments -> informational unless clearly required language
    for ln in attachments:
        kind = "attachment"
        title = "Attachment / exhibit mentioned"
        detail = ln
        gating, conf = classify_item(kind, title, detail, context)
        items.append(ExtractedItem(
            item_id=f"I{rid:04d}", kind=kind, title=title, detail=detail,
            bucket="Attachments & exhibits" if gating == G_ACTIONABLE else "Reference",
            gating_label=gating, confidence=conf,
            status="open" if gating == G_ACTIONABLE else "done",
            source="RFP"
        ))
        rid += 1

    return items


def items_actionable(items: List[ExtractedItem], conf_min: float = 0.45) -> List[ExtractedItem]:
    return [
        x for x in (items or [])
        if x.gating_label == G_ACTIONABLE and x.confidence >= conf_min
    ]


def items_informational(items: List[ExtractedItem], conf_min: float = 0.35) -> List[ExtractedItem]:
    return [
        x for x in (items or [])
        if x.gating_label == G_INFO and x.confidence >= conf_min
    ]


# ============================================================
# KPI + Progress (based on ACTIONABLE only)
# ============================================================
def compute_task_kpis(task_state: Dict[str, bool], actionable_items: List[ExtractedItem]) -> Dict[str, Any]:
    total = len(actionable_items)
    done = 0
    for it in actionable_items:
        key = f"task::{it.item_id}"
        if task_state.get(key, False):
            done += 1
    pct = int(round((done / max(1, total)) * 100))
    return {"total": total, "done": done, "pct": pct}


def kpi_color_from_status(pct: int) -> str:
    if pct >= 85:
        return "good"
    if pct >= 55:
        return "warn"
    return "bad"


def render_kpis(task_kpi: Dict[str, Any], matrix_kpi: Dict[str, int], gate_status: str):
    task_pct = task_kpi.get("pct", 0)

    # Matrix chip: based on fails/unknowns
    fail = matrix_kpi.get("fail", 0)
    unk = matrix_kpi.get("unknown", 0)

    matrix_level = "good"
    if fail > 0:
        matrix_level = "bad"
    elif unk > 0:
        matrix_level = "warn"

    gate_level = "good" if gate_status == "READY" else ("warn" if gate_status == "AT RISK" else "bad")

    def chip(label: str, level: str) -> str:
        dot = "dot-good" if level == "good" else ("dot-warn" if level == "warn" else "dot-bad")
        return f"""
          <span class="chip"><span class="dot {dot}"></span>{label}</span>
        """

    width = f"{task_pct}%"
    st.markdown(
        f"""
        <div class="kpi-wrap">
            <div class="kpi-row">
                <div class="chips">
                    {chip(f"Tasks: {task_kpi['done']}/{task_kpi['total']} ({task_pct}%)", kpi_color_from_status(task_pct))}
                    {chip(f"Matrix — Fail: {fail}", "bad" if fail>0 else "good")}
                    {chip(f"Matrix — Unknown: {unk}", "warn" if unk>0 else "good")}
                    {chip(f"Gate: {gate_status}", gate_level)}
                </div>
                <div style="display:flex; align-items:center; gap:10px;">
                    <div class="muted" style="font-weight:800;">Progress</div>
                    <div class="progress-shell">
                        <div class="progress-bar" style="--w:{width};"></div>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# Compliance Matrix state + gate
# ============================================================
def compute_matrix_kpis(matrix_rows: List[Dict[str, str]]) -> Dict[str, int]:
    total = len(matrix_rows or [])
    pass_ct = sum(1 for r in (matrix_rows or []) if (r.get("status") == "Pass"))
    fail_ct = sum(1 for r in (matrix_rows or []) if (r.get("status") == "Fail"))
    unk_ct = sum(1 for r in (matrix_rows or []) if (r.get("status") in [None, "", "Unknown"]))
    return {"total": total, "pass": pass_ct, "fail": fail_ct, "unknown": unk_ct}


def run_gate(company: CompanyInfo, rules: Dict[str, List[str]], matrix_rows: List[Dict[str, str]]) -> Tuple[str, List[str]]:
    """
    READY:
      - critical company fields present
      - 0 FAIL in matrix
      - deadline + method detected OR user acknowledges missing and proceeds later (we keep strict: detected recommended)
    AT RISK:
      - 0 FAIL, but unknowns exist or missing submission method/deadline/format
    NOT READY:
      - FAIL exists OR critical company missing
    """
    crit, _ = missing_info_alerts(company)
    k = compute_matrix_kpis(matrix_rows)

    reasons = []
    if crit:
        reasons.append("Company profile has missing critical fields.")
    if k["fail"] > 0:
        reasons.append("Compliance matrix has items marked FAIL.")
    if not rules.get("Submission deadline"):
        reasons.append("Submission deadline not detected.")
    if not rules.get("Submission method"):
        reasons.append("Submission method not detected.")
    if not rules.get("File format"):
        reasons.append("File format rules not detected.")

    if crit or k["fail"] > 0:
        return "NOT READY", reasons

    if k["unknown"] > 0 or (not rules.get("Submission deadline") or not rules.get("Submission method") or not rules.get("File format")):
        return "AT RISK", reasons

    return "READY", []


# ============================================================
# Word Export Helpers
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
    tasks: List[ExtractedItem],
    task_state: Dict[str, bool],
    matrix_rows: List[Dict[str, str]],
    drafts: Dict[str, str],
    gate_status: str,
    gate_reasons: List[str],
) -> bytes:
    doc = docx.Document()

    set_word_styles_no_blue_links(doc)
    add_page_numbers(doc)
    add_title_page(doc, company, logo_bytes)
    add_table_of_contents(doc)

    # Diagnostics
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
        doc.add_paragraph("No file diagnostics available.")
    doc.add_page_break()

    # Gate
    doc.add_heading("Gate Status", level=1)
    doc.add_paragraph(f"Status: {gate_status}")
    if gate_reasons:
        doc.add_paragraph("Notes:", style="List Bullet")
        for r in gate_reasons:
            doc.add_paragraph(r, style="List Bullet 2")
    doc.add_page_break()

    # Tasks (ACTIONABLE only)
    doc.add_heading("Submission Task List (Actionable)", level=1)
    if tasks:
        for it in tasks:
            key = f"task::{it.item_id}"
            done = task_state.get(key, False)
            mark = "☑" if done else "☐"
            doc.add_paragraph(f"{mark} {it.bucket} — {it.title}: {it.detail}", style="List Bullet")
    else:
        doc.add_paragraph("No actionable tasks detected.")
    doc.add_page_break()

    # Matrix
    doc.add_heading("Compliance Matrix (Best-effort)", level=1)
    if matrix_rows:
        table = doc.add_table(rows=1, cols=5)
        hdr = table.rows[0].cells
        hdr[0].text = "Req ID"
        hdr[1].text = "Requirement"
        hdr[2].text = "Mapped Section"
        hdr[3].text = "Status"
        hdr[4].text = "Notes"

        for row in matrix_rows[:120]:
            r = table.add_row().cells
            r[0].text = row.get("id", "")
            r[1].text = row.get("requirement", "")
            r[2].text = row.get("section", "")
            r[3].text = row.get("status", "Unknown")
            r[4].text = row.get("notes", "")
    else:
        doc.add_paragraph("No requirements extracted.", style="List Bullet")
    doc.add_page_break()

    # Evidence
    doc.add_heading("Submission Rules (Detected)", level=1)
    if rules:
        for k, lines in rules.items():
            doc.add_paragraph(k, style="List Bullet")
            for ln in (lines or [])[:8]:
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
        for a in attachments[:20]:
            doc.add_paragraph(a, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc.add_heading("Amendments / Mods (Detected)", level=2)
    if amendments:
        for a in amendments[:20]:
            doc.add_paragraph(a, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")
    doc.add_page_break()

    # Drafts
    doc.add_heading("Draft Proposal Sections", level=1)
    if drafts:
        for title, body in drafts.items():
            doc.add_heading(title, level=2)
            add_paragraph_lines(doc, body)
    else:
        doc.add_paragraph("No draft sections generated.", style="List Bullet")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ============================================================
# Excel Export (Tasks + Matrix)
# ============================================================
def _auto_fit(ws):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                val = str(cell.value) if cell.value is not None else ""
                max_len = max(max_len, len(val))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(55, max(12, max_len + 2))


def build_excel_bytes(actionable: List[ExtractedItem], task_state: Dict[str, bool], matrix_rows: List[Dict[str, str]]) -> bytes:
    wb = Workbook()

    # Sheet 1: Tasks
    ws = wb.active
    ws.title = "Tasks"
    ws.append(["Task ID", "Bucket", "Title", "Detail", "Confidence", "Done"])
    for it in actionable:
        key = f"task::{it.item_id}"
        done = bool(task_state.get(key, False))
        ws.append([it.item_id, it.bucket, it.title, it.detail, round(it.confidence, 2), "YES" if done else "NO"])
    _auto_fit(ws)

    # Sheet 2: Matrix
    ws2 = wb.create_sheet("Compliance Matrix")
    ws2.append(["Req ID", "Requirement", "Mapped Section", "Status", "Notes"])
    for r in (matrix_rows or [])[:500]:
        ws2.append([
            r.get("id",""),
            r.get("requirement",""),
            r.get("section",""),
            r.get("status","Unknown"),
            r.get("notes","")
        ])
    _auto_fit(ws2)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ============================================================
# Persistence (Project Save/Load)
# ============================================================
PROJECT_KEYS = [
    "rfp_text", "rfp_diag", "rules", "forms", "attachments", "amendments", "separate_submit",
    "required_certs", "sow_snips", "keywords", "drafts", "company", "logo_bytes",
    "matrix_rows", "task_checks"
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
        "matrix_rows": st.session_state.matrix_rows,
        "task_checks": st.session_state.task_checks,
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
        st.session_state.matrix_rows = payload.get("matrix_rows", []) or []
        st.session_state.task_checks = payload.get("task_checks", {}) or {}

        return True, "Project loaded."
    except Exception as e:
        return False, f"Could not load project: {e}"


# ============================================================
# Session State Init
# ============================================================
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
if "matrix_rows" not in st.session_state: st.session_state.matrix_rows = []
if "task_checks" not in st.session_state: st.session_state.task_checks = {}


# ============================================================
# App Header
# ============================================================
render_hero()

# Project Save/Load (small, not noisy)
with st.expander("Project save / load", expanded=False):
    st.download_button(
        "Download project (.json)",
        data=export_project_json(),
        file_name="path_ai_project.json",
        mime="application/json",
        use_container_width=True
    )
    up_proj = st.file_uploader("Upload project (.json)", type=["json"])
    if up_proj:
        ok, msg = import_project_json(up_proj.read().decode("utf-8", errors="ignore"))
        ui_notice("Project loaded" if ok else "Load failed", msg, tone="good" if ok else "bad")


# ============================================================
# Horizontal navigation (guided path)
# ============================================================
tabs = st.tabs(["Intake", "Company", "Tasks", "Draft", "Export"])

# Build gated items + KPIs globally
context = {
    "rfp_text": st.session_state.rfp_text,
    "rfp_diag": st.session_state.rfp_diag,
    "rules": st.session_state.rules,
    "forms": st.session_state.forms,
    "attachments": st.session_state.attachments,
    "amendments": st.session_state.amendments,
    "company": st.session_state.company,
}
gated_items = build_items_from_analysis(context)
actionable = items_actionable(gated_items, conf_min=0.45)
info_items = items_informational(gated_items, conf_min=0.35)

task_kpi = compute_task_kpis(st.session_state.task_checks, actionable)
matrix_kpi = compute_matrix_kpis(st.session_state.matrix_rows)
gate_status, gate_reasons = run_gate(st.session_state.company, st.session_state.rules, st.session_state.matrix_rows)

render_kpis(task_kpi, matrix_kpi, gate_status)


# ============================================================
# TAB 1 — Intake
# ============================================================
with tabs[0]:
    st.markdown("### Intake")
    st.markdown('<div class="card"><h4>Upload or paste your solicitation</h4><div class="muted">PDF, DOCX, or text paste. Then click Analyze.</div></div>', unsafe_allow_html=True)

    uploaded = st.file_uploader("Upload RFP (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"])
    pasted = st.text_area("Or paste RFP / RFI text", value=st.session_state.rfp_text, height=240)

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
                ui_notice("Input needed", "Upload a readable file or paste text.", tone="bad")
            else:
                st.session_state.rfp_text = text

                rules = detect_submission_rules(text)
                rules = refine_deadline(text, rules)
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

                # Reset tasks because new analysis can change what’s actionable
                st.session_state.task_checks = {}

                ui_notice("Analysis complete", "Go to Tasks to see what matters.", tone="good")

    with colB:
        diag = st.session_state.rfp_diag or {}
        if diag.get("likely_scanned"):
            ui_notice(
                "Heads up",
                "This PDF looks scanned. If tasks feel incomplete, paste Section L/M text and re-analyze.",
                tone="warn"
            )
        else:
            ui_notice(
                "Tip",
                "If you paste Section L/M, the task list becomes much smarter.",
                tone="neutral"
            )

    with st.expander("Reference (what was detected)", expanded=False):
        st.markdown("**Preview (first 900 characters)**")
        st.text_area("Preview", (st.session_state.rfp_text or "")[:900], height=180)


# ============================================================
# TAB 2 — Company
# ============================================================
with tabs[1]:
    st.markdown("### Company profile")
    st.markdown('<div class="card"><h4>Fill this once — Path.ai reuses it everywhere.</h4><div class="muted">Cover letter, title page, signature block, exports.</div></div>', unsafe_allow_html=True)

    c: CompanyInfo = st.session_state.company

    logo = st.file_uploader("Logo (optional)", type=["png", "jpg", "jpeg"])
    if logo:
        st.session_state.logo_bytes = logo.read()
        ui_notice("Saved", "Logo will appear on the title page export.", tone="good")
        st.image(st.session_state.logo_bytes, width=180)

    st.markdown("#### Proposal details")
    c.proposal_title = st.text_input("Proposal / contract title", value=c.proposal_title)
    c.solicitation_number = st.text_input("Solicitation number", value=c.solicitation_number)
    c.agency_customer = st.text_input("Agency / customer", value=c.agency_customer)

    st.markdown("#### Company details")
    col1, col2 = st.columns(2)
    with col1:
        c.legal_name = st.text_input("Legal company name", value=c.legal_name)
        c.uei = st.text_input("UEI", value=c.uei)
        c.cage = st.text_input("CAGE (optional)", value=c.cage)
        c.naics = st.text_input("Primary NAICS (optional)", value=c.naics)
        c.psc = st.text_input("PSC (optional)", value=c.psc)
    with col2:
        c.address = st.text_area("Business address", value=c.address, height=110)
        c.poc_name = st.text_input("Point of contact name", value=c.poc_name)
        c.poc_email = st.text_input("Point of contact email", value=c.poc_email)
        c.poc_phone = st.text_input("Point of contact phone", value=c.poc_phone)
        c.website = st.text_input("Website (optional)", value=c.website)

    st.markdown("#### Certifications / set-asides")
    options = ["SDVOSB", "VOSB", "8(a)", "WOSB/EDWOSB", "HUBZone", "SBA Small Business", "ISO 9001"]
    c.certifications = st.multiselect("Select all that apply", options=options, default=c.certifications or [])

    st.markdown("#### Capabilities & differentiators")
    c.capabilities = st.text_area("Capabilities (short bullets or paragraph)", value=c.capabilities, height=110)
    c.differentiators = st.text_area("Differentiators (why you)", value=c.differentiators, height=90)

    st.markdown("#### Past performance (optional)")
    c.past_performance = st.text_area("Past performance notes", value=c.past_performance, height=120)

    st.markdown("#### Signature block (cover letter)")
    s1, s2 = st.columns(2)
    with s1:
        c.signer_name = st.text_input("Signer name (optional)", value=c.signer_name)
        c.signer_title = st.text_input("Signer title (optional)", value=c.signer_title)
        c.signer_company = st.text_input("Signer company (optional)", value=c.signer_company)
    with s2:
        c.signer_phone = st.text_input("Signer phone (optional)", value=c.signer_phone)
        c.signer_email = st.text_input("Signer email (optional)", value=c.signer_email)

    st.session_state.company = c

    crit, rec = missing_info_alerts(c)
    if crit:
        ui_notice("Needs attention", "Complete the missing fields to unlock export cleanly.", tone="warn")
        for x in crit:
            st.write("•", x)
    else:
        ui_notice("Looks good", "Critical company fields are complete.", tone="good")

    with st.expander("Reference (recommended improvements)", expanded=False):
        for x in rec:
            st.write("•", x)


# ============================================================
# TAB 3 — Tasks (Home screen)
# ============================================================
with tabs[2]:
    st.markdown("### Task list")
    st.markdown('<div class="card"><h4>Only what matters for this solicitation</h4><div class="muted">These are the items that affect compliance or submission success.</div></div>', unsafe_allow_html=True)

    # Rebuild items live
    context = {
        "rfp_text": st.session_state.rfp_text,
        "rfp_diag": st.session_state.rfp_diag,
        "rules": st.session_state.rules,
        "forms": st.session_state.forms,
        "attachments": st.session_state.attachments,
        "amendments": st.session_state.amendments,
        "company": st.session_state.company,
    }
    gated_items = build_items_from_analysis(context)
    actionable = items_actionable(gated_items, conf_min=0.45)
    info_items = items_informational(gated_items, conf_min=0.35)

    if not st.session_state.rfp_text.strip():
        ui_notice("Start here", "Go to Intake and click Analyze.", tone="warn")
    elif not actionable:
        ui_notice("No tasks found", "That usually means Section L/M wasn’t detected. Paste it into Intake and re-analyze.", tone="warn")
    else:
        # Smart grouping buckets
        buckets: Dict[str, List[ExtractedItem]] = {}
        for it in actionable:
            buckets.setdefault(it.bucket, []).append(it)

        # Render
        for bucket_name in ["Intake", "Submission & format", "Company", "Attachments & exhibits"]:
            if bucket_name in buckets:
                with st.expander(bucket_name, expanded=True):
                    for it in buckets[bucket_name]:
                        key = f"task::{it.item_id}"
                        if key not in st.session_state.task_checks:
                            st.session_state.task_checks[key] = False
                        label = f"{it.title} — {it.detail}"
                        st.session_state.task_checks[key] = st.checkbox(label, value=st.session_state.task_checks[key], key=key)
                        st.caption(f"Confidence: {int(it.confidence*100)}%")

        # Any other buckets
        for bucket_name, its in buckets.items():
            if bucket_name in ["Intake", "Submission & format", "Company", "Attachments & exhibits"]:
                continue
            with st.expander(bucket_name, expanded=False):
                for it in its:
                    key = f"task::{it.item_id}"
                    if key not in st.session_state.task_checks:
                        st.session_state.task_checks[key] = False
                    label = f"{it.title} — {it.detail}"
                    st.session_state.task_checks[key] = st.checkbox(label, value=st.session_state.task_checks[key], key=key)
                    st.caption(f"Confidence: {int(it.confidence*100)}%")

    # Reference drawer
    st.markdown("---")
    with st.expander("Reference (detected details)", expanded=False):
        q = st.text_input("Search reference", value="")
        shown = 0
        for it in info_items:
            blob = f"{it.title} {it.detail}".lower()
            if q.strip() and q.lower() not in blob:
                continue
            st.write(f"• **{it.title}** — {it.detail}")
            shown += 1
            if shown >= 80:
                st.caption("Showing first 80 reference items.")
                break


# ============================================================
# TAB 4 — Draft (includes matrix)
# ============================================================
with tabs[3]:
    st.markdown("### Draft + compliance matrix")
    st.markdown('<div class="card"><h4>Draft sections + quick compliance tracking</h4><div class="muted">Update the matrix only when it’s useful. Otherwise focus on Tasks.</div></div>', unsafe_allow_html=True)

    if not st.session_state.rfp_text.strip():
        ui_notice("Not ready yet", "Analyze an RFP in Intake first.", tone="warn")
    else:
        # Draft generator
        kws = st.session_state.keywords or []
        colA, colB = st.columns([1, 1])
        with colA:
            if st.button("Generate / refresh draft sections", use_container_width=True):
                st.session_state.drafts = generate_drafts(
                    sow_snips=st.session_state.sow_snips or [],
                    keywords=kws,
                    rules=st.session_state.rules or {},
                    forms=st.session_state.forms or [],
                    attachments=st.session_state.attachments or [],
                    company=st.session_state.company
                )
                ui_notice("Draft created", "You can edit these before exporting.", tone="good")
        with colB:
            st.caption("Tailoring keywords: " + (", ".join(kws[:10]) if kws else "Not detected"))

        drafts = st.session_state.drafts or {}
        if drafts:
            for title, body in drafts.items():
                with st.expander(title, expanded=False):
                    drafts[title] = st.text_area("", value=body, height=240)
            st.session_state.drafts = drafts
        else:
            ui_notice("Draft not generated", "Click the draft button above.", tone="neutral")

        st.markdown("---")

        # Matrix (kept, but not forcing users to live here)
        matrix_rows = st.session_state.matrix_rows or []
        if not matrix_rows:
            ui_notice("Matrix not available", "Paste Section L/M and re-analyze in Intake.", tone="warn")
        else:
            with st.expander("Compliance matrix (edit)", expanded=False):
                section_options = DEFAULT_SECTIONS.copy()
                for kname in (drafts or {}).keys():
                    if kname not in section_options:
                        section_options.insert(-1, kname)

                # Show fewer at once for phone usability
                for row in matrix_rows[:50]:
                    with st.expander(f"{row['id']} — {row['requirement'][:80]}{'...' if len(row['requirement'])>80 else ''}", expanded=False):
                        st.write(row["requirement"])

                        col1, col2, col3 = st.columns([1.2, 1, 1.2])
                        with col1:
                            row["section"] = st.selectbox(
                                "Mapped section",
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

                st.session_state.matrix_rows = matrix_rows


# ============================================================
# TAB 5 — Export
# ============================================================
with tabs[4]:
    st.markdown("### Export")
    st.markdown('<div class="card"><h4>Export only when it’s actually ready</h4><div class="muted">Path.ai uses your tasks + matrix to decide readiness.</div></div>', unsafe_allow_html=True)

    # Refresh computed state for exports
    context = {
        "rfp_text": st.session_state.rfp_text,
        "rfp_diag": st.session_state.rfp_diag,
        "rules": st.session_state.rules,
        "forms": st.session_state.forms,
        "attachments": st.session_state.attachments,
        "amendments": st.session_state.amendments,
        "company": st.session_state.company,
    }
    gated_items = build_items_from_analysis(context)
    actionable = items_actionable(gated_items, conf_min=0.45)
    task_kpi = compute_task_kpis(st.session_state.task_checks, actionable)
    matrix_kpi = compute_matrix_kpis(st.session_state.matrix_rows)
    gate_status, gate_reasons = run_gate(st.session_state.company, st.session_state.rules, st.session_state.matrix_rows)

    # Export policy:
    # - require draft exists
    # - require no FAIL in matrix for "READY"; allow export at "AT RISK" but show warning
    drafts = st.session_state.drafts or {}
    if not st.session_state.rfp_text.strip():
        ui_notice("Not ready", "Analyze an RFP first.", tone="warn")
        st.stop()

    if not drafts:
        ui_notice("Draft needed", "Generate drafts in the Draft tab before exporting.", tone="warn")
        st.stop()

    if gate_status == "NOT READY":
        ui_notice("Export locked", "Fix the issues in Tasks and Draft first.", tone="bad")
        for r in gate_reasons[:10]:
            st.write("•", r)
        st.stop()

    if gate_status == "AT RISK":
        ui_notice("Export allowed (at risk)", "You can export, but you still have risks to resolve.", tone="warn")
        for r in gate_reasons[:10]:
            st.write("•", r)
    else:
        ui_notice("Export ready", "You’re clear to export.", tone="good")

    # Export buttons
    col1, col2 = st.columns([1, 1])

    with col1:
        # Word package
        doc_bytes = build_proposal_docx_bytes(
            company=st.session_state.company,
            logo_bytes=st.session_state.logo_bytes,
            rfp_diag=st.session_state.rfp_diag,
            rules=st.session_state.rules,
            forms=st.session_state.forms,
            attachments=st.session_state.attachments,
            amendments=st.session_state.amendments,
            tasks=actionable,
            task_state=st.session_state.task_checks,
            matrix_rows=st.session_state.matrix_rows,
            drafts=drafts,
            gate_status=gate_status,
            gate_reasons=gate_reasons,
        )
        st.download_button(
            "Download Word package (.docx)",
            data=doc_bytes,
            file_name="path_ai_proposal_package.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )

    with col2:
        # Excel export
        xlsx_bytes = build_excel_bytes(actionable, st.session_state.task_checks, st.session_state.matrix_rows)
        st.download_button(
            "Download Excel (tasks + matrix) (.xlsx)",
            data=xlsx_bytes,
            file_name="path_ai_tasks_matrix.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    # AI export (explained + JSON export)
    st.markdown("---")
    with st.expander("AI export (for later)", expanded=False):
        st.caption(
            "This does NOT call AI yet. It packages your run into a clean JSON bundle "
            "so you can later plug in an LLM (OpenAI, Azure, etc.) to generate responses more intelligently."
        )

        ai_bundle = {
            "app": APP_NAME,
            "build": {"version": BUILD_VERSION, "date": BUILD_DATE},
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "company": st.session_state.company.to_dict(),
            "rules": st.session_state.rules,
            "forms": st.session_state.forms,
            "attachments": st.session_state.attachments,
            "amendments": st.session_state.amendments,
            "tasks_actionable": [
                {
                    "id": it.item_id,
                    "bucket": it.bucket,
                    "title": it.title,
                    "detail": it.detail,
                    "confidence": round(it.confidence, 3),
                    "done": bool(st.session_state.task_checks.get(f"task::{it.item_id}", False))
                }
                for it in actionable
            ],
            "matrix": st.session_state.matrix_rows,
            "drafts": drafts,
        }

        st.download_button(
            "Download AI bundle (.json)",
            data=json.dumps(ai_bundle, indent=2),
            file_name="path_ai_bundle.json",
            mime="application/json",
            use_container_width=True
        )