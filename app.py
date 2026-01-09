import io
import json
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional, Any

import streamlit as st
from pypdf import PdfReader
import docx  # python-docx

from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# =========================
# App Config
# =========================
st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")

BUILD_VERSION = "v0.9.0"
BUILD_DATE = "Jan 9, 2026"

# =========================
# UI Styling (makes it look like a website)
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

        /* Section headers spacing */
        .section-head { margin-top: 4px; }

        /* Make checkboxes more compact */
        div[data-testid="stCheckbox"] label p { font-size: 0.92rem; }

        </style>
        """,
        unsafe_allow_html=True
    )

inject_css()

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

    # Heuristic for scanned
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
    (r"\bdue\b|\bdue date\b|\bdeadline\b|\bno later than\b|\boffers?\s+are\s+due\b", "Due Date/Deadline"),
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

def compliance_warnings(rules: Dict[str, List[str]], forms: List[str], amendments: List[str], separate: List[str]) -> List[str]:
    warnings = []
    if not rules:
        warnings.append("No submission rules detected. If you pasted partial text, upload the full text-based solicitation.")
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
        warnings.append("Items may require separate files/submissions (signed forms, spreadsheets, attachments). Review the list below.")
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
        recommended.append("Past performance is blank (app will use capability-based language).")

    if not company.proposal_title.strip():
        recommended.append("Proposal/Contract title is blank (recommended for title page).")
    if not company.solicitation_number.strip():
        recommended.append("Solicitation number is blank (recommended for title page).")
    if not company.agency_customer.strip():
        recommended.append("Agency/Customer is blank (recommended for title page).")

    return critical, recommended

# =========================
# Draft Generator
# =========================
def _signature_block(company: CompanyInfo) -> str:
    signer_name = company.signer_name.strip() or company.poc_name.strip()
    signer_title = company.signer_title.strip()
    signer_company = company.signer_company.strip() or company.legal_name.strip()
    signer_phone = company.signer_phone.strip() or company.poc_phone.strip()
    signer_email = company.signer_email.strip() or company.poc_email.strip()

    lines = ["Respectfully,", "", "__________________________________", "(Signature – wet ink or DocuSign)"]
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

{_signature_block(company)}
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
    att_block = "\n".join([f"- {a}" for a in (attachments or [])[:10]]) if attachments else "- None detected"

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
# Checklist v1
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
# Compliance Matrix v2 (best-effort)
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

    # Volume I – Technical evidence
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

        # include custom sections that exist
        base = {"Cover Letter","Executive Summary","Technical Approach","Management Plan","Past Performance","Compliance Snapshot"}
        for k in (drafts or {}).keys():
            if k not in base:
                items.append(f"Include: {k}")

        if "Page Limit" in rules: items.append("Verify page limit and stay within maximum pages")
        if "Font Requirement" in rules or "Margin Requirement" in rules:
            items.append("Verify font/margin formatting requirements")

        pkg["Volume I – Technical (Detected)"] = unique_keep_order(items)

    # Volume II – Past Performance evidence
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
        pkg["Volume II – Past Performance (Detected)"] = unique_keep_order(items)

    # Volume III – Price/Cost evidence
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
        pkg["Volume III – Price/Cost (Detected)"] = unique_keep_order(items)

    if has_forms:
        pkg["Required Forms (Detected)"] = unique_keep_order([f"Complete/attach: {f}" for f in forms])

    if has_attachments:
        pkg["Attachments / Exhibits (Detected)"] = unique_keep_order(attachments[:20])

    if has_separate:
        pkg["Separate Submission Items (Detected)"] = unique_keep_order(separate[:25])

    instr = []
    if rules.get("Due Date/Deadline"):
        instr.append(f"Deadline (detected): {rules['Due Date/Deadline'][0]}")
    if rules.get("Submission Method"):
        instr.append(f"Method (detected): {rules['Submission Method'][0]}")
    if rules.get("File Format Rules"):
        instr.append("File format rules detected — confirm each required format")
    if instr:
        pkg["Submission Instructions (Detected)"] = unique_keep_order(instr)

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

    reasons_block = []
    reasons_risk = []

    if kpi["fail"] > 0:
        reasons_block.append(f"{kpi['fail']} requirements are marked FAIL in the compliance matrix.")
    if crit:
        reasons_block.append("Critical company info missing: " + "; ".join(crit))

    deadline_detected = bool(rules.get("Due Date/Deadline"))
    if deadline_detected and not deadline_acknowledged:
        reasons_block.append("Deadline detected but not acknowledged. Check the acknowledgement box to proceed.")

    if kpi["unknown"] > 0:
        reasons_risk.append(f"{kpi['unknown']} requirements are still UNKNOWN (not evaluated).")
    if not rules.get("Submission Method"):
        reasons_risk.append("Submission method not detected. Verify email/portal details in Section L.")

    if reasons_block:
        return {"status": "NOT COMPLIANT", "level": "blocked", "blocked_reasons": reasons_block, "risk_reasons": reasons_risk, "kpi": kpi}
    if reasons_risk:
        return {"status": "AT RISK", "level": "risk", "blocked_reasons": [], "risk_reasons": reasons_risk, "kpi": kpi}
    return {"status": "READY", "level": "ready", "blocked_reasons": [], "risk_reasons": [], "kpi": kpi}

# =========================
# Word Export Helpers: TOC + page numbers
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

def add_table_of_contents(doc: docx.Document):
    doc.add_page_break()
    doc.add_heading("Table of Contents", level=1)
    p = doc.add_paragraph()
    add_field(p, r'TOC \o "1-3" \h \z \u')
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
    add_page_numbers(doc)
    add_title_page(doc, company, logo_bytes)
    add_table_of_contents(doc)

    # Diagnostics summary (human readable)
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

    # Gate
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

    # Submission package
    doc.add_heading("Submission Package Checklist (Detected)", level=1)
    if submission_pkg:
        for bucket, items in submission_pkg.items():
            doc.add_paragraph(bucket, style="List Bullet")
            for it in items:
                doc.add_paragraph(f"☐ {it}", style="List Bullet 2")
    else:
        doc.add_paragraph("No submission package items detected yet.")
    doc.add_page_break()

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

    # Checklist
    doc.add_heading("Compliance Checklist v1", level=1)
    for it in checklist_items:
        doc.add_paragraph(f"☐ {it['item']}  ({it['status']})", style="List Bullet")

    # Matrix
    doc.add_heading("Compliance Matrix v2 (Best-Effort)", level=1)
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

    # Evidence sections
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
# Diagnostics UI (Website look)
# =========================
def diagnostics_quality(diag: Dict[str, Any]) -> Tuple[str, str]:
    """
    Returns (label, level): level in ["good","warn","bad"]
    """
    if not diag:
        return ("No diagnostics (text pasted)", "warn")
    if diag.get("file_type") != "pdf":
        return ("Extraction quality: Good", "good")
    pages = diag.get("pages_total") or 0
    pages_text = diag.get("pages_with_text") or 0
    chars = diag.get("chars_extracted") or 0
    scanned = bool(diag.get("likely_scanned"))
    if scanned:
        return ("Extraction quality: Poor (likely scanned)", "bad")
    # Good if many pages have text and enough chars
    if pages > 0 and (pages_text / max(1, pages)) >= 0.6 and chars >= 2000:
        return ("Extraction quality: Excellent", "good")
    return ("Extraction quality: OK (verify Section L/M)", "warn")

def render_diagnostics_card(diag: Dict[str, Any]):
    label, level = diagnostics_quality(diag)
    badge_class = "pill-good" if level == "good" else ("pill-warn" if level == "warn" else "pill-bad")
    scanned = "Yes" if diag.get("likely_scanned") else "No"
    file_type = diag.get("file_type", "—") if diag else "—"

    pages_total = diag.get("pages_total", "—") if diag else "—"
    pages_text = diag.get("pages_with_text", "—") if diag else "—"
    chars = diag.get("chars_extracted", "—") if diag else "—"

    st.markdown(
        f"""
        <div class="card">
          <h4>Diagnostics</h4>
          <div class="muted">This helps you understand if the PDF text was actually readable.</div>
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
        st.warning("This PDF looks scanned/image-based. OCR is Tier-3 priority #5 on your roadmap. For now, paste the text if possible.")

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
if "pkg_checks" not in st.session_state: st.session_state.pkg_checks = {}  # checkbox state for submission package

