import io
import json
import re
import base64
import textwrap
import os
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Tuple, Optional, Any

import streamlit as st

from pypdf import PdfReader
import docx  # python-docx
import requests

from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# ============================================================
# Path.ai — Federal Proposal Prep (Rigid Futuristic v2)
# Relevance-only UI • Readiness Console • Export gating
# ============================================================

APP_NAME = "Path.ai"
BUILD_VERSION = "v1.1.0"
BUILD_DATE = "Jan 10, 2026"

st.set_page_config(page_title=f"{APP_NAME} – Proposal Prep", layout="wide")


key = os.getenv("OPENAI_API_KEY", "")
st.sidebar.write("ENV TEST:", {
    "has_openai_api_key": bool(key),
    "key_prefix": key[:3] if key else None,
    "key_length": len(key) if key else 0
})

# ============================================================
# HTML helper (prevents Streamlit Markdown code-block rendering)
# ============================================================
def html(block: str):
    st.markdown(textwrap.dedent(block), unsafe_allow_html=True)


# ============================================================
# Styling (Rigid Futuristic)
# ============================================================
def inject_css():
    html("""
    <style>
    :root{
      --bg: rgba(255,255,255,0.92);
      --bd: rgba(49,51,63,0.14);
      --tx: rgba(49,51,63,0.92);
      --mut: rgba(49,51,63,0.66);
      --good: rgba(34,197,94,0.18);
      --warn: rgba(234,179,8,0.20);
      --bad:  rgba(239,68,68,0.18);
      --neu:  rgba(92,124,250,0.14);
      --ink: rgba(20, 22, 30, 0.9);
    }

    .block-container { padding-top: 0.75rem; padding-bottom: 2.2rem; max-width: 1180px; }
    header[data-testid="stHeader"] { background: rgba(255,255,255,0.90); backdrop-filter: blur(8px); }

    /* Top System Banner */
    .sysbar{
      display:flex; align-items:center; justify-content:space-between;
      border: 1px solid var(--bd);
      border-radius: 14px;
      padding: 12px 14px;
      background: linear-gradient(135deg, rgba(92,124,250,0.10), rgba(20,22,30,0.04));
      margin-bottom: 12px;
      gap: 12px;
    }
    .sys-left{display:flex; gap:12px; align-items:flex-start; min-width: 0;}
    .sys-dot{
      width: 10px; height: 10px; border-radius: 999px;
      background: radial-gradient(circle at 30% 30%, #22c55e, #5c7cfa);
      margin-top: 6px;
      flex: 0 0 auto;
    }
    .sys-title{
      font-weight: 900;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      font-size: 0.84rem;
      color: rgba(20,22,30,0.88);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 64vw;
    }
    .sys-quote{
      font-weight: 900;
      letter-spacing: 0.02em;
      font-size: 1.05rem;
      color: rgba(20,22,30,0.92);
      margin-top: 2px;
    }
    .sys-sub{
      font-size: 0.90rem;
      color: var(--mut);
      margin-top: 2px;
    }

    /* Console Card */
    .console{
      border: 1px solid var(--bd);
      border-radius: 16px;
      padding: 14px 14px 12px 14px;
      background: var(--bg);
      margin-bottom: 12px;
    }
    .console h4{
      margin: 0;
      font-size: 0.92rem;
      font-weight: 900;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: rgba(20,22,30,0.86);
    }
    .console-sub{
      margin-top: 4px;
      color: var(--mut);
      font-size: 0.90rem;
    }
    .divider{ height: 1px; background: rgba(49,51,63,0.10); margin: 10px 0; }

    /* Bars */
    .barrow{ display:flex; align-items:center; justify-content:space-between; gap: 10px; margin: 10px 0 6px 0; }
    .barlabel{
      font-weight: 900;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      font-size: 0.78rem;
      color: rgba(20,22,30,0.86);
      white-space: nowrap;
    }
    .barmeta{
      font-size: 0.84rem;
      color: var(--mut);
      white-space: nowrap;
    }
    .barwrap{
      position: relative;
      height: 12px;
      border-radius: 999px;
      border: 1px solid rgba(49,51,63,0.18);
      background: rgba(20,22,30,0.04);
      overflow: hidden;
    }
    .barfill{
      height: 100%;
      border-radius: 999px;
    }

    /* Path Walker */
    .walker{
      position:absolute;
      top: -14px; /* floats above bar */
      width: 24px;
      height: 24px;
      transform: translateX(-50%);
      display:flex;
      align-items:center;
      justify-content:center;
      pointer-events: none;
    }
    .walker svg{ width: 22px; height: 22px; }
    .walker, .walker svg{
      max-width: 24px !important;
      max-height: 24px !important;
    }

    /* Status chips */
    .chip{
      display:inline-block;
      border: 1px solid rgba(49,51,63,0.18);
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 0.82rem;
      font-weight: 900;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin-right: 8px;
      margin-top: 6px;
      color: rgba(20,22,30,0.86);
      background: rgba(255,255,255,0.9);
    }
    .chip-good{ background: var(--good); }
    .chip-warn{ background: var(--warn); }
    .chip-bad{  background: var(--bad);  }
    .chip-neu{  background: var(--neu);  }

    /* Notices */
    .notice{
      border-radius: 14px;
      padding: 11px 12px;
      border: 1px solid var(--bd);
      background: var(--bg);
      margin: 10px 0 12px 0;
    }
    .notice-title{ font-weight: 900; letter-spacing:0.04em; text-transform:uppercase; margin: 0 0 4px 0; font-size: 0.80rem; color: rgba(20,22,30,0.86); }
    .notice-body{ margin: 0; font-size: 0.93rem; color: rgba(20,22,30,0.80); }

    .tone-good { background: var(--good); }
    .tone-warn { background: var(--warn); }
    .tone-bad  { background: var(--bad); }
    .tone-neutral { background: var(--neu); }

    /* Buttons */
    .stButton>button {
      border-radius: 12px !important;
      padding: 0.68rem 0.95rem !important;
      font-weight: 900 !important;
      letter-spacing: 0.02em !important;
    }

    /* Expanders */
    div[data-testid="stExpander"] details summary p { font-size: 0.92rem; font-weight: 900; letter-spacing:0.02em; }

    /* Task cards */
    .taskcard{
      border: 1px solid rgba(49,51,63,0.14);
      border-radius: 14px;
      padding: 12px 12px 10px 12px;
      background: rgba(255,255,255,0.94);
      margin-bottom: 10px;
    }
    .tasktitle{
      font-weight: 900;
      color: rgba(20,22,30,0.90);
      font-size: 0.95rem;
      margin: 0;
    }
    .taskmeta{
      margin-top: 4px;
      color: var(--mut);
      font-size: 0.86rem;
    }
    .taskimpact{
      margin-top: 6px;
      font-size: 0.82rem;
      font-weight: 900;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: rgba(20,22,30,0.78);
    }

    /* Mobile fit */
    @media (max-width: 700px){
      .block-container { padding-left: 0.7rem; padding-right: 0.7rem; }
      .sysbar{ flex-direction: column; align-items: stretch; }
      .sys-title{ max-width: 100%; }
    }
    </style>
    """)


