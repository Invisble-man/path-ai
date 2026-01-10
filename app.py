import io
import json
import re
import base64
import zipfile
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
# Full build: Guided flow + AI gating + DOCX export
# ============================================================

APP_NAME = "Path.ai"
BUILD_VERSION = "v1.0.0"
BUILD_DATE = "Jan 9, 2026"

# -------------------------
# Streamlit page config
# -------------------------
st.set_page_config(page_title=f"{APP_NAME} – Proposal Prep", layout="wide")


# ============================================================
# Styling (warmer, more product-like)
# ============================================================
def inject_css():
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.0rem; padding-bottom: 2.5rem; max-width: 1200px; }
        header[data-testid="stHeader"] { background: rgba(255,255,255,0.85); backdrop-filter: blur(6px); }

        /* Brand header */
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

        /* Cards */
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

        /* Pills (KPI chips) */
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

        /* Notices */
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

        /* Bigger friendly buttons */
        .stButton>button {
            border-radius: 14px !important;
            padding: 0.70rem 0.95rem !important;
            font-weight: 800 !important;
        }

        /* Expanders slightly tighter */
        div[data-testid="stExpander"] details summary p { font-size: 0.96rem; font-weight: 700; }

        /* Checkbox text */
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
# Data model: Items with gating
# ============================================================
GATING_LABELS = ["ACTIONABLE", "INFORMATIONAL", "IRRELEVANT", "AUTO_RESOLVED"]


@dataclass
class ProposalItem:
    id: str
    kind: str               # rule/form/attachment/amendment/separate/requirement/field_missing
    text: str
    source: str             # e.g., "Submission Rules", "Forms", "RFP", etc.
    bucket: str             # grouping bucket for UI
    gating_label: str       # ACTIONABLE/INFORMATIONAL/IRRELEVANT/AUTO_RESOLVED
    confidence: float       # 0.0–1.0
    status: str = "Unknown" # Pass/Fail/Unknown for requirements; Done/Not Done for tasks; used flexibly
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


def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def score_to_confidence(score: int, max_score: int = 10) -> float:
    if max_score <= 0:
        return 0.0
    v = max(0, min(max_score, score))
    return round(v / max_score, 2)


# ============================================================
# Extraction (PDF/DOCX/TXT)
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
# RFP intelligence (starter heuristics)
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


DATE_PATTERNS = [
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
]
TIME_PATTERNS = [r"\b\d{1,2}:\d{2}\s*(?:am|pm)\b", r"\b\d{1,2}\s*(?:am|pm)\b", r"\b\d{1,2}:\d{2}\b"]
TZ_PATTERNS = [r"\b(?:et|ct|mt|pt|est|edt|cst|cdt|mst|mdt|pst|pdt|utc|zulu)\b"]
DUE_KEYWORDS = ["offer due", "offers are due", "proposal due", "proposal is due", "submission due", "deadline", "no later than", "due date", "closing date", "response due"]


def refine_due_date_rule(text: str, rules: Dict[str, List[str]]) -> Dict[str, List[str]]:
    lines = scan_lines(text, max_lines=14000)
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
            if ("attachment" in low or "appendix" in low or "exhibit" in low or "sf " in low or "sf-" in low or
                "amendment" in low or "pricing" in low or "spreadsheet" in low or "excel" in low):
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


def extract_requirements_best_effort(rfp_text: str, max_reqs: int = 70) -> List[str]:
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
                reqs.append(line)
                if len(reqs) >= max_reqs:
                    return reqs

    return reqs


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
# AI integration (OpenAI via HTTP)
# ============================================================
def get_openai_key() -> Optional[str]:
    # 1) st.secrets
    try:
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass
    # 2) environment
    import os
    return os.environ.get("OPENAI_API_KEY")


def openai_chat(messages: List[Dict[str, str]], model: str = "gpt-4.1-mini", temperature: float = 0.2, max_tokens: int = 450) -> Optional[str]:
    api_key = get_openai_key()
    if not api_key:
        return None

    # Using the Chat Completions style endpoint for maximum compatibility
    # If your key is valid, this works on Render without extra packages.
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=25)
        if r.status_code >= 300:
            return None
        data = r.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    except Exception:
        return None


