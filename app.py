import io
import json
import re
import base64
import csv
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional, Any

import streamlit as st
from pypdf import PdfReader
import docx  # python-docx

from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


# =========================
# Version stamp (Feature 1)
# =========================
APP_VERSION = "v0.7.0"
APP_BUILD_DATE = "Jan 9, 2026"

st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")


# =========================
# Helpers
# =========================
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

def scan_lines(text: str, max_lines: int = 10000) -> List[str]:
    lines = []
    for raw in text.splitlines():
        s = normalize_line(raw)
        if s:
            lines.append(s)
        if len(lines) >= max_lines:
            break
    return lines

def scan_raw_lines(text: str, max_lines: int = 20000) -> List[str]:
    """Preserve indentation for multi-line bullet grouping."""
    out = []
    for raw in text.splitlines():
        r = raw.rstrip("\n\r")
        if r.strip():
            out.append(r)
        if len(out) >= max_lines:
            break
    return out

def b64_encode_bytes(b: Optional[bytes]) -> str:
    if not b:
        return ""
    return base64.b64encode(b).decode("utf-8")

def b64_decode_bytes(s: str) -> Optional[bytes]:
    if not s:
        return None
    try:
        return base64.b64decode(s.encode("utf-8"))
    except Exception:
        return None


# =========================
# PDF diagnostics + extraction (Feature 3)
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
    diag["pages_total"] = len(reader.pages)

    parts = []
    for page in reader.pages:
        t = page.extract_text() or ""
        if t.strip():
            diag["pages_with_text"] += 1
        parts.append(t)

    text = "\n".join(parts).strip()
    diag["chars_extracted"] = len(text)

    if diag["pages_total"] > 0:
        ratio = diag["pages_with_text"] / max(1, diag["pages_total"])
        diag["likely_scanned"] = (ratio < 0.3) or (diag["chars_extracted"] < 800)

    return text, diag