def ui_notice(title: str, body: str, tone: str = "neutral"):
    tone_class = {
        "neutral": "tone-neutral",
        "good": "tone-good",
        "warn": "tone-warn",
        "bad": "tone-bad",
    }.get(tone, "tone-neutral")

    html(f"""
    <div class="notice {tone_class}">
      <div class="notice-title">{title}</div>
      <p class="notice-body">{body}</p>
    </div>
    """)


inject_css()

# ============================================================
# Data model
# ============================================================
GATING_LABELS = ["ACTIONABLE", "INFORMATIONAL", "IRRELEVANT", "AUTO_RESOLVED"]

DEFAULT_SECTIONS = [
    "Cover Letter",
    "Executive Summary",
    "Technical Approach",
    "Management Plan",
    "Past Performance",
    "Compliance Snapshot"
]


@dataclass
class ProposalItem:
    id: str
    kind: str
    text: str
    source: str
    bucket: str
    gating_label: str
    confidence: float
    status: str = "Unknown"  # for requirement items only
    notes: str = ""
    mapped_section: str = ""
    display_title: str = ""  # cleaned, user-facing
    display_detail: str = ""  # concise detail (optional)
    priority: str = "NORMAL"  # CRITICAL/HIGH/NORMAL/OPTIONAL
    impact: str = "SCORE"  # COMPLIANCE/SCORE/READINESS


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


def clamp_pct(x: float) -> int:
    return int(max(0, min(100, round(x))))


def pct_color(p: int) -> Tuple[str, str]:
    if p < 50:
        return "#ef4444", "chip-bad"
    if p < 70:
        return "#f59e0b", "chip-warn"
    if p < 80:
        return "#eab308", "chip-warn"
    return "#22c55e", "chip-good"


def grade_from_pct(p: int) -> str:
    if p >= 90: return "A"
    if p >= 80: return "B"
    if p >= 70: return "C"
    if p >= 60: return "D"
    return "F"