# =========================
# Sidebar Navigation
# =========================
st.sidebar.title("Path")
st.sidebar.caption(f"{BUILD_VERSION} • {BUILD_DATE}")
page = st.sidebar.radio("Go to", ["RFP Intake", "Company Info", "Proposal Output"])
st.sidebar.caption("Flow: Upload/Paste → Analyze → Matrix → Drafts → Gate → Export")

# =========================
# Page 1: RFP Intake
# =========================
if page == "RFP Intake":
    st.title("1) RFP Intake")

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
                st.success("Analysis saved. Go to Proposal Output.")

    with colB:
        st.info("Tip: If your PDF is scanned, text extraction may be weak until OCR is added (roadmap item #5).")

    st.markdown("### Diagnostics Preview")
    render_diagnostics_card(st.session_state.rfp_diag)

    st.markdown("### Preview (first 1200 characters)")
    st.text_area("RFP Preview", (st.session_state.rfp_text or "")[:1200], height=220)

# =========================
# Page 2: Company Info
# =========================
elif page == "Company Info":
    st.title("2) Company Info")
    st.caption("Fill this out once. It auto-fills drafts, export title page, and signature block.")

    c: CompanyInfo = st.session_state.company

    st.markdown("### Logo (optional)")
    logo = st.file_uploader("Upload company logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
    if logo:
        st.session_state.logo_bytes = logo.read()
        st.success("Logo saved. It will be placed on the title page.")
        st.image(st.session_state.logo_bytes, width=180)

    st.markdown("---")
    st.markdown("### Proposal / Contract Information (Title Page)")
    c.proposal_title = st.text_input("Proposal/Contract Title", value=c.proposal_title, placeholder="e.g., Proposal for IT Support Services")
    c.solicitation_number = st.text_input("Solicitation Number", value=c.solicitation_number, placeholder="e.g., W91XXX-26-R-0001")
    c.agency_customer = st.text_input("Agency/Customer", value=c.agency_customer, placeholder="e.g., Department of X / Agency Y")

    st.markdown("---")
    st.markdown("### Company Information")

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
    st.caption("Leave anything blank and the system will fall back to POC/company fields, or omit lines.")
    s1, s2 = st.columns(2)
    with s1:
        c.signer_name = st.text_input("Signer Name (optional)", value=c.signer_name, placeholder="If blank, uses POC name")
        c.signer_title = st.text_input("Signer Title (optional)", value=c.signer_title)
        c.signer_company = st.text_input("Signer Company (optional)", value=c.signer_company, placeholder="If blank, uses Legal Company Name")
    with s2:
        c.signer_phone = st.text_input("Signer Phone (optional)", value=c.signer_phone, placeholder="If blank, uses POC phone")
        c.signer_email = st.text_input("Signer Email (optional)", value=c.signer_email, placeholder="If blank, uses POC email")

    st.session_state.company = c

    st.markdown("---")
    colA, colB = st.columns(2)
    with colA:
        if st.button("Download Company Info (JSON backup)"):
            backup = json.dumps(c.to_dict(), indent=2)
            st.download_button("Click to download JSON", data=backup, file_name="company_profile.json", mime="application/json")

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
          <div class="kpi-title">Compliance KPI (always visible)</div>
          <span class="pill pill-good">Compliance: {compliance_pct}%</span>
          <span class="pill pill-good">Pass: {k["pass"]}</span>
          <span class="pill pill-bad">Fail: {k["fail"]}</span>
          <span class="pill pill-warn">Unknown: {k["unknown"]}</span>
          <span class="pill {gate_class}">Gate: {gate_label}</span>
          <span class="pill pill-warn">Missing critical fields: {missing_crit_ct}</span>
          <div class="muted">Focus: detect Section L/M → matrix → gate → export</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # A) Diagnostics (Website style)
    st.markdown("### A) Diagnostics (Looks like a website now)")
    render_diagnostics_card(diag)

    # B) Missing Info Alerts
    st.markdown("### B) Missing Info Alerts")
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

    # C) Submission Package Checklist (Detected-only) with completion %
    st.markdown("### C) Submission Package Checklist (Detected-Only)")
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

    if not submission_pkg:
        st.info("No submission package items detected yet. Upload/paste more Section L/M and click Analyze.")
    else:
        # completion metrics
        total_items = 0
        checked_items = 0

        for bucket, items in submission_pkg.items():
            if not items:
                continue

            with st.expander(bucket, expanded=("Submission Instructions" in bucket)):
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
              <div class="muted">This is just your checklist progress (not compliance).</div>
              <div class="divider"></div>
              <b>{pct}%</b> complete ({checked_items}/{total_items})
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("---")

    # D) Compliance Matrix
    st.markdown("### D) Compliance Matrix v2")
    st.caption("Map each requirement → proposal section and set Pass/Fail/Unknown. Fail blocks Export after Gate runs.")

    if not matrix_rows:
        st.warning("No requirements extracted yet. Try uploading/pasting Section L/M and re-run Analyze.")
    else:
        section_options = DEFAULT_SECTIONS.copy()
        for kname in (drafts or {}).keys():
            if kname not in section_options:
                section_options.insert(-1, kname)

        for row in matrix_rows[:50]:
            with st.expander(f"{row['id']} — {row['requirement'][:90]}{'...' if len(row['requirement'])>90 else ''}", expanded=False):
                st.write("**Requirement:**", row["requirement"])

                col1, col2, col3 = st.columns([1.2, 1, 1.2])
                with col1:
                    row["section"] = st.selectbox(
                        "Mapped Section",
                        options=section_options,
                        index=section_options.index(row.get("section") or "Technical Approach") if (row.get("section") in section_options) else section_options.index("Technical Approach"),
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
                        st.success(f"Added section: {new_title}")

        st.session_state.matrix_rows = matrix_rows

    st.markdown("---")

    # E) Gate (Pre-submit lock)
    st.markdown("### E) Validation Lock (Pre-Submit Gate)")
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
            st.error(f"Status: {vr['status']}")
            for r in vr["blocked_reasons"]:
                st.write("•", r)
            if vr["risk_reasons"]:
                st.warning("Additional risks:")
                for r in vr["risk_reasons"]:
                    st.write("•", r)
        elif vr["level"] == "risk":
            st.warning(f"Status: {vr['status']}")
            for r in vr["risk_reasons"]:
                st.write("•", r)
        else:
            st.success(f"Status: {vr['status']}")

    st.markdown("---")

    # F) Submission Rules / Evidence
    st.markdown("### F) Submission Rules Found (starter)")
    if rules:
        for label, lines in rules.items():
            with st.expander(label, expanded=False):
                for ln in lines:
                    st.write("•", ln)
    else:
        st.write("No obvious submission rules detected yet. Upload/paste more of Section L/M.")

    st.markdown("---")

    st.markdown("### G) Forms, Attachments, Amendments (starter)")
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
        else:
            st.write("No amendments detected.")

    st.markdown("**Attachment / Appendix / Exhibit lines**")
    if attachments:
        for a in attachments[:25]:
            st.write("•", a)
    else:
        st.write("No obvious attachment references detected.")

    st.markdown("---")

    # H) Warnings + Checklist
    st.markdown("### H) Compliance Warnings (starter)")
    warns = compliance_warnings(rules, forms, amendments, separate)
    for w in warns:
        st.warning(w)

    if separate:
        st.markdown("**Separate submission indicators**")
        for ln in separate[:25]:
            st.write("•", ln)

    st.markdown("---")

    st.markdown("### I) Compliance Checklist v1")
    checklist_items = build_checklist_items(rules, forms, attachments, amendments, separate, required_certs)
    for idx, it in enumerate(checklist_items):
        key = f"chk_{idx}_{it['source']}"
        if key not in st.session_state.checklist_done:
            st.session_state.checklist_done[key] = False
        label = f"{it['item']}  —  [{it['status']}]  ({it['source']})"
        st.session_state.checklist_done[key] = st.checkbox(label, value=st.session_state.checklist_done[key], key=key)

    st.markdown("---")

    # J) Draft generator
    st.markdown("### J) Draft Proposal Sections (template-based)")
    kws = st.session_state.keywords or []
    if kws:
        st.caption("Tailoring keywords (auto-extracted): " + ", ".join(kws[:10]))
    else:
        st.caption("Tailoring keywords: (none detected yet)")

    if st.button("Generate Draft Sections", use_container_width=True):
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

    # K) Export (LOCKED by Gate)
    st.markdown("### K) Export (Professional Word Proposal Package)")
    export_blocked = False
    block_reason = ""

    if vr and vr.get("level") == "blocked":
        export_blocked = True
        block_reason = "Export is disabled because the Pre-Submission Gate is NOT COMPLIANT."
    elif not drafts:
        export_blocked = True
        block_reason = "Export is disabled until you generate draft sections."

    if export_blocked:
        st.error(block_reason)
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
            drafts=drafts,
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

    st.markdown("---")
    st.markdown("### L) RFP Preview (first 1500 characters)")
    st.text_area("RFP Preview", st.session_state.rfp_text[:1500], height=220)