def extract_text_from_docx(file_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
    document = docx.Document(io.BytesIO(file_bytes))
    text = "\n".join([p.text for p in document.paragraphs if p.text]).strip()
    diag = {
        "file_type": "docx",
        "pages_total": None,
        "pages_with_text": None,
        "chars_extracted": len(text),
        "likely_scanned": False,
    }
    return text, diag

def read_uploaded_file(uploaded_file) -> Tuple[str, Dict[str, Any]]:
    if not uploaded_file:
        return "", {}
    name = uploaded_file.name.lower()
    data = uploaded_file.read()

    if name.endswith(".pdf"):
        return extract_text_from_pdf(data)
    if name.endswith(".docx"):
        return extract_text_from_docx(data)

    # txt/other
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

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["certifications"] is None:
            d["certifications"] = []
        return d

    @staticmethod
    def from_dict(d: dict) -> "CompanyInfo":
        c = CompanyInfo()
        for k, v in d.items():
            if hasattr(c, k):
                setattr(c, k, v)
        if c.certifications is None:
            c.certifications = []
        return c


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
# Draft generation
# =========================
def _signature_block(company: CompanyInfo) -> str:
    signer_name = company.signer_name.strip() or company.poc_name.strip()
    signer_title = company.signer_title.strip()
    signer_company = company.signer_company.strip() or company.legal_name.strip()
    signer_phone = company.signer_phone.strip() or company.poc_phone.strip()
    signer_email = company.signer_email.strip() or company.poc_email.strip()

    lines = ["Respectfully,", "", "__________________________________", "(Signature – wet ink or DocuSign)"]
    if signer_name:
        lines.append(signer_name)
    if signer_title:
        lines.append(signer_title)
    if signer_company:
        lines.append(signer_company)
    if signer_phone:
        lines.append(signer_phone)
    if signer_email:
        lines.append(signer_email)
    return "\n".join(lines).strip()

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

    cover = f"""COVER LETTER

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

    exec_summary = f"""EXECUTIVE SUMMARY

{company.legal_name or "[Company Name]"} will deliver the required scope with disciplined execution, clear communication, and measurable outcomes.

Tailoring keywords (auto-extracted from SOW text):
{kw}

Capabilities:
{company.capabilities or "[Add capabilities]"}
"""

    tech = f"""TECHNICAL APPROACH

Understanding of Requirement (SOW/PWS excerpts – starter):
{sow_block}

Approach:
- Requirements-to-Deliverables Mapping: map each requirement to a deliverable, owner, schedule, and acceptance criteria.
- Execution Plan: controlled phases with weekly status, quality checks, and documented approvals.
- Quality Control: peer review, checklists, and objective evidence to confirm compliance.

Designed around:
{kw}
"""

    mgmt = """MANAGEMENT PLAN

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

    vol_block = "; ".join(vols) if vols else "Not detected"
    forms_block = "\n".join([f"- {f}" for f in forms]) if forms else "- None detected"
    att_block = "\n".join([f"- {a}" for a in attachments[:10]]) if attachments else "- None detected"

    compliance = f"""COMPLIANCE SNAPSHOT (STARTER)

Submission Rules (best-effort):
- Deadline: {due}
- Method: {method}
- Volumes: {vol_block}

Forms detected:
{forms_block}

Attachment/Appendix/Exhibit mentions:
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
# Feature (5): L/M Targeting v2 + Requirement Extraction v3
# =========================
REQ_TRIGGER = re.compile(r"\b(shall|must|will)\b", re.IGNORECASE)

LM_ANCHORS = [
    ("Section L", re.compile(r"\bsection\s+l\b", re.IGNORECASE)),
    ("Instructions to Offerors", re.compile(r"\binstructions?\s+to\s+offerors?\b", re.IGNORECASE)),
    ("Proposal Preparation", re.compile(r"\bproposal\s+preparation\b|\bproposal\s+preparation\s+instructions\b|\bproposal\s+submission\b", re.IGNORECASE)),
    ("Section M", re.compile(r"\bsection\s+m\b", re.IGNORECASE)),
    ("Evaluation Criteria", re.compile(r"\bevaluation\s+criteria\b|\bevaluation\s+factors?\b", re.IGNORECASE)),
]

def looks_like_bullet(line: str) -> bool:
    s = line.strip()
    return bool(re.match(r"^(\d+[\.\)]|[a-zA-Z][\.\)]|\([a-zA-Z0-9]+\)|[-•*])\s+", s))

def indent_level(line: str) -> int:
    return len(line) - len(line.lstrip(" "))

def build_target_windows(raw_lines: List[str]) -> Tuple[List[Tuple[int, int, str]], List[str]]:
    """
    Returns:
      windows: list of (start, end, label)
      found_labels: list of labels found
    """
    idxs = []
    labels_found = []

    for i, line in enumerate(raw_lines):
        for label, pat in LM_ANCHORS:
            if pat.search(line):
                idxs.append((i, label))
                labels_found.append(label)

    labels_found = unique_keep_order(labels_found)

    windows = []
    for i, label in idxs[:12]:
        start = max(0, i - 120)
        end = min(len(raw_lines), i + 520)
        windows.append((start, end, label))

    # If nothing found, fall back to whole doc
    if not windows:
        windows = [(0, len(raw_lines), "Whole Document (fallback)")]

    # Merge overlapping windows
    windows.sort(key=lambda x: x[0])
    merged = []
    for w in windows:
        if not merged:
            merged.append(list(w))
        else:
            prev = merged[-1]
            if w[0] <= prev[1]:
                prev[1] = max(prev[1], w[1])
                # keep most informative label if prev is fallback
                if prev[2].startswith("Whole") and not w[2].startswith("Whole"):
                    prev[2] = w[2]
            else:
                merged.append(list(w))
    return [(a, b, c) for a, b, c in merged], labels_found

def extract_requirements_targeted_v3(rfp_text: str, max_reqs: int = 90) -> Tuple[List[Dict[str, str]], str]:
    raw = scan_raw_lines(rfp_text, max_lines=20000)
    if not raw:
        return [], "No text"

    windows, labels_found = build_target_windows(raw)
    source_note = ", ".join(labels_found) if labels_found else "Whole Document (fallback)"

    def score_block(txt: str) -> int:
        score = 0
        low = txt.lower()
        if REQ_TRIGGER.search(txt):
            score += 4
        if "offeror" in low or "proposal" in low or "submit" in low:
            score += 2
        if any(k in low for k in ["volume", "format", "page", "font", "margin", "attach", "include", "complete", "sign", "acknowledge"]):
            score += 1
        return score

    blocks: List[Tuple[int, str]] = []

    # Build blocks inside each target window
    for start, end, _label in windows:
        i = start
        while i < end:
            line = raw[i]
            if looks_like_bullet(line):
                base_indent = indent_level(line)
                block_lines = [normalize_line(line)]
                j = i + 1
                while j < end:
                    nxt = raw[j]
                    # new peer bullet ends the block
                    if looks_like_bullet(nxt) and indent_level(nxt) <= base_indent:
                        break
                    # indented / sub-bullet continues
                    if indent_level(nxt) > base_indent or nxt.strip().startswith(("(", "-", "•", "*")):
                        block_lines.append(normalize_line(nxt))
                        j += 1
                        continue
                    # long wrapped lines continue
                    if len(normalize_line(nxt)) > 70 and indent_level(nxt) >= base_indent:
                        block_lines.append(normalize_line(nxt))
                        j += 1
                        continue
                    break
                block_text = " ".join(block_lines).strip()
                blocks.append((i, block_text))
                i = j
            else:
                # Also capture strong single lines in target zones
                s = normalize_line(line)
                low = s.lower()
                if len(s) >= 45 and (REQ_TRIGGER.search(s) or ("offeror" in low and "shall" in low) or ("proposal" in low and "submit" in low)):
                    blocks.append((i, s))
                i += 1

    # Filter + dedupe + sort
    seen = set()
    scored = []
    for idx, txt in blocks:
        t = txt.strip()
        if len(t) < 35:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)

        low = key
        keep = REQ_TRIGGER.search(t) or ("offeror" in low or "proposal" in low or "submit" in low)
        if not keep:
            continue

        scored.append((score_block(t), idx, t))

    scored.sort(key=lambda x: (-x[0], x[1]))

    reqs = []
    rid = 1
    for _, _, t in scored[:max_reqs]:
        reqs.append({"id": f"R{rid:03d}", "requirement": t, "source": f"Targeted: {source_note}"})
        rid += 1

    return reqs, source_note


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
    t = req_text.lower()
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
    if "compliance" in t or "matrix" in t or "section l" in t or "section m" in t or "evaluation" in t:
        return "Compliance Snapshot"
    return "Technical Approach"


# =========================
# Feature (8): Per-requirement response generator
# =========================
def generate_requirement_response(req_text: str, company: CompanyInfo, keywords: List[str]) -> str:
    kw = ", ".join(keywords[:10]) if keywords else "quality, schedule, reporting, risk"
    caps = company.capabilities.strip() or "[Add capabilities]"
    diffs = company.differentiators.strip() or "[Add differentiators]"

    return f"""REQUIREMENT RESPONSE (DRAFT)

Requirement:
{req_text}

Approach:
- {company.legal_name or "[Company Name]"} will address this requirement using a structured plan aligned to: {kw}.
- We will confirm acceptance criteria, produce objective evidence, and maintain traceability to Section L/M.

Deliverables / Evidence:
- [List deliverables tied to this requirement]
- [List evidence artifacts: reports, logs, checklists, screenshots, sign-offs, etc.]

Execution & Controls:
- Quality: peer review + QC checklist before submission
- Reporting: weekly status, risks/issues log, action tracker
- Risk: identify early, mitigate, communicate options

Why Us:
Capabilities:
{caps}

Differentiators:
{diffs}
"""


# =========================
# Feature (7): Matrix CSV export
# =========================
def matrix_to_csv_bytes(matrix_rows: List[Dict[str, str]]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Req ID", "Requirement", "Mapped Section", "Status", "Notes", "Source"])
    for r in matrix_rows:
        writer.writerow([
            r.get("id", ""),
            r.get("requirement", ""),
            r.get("section", ""),
            r.get("status", "Unknown"),
            r.get("notes", ""),
            r.get("source", ""),
        ])
    return output.getvalue().encode("utf-8")


# =========================
# Word Export v2 (Feature 9): Title page separate + header/footer + page nums after title page
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

def set_header_footer_for_section(section, header_text: str):
    # Header
    header = section.header
    hp = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    hp.text = header_text
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Footer with page numbering
    footer = section.footer
    fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.add_run("Page ")
    add_field(fp, "PAGE")
    fp.add_run(" of ")
    add_field(fp, "NUMPAGES")

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
    p1.add_run(company_name).bold = True

    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p2.add_run(title).bold = True

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

    doc.add_paragraph("")
    p6 = doc.add_paragraph()
    p6.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p6.add_run("Submitted By: ").bold = True
    doc.add_paragraph(f"{company.address or ''}")
    doc.add_paragraph("")

def add_paragraph_lines(doc: docx.Document, text: str):
    for line in text.splitlines():
        doc.add_paragraph(line)

def build_proposal_docx_bytes(
    company: CompanyInfo,
    logo_bytes: Optional[bytes],
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    amendments: List[str],
    separate: List[str],
    required_certs: List[str],
    warnings: List[str],
    checklist_items: List[Dict[str, str]],
    matrix_rows: List[Dict[str, str]],
    drafts: Dict[str, str],
    lm_source_note: str,
) -> bytes:
    doc = docx.Document()

    # Section 0: Title page ONLY (no page numbering)
    add_title_page(doc, company, logo_bytes)

    # Section 1: rest of document, new page, header/footer + page numbering
    doc.add_section(WD_SECTION.NEW_PAGE)
    header_text = f"{company.legal_name or 'Company'} | {company.solicitation_number or 'Solicitation'} | {company.proposal_title or 'Proposal'}"
    set_header_footer_for_section(doc.sections[1], header_text)

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

    # Checklist
    doc.add_heading("Submission Checklist (Compliance Checklist v1)", level=1)
    for it in checklist_items:
        doc.add_paragraph(f"☐ {it['item']}  ({it['status']})", style="List Bullet")

    # Matrix
    doc.add_heading("Compliance Matrix (Targeted v2 / Grouped v3)", level=1)
    doc.add_paragraph(f"Extraction focus: {lm_source_note}", style="List Bullet")

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
        doc.add_paragraph("No requirements extracted yet.", style="List Bullet")

    # Detected evidence sections
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
    for w in warnings:
        doc.add_paragraph(w, style="List Bullet")

    # Drafts
    doc.add_page_break()
    doc.add_heading("Draft Proposal Sections", level=1)
    for title, body in drafts.items():
        doc.add_heading(title, level=2)
        add_paragraph_lines(doc, body)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# =========================
# Save / Load Project (Feature 2)
# =========================
def serialize_project_state() -> dict:
    company: CompanyInfo = st.session_state.company
    payload = {
        "app_version": APP_VERSION,
        "app_build_date": APP_BUILD_DATE,
        "rfp_text": st.session_state.rfp_text,
        "pdf_diag": st.session_state.get("pdf_diag", {}),
        "lm_source_note": st.session_state.get("lm_source_note", ""),
        "rules": st.session_state.rules,
        "forms": st.session_state.forms,
        "attachments": st.session_state.attachments,
        "amendments": st.session_state.amendments,
        "separate_submit": st.session_state.separate_submit,
        "required_certs": st.session_state.required_certs,
        "sow_snips": st.session_state.sow_snips,
        "keywords": st.session_state.keywords,
        "drafts": st.session_state.drafts,
        "checklist_done": st.session_state.checklist_done,
        "matrix_rows": st.session_state.matrix_rows,
        "company": company.to_dict(),
        "logo_b64": b64_encode_bytes(st.session_state.logo_bytes),
    }
    return payload

def load_project_state(payload: dict):
    st.session_state.rfp_text = payload.get("rfp_text", "") or ""
    st.session_state.pdf_diag = payload.get("pdf_diag", {}) or {}
    st.session_state.lm_source_note = payload.get("lm_source_note", "") or ""
    st.session_state.rules = payload.get("rules", {}) or {}
    st.session_state.forms = payload.get("forms", []) or []
    st.session_state.attachments = payload.get("attachments", []) or []
    st.session_state.amendments = payload.get("amendments", []) or []
    st.session_state.separate_submit = payload.get("separate_submit", []) or []
    st.session_state.required_certs = payload.get("required_certs", []) or []
    st.session_state.sow_snips = payload.get("sow_snips", []) or []
    st.session_state.keywords = payload.get("keywords", []) or []
    st.session_state.drafts = payload.get("drafts", {}) or {}
    st.session_state.checklist_done = payload.get("checklist_done", {}) or {}
    st.session_state.matrix_rows = payload.get("matrix_rows", []) or []

    comp = payload.get("company", {}) or {}
    st.session_state.company = CompanyInfo.from_dict(comp)

    logo_b64 = payload.get("logo_b64", "") or ""
    st.session_state.logo_bytes = b64_decode_bytes(logo_b64)


# =========================
# Session State Init
# =========================
if "rfp_text" not in st.session_state:
    st.session_state.rfp_text = ""
if "pdf_diag" not in st.session_state:
    st.session_state.pdf_diag = {}
if "lm_source_note" not in st.session_state:
    st.session_state.lm_source_note = ""
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
    st.session_state.checklist_done = {}
if "matrix_rows" not in st.session_state:
    st.session_state.matrix_rows = []


# =========================
# Sidebar
# =========================
st.sidebar.title("Path")
st.sidebar.caption(f"{APP_VERSION} • {APP_BUILD_DATE}")

page = st.sidebar.radio("Go to", ["RFP Intake", "Company Info", "Proposal Output"])
st.sidebar.caption("Flow: Upload/Paste → Analyze → Matrix → Drafts → Export")

st.sidebar.markdown("---")
st.sidebar.subheader("Save / Load Project")

save_payload = json.dumps(serialize_project_state(), indent=2)
st.sidebar.download_button(
    "Save Project (.json)",
    data=save_payload,
    file_name="path_project.json",
    mime="application/json",
)

loaded = st.sidebar.file_uploader("Load Project (.json)", type=["json"])
if loaded:
    try:
        payload = json.loads(loaded.read().decode("utf-8"))
        if isinstance(payload, dict):
            load_project_state(payload)
            st.sidebar.success("Project loaded.")
        else:
            st.sidebar.error("That file is not a valid project JSON.")
    except Exception as e:
        st.sidebar.error(f"Could not load: {e}")


# =========================
# Page 1: RFP Intake
# =========================
if page == "RFP Intake":
    st.title("1) RFP Intake")

    uploaded = st.file_uploader("Upload RFP (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"])
    pasted = st.text_area("Or paste RFP / RFI text", value=st.session_state.rfp_text, height=320)

    if st.button("Analyze"):
        text = ""
        diag = {}

        if uploaded:
            text, diag = read_uploaded_file(uploaded)
            st.session_state.pdf_diag = diag or {}
            if not text.strip():
                st.warning("File uploaded, but no text could be extracted. If PDF is scanned, we’ll need OCR later.")

        if pasted.strip():
            text = pasted.strip()
            if not st.session_state.pdf_diag:
                st.session_state.pdf_diag = {"file_type": "pasted_text", "chars_extracted": len(text), "likely_scanned": False}

        if not text.strip():
            st.error("Please upload a readable file OR paste text.")
        else:
            st.session_state.rfp_text = text

            # starter scans
            st.session_state.rules = detect_submission_rules(text)
            st.session_state.forms = find_forms(text)
            st.session_state.attachments = find_attachment_lines(text)
            st.session_state.amendments = detect_amendment_lines(text)
            st.session_state.separate_submit = detect_separate_submit_lines(text)
            st.session_state.sow_snips = extract_sow_snippets(text)
            st.session_state.keywords = derive_tailor_keywords(st.session_state.sow_snips)
            st.session_state.required_certs = detect_required_certifications(text)

            # Feature (5): targeted extraction
            extracted, lm_note = extract_requirements_targeted_v3(text)
            st.session_state.lm_source_note = lm_note

            matrix_rows = []
            for r in extracted:
                matrix_rows.append({
                    "id": r["id"],
                    "requirement": r["requirement"],
                    "section": auto_map_section(r["requirement"]),
                    "status": "Unknown",
                    "notes": "",
                    "source": r.get("source", ""),
                })
            st.session_state.matrix_rows = matrix_rows

            st.success("Analysis saved. Go to Proposal Output.")

    st.markdown("---")
    st.subheader("PDF Intake Diagnostics")
    diag = st.session_state.get("pdf_diag", {}) or {}
    if diag:
        cols = st.columns(4)
        cols[0].metric("File Type", str(diag.get("file_type", "—")))
        cols[1].metric("Pages", str(diag.get("pages_total", "—")))
        cols[2].metric("Pages w/ Text", str(diag.get("pages_with_text", "—")))
        cols[3].metric("Chars Extracted", str(diag.get("chars_extracted", "—")))

        if diag.get("likely_scanned"):
            st.warning("This PDF looks like it may be scanned/image-based. Text extraction will be unreliable until OCR is added.")
        else:
            st.success("This looks like a text-based file (good for extraction).")
    else:
        st.caption("Upload a file and click Analyze to see diagnostics.")

    st.markdown("---")
    st.subheader("Preview (first 1200 characters)")
    st.code((st.session_state.rfp_text or "")[:1200], language="text")


# =========================
# Page 2: Company Info
# =========================
elif page == "Company Info":
    st.title("2) Company Info")
    st.caption("Fill this out once. It auto-fills drafts and export title page, header/footer, and signature block.")

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
    c.capabilities = st.text_area("Capabilities (short paragraph or bullets)", value=c.capabilities, height=120)
    c.differentiators = st.text_area("Differentiators (why you)", value=c.differentiators, height=100)

    st.markdown("### Past Performance (optional)")
    st.caption("If blank, the draft will use capability-based language.")
    c.past_performance = st.text_area("Paste past performance notes", value=c.past_performance, height=140)

    st.markdown("---")
    st.subheader("Signature Block (Cover Letter)")
    st.caption("Leave anything blank and the system will gracefully fall back to POC/company fields, or omit lines.")
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
    lm_source_note = st.session_state.get("lm_source_note", "") or "—"
    kws = st.session_state.keywords or []

    # Feature (6): Compliance score KPI box
    total = len(matrix_rows)
    p = sum(1 for r in matrix_rows if r.get("status") == "Pass")
    f = sum(1 for r in matrix_rows if r.get("status") == "Fail")
    u = sum(1 for r in matrix_rows if r.get("status") == "Unknown" or not r.get("status"))
    score = (p / total * 100.0) if total > 0 else 0.0

    st.subheader("A) Compliance KPI")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compliance %", f"{score:.0f}%")
    c2.metric("Pass", str(p))
    c3.metric("Fail", str(f))
    c4.metric("Unknown", str(u))
    st.caption(f"Requirement extraction focus: {lm_source_note}")

    st.markdown("---")
    st.subheader("B) Missing Info Alerts (fix before submission)")
    crit, rec = missing_info_alerts(c)
    if crit:
        for x in crit:
            st.error(x)
    else:
        st.success("No critical company-info fields missing.")
    for x in rec:
        st.warning(x)
    if required_certs:
        st.info("RFP mentions these certification types (starter detection): " + ", ".join(required_certs))

    st.markdown("---")

    # Feature (7): Matrix Export CSV
    st.subheader("C) Compliance Matrix + CSV Export")
    if matrix_rows:
        csv_bytes = matrix_to_csv_bytes(matrix_rows)
        st.download_button(
            "Download Compliance Matrix (.csv)",
            data=csv_bytes,
            file_name="compliance_matrix.csv",
            mime="text/csv",
        )
    else:
        st.info("No matrix rows yet. Run Analyze first.")

    st.markdown("---")
    st.subheader("D) Compliance Matrix (Targeted v2 / Grouped v3)")
    st.caption("Map each requirement to a proposal section and set Pass/Fail/Unknown. Use Generate Response Draft to build content fast.")

    if not matrix_rows:
        st.warning("No requirements extracted yet. Upload/paste full solicitation (especially Section L/M) and re-run Analyze.")
    else:
        section_options = DEFAULT_SECTIONS.copy()
        drafts = st.session_state.drafts or {}
        for k in drafts.keys():
            if k not in section_options:
                section_options.insert(-1, k)

        for row in matrix_rows[:50]:
            with st.expander(f"{row['id']} — {row['requirement'][:90]}{'...' if len(row['requirement'])>90 else ''}", expanded=False):
                st.write("**Requirement:**", row["requirement"])
                if row.get("source"):
                    st.caption(row["source"])

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

                # Feature (8): Generate Response Draft
                draft_key = row.get("section") if row.get("section") and row.get("section") != "Other / Add New Section" else f"{row['id']} Requirement Response"
                if st.button("Generate Response Draft", key=f"genresp_{row['id']}"):
                    drafts = st.session_state.drafts or {}
                    drafts[draft_key] = generate_requirement_response(row["requirement"], c, kws)
                    st.session_state.drafts = drafts
                    st.success(f"Draft created/updated: {draft_key}")

                # Existing: add missing section if user chose "Other"
                if row["section"] == "Other / Add New Section":
                    new_title_default = f"{row['id']} Requirement Response"
                    new_title = st.text_input("New section title", value=new_title_default, key=f"newtitle_{row['id']}")
                    if st.button("Add missing section to Drafts", key=f"addsection_{row['id']}"):
                        drafts = st.session_state.drafts or {}
                        if new_title not in drafts:
                            drafts[new_title] = f"{new_title}\n\n[Write your response here.]\n\nRequirement:\n{row['requirement']}\n"
                            st.session_state.drafts = drafts
                        row["section"] = new_title
                        st.success(f"Added section: {new_title}")

        st.session_state.matrix_rows = matrix_rows

    st.markdown("---")
    st.subheader("E) Submission Rules Found (starter)")
    if rules:
        for label, lines in rules.items():
            with st.expander(label, expanded=False):
                for ln in lines:
                    st.write("•", ln)
    else:
        st.write("No obvious submission rules detected yet. Upload full solicitation or paste Section L/M.")

    st.markdown("---")
    st.subheader("F) Forms & Attachments Detected (starter)")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Forms (SF/DD) Found**")
        if forms:
            for ff in forms:
                st.write("•", ff)
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
    st.subheader("G) Compliance Warnings (starter)")
    warns = compliance_warnings(rules, forms, amendments, separate)
    for w in warns:
        st.warning(w)
    if separate:
        st.markdown("**Separate submission indicators**")
        for ln in separate[:25]:
            st.write("•", ln)

    st.markdown("---")
    st.subheader("H) Compliance Checklist v1 (check things off)")
    checklist_items = build_checklist_items(rules, forms, attachments, amendments, separate, required_certs)
    for idx, it in enumerate(checklist_items):
        key = f"chk_{idx}_{it['source']}"
        if key not in st.session_state.checklist_done:
            st.session_state.checklist_done[key] = False
        label = f"{it['item']}  —  [{it['status']}]  ({it['source']})"
        st.session_state.checklist_done[key] = st.checkbox(label, value=st.session_state.checklist_done[key], key=key)

    st.markdown("---")
    st.subheader("I) Draft Proposal Sections (template-based)")
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
    st.subheader("J) Export (Professional Word Proposal Package v2)")
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
            matrix_rows=st.session_state.matrix_rows or [],
            drafts=drafts,
            lm_source_note=lm_source_note,
        )
        st.download_button(
            label="Download Proposal Package (.docx)",
            data=doc_bytes,
            file_name="proposal_package.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        st.caption("In Word: right-click the Table of Contents → Update Field → Update entire table.")
    else:
        st.write("Generate draft sections first, then export.")