def safe_no_insert(text: str) -> bool:
    t = (text or "").lower()
    banned = ["insert ", "tbd", "[", "]", "lorem ipsum", "fill in", "placeholder"]
    return not any(b in t for b in banned)


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
# Detection heuristics (minimal, relevance-first)
# ============================================================
FORM_PATTERNS = [
    (r"\bSF[-\s]?1449\b", "SF 1449 (Commercial Items)"),
    (r"\bSF[-\s]?33\b", "SF 33 (Solicitation/Offer and Award)"),
    (r"\bSF[-\s]?30\b", "SF 30 (Amendment/Modification)"),
    (r"\bSF[-\s]?18\b", "SF 18 (RFQ)"),
    (r"\bDD[-\s]?1155\b", "DD 1155 (Order for Supplies or Services)"),
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

ATTACHMENT_KEYWORDS = [
    "attachment", "appendix", "exhibit", "annex", "enclosure", "addendum",
    "amendment", "modification", "pricing", "price schedule", "rate sheet",
    "spreadsheet", "xlsx", "excel",
]


def find_forms(text: str) -> List[str]:
    found = []
    for pat, label in FORM_PATTERNS:
        if re.search(pat, text or "", re.IGNORECASE):
            found.append(label)
    return unique_keep_order(found)


def detect_submission_rules(text: str) -> Dict[str, List[str]]:
    lines = scan_lines(text)
    grouped: Dict[str, List[str]] = {}
    for line in lines:
        for pat, label in SUBMISSION_RULE_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                grouped.setdefault(label, []).append(line)
    for k in list(grouped.keys()):
        grouped[k] = unique_keep_order(grouped[k])[:10]
    return grouped


def find_attachment_lines(text: str) -> List[str]:
    lines = scan_lines(text)
    hits = []
    for line in lines:
        low = line.lower()
        if any(k in low for k in ATTACHMENT_KEYWORDS):
            if len(line) <= 260:
                hits.append(line)
    return unique_keep_order(hits)


def detect_amendment_lines(text: str) -> List[str]:
    lines = scan_lines(text)
    hits = [l for l in lines if re.search(AMENDMENT_PATTERN, l, re.IGNORECASE)]
    return unique_keep_order(hits)[:20]


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
    certifications: List[str] = field(default_factory=list)
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
        if d.get("certifications") is None:
            d["certifications"] = []
        return d


CRITICAL_FIELDS = ["legal_name", "uei", "poc_name", "poc_email", "proposal_title", "solicitation_number", "agency_customer"]
RECOMMENDED_FIELDS = ["address", "poc_phone", "capabilities", "differentiators"]


def company_completeness(company: CompanyInfo) -> int:
    c = company
    crit_total = len(CRITICAL_FIELDS)
    rec_total = len(RECOMMENDED_FIELDS)

    crit_done = sum(1 for f in CRITICAL_FIELDS if getattr(c, f, "").strip())
    rec_done = sum(1 for f in RECOMMENDED_FIELDS if getattr(c, f, "").strip())

    pct = (crit_done / max(1, crit_total)) * 80 + (rec_done / max(1, rec_total)) * 20
    return clamp_pct(pct)


def missing_critical(company: CompanyInfo) -> List[str]:
    miss = []
    for f in CRITICAL_FIELDS:
        if not getattr(company, f, "").strip():
            miss.append(f)
    return miss


# ============================================================
# AI (OpenAI) — minimal, reliable
# ============================================================
def get_openai_key() -> Optional[str]:
    try:
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass
    import os
    return os.environ.get("OPENAI_API_KEY")


def extract_json_object(s: str) -> Optional[dict]:
    if not s:
        return None
    s = s.strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        candidate = s[start: end + 1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None


def openai_response_json(system: str, user: str, model: str, timeout: int = 30, max_output_tokens: int = 900, temperature: float = 0.1) -> Optional[dict]:
    api_key = get_openai_key()
    if not api_key:
        return None

    url = "https://api.openai.com/v1/responses"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if r.status_code >= 300:
            try:
                st.sidebar.error(f"OpenAI error {r.status_code}")
            except Exception:
                pass
            return None

        data = r.json()
        text_parts = []
        for item in data.get("output", []) or []:
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text" and c.get("text"):
                    text_parts.append(c["text"])

        raw = "\n".join(text_parts).strip()
        return extract_json_object(raw)
    except Exception:
        return None


def heuristic_gate_item(text: str, kind: str) -> Tuple[str, float, str]:
    low = (text or "").lower()

    bucket = "Other"
    if kind == "rule":
        bucket = "Submission"
    elif kind == "form":
        bucket = "Forms"
    elif kind == "attachment":
        bucket = "Attachments"
    elif kind == "amendment":
        bucket = "Amendments"
    elif kind == "requirement":
        bucket = "Compliance"
    elif kind == "field_missing":
        bucket = "Company"

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

    if len(text) < 18:
        return "IRRELEVANT", 0.70, bucket

    if actionable_hits >= 4:
        return "ACTIONABLE", min(1.0, round(actionable_hits / 10, 2)), bucket

    if kind in ["form", "attachment", "amendment", "field_missing", "requirement", "rule"]:
        return "ACTIONABLE", 0.66, bucket

    return "INFORMATIONAL", 0.60, bucket


def ai_gate_item(text: str, kind: str, context_hint: str = "") -> Tuple[str, float, str]:
    h_label, h_conf, h_bucket = heuristic_gate_item(text, kind)

    if not st.session_state.get("ai_enabled", False):
        return h_label, h_conf, h_bucket

    prompt = f"""
Classify the item for proposal fix workflow.

Return ONLY JSON:
{{
  "gating_label": "ACTIONABLE|INFORMATIONAL|IRRELEVANT|AUTO_RESOLVED",
  "confidence": 0.0,
  "bucket": "Submission|Forms|Attachments|Amendments|Compliance|Company|Other"
}}

kind: {kind}
context: {context_hint}
text: {text}
""".strip()

    j = openai_response_json(
        system="Return only JSON.",
        user=prompt,
        model=st.session_state.get("ai_model", "gpt-4.1-mini"),
        max_output_tokens=220,
        temperature=0.1
    )
    if not j:
        return h_label, h_conf, h_bucket

    gl = (j.get("gating_label") or "").strip().upper()
    try:
        cf = float(j.get("confidence", h_conf))
    except Exception:
        cf = h_conf
    bk = (j.get("bucket") or h_bucket).strip()

    if gl not in GATING_LABELS:
        return h_label, h_conf, h_bucket
    cf = max(0.0, min(1.0, cf))
    return gl, cf, (bk or h_bucket)


def ai_write_drafts(company: CompanyInfo, rfp_text: str) -> Optional[Dict[str, str]]:
    if not st.session_state.get("ai_enabled", False):
        return None

    company_block = json.dumps(company.to_dict(), indent=2)[:2600]
    rfp_excerpt = (rfp_text or "")[:6500]

    prompt = f"""
Write a complete, submission-ready federal proposal draft with these sections:
- Cover Letter
- Executive Summary
- Technical Approach
- Management Plan
- Past Performance

Rules:
- Use ONLY company facts provided. Never invent certifications, clients, contract history, years of experience, staff counts, clearances, or locations.
- Use the RFP/SOW language to mirror requirements and evaluation intent.
- Fill gaps using context and safe general statements (delivery method, quality, risk control) without fabricating facts.
- Do NOT use placeholders like "insert", "TBD", brackets, or "fill in".
- Keep tone controlled, precise, evaluator-focused.

Return ONLY JSON with keys exactly:
"Cover Letter", "Executive Summary", "Technical Approach", "Management Plan", "Past Performance"

Company JSON:
{company_block}

RFP excerpt:
{rfp_excerpt}
""".strip()

    j = openai_response_json(
        system="Return only JSON.",
        user=prompt,
        model=st.session_state.get("ai_model", "gpt-4.1-mini"),
        max_output_tokens=1400,
        temperature=0.25
    )
    if not j or not isinstance(j, dict):
        return None

    keys = ["Cover Letter", "Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]
    if not all(k in j for k in keys):
        return None

    out = {k: str(j[k]).strip() for k in keys}
    for k, v in out.items():
        if not v or not safe_no_insert(v):
            return None
    return out


# ============================================================
# Relevance-only task cleaning
# ============================================================
def task_rewrite_basic(kind: str, raw: str) -> Tuple[str, str]:
    t = normalize_line(raw)
    low = t.lower()

    t = re.sub(
        r"^(Page Limit|Font Requirement|Margin Requirement|Due Date/Deadline|Submission Method|File Format Rules|Sections L/M referenced)\s*:\s*",
        "", t, flags=re.IGNORECASE
    )

    if kind == "rule":
        if "page" in low and "limit" in low:
            return ("Confirm page limit compliance", t[:220])
        if "font" in low or "point" in low:
            return ("Apply required font and size", t[:220])
        if "margin" in low or "inch" in low:
            return ("Apply required margins", t[:220])
        if "deadline" in low or "due" in low or "no later than" in low:
            return ("Verify submission deadline", t[:220])
        if any(k in low for k in ["portal", "upload", "email", "submit", "sam.gov", "ebuy", "piee", "fedconnect"]):
            return ("Confirm submission method", t[:220])
        if any(k in low for k in ["pdf", "docx", "xlsx", "zip", "encrypt", "password", "file format"]):
            return ("Confirm file format requirements", t[:220])
        if "section l" in low or "section m" in low:
            return ("Review Sections L/M requirements", t[:220])
        return ("Confirm submission rule", t[:220])

    if kind == "form":
        return ("Include required government forms", t[:220])

    if kind == "attachment":
        return ("Confirm required attachments", t[:220])

    if kind == "amendment":
        return ("Review amendments and incorporate changes", t[:220])

    if kind == "field_missing":
        return ("Complete required company profile fields", t[:220])

    if kind == "requirement":
        if "shall" in low or "must" in low or "will" in low:
            short = t
            short = re.sub(r"\s{2,}", " ", short)
            if len(short) > 220:
                short = short[:217] + "..."
            return ("Address a mandatory requirement", short)
        return ("Address a requirement", t[:220])

    return ("Action required", t[:220])


def classify_priority_impact(kind: str, raw: str) -> Tuple[str, str]:
    low = (raw or "").lower()

    if kind in ["requirement", "rule", "form", "amendment"]:
        impact = "COMPLIANCE"
    elif kind == "field_missing":
        impact = "READINESS"
    else:
        impact = "SCORE"

    priority = "NORMAL"
    if any(k in low for k in ["due date", "deadline", "no later than", "offers are due", "proposal is due"]):
        priority = "CRITICAL"
    if kind == "field_missing":
        priority = "HIGH"
    if kind in ["form", "amendment"]:
        priority = "HIGH"
    if kind == "requirement" and any(k in low for k in ["shall", "must"]):
        priority = "HIGH"
    if kind == "rule" and any(k in low for k in ["page limit", "font", "margins", "file format"]):
        priority = "HIGH"

    return priority, impact


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
        title, detail = task_rewrite_basic(kind, text)
        pr, imp = classify_priority_impact(kind, text)

        items.append(
            ProposalItem(
                id=f"I{seq:04d}",
                kind=kind,
                text=text,
                source=source,
                bucket=bucket,
                gating_label=gl,
                confidence=cf,
                display_title=title,
                display_detail=detail,
                priority=pr,
                impact=imp
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

    miss = missing_critical(company)
    for f in miss:
        add("field_missing", f"Missing required company field: {f.replace('_',' ').title()}", "Company Profile", "Missing company field")

    out = []
    seen = set()
    for it in items:
        k = (it.kind + "|" + it.text.strip().lower())
        if k not in seen:
            seen.add(k)
            out.append(it)

    for it in out:
        if it.kind == "requirement":
            it.mapped_section = auto_map_section(it.text)
            it.status = "Unknown"

    return out


def get_actionable_items(items: List[ProposalItem]) -> List[ProposalItem]:
    return [i for i in (items or []) if i.gating_label == "ACTIONABLE"]


# ============================================================
# Scoring Engine (Locked rules)
# - Export gate: Overall >= 60 AND Compliance >= 80
# - Win ability does NOT affect overall progress
# - No hard blocks; missing reduces score
# ============================================================
def compliance_score(items: List[ProposalItem]) -> int:
    reqs = [i for i in (items or []) if i.kind == "requirement" and i.gating_label == "ACTIONABLE"]
    if not reqs:
        return 0
    total = 0.0
    for r in reqs:
        if r.status == "Pass":
            total += 1.0
        elif r.status == "Unknown":
            total += 0.5
        else:
            total += 0.0
    pct = (total / max(1, len(reqs))) * 100
    return clamp_pct(pct)


def tasks_score(items: List[ProposalItem], checks: Dict[str, bool]) -> int:
    act = get_actionable_items(items)
    if not act:
        return 0
    done = sum(1 for i in act if checks.get(i.id, False))
    return clamp_pct((done / max(1, len(act))) * 100)


def drafts_score(drafts: Dict[str, str]) -> int:
    if not drafts:
        return 0
    keys = ["Cover Letter", "Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]
    present = 0
    for k in keys:
        v = (drafts or {}).get(k, "").strip()
        if v and safe_no_insert(v) and len(v) >= 200:
            present += 1
    return clamp_pct((present / max(1, len(keys))) * 100)


def overall_progress_score(items: List[ProposalItem], checks: Dict[str, bool], company: CompanyInfo, drafts: Dict[str, str]) -> int:
    t = tasks_score(items, checks)
    c = company_completeness(company)
    d = drafts_score(drafts)
    pct = (t * 0.60) + (c * 0.20) + (d * 0.20)
    return clamp_pct(pct)


def win_ability_score(company: CompanyInfo, drafts: Dict[str, str], rfp_text: str) -> int:
    score = 0
    if company.differentiators.strip(): score += 25
    if company.capabilities.strip(): score += 20
    if company.past_performance.strip(): score += 15
    if drafts_score(drafts) >= 60: score += 20
    if rfp_text and company.capabilities:
        a = set(re.findall(r"[a-z]{4,}", rfp_text.lower()[:4000]))
        b = set(re.findall(r"[a-z]{4,}", company.capabilities.lower()))
        overlap = len(a.intersection(b))
        if overlap >= 30: score += 20
        elif overlap >= 15: score += 12
        elif overlap >= 8: score += 6
    return clamp_pct(score)


def ready_state(overall: int, compliance: int) -> str:
    if compliance >= 80 and overall >= 60:
        return "READY"
    if compliance >= 70 and overall >= 50:
        return "ALMOST"
    return "NOT READY"


def export_allowed(overall: int, compliance: int) -> bool:
    return (overall >= 60) and (compliance >= 80)


# ============================================================
# DOCX export helpers
# ============================================================
def add_field(paragraph, field_code: str):
    run = paragraph.add_run()
    r = run._r
    fldChar1 = OxmlElement('w:fldChar'); fldChar1.set(qn('w:fldCharType'), 'begin')
    instrText = OxmlElement('w:instrText'); instrText.set(qn('xml:space'), 'preserve'); instrText.text = field_code
    fldChar2 = OxmlElement('w:fldChar'); fldChar2.set(qn('w:fldCharType'), 'separate')
    fldChar3 = OxmlElement('w:fldChar'); fldChar3.set(qn('w:fldCharType'), 'end')
    r.append(fldChar1); r.append(instrText); r.append(fldChar2); r.append(fldChar3)


def add_page_numbers(doc: docx.Document):
    section = doc.sections[0]
    footer = section.footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("Page "); add_field(p, "PAGE"); p.add_run(" of "); add_field(p, "NUMPAGES")


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

    p1 = doc.add_paragraph(); p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p1.add_run(company.legal_name); r1.bold = True

    p2 = doc.add_paragraph(); p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run(company.proposal_title); r2.bold = True

    doc.add_paragraph("")
    p3 = doc.add_paragraph(); p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p3.add_run(f"Solicitation: {company.solicitation_number}")

    p4 = doc.add_paragraph(); p4.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p4.add_run(f"Agency/Customer: {company.agency_customer}")

    doc.add_paragraph("")
    p5 = doc.add_paragraph(); p5.alignment = WD_ALIGN_PARAGRAPH.CENTER
    line = f"UEI: {company.uei}"
    if company.cage.strip():
        line += f"    CAGE: {company.cage}"
    p5.add_run(line)

    doc.add_page_break()


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
    doc.add_page_break()

    doc.add_heading("Actionable Task Checklist", level=1)
    act = get_actionable_items(items)
    if act:
        for it in act:
            checked = task_checks.get(it.id, False)
            mark = "☑" if checked else "☐"
            doc.add_paragraph(f"{mark} [{it.bucket}] {it.display_title}: {it.display_detail}", style="List Bullet")
    doc.add_page_break()

    doc.add_heading("Draft Proposal Sections", level=1)
    for k in ["Cover Letter", "Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]:
        if k in drafts and drafts[k].strip():
            doc.add_heading(k, level=2)
            add_paragraph_lines(doc, drafts[k])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_matrix_csv(items: List[ProposalItem]) -> str:
    rows = ["id,kind,bucket,gating_label,confidence,status,mapped_section,display_title,display_detail,text,notes"]
    for it in items:
        if it.kind != "requirement":
            continue
        row = [
            it.id, it.kind, it.bucket, it.gating_label, str(it.confidence),
            it.status, (it.mapped_section or ""),
            '"' + (it.display_title or "").replace('"', '""') + '"',
            '"' + (it.display_detail or "").replace('"', '""') + '"',
            '"' + (it.text or "").replace('"', '""') + '"',
            '"' + (it.notes or "").replace('"', '""') + '"'
        ]
        rows.append(",".join(row))
    return "\n".join(rows)


# ============================================================
# Persistence
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
        c = CompanyInfo()
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
# Session init
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
ss_init("company", CompanyInfo())
ss_init("logo_bytes", None)
ss_init("items", [])
ss_init("task_checks", {})
ss_init("drafts", {})
ss_init("analysis_done", False)
ss_init("ai_enabled", False)
ss_init("ai_model", "gpt-4.1-mini")
ss_init("step", 0)


# ============================================================
# System banner + readiness console + path walker bar
# ============================================================
def walker_svg(color: str) -> str:
    return f"""
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="12" cy="5.5" r="2.5" fill="{color}"/>
      <path d="M9.3 22V12.2c0-1.2.7-2.3 1.8-2.8l.2-.1c.9-.4 2-.4 2.9 0l.2.1c1.1.5 1.8 1.6 1.8 2.8V22"
            stroke="{color}" stroke-width="2" stroke-linecap="round"/>
      <path d="M8 14.5h8" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
      <path d="M11.2 22v-5.2" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
      <path d="M12.8 22v-5.2" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
    </svg>
    """


def render_console(items: List[ProposalItem], checks: Dict[str, bool], company: CompanyInfo, drafts: Dict[str, str], rfp_text: str):
    comp = compliance_score(items)
    overall = overall_progress_score(items, checks, company, drafts)
    company_pct = company_completeness(company)
    win = win_ability_score(company, drafts, rfp_text)
    state = ready_state(overall, comp)

    comp_grade = grade_from_pct(comp)
    comp_color, _ = pct_color(comp)
    overall_color, _ = pct_color(overall)
    company_color, _ = pct_color(company_pct)
    win_color, _ = pct_color(win)

    exp = "UNLOCKED" if export_allowed(overall, comp) else "LOCKED"
    exp_chip = "chip-good" if exp == "UNLOCKED" else "chip-bad"

    state_text = {"READY": "READY", "ALMOST": "ALMOST READY", "NOT READY": "NOT READY"}[state]
    state_chip = "chip-good" if state == "READY" else ("chip-warn" if state == "ALMOST" else "chip-bad")

    def bar_html(label: str, pct: int, meta: str, color: str, walker: bool = False) -> str:
        left = max(2, min(98, pct))
        walker_block = ""
        if walker:
            walker_block = f"""
            <div class="walker" style="left:{left}%;">
              {walker_svg(color)}
            </div>
            """
        return textwrap.dedent(f"""
        <div class="barrow">
          <div class="barlabel">{label}</div>
          <div class="barmeta">{meta}</div>
        </div>
        <div class="barwrap">
          <div class="barfill" style="width:{pct}%; background:{color};"></div>
          {textwrap.dedent(walker_block).strip()}
        </div>
        """)

    html(f"""
    <div class="sysbar">
      <div class="sys-left">
        <div class="sys-dot"></div>
        <div>
          <div class="sys-title">PATH STATUS: ACTIVE • {BUILD_VERSION} • {BUILD_DATE}</div>
          <div class="sys-quote">YOU ARE NOW ON THE PATH TO SUCCESS!</div>
          <div class="sys-sub">System-guided. Compliance-first. Submission-ready.</div>
        </div>
      </div>
      <div style="text-align:right;">
        <span class="chip {state_chip}">READY STATE: {state_text}</span>
        <span class="chip {exp_chip}">EXPORT: {exp}</span>
      </div>
    </div>
    """)

    html(f"""
    <div class="console">
      <h4>Readiness Console</h4>
      <div class="console-sub">Only unresolved items that affect readiness are shown.</div>
      <div class="divider"></div>

      {bar_html("Compliance", comp, f"{comp}% • Grade {comp_grade}", comp_color, walker=False)}
      {bar_html("Company Profile", company_pct, f"{company_pct}%", company_color, walker=False)}
      {bar_html("Win Strength", win, f"{win}%", win_color, walker=False)}

      <div class="divider"></div>

      {bar_html("Overall Progress", overall, f"{overall}%", overall_color, walker=True)}
    </div>
    """)

    if not export_allowed(overall, comp):
        reasons = []
        if comp < 80:
            reasons.append(f"Compliance is {comp}% (minimum 80%).")
        if overall < 60:
            reasons.append(f"Overall progress is {overall}% (minimum 60%).")
        if reasons:
            ui_notice("EXPORT LOCKED", " • ".join(reasons), tone="warn")

    return comp, overall, company_pct, win, state


# ============================================================
# Sidebar
# ============================================================
st.sidebar.title(APP_NAME)

with st.sidebar.expander("AI", expanded=False):
    key_present = bool(get_openai_key())
    st.session_state["ai_enabled"] = st.toggle("Enable AI Drafts", value=st.session_state["ai_enabled"], disabled=not key_present)
    st.session_state["ai_model"] = st.selectbox("Model", options=["gpt-4.1-mini", "gpt-4.1"], index=0)
    if not key_present:
        ui_notice("AI OFF", "Set OPENAI_API_KEY in Render Environment to enable drafts.", tone="warn")

with st.sidebar.expander("Project", expanded=False):
    st.download_button(
        "Download Project",
        data=export_project_json(),
        file_name="path_ai_project.json",
        mime="application/json"
    )
    up_proj = st.file_uploader("Load Project", type=["json"], key="proj_uploader")
    if up_proj:
        ok, msg = import_project_json(up_proj.read().decode("utf-8", errors="ignore"))
        ui_notice("PROJECT", msg, tone=("good" if ok else "bad"))

steps = ["Intake", "Company", "Fix", "Draft", "Export"]
chosen = st.sidebar.radio("Navigate", options=list(range(len(steps))), format_func=lambda i: steps[i], index=st.session_state["step"])
st.session_state["step"] = chosen

# Nav buttons (never hard-block navigation; only disable actions inside pages)
col_nav1, col_nav2, col_nav3 = st.columns([1, 1, 6])
with col_nav1:
    if st.button("Back", use_container_width=True, disabled=(st.session_state["step"] == 0)):
        st.session_state["step"] = max(0, st.session_state["step"] - 1)
        st.rerun()
with col_nav2:
    if st.button("Continue", use_container_width=True, disabled=(st.session_state["step"] == len(steps) - 1)):
        st.session_state["step"] = min(len(steps) - 1, st.session_state["step"] + 1)
        st.rerun()
with col_nav3:
    st.caption("Navigate freely. Scores and export unlock as you complete requirements.")

# Render banner + console (always)
_ = render_console(
    items=st.session_state["items"] or [],
    checks=st.session_state["task_checks"] or {},
    company=st.session_state["company"],
    drafts=st.session_state["drafts"] or {},
    rfp_text=st.session_state["rfp_text"] or ""
)


# ============================================================
# Pages
# ============================================================
def page_intake():
    st.subheader("INTAKE")

    left, right = st.columns([1.1, 0.9], gap="large")

    with left:
        uploaded = st.file_uploader("Upload RFP (PDF, DOCX, TXT)", type=["pdf", "docx", "txt"])
        pasted = st.text_area("Or paste solicitation text", value=st.session_state["rfp_text"], height=240)

        if st.button("ANALYZE", use_container_width=True):
            text = ""
            diag = {}

            if uploaded:
                text, diag = read_uploaded_file(uploaded)
                st.session_state["rfp_diag"] = diag

            if pasted.strip():
                text = pasted.strip()

            if not text.strip():
                ui_notice("INPUT REQUIRED", "Upload a readable file or paste text.", tone="bad")
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
                checks.setdefault(it.id, False)
            st.session_state["task_checks"] = checks

            st.session_state["analysis_done"] = True
            ui_notice("STATUS", "Analysis complete.", tone="good")

    with right:
        diag = st.session_state["rfp_diag"] or {}
        if diag:
            scanned = "YES" if diag.get("likely_scanned") else "NO"
            html(f"""
            <div class="console">
              <h4>Input Signal</h4>
              <div class="divider"></div>
              <div class="console-sub"><b>Type</b>: {diag.get('file_type','—')}</div>
              <div class="console-sub"><b>Pages</b>: {diag.get('pages_total','—')} • <b>Pages w/ text</b>: {diag.get('pages_with_text','—')}</div>
              <div class="console-sub"><b>Chars</b>: {diag.get('chars_extracted','—')}</div>
              <div class="console-sub"><b>Scanned</b>: {scanned}</div>
            </div>
            """)
            if diag.get("likely_scanned"):
                ui_notice("SIGNAL WARNING", "Paste solicitation text for maximum accuracy.", tone="warn")
        else:
            ui_notice("STATUS", "No input diagnostics yet.", tone="neutral")


def page_company():
    st.subheader("COMPANY PROFILE")
    c: CompanyInfo = st.session_state["company"]

    col_logo, col_fields = st.columns([0.7, 1.3], gap="large")
    with col_logo:
        logo = st.file_uploader("Logo (optional)", type=["png", "jpg", "jpeg"])
        if logo:
            st.session_state["logo_bytes"] = logo.read()
            ui_notice("STATUS", "Logo saved.", tone="good")
        if st.session_state["logo_bytes"]:
            st.image(st.session_state["logo_bytes"], width=180)

    with col_fields:
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
            c.poc_phone = st.text_input("Point of Contact Phone (optional)", value=c.poc_phone)

        c.capabilities = st.text_area("Capabilities", value=c.capabilities, height=110)
        c.differentiators = st.text_area("Differentiators", value=c.differentiators, height=110)
        c.past_performance = st.text_area("Past Performance (optional)", value=c.past_performance, height=130)

    st.session_state["company"] = c

    miss = missing_critical(c)
    if miss:
        ui_notice("STATUS", "Missing required fields: " + " • ".join([m.replace('_',' ').title() for m in miss]), tone="warn")
    else:
        ui_notice("STATUS", "Required fields captured.", tone="good")

    if st.button("REFRESH FIX LIST", use_container_width=True):
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
            ui_notice("STATUS", "Fix list refreshed.", tone="good")
        else:
            ui_notice("STATUS", "Run Intake → Analyze first.", tone="warn")


def page_fix():
    st.subheader("FIX MODE")

    if not st.session_state["analysis_done"] or not (st.session_state["rfp_text"] or "").strip():
        ui_notice("STATUS", "Run Intake → Analyze to generate a fix list.", tone="warn")
        return

    items = st.session_state["items"] or []
    if not items:
        ui_notice("STATUS", "No items found. Try re-running Analyze.", tone="warn")
        return

    checks = st.session_state["task_checks"] or {}

    actionable = get_actionable_items(items)
    unresolved = [i for i in actionable if not checks.get(i.id, False)]
    show = [i for i in unresolved if i.impact in ["COMPLIANCE", "READINESS", "SCORE"]]

    pr_order = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "OPTIONAL": 3}
    show.sort(key=lambda x: (pr_order.get(x.priority, 9), x.bucket, x.id))

    if not show:
        ui_notice("STATUS", "No fix items remaining.", tone="good")
        return

    priorities = ["CRITICAL", "HIGH", "NORMAL", "OPTIONAL"]
    for pr in priorities:
        grp = [i for i in show if i.priority == pr]
        if not grp:
            continue

        with st.expander(f"{pr} ({len(grp)})", expanded=(pr in ["CRITICAL", "HIGH"])):
            buckets = unique_keep_order([g.bucket for g in grp])
            for b in buckets:
                bucket_items = [g for g in grp if g.bucket == b]
                if not bucket_items:
                    continue

                st.markdown(f"**{b.upper()}**")

                for it in bucket_items:
                    title = it.display_title or "Action Required"
                    detail = it.display_detail or ""
                    impact = it.impact

                    html(f"""
                    <div class="taskcard">
                      <p class="tasktitle">{title}</p>
                      <div class="taskmeta">{detail}</div>
                      <div class="taskimpact">Impact: {impact} • Priority: {it.priority}</div>
                    </div>
                    """)

                    checks[it.id] = st.checkbox("Resolved", value=checks.get(it.id, False), key=f"resolve_{it.id}")

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
                                "Mapped Section",
                                options=DEFAULT_SECTIONS,
                                index=DEFAULT_SECTIONS.index(it.mapped_section) if it.mapped_section in DEFAULT_SECTIONS else 2,
                                key=f"map_{it.id}"
                            )
                        with cols[2]:
                            it.notes = st.text_input("Notes (optional)", value=it.notes, key=f"notes_{it.id}")

                    st.markdown("---")

    st.session_state["task_checks"] = checks


def page_draft():
    st.subheader("DRAFT SYSTEM")

    if not st.session_state["analysis_done"] or not (st.session_state["rfp_text"] or "").strip():
        ui_notice("STATUS", "Run Intake → Analyze first (drafts mirror the SOW/RFP).", tone="warn")

    if not st.session_state["ai_enabled"]:
        ui_notice("STATUS", "Enable AI Drafts in the sidebar to generate proposal sections.", tone="warn")

    c: CompanyInfo = st.session_state["company"]
    miss = missing_critical(c)
    if miss:
        ui_notice("STATUS", "Complete required company fields to improve draft strength.", tone="warn")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("GENERATE DRAFTS", use_container_width=True, disabled=not st.session_state["ai_enabled"]):
            if not (st.session_state["rfp_text"] or "").strip():
                ui_notice("STATUS", "Paste/upload the RFP text first (Intake).", tone="bad")
            else:
                d = ai_write_drafts(company=c, rfp_text=st.session_state["rfp_text"])
                if d:
                    st.session_state["drafts"] = d
                    ui_notice("STATUS", "Drafts generated.", tone="good")
                else:
                    ui_notice("STATUS", "Draft generation failed.", tone="bad")
    with col2:
        if st.button("CLEAR DRAFTS", use_container_width=True):
            st.session_state["drafts"] = {}
            ui_notice("STATUS", "Drafts cleared.", tone="neutral")

    drafts = st.session_state["drafts"] or {}
    if not drafts:
        ui_notice("STATUS", "No drafts available.", tone="neutral")
        return

    for k in ["Cover Letter", "Executive Summary", "Technical Approach", "Management Plan", "Past Performance"]:
        if k in drafts:
            with st.expander(k, expanded=(k == "Executive Summary")):
                drafts[k] = st.text_area(k, value=drafts[k], height=260)

    for k, v in drafts.items():
        if v and not safe_no_insert(v):
            ui_notice("STATUS", f"{k} contains placeholder language. Remove it.", tone="warn")
    st.session_state["drafts"] = drafts


def page_export():
    st.subheader("EXPORT MODULE")

    if not st.session_state["analysis_done"]:
        ui_notice("STATUS", "Run Intake → Analyze first.", tone="warn")

    items = st.session_state["items"] or []
    checks = st.session_state["task_checks"] or {}
    c: CompanyInfo = st.session_state["company"]
    drafts = st.session_state["drafts"] or {}

    comp = compliance_score(items)
    overall = overall_progress_score(items, checks, c, drafts)
    allowed = export_allowed(overall, comp)

    if not drafts:
        ui_notice("STATUS", "Generate drafts before export.", tone="warn")
        return

    if not allowed:
        ui_notice("EXPORT LOCKED", "Raise Compliance to 80%+ and Overall to 60%+ to unlock export.", tone="warn")
        return

    doc_bytes = build_docx_package(
        company=c,
        logo_bytes=st.session_state["logo_bytes"],
        diag=st.session_state["rfp_diag"],
        items=items,
        drafts=drafts,
        rules=st.session_state["rules"],
        task_checks=checks
    )

    st.download_button(
        "DOWNLOAD PROPOSAL PACKAGE (DOCX)",
        data=doc_bytes,
        file_name="PathAI_Proposal_Package.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True
    )

    csv_text = build_matrix_csv(items)
    st.download_button(
        "DOWNLOAD COMPLIANCE MATRIX (CSV)",
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
    page_fix()
elif step == 3:
    page_draft()
else:
    page_export()