def ai_gate_item(text: str, kind: str, context_hint: str = "") -> Tuple[str, float, str]:
    """
    Returns: (gating_label, confidence, bucket)
    If no API key, returns heuristic gating.
    """
    # Heuristic fallback first (fast)
    h_label, h_conf, h_bucket = heuristic_gate_item(text, kind)

    if not st.session_state.get("ai_enabled", False):
        return h_label, h_conf, h_bucket

    # AI gating (best effort)
    prompt = f"""
You are a strict proposal compliance assistant. Classify the item into one gating label:
- ACTIONABLE: user must do something to become compliant
- INFORMATIONAL: useful reference but not a task
- IRRELEVANT: not useful
- AUTO_RESOLVED: can be considered complete without user action (e.g., obvious metadata or duplicates)

Also assign:
- confidence: 0.00 to 1.00
- bucket: one of these:
  Submission & Format
  Required Forms
  Attachments/Exhibits
  Amendments
  Separate Submissions
  Compliance Requirements
  Company Profile
  Other

Return ONLY valid JSON: {{ "gating_label": "...", "confidence": 0.0, "bucket": "..." }}.

Item kind: {kind}
Context: {context_hint}
Item text: {text}
""".strip()

    out = openai_chat(
        [
            {"role": "system", "content": "Return only JSON. No extra words."},
            {"role": "user", "content": prompt}
        ],
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
        if not bk:
            bk = h_bucket
        return gl, cf, bk
    except Exception:
        return h_label, h_conf, h_bucket


def ai_write_drafts(company: CompanyInfo, rfp_text: str, keywords: List[str]) -> Optional[Dict[str, str]]:
    """
    Uses AI to draft sections. If AI off or no key, returns None.
    """
    if not st.session_state.get("ai_enabled", False):
        return None

    kw = ", ".join((keywords or [])[:10]) if keywords else "quality, schedule, reporting, risk"
    company_block = json.dumps(company.to_dict(), indent=2)[:2500]
    rfp_excerpt = (rfp_text or "")[:6000]

    prompt = f"""
Write a concise, professional federal proposal draft with these sections:
1) Executive Summary
2) Technical Approach
3) Management Plan
4) Past Performance (if provided; otherwise capability-based)

Rules:
- Do NOT invent certifications or past performance.
- Use the company data as the source of truth.
- Keep each section readable and tight.
- Align language to the RFP excerpt.
- Use tailoring keywords naturally.

Company JSON:
{company_block}

Tailoring keywords:
{kw}

RFP excerpt:
{rfp_excerpt}

Return ONLY JSON with keys:
Executive Summary, Technical Approach, Management Plan, Past Performance
""".strip()

    out = openai_chat(
        [
            {"role": "system", "content": "Return only JSON. No extra words."},
            {"role": "user", "content": prompt}
        ],
        model=st.session_state.get("ai_model", "gpt-4.1-mini"),
        temperature=0.25,
        max_tokens=1200
    )
    if not out:
        return None

    try:
        j = json.loads(out)
        # Basic validation
        if not isinstance(j, dict):
            return None
        for k in ["Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]:
            if k not in j:
                return None
        return {
            "Executive Summary": str(j["Executive Summary"]).strip(),
            "Technical Approach": str(j["Technical Approach"]).strip(),
            "Management Plan": str(j["Management Plan"]).strip(),
            "Past Performance": str(j["Past Performance"]).strip(),
        }
    except Exception:
        return None


# ============================================================
# Heuristic gating rules (baseline)
# ============================================================
def heuristic_gate_item(text: str, kind: str) -> Tuple[str, float, str]:
    low = (text or "").lower()

    # Buckets
    bucket = "Other"
    if kind == "rule":
        bucket = "Submission & Format"
    elif kind == "form":
        bucket = "Required Forms"
    elif kind == "attachment":
        bucket = "Attachments/Exhibits"
    elif kind == "amendment":
        bucket = "Amendments"
    elif kind == "separate":
        bucket = "Separate Submissions"
    elif kind == "requirement":
        bucket = "Compliance Requirements"
    elif kind == "field_missing":
        bucket = "Company Profile"

    # High-value actionable triggers
    actionable_hits = 0
    if any(k in low for k in ["due date", "deadline", "no later than", "offers are due", "proposal is due"]):
        actionable_hits += 4
    if any(k in low for k in ["submit", "submission", "portal", "email", "upload", "fedconnect", "ebuy", "piee", "sam.gov"]):
        actionable_hits += 3
    if any(k in low for k in ["page limit", "not exceed", "font", "margins", "file format", "pdf", "docx", "xlsx", "excel", "zip"]):
        actionable_hits += 3
    if kind in ["form", "attachment", "amendment", "separate", "field_missing"]:
        actionable_hits += 3
    if kind == "requirement" and any(k in low for k in ["shall", "must", "will"]):
        actionable_hits += 2

    # Informational triggers
    info_hits = 0
    if any(k in low for k in ["section l", "section m", "evaluation criteria", "instructions to offerors"]):
        info_hits += 3
    if "for reference" in low or "reference only" in low:
        info_hits += 3

    # Dedupe / low-value / irrelevant
    if len(text) < 20:
        return "IRRELEVANT", 0.70, bucket

    # Auto-resolved patterns (simple)
    if "pages with text" in low or "characters extracted" in low:
        return "AUTO_RESOLVED", 0.80, bucket

    # Decide
    if actionable_hits >= 4:
        return "ACTIONABLE", score_to_confidence(min(10, actionable_hits), 10), bucket
    if info_hits >= 3:
        return "INFORMATIONAL", score_to_confidence(min(10, info_hits), 10), bucket

    # Default by type
    if kind in ["form", "attachment", "amendment", "separate", "field_missing"]:
        return "ACTIONABLE", 0.70, bucket
    if kind == "requirement":
        return "ACTIONABLE", 0.68, bucket
    if kind == "rule":
        return "INFORMATIONAL", 0.60, bucket

    return "IRRELEVANT", 0.60, bucket


# ============================================================
# Build Items (with gating)
# ============================================================
def build_items_from_analysis(
    rfp_text: str,
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    amendments: List[str],
    separate: List[str],
    requirements: List[str],
    company: CompanyInfo
) -> List[ProposalItem]:
    items: List[ProposalItem] = []
    seq = 1

    def add(kind: str, text: str, source: str, context_hint: str = ""):
        nonlocal seq
        gl, cf, bucket = ai_gate_item(text=text, kind=kind, context_hint=context_hint)
        item = ProposalItem(
            id=f"I{seq:04d}",
            kind=kind,
            text=text,
            source=source,
            bucket=bucket,
            gating_label=gl,
            confidence=cf
        )
        items.append(item)
        seq += 1

    # Submission rules
    for label, lines in (rules or {}).items():
        for ln in lines:
            add("rule", f"{label}: {ln}", "Submission Rules", context_hint="Submission compliance rules")

    # Forms
    for f in (forms or []):
        add("form", f, "Forms", context_hint="Required government forms to include/complete")

    # Attachments/exhibits mentions
    for a in (attachments or []):
        add("attachment", a, "Attachments", context_hint="Attachment/exhibit mention that may require inclusion")

    # Amendments
    for a in (amendments or []):
        add("amendment", a, "Amendments", context_hint="Amendment/modification mention to acknowledge or incorporate")

    # Separate submissions
    for s in (separate or []):
        add("separate", s, "Separate Submissions", context_hint="May need separate file (pricing spreadsheet, signed form, etc.)")

    # Requirements
    for req in (requirements or []):
        add("requirement", req, "RFP", context_hint="Compliance requirement (Section L/M best-effort extraction)")

    # Missing critical fields -> top-priority tasks
    critical, _ = missing_info_alerts(company)
    for c in critical:
        add("field_missing", c, "Company Profile", context_hint="Missing critical company field required for submission")

    # De-dup items by text
    out = []
    seen = set()
    for it in items:
        k = (it.kind + "|" + it.text.strip().lower())
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


# ============================================================
# Progress + KPI logic (actionable-only)
# ============================================================
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


def kpi_color(value: str) -> str:
    """
    value: 'good'|'warn'|'bad' -> pill css class
    """
    return {"good": "pill-green", "warn": "pill-yellow", "bad": "pill-red"}.get(value, "pill-blue")


def gate_status_for_flow() -> Tuple[str, str]:
    """
    Returns: (label, level)
    """
    # Intake complete?
    if not st.session_state.rfp_text.strip():
        return ("Needs Intake", "warn")
    if not st.session_state.analysis_done:
        return ("Needs Analysis", "warn")

    # Company critical fields?
    crit, _ = missing_info_alerts(st.session_state.company)
    if crit:
        return ("Needs Company Info", "warn")

    # Compliance progress?
    items = st.session_state.items or []
    checks = st.session_state.task_checks or {}
    total, done, _ = completion_stats(items, checks)
    if total > 0:
        pct = int(round((done / max(1, total)) * 100))
        if pct < 40:
            return ("Compliance In Progress", "warn")
        if pct < 90:
            return ("Almost Ready", "warn")
        return ("Ready to Export", "good")

    return ("Ready to Draft", "good")


# ============================================================
# DOCX Export helpers
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


def add_paragraph_lines(doc: docx.Document, text: str):
    for line in (text or "").splitlines():
        doc.add_paragraph(line)


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


def build_docx_package(
    company: CompanyInfo,
    logo_bytes: Optional[bytes],
    rfp_diag: Dict[str, Any],
    items: List[ProposalItem],
    drafts: Dict[str, str],
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    amendments: List[str],
    separate: List[str],
    task_checks: Dict[str, bool]
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

    # Submission essentials
    doc.add_heading("Submission Essentials", level=1)
    if rules:
        for k, lines in rules.items():
            doc.add_paragraph(k, style="List Bullet")
            for ln in (lines or [])[:6]:
                doc.add_paragraph(ln, style="List Bullet 2")
    else:
        doc.add_paragraph("No submission rules detected.", style="List Bullet")

    if forms:
        doc.add_heading("Forms (Detected)", level=2)
        for f in forms:
            doc.add_paragraph(f, style="List Bullet")

    if attachments:
        doc.add_heading("Attachments/Exhibits (Detected)", level=2)
        for a in attachments[:18]:
            doc.add_paragraph(a, style="List Bullet")

    if amendments:
        doc.add_heading("Amendments/Mods (Detected)", level=2)
        for a in amendments[:18]:
            doc.add_paragraph(a, style="List Bullet")

    if separate:
        doc.add_heading("Separate Submission Indicators (Detected)", level=2)
        for s in separate[:20]:
            doc.add_paragraph(s, style="List Bullet")

    doc.add_page_break()

    # Actionable task checklist
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

    # Company block
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

    # Draft proposal sections
    doc.add_page_break()
    doc.add_heading("Draft Proposal Sections", level=1)

    # Cover letter (generated)
    doc.add_heading("Cover Letter", level=2)
    due = (rules.get("Due Date/Deadline") or ["Not detected"])[0]
    method = (rules.get("Submission Method") or ["Not detected"])[0]
    cover = f"""COVER LETTER

{company.legal_name or "[Company Name]"}
{company.address or "[Address]"}
UEI: {company.uei or "[UEI]"} | CAGE: {company.cage or "[CAGE]"}
POC: {company.poc_name or "[POC]"} | {company.poc_email or "[email]"} | {company.poc_phone or "[phone]"}

Subject: {company.proposal_title or "Proposal Submission"}

Dear Contracting Officer,

{company.legal_name or "[Company Name]"} submits this proposal in response to the solicitation. We understand the requirement and will execute with a low-risk approach aligned to schedule, quality, reporting, and risk management.

Submission details (verify Section L and cover page):
- Deadline: {due}
- Submission Method: {method}

{signature_block(company)}
"""
    add_paragraph_lines(doc, cover)

    # Add AI or rule-based drafts
    if drafts:
        for title in ["Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]:
            if title in drafts:
                doc.add_heading(title, level=2)
                add_paragraph_lines(doc, drafts[title])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ============================================================
# Excel export (CSV) for matrix (simple + compatible)
# ============================================================
def build_matrix_csv(items: List[ProposalItem]) -> str:
    rows = ["id,kind,bucket,gating_label,confidence,status,mapped_section,text,notes"]
    for it in items:
        # Only requirements are matrix-ish
        if it.kind != "requirement":
            continue
        row = [
            it.id,
            it.kind,
            it.bucket,
            it.gating_label,
            str(it.confidence),
            it.status,
            (it.mapped_section or ""),
            '"' + (it.text or "").replace('"', '""') + '"',
            '"' + (it.notes or "").replace('"', '""') + '"'
        ]
        rows.append(",".join(row))
    return "\n".join(rows)


# ============================================================
# Persistence (Save/Load project)
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
        "keywords": st.session_state.keywords,
        "company": c.to_dict(),
        "logo_b64": b64_from_bytes(st.session_state.logo_bytes),
        "items": [asdict(i) for i in (st.session_state.items or [])],
        "task_checks": st.session_state.task_checks,
        "drafts": st.session_state.drafts,
        "analysis_done": st.session_state.analysis_done,
        "ai_enabled": st.session_state.ai_enabled,
        "ai_model": st.session_state.ai_model,
        "step": st.session_state.step,
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
        st.session_state.keywords = payload.get("keywords", []) or []

        company_dict = payload.get("company", {}) or {}
        c = CompanyInfo(certifications=[])
        for k, v in company_dict.items():
            if hasattr(c, k):
                setattr(c, k, v)
        if c.certifications is None:
            c.certifications = []
        st.session_state.company = c

        st.session_state.logo_bytes = bytes_from_b64(payload.get("logo_b64"))

        st.session_state.items = [ProposalItem(**i) for i in (payload.get("items") or [])]
        st.session_state.task_checks = payload.get("task_checks", {}) or {}
        st.session_state.drafts = payload.get("drafts", {}) or {}
        st.session_state.analysis_done = bool(payload.get("analysis_done", False))
        st.session_state.ai_enabled = bool(payload.get("ai_enabled", False))
        st.session_state.ai_model = payload.get("ai_model", "gpt-4.1-mini")
        st.session_state.step = payload.get("step", 0)

        return True, "Project loaded."
    except Exception as e:
        return False, f"Could not load project: {e}"


# ============================================================
# Session state init
# ============================================================
if "rfp_text" not in st.session_state: st.session_state.rfp_text = ""
if "rfp_diag" not in st.session_state: st.session_state.rfp_diag = {}
if "rules" not in st.session_state: st.session_state.rules = {}
if "forms" not in st.session_state: st.session_state.forms = []
if "attachments" not in st.session_state: st.session_state.attachments = []
if "amendments" not in st.session_state: st.session_state.amendments = []
if "separate_submit" not in st.session_state: st.session_state.separate_submit = []
if "keywords" not in st.session_state: st.session_state.keywords = []
if "company" not in st.session_state: st.session_state.company = CompanyInfo(certifications=[])
if "logo_bytes" not in st.session_state: st.session_state.logo_bytes = None
if "items" not in st.session_state: st.session_state.items = []
if "task_checks" not in st.session_state: st.session_state.task_checks = {}
if "drafts" not in st.session_state: st.session_state.drafts = {}
if "analysis_done" not in st.session_state: st.session_state.analysis_done = False
if "ai_enabled" not in st.session_state: st.session_state.ai_enabled = False
if "ai_model" not in st.session_state: st.session_state.ai_model = "gpt-4.1-mini"
if "step" not in st.session_state: st.session_state.step = 0

# ============================================================
# Layout: Brand header + sidebar nav + guided steps
# ============================================================
steps = ["Intake", "Company", "Compliance", "Draft", "Export"]

# Brand bar
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

# Sidebar: AI + Save/Load + step nav
st.sidebar.title(APP_NAME)

# AI controls
with st.sidebar.expander("AI Settings", expanded=False):
    key_present = bool(get_openai_key())
    st.session_state.ai_enabled = st.toggle("Enable AI (gating + drafts)", value=st.session_state.ai_enabled, disabled=not key_present)
    st.session_state.ai_model = st.selectbox("AI model", options=["gpt-4.1-mini", "gpt-4.1"], index=0)
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

# Sidebar step navigation (allowed but guided)
chosen = st.sidebar.radio("Navigate", options=list(range(len(steps))), format_func=lambda i: steps[i], index=st.session_state.step)

# Enforce guided flow by preventing skipping forward when prerequisites not met
def can_enter_step(target_step: int) -> Tuple[bool, str]:
    if target_step <= 0:
        return True, ""

    # Step 1 Company requires analyzed intake
    if target_step >= 1:
        if not st.session_state.rfp_text.strip() or not st.session_state.analysis_done:
            return False, "Complete Intake and run Analyze first."

    # Step 2 Compliance requires company critical fields? (we still allow viewing company first)
    if target_step >= 2:
        crit, _ = missing_info_alerts(st.session_state.company)
        if crit:
            return False, "Complete critical Company fields first."

    # Step 3 Draft: allow if analysis exists + company critical fields
    if target_step >= 3:
        crit, _ = missing_info_alerts(st.session_state.company)
        if crit:
            return False, "Complete critical Company fields first."
        if not st.session_state.items:
            return False, "Run Analyze in Intake first."

    # Step 4 Export: require drafts generated
    if target_step >= 4:
        if not (st.session_state.drafts or {}):
            return False, "Generate drafts first."

    return True, ""


allowed, why = can_enter_step(chosen)
if not allowed:
    ui_notice("Not yet", why, tone="warn")
    chosen = st.session_state.step
else:
    st.session_state.step = chosen

# Top progress bar (actionable completion)
items_now = st.session_state.items or []
total_tasks, done_tasks, remaining_tasks = completion_stats(items_now, st.session_state.task_checks or {})
pct = int(round((done_tasks / max(1, total_tasks)) * 100)) if total_tasks else 0
st.progress(pct / 100.0)

# KPI chips row
gate_label, gate_level = gate_status_for_flow()
gate_css = kpi_color("good" if gate_level == "good" else "warn")

crit, rec = missing_info_alerts(st.session_state.company)
crit_ct = len(crit)

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
      <span class="pill pill-red">Missing critical fields: {crit_ct}</span>
    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# Step navigation buttons (Next/Back) + main page rendering
# ============================================================
col_nav1, col_nav2, col_nav3 = st.columns([1, 1, 6])
with col_nav1:
    if st.button("⬅ Back", use_container_width=True, disabled=(st.session_state.step == 0)):
        st.session_state.step = max(0, st.session_state.step - 1)
        st.rerun()
with col_nav2:
    # Next is disabled if can't enter next step
    nxt = min(len(steps) - 1, st.session_state.step + 1)
    ok_next, why_next = can_enter_step(nxt)
    if st.button("Next ➜", use_container_width=True, disabled=not ok_next):
        st.session_state.step = nxt
        st.rerun()
with col_nav3:
    if not ok_next and st.session_state.step < len(steps) - 1:
        st.caption(f"To continue: {why_next}")


# ============================================================
# Step 0: Intake
# ============================================================
def page_intake():
    st.subheader("Intake")

    left, right = st.columns([1.1, 0.9], gap="large")

    with left:
        st.markdown("### Upload or paste the solicitation")
        uploaded = st.file_uploader("Upload RFP (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"])
        pasted = st.text_area("Or paste text", value=st.session_state.rfp_text, height=260)

        st.markdown("")

        if st.button("Analyze", use_container_width=True):
            text = ""
            diag = {}

            if uploaded:
                text, diag = read_uploaded_file(uploaded)
                st.session_state.rfp_diag = diag

            if pasted.strip():
                text = pasted.strip()

            if not text.strip():
                ui_notice("Missing input", "Upload a readable file or paste text to continue.", tone="bad")
                return

            st.session_state.rfp_text = text

            # Run extraction heuristics
            rules = detect_submission_rules(text)
            rules = refine_due_date_rule(text, rules)

            forms = find_forms(text)
            attachments = find_attachment_lines(text)
            amendments = detect_amendment_lines(text)
            separate = detect_separate_submit_lines(text)

            snips = extract_sow_snippets(text)
            keywords = derive_tailor_keywords(snips)

            # Requirements
            reqs = extract_requirements_best_effort(text)

            st.session_state.rules = rules
            st.session_state.forms = forms
            st.session_state.attachments = attachments
            st.session_state.amendments = amendments
            st.session_state.separate_submit = separate
            st.session_state.keywords = keywords

            # Build items with gating
            st.session_state.items = build_items_from_analysis(
                rfp_text=text,
                rules=rules,
                forms=forms,
                attachments=attachments,
                amendments=amendments,
                separate=separate,
                requirements=reqs,
                company=st.session_state.company
            )

            # Initialize task checks only for actionable
            checks = st.session_state.task_checks or {}
            for it in get_actionable_items(st.session_state.items):
                if it.id not in checks:
                    checks[it.id] = False
            st.session_state.task_checks = checks

            # Pre-map requirement sections + status default
            for it in st.session_state.items:
                if it.kind == "requirement":
                    it.mapped_section = auto_map_section(it.text)
                    it.status = "Unknown"

            st.session_state.analysis_done = True
            ui_notice("Analysis complete", "Next: fill Company info.", tone="good")

    with right:
        st.markdown("### Diagnostics")
        diag = st.session_state.rfp_diag or {}
        if not st.session_state.analysis_done:
            ui_notice("Tip", "If the PDF is scanned, paste the text version for best results.", tone="neutral")

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

        if st.session_state.rfp_text:
            with st.expander("Preview (first 1200 chars)", expanded=False):
                st.text_area("RFP Preview", st.session_state.rfp_text[:1200], height=220)


# ============================================================
# Step 1: Company
# ============================================================
def page_company():
    st.subheader("Company")

    c: CompanyInfo = st.session_state.company

    st.markdown("### Logo (optional)")
    logo = st.file_uploader("Upload logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
    if logo:
        st.session_state.logo_bytes = logo.read()
        ui_notice("Saved", "Logo will appear on the title page export.", tone="good")
        st.image(st.session_state.logo_bytes, width=180)

    st.markdown("### Proposal details")
    colA, colB, colC = st.columns(3)
    with colA:
        c.proposal_title = st.text_input("Proposal/Contract Title", value=c.proposal_title)
    with colB:
        c.solicitation_number = st.text_input("Solicitation Number", value=c.solicitation_number)
    with colC:
        c.agency_customer = st.text_input("Agency/Customer", value=c.agency_customer)

    st.markdown("### Company information")
    col1, col2 = st.columns(2)
    with col1:
        c.legal_name = st.text_input("Legal Company Name", value=c.legal_name)
        c.uei = st.text_input("UEI", value=c.uei)
        c.cage = st.text_input("CAGE (optional)", value=c.cage)
        c.naics = st.text_input("Primary NAICS (optional)", value=c.naics)
        c.psc = st.text_input("PSC (optional)", value=c.psc)
    with col2:
        c.address = st.text_area("Business Address", value=c.address, height=120)
        c.poc_name = st.text_input("Point of Contact Name", value=c.poc_name)
        c.poc_email = st.text_input("Point of Contact Email", value=c.poc_email)
        c.poc_phone = st.text_input("Point of Contact Phone", value=c.poc_phone)
        c.website = st.text_input("Website (optional)", value=c.website)

    st.markdown("### Certifications / set-asides")
    options = ["SDVOSB", "VOSB", "8(a)", "WOSB/EDWOSB", "HUBZone", "SBA Small Business", "ISO 9001", "None"]
    c.certifications = st.multiselect("Select all that apply", options=options, default=c.certifications or [])

    st.markdown("### Capabilities")
    c.capabilities = st.text_area("Capabilities (short bullets or paragraph)", value=c.capabilities, height=120)
    c.differentiators = st.text_area("Differentiators (why you)", value=c.differentiators, height=110)

    st.markdown("### Past performance (optional)")
    c.past_performance = st.text_area("Paste past performance notes", value=c.past_performance, height=140)

    st.markdown("### Signature block")
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
        ui_notice("Missing critical fields", "Complete these before moving forward: " + " • ".join(crit), tone="warn")
    else:
        ui_notice("Looks good", "Critical fields are complete.", tone="good")

    if rec:
        with st.expander("Optional improvements", expanded=False):
            for r in rec:
                st.write("•", r)

    # If company changed, rebuild items so missing field tasks stay accurate
    if st.button("Refresh tasks with updated company info", use_container_width=True):
        if st.session_state.rfp_text.strip() and st.session_state.analysis_done:
            st.session_state.items = build_items_from_analysis(
                rfp_text=st.session_state.rfp_text,
                rules=st.session_state.rules,
                forms=st.session_state.forms,
                attachments=st.session_state.attachments,
                amendments=st.session_state.amendments,
                separate=st.session_state.separate_submit,
                requirements=[it.text for it in (st.session_state.items or []) if it.kind == "requirement"],
                company=st.session_state.company
            )
            checks = st.session_state.task_checks or {}
            for it in get_actionable_items(st.session_state.items):
                if it.id not in checks:
                    checks[it.id] = False
            st.session_state.task_checks = checks
            ui_notice("Updated", "Tasks refreshed.", tone="good")


# ============================================================
# Step 2: Compliance (tasks + reference drawer)
# ============================================================
def page_compliance():
    st.subheader("Compliance")

    items = st.session_state.items or []
    if not items:
        ui_notice("Nothing to review yet", "Go back to Intake and run Analyze.", tone="warn")
        return

    checks = st.session_state.task_checks or {}

    # Smart grouping buckets (actionable only)
    buckets_order = [
        "Submission & Format",
        "Required Forms",
        "Attachments/Exhibits",
        "Amendments",
        "Separate Submissions",
        "Company Profile",
        "Compliance Requirements",
        "Other",
    ]
    actionable = get_actionable_items(items)
    info = get_informational_items(items)

    # Show actionable tasks only (checkboxes)
    st.markdown("### What to fix (tasks)")
    if not actionable:
        ui_notice("No tasks found", "No actionable items detected from current text.", tone="neutral")
    else:
        for bucket in buckets_order:
            bucket_items = [i for i in actionable if i.bucket == bucket]
            if not bucket_items:
                continue

            with st.expander(bucket, expanded=(bucket in ["Submission & Format", "Company Profile"])):
                for it in bucket_items:
                    if it.id not in checks:
                        checks[it.id] = False
                    label = it.text
                    checks[it.id] = st.checkbox(label, value=checks[it.id], key=f"task_{it.id}")

                    # Requirements get status + notes (still only if actionable)
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

    st.session_state.task_checks = checks

    # Reference drawer (informational only)
    st.markdown("---")
    st.markdown("### Reference (collapsed)")
    with st.expander("Open Reference", expanded=False):
        if not info:
            st.write("No informational items.")
        else:
            q = st.text_input("Search reference", value="", placeholder="type to filter (e.g., Section L, evaluation, portal)")
            filt = (q or "").strip().lower()

            show = info
            if filt:
                show = [i for i in info if filt in i.text.lower() or filt in i.source.lower() or filt in i.bucket.lower()]

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


# ============================================================
# Step 3: Draft
# ============================================================
def page_draft():
    st.subheader("Draft")

    if not st.session_state.rfp_text.strip() or not st.session_state.analysis_done:
        ui_notice("Missing analysis", "Go to Intake and run Analyze first.", tone="warn")
        return

    c: CompanyInfo = st.session_state.company
    crit, _ = missing_info_alerts(c)
    if crit:
        ui_notice("Company info needed", "Finish critical company fields in Company step.", tone="warn")
        return

    st.markdown("### Generate drafts")
    st.caption("If AI is enabled, drafts are AI-written. If not, exports still include a clean baseline cover letter and your company info.")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Generate AI Drafts", use_container_width=True, disabled=not st.session_state.ai_enabled):
            d = ai_write_drafts(company=c, rfp_text=st.session_state.rfp_text, keywords=st.session_state.keywords or [])
            if d:
                st.session_state.drafts = d
                ui_notice("Drafts created", "Review and adjust anything you want.", tone="good")
            else:
                ui_notice("AI draft failed", "AI did not return valid output. Check API key or try again.", tone="bad")

    with col2:
        if st.button("Clear drafts", use_container_width=True):
            st.session_state.drafts = {}
            ui_notice("Cleared", "Drafts removed.", tone="neutral")

    drafts = st.session_state.drafts or {}
    if drafts:
        st.markdown("### Review drafts")
        for k in ["Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]:
            if k in drafts:
                with st.expander(k, expanded=(k == "Executive Summary")):
                    drafts[k] = st.text_area(k, value=drafts[k], height=260)
        st.session_state.drafts = drafts
    else:
        ui_notice("No drafts yet", "If you want AI-written drafts, enable AI in the sidebar, then generate drafts.", tone="neutral")


# ============================================================
# Step 4: Export (DOCX + matrix csv)
# ============================================================
def page_export():
    st.subheader("Export")

    if not (st.session_state.drafts or {}):
        ui_notice("Drafts needed", "Go to Draft and generate drafts (AI) before export.", tone="warn")
        return

    c: CompanyInfo = st.session_state.company
    doc_bytes = build_docx_package(
        company=c,
        logo_bytes=st.session_state.logo_bytes,
        rfp_diag=st.session_state.rfp_diag,
        items=st.session_state.items,
        drafts=st.session_state.drafts,
        rules=st.session_state.rules,
        forms=st.session_state.forms,
        attachments=st.session_state.attachments,
        amendments=st.session_state.amendments,
        separate=st.session_state.separate_submit,
        task_checks=st.session_state.task_checks or {}
    )

    st.markdown("### Download files")

    st.download_button(
        "Download Proposal Package (.docx)",
        data=doc_bytes,
        file_name="PathAI_Proposal_Package.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True
    )

    # Matrix CSV (Excel-friendly)
    csv_text = build_matrix_csv(st.session_state.items or [])
    st.download_button(
        "Download Compliance Matrix (.csv)",
        data=csv_text.encode("utf-8"),
        file_name="PathAI_Compliance_Matrix.csv",
        mime="text/csv",
        use_container_width=True
    )

    ui_notice("Tip", "In Word: right-click the Table of Contents → Update Field → Update entire table.", tone="neutral")


# ============================================================
# Render the active step
# ============================================================
if st.session_state.step == 0:
    page_intake()
elif st.session_state.step == 1:
    page_company()
elif st.session_state.step == 2:
    page_compliance()
elif st.session_state.step == 3:
    page_draft()
else:
    page_export()