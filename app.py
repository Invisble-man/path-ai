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

st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")


# =========================
# Build stamp
# =========================
BUILD_VERSION = "v0.9.0"
BUILD_DATE = "Jan 9, 2026"


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

    # Heuristic: if very few pages have text OR output is tiny -> likely scanned
    if diag["pages_total"] > 0:
        ratio = diag["pages_with_text"] / diag["pages_total"]
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

PRICE_HINTS = [
    "price", "pricing", "cost", "rates", "rate", "labor category", "labor categories",
    "excel", "xlsx", "spreadsheet", "price schedule", "cost proposal", "fee"
]

PAST_PERF_HINTS = [
    "past performance", "cpars", "references", "experience", "relevant experience", "prior contracts"
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


def scan_lines(text: str, max_lines: int = 10000) -> List[str]:
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
# Company Info + Signature Fields
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


# =========================
# Save/Load Project (JSON)
# =========================

def serialize_project_state() -> Dict[str, Any]:
    c: CompanyInfo = st.session_state.company
    return {
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
        "matrix_rows": st.session_state.matrix_rows,
        "deadline_ack": st.session_state.deadline_ack,
        "checklist_done": st.session_state.checklist_done,
        "company": c.to_dict(),
        # logo bytes intentionally not stored (can be big); add later if desired
    }


def load_project_state(payload: Dict[str, Any]) -> None:
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
    st.session_state.matrix_rows = payload.get("matrix_rows", []) or []
    st.session_state.deadline_ack = bool(payload.get("deadline_ack", False))
    st.session_state.checklist_done = payload.get("checklist_done", {}) or {}

    company_dict = payload.get("company", {}) or {}
    c = CompanyInfo(certifications=[])
    for k, v in company_dict.items():
        if hasattr(c, k):
            setattr(c, k, v)
    if c.certifications is None:
        c.certifications = []
    st.session_state.company = c


# =========================
# Missing Info Alerts
# =========================

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
# Draft Generator (with signature block)
# =========================

def _signature_block(company: CompanyInfo) -> str:
    signer_name = company.signer_name.strip() or company.poc_name.strip()
    signer_title = company.signer_title.strip()
    signer_company = company.signer_company.strip() or company.legal_name.strip()
    signer_phone = company.signer_phone.strip() or company.poc_phone.strip()
    signer_email = company.signer_email.strip() or company.poc_email.strip()

    lines = []
    lines.append("Respectfully,")
    lines.append("")
    lines.append("__________________________________")
    lines.append("(Signature – wet ink or DocuSign)")

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
# Compliance Matrix v2 (best-effort extraction)
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
    if "compliance" in t or "matrix" in t or "section l" in t or "section m" in t:
        return "Compliance Snapshot"
    return "Technical Approach"


# =========================
# Submission Package Checklist (Detected-only)
# =========================

def _contains_any(text: str, keywords: List[str]) -> bool:
    low = (text or "").lower()
    return any(k in low for k in keywords)


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
    if matrix_rows:
        if any(r.get("section") in ["Technical Approach", "Management Plan", "Executive Summary"] for r in matrix_rows):
            tech_evidence = True

    if tech_evidence:
        items = []
        if drafts.get("Executive Summary"):
            items.append("Include: Executive Summary")
        if drafts.get("Technical Approach"):
            items.append("Include: Technical Approach")
        if drafts.get("Management Plan"):
            items.append("Include: Management Plan")

        if drafts:
            for k in drafts.keys():
                if k not in ["Cover Letter", "Executive Summary", "Technical Approach", "Management Plan", "Past Performance", "Compliance Snapshot"]:
                    items.append(f"Include: {k}")

        if "Page Limit" in rules:
            items.append("Verify page limit and stay within maximum pages")
        if "Font Requirement" in rules or "Margin Requirement" in rules:
            items.append("Verify font/margin formatting requirements")

        pkg["Volume I – Technical (Detected)"] = unique_keep_order(items)

    pp_evidence = False
    if drafts.get("Past Performance"):
        if company.past_performance.strip():
            pp_evidence = True
        if _contains_any(rfp_text, PAST_PERF_HINTS):
            pp_evidence = True
        if any(_contains_any((r.get("requirement") or ""), PAST_PERF_HINTS) for r in (matrix_rows or [])):
            pp_evidence = True

    if pp_evidence:
        items = []
        items.append("Include: Past Performance section")
        if _contains_any(rfp_text, ["cpars"]):
            items.append("If required: attach CPARS or performance evaluations")
        if _contains_any(rfp_text, ["reference", "references"]):
            items.append("If required: include references/contact information")
        pkg["Volume II – Past Performance (Detected)"] = unique_keep_order(items)

    price_evidence = False
    if has_attachments and any(_contains_any(a, PRICE_HINTS) for a in attachments):
        price_evidence = True
    if has_separate and any(_contains_any(s, PRICE_HINTS) for s in separate):
        price_evidence = True
    if _contains_any(rfp_text, PRICE_HINTS):
        if has_attachments or has_separate or ("File Format Rules" in rules):
            price_evidence = True

    if price_evidence:
        items = []
        items.append("Prepare: Price/Cost volume (as instructed)")
        if has_attachments:
            for a in attachments:
                if _contains_any(a, PRICE_HINTS):
                    items.append(f"Attachment mention: {a}")
        if "File Format Rules" in rules:
            items.append("Verify required pricing file format (Excel/PDF) and naming rules")
        pkg["Volume III – Price/Cost (Detected)"] = unique_keep_order(items)

    if has_forms:
        items = []
        for f in forms:
            items.append(f"Complete/attach: {f}")
        pkg["Required Forms (Detected)"] = unique_keep_order(items)

    if has_attachments:
        items = []
        for a in attachments[:20]:
            items.append(a)
        pkg["Attachments / Exhibits (Detected)"] = unique_keep_order(items)

    if has_separate:
        items = []
        for s in separate[:25]:
            items.append(s)
        pkg["Separate Submission Items (Detected)"] = unique_keep_order(items)

    instr = []
    if "Due Date/Deadline" in rules and rules["Due Date/Deadline"]:
        instr.append(f"Deadline (detected): {rules['Due Date/Deadline'][0]}")
    if "Submission Method" in rules and rules["Submission Method"]:
        instr.append(f"Method (detected): {rules['Submission Method'][0]}")
    if "File Format Rules" in rules and rules["File Format Rules"]:
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
    unk_ct = sum(1 for r in (matrix_rows or []) if (r.get("status") == "Unknown" or not r.get("status")))
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
        status = "NOT COMPLIANT"
        level = "blocked"
    elif reasons_risk:
        status = "AT RISK"
        level = "risk"
    else:
        status = "READY"
        level = "ready"

    return {
        "status": status,
        "level": level,
        "blocked_reasons": reasons_block,
        "risk_reasons": reasons_risk,
        "kpi": kpi,
    }


# =========================
# DOCX Export: Title page + TOC + Page numbers
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
    r1 = p1.add_run(company_name)
    r1.bold = True

    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run(title)
    r2.bold = True

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

    doc.add_page_break()


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
    validation_result: Optional[Dict[str, Any]] = None,
    submission_pkg: Optional[Dict[str, List[str]]] = None,
) -> bytes:
    doc = docx.Document()

    add_page_numbers(doc)
    add_title_page(doc, company, logo_bytes)
    add_table_of_contents(doc)

    if validation_result:
        doc.add_heading("Pre-Submission Gate Result", level=1)
        doc.add_paragraph(f"Status: {validation_result.get('status', '—')}")
        if validation_result.get("blocked_reasons"):
            doc.add_paragraph("Blocked Reasons:", style="List Bullet")
            for r in validation_result["blocked_reasons"]:
                doc.add_paragraph(r, style="List Bullet 2")
        if validation_result.get("risk_reasons"):
            doc.add_paragraph("Risk Reasons:", style="List Bullet")
            for r in validation_result["risk_reasons"]:
                doc.add_paragraph(r, style="List Bullet 2")
        doc.add_page_break()

    if submission_pkg:
        doc.add_heading("Submission Package Checklist (Detected)", level=1)
        for bucket, items in submission_pkg.items():
            doc.add_paragraph(bucket, style="List Bullet")
            for it in items:
                doc.add_paragraph(f"☐ {it}", style="List Bullet 2")
        doc.add_page_break()

    certs = ", ".join(company.certifications or []) if company.certifications else "—"

    doc.add_heading("Company Profile", level=1)
    profile = f"""Company: {company.legal_name or "—"}
Address: {company.address or "—"}
UEI: {company.uei or "—"} | CAGE: {company.cage or "—"}
NAICS: {company.naics or "—"} | PSC: {company.psc or "—"}
POC: {company.poc_name or "—"} | {company.poc_email or "—"} | {company.poc_phone or "—"}
Certifications/Set-Asides: {certs}
Website: {company.website or "—"}
"""
    add_paragraph_lines(doc, profile)

    doc.add_heading("Compliance Checklist v1", level=1)
    for it in checklist_items:
        doc.add_paragraph(f"☐ {it['item']}  ({it['status']})", style="List Bullet")

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
        doc.add_paragraph("No requirements extracted yet. Add/paste Section L/M text and re-run analysis.", style="List Bullet")

    doc.add_page_break()
    doc.add_heading("Draft Proposal Sections", level=1)
    if drafts:
        for title, body in drafts.items():
            doc.add_heading(title, level=2)
            add_paragraph_lines(doc, body)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# =========================
# Session State Init
# =========================

if "rfp_text" not in st.session_state:
    st.session_state.rfp_text = ""
if "rfp_diag" not in st.session_state:
    st.session_state.rfp_diag = {}
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
if "deadline_ack" not in st.session_state:
    st.session_state.deadline_ack = False
if "validation_last" not in st.session_state:
    st.session_state.validation_last = None


# =========================
# Sidebar: Navigation + Save/Load + Diagnostics
# =========================

st.sidebar.title("Path")
st.sidebar.caption(f"{BUILD_VERSION} • {BUILD_DATE}")

page = st.sidebar.radio("Go to", ["RFP Intake", "Company Info", "Proposal Output"])
st.sidebar.caption("Flow: Upload/Paste → Analyze → Matrix → Drafts → Export")

st.sidebar.markdown("---")
st.sidebar.subheader("Save / Load Project (JSON)")

# Always-available project download (no double-click workflow)
project_json = json.dumps(serialize_project_state(), indent=2)
st.sidebar.download_button(
    label="Download Project (.json)",
    data=project_json,
    file_name="path_project.json",
    mime="application/json"
)

uploaded_project = st.sidebar.file_uploader("Load Project (.json)", type=["json"])
if uploaded_project:
    try:
        payload = json.loads(uploaded_project.read().decode("utf-8"))
        if isinstance(payload, dict):
            load_project_state(payload)
            st.sidebar.success("Project loaded.")
        else:
            st.sidebar.error("Invalid project file.")
    except Exception as e:
        st.sidebar.error(f"Could not load project: {e}")

st.sidebar.markdown("---")
with st.sidebar.expander("Diagnostics (Quick)", expanded=False):
    diag = st.session_state.get("rfp_diag", {}) or {}
    if diag:
        st.write("File type:", diag.get("file_type"))
        st.write("Pages:", diag.get("pages_total"))
        st.write("Pages w/ text:", diag.get("pages_with_text"))
        st.write("Chars extracted:", diag.get("chars_extracted"))
        st.write("Likely scanned:", diag.get("likely_scanned"))
    else:
        st.write("No diagnostics yet. Upload an RFP and click Analyze.")


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
            st.session_state.rfp_diag = diag
            if not text.strip():
                st.warning("File uploaded, but no text could be extracted. If PDF is scanned, we’ll need OCR later.")
            elif diag.get("likely_scanned"):
                st.warning("This PDF looks like it may be scanned (low extractable text). OCR will be needed for perfect results.")

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

            st.success("Analysis saved. Go to Proposal Output.")

    st.markdown("---")
    st.subheader("Diagnostics (Full)")
    if st.session_state.rfp_diag:
        st.json(st.session_state.rfp_diag)

    st.subheader("Preview (first 1200 characters)")
    st.code((st.session_state.rfp_text or "")[:1200], language="text")


# =========================
# Page 2: Company Info
# =========================

elif page == "Company Info":
    st.title("2) Company Info")
    st.caption("Fill this out once. It auto-fills drafts and the export title page and signature block.")

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
    st.caption("Leave anything blank and the system will fall back to POC/company fields or omit lines.")

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
    st.info("Project Save/Load is now in the sidebar. Use it anytime.")


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

    # A) KPI
    st.subheader("A) Compliance KPI")
    k = compute_matrix_kpis(matrix_rows)
    total = max(1, k["total"])
    compliance_pct = int(round((k["pass"] / total) * 100))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Compliance %", f"{compliance_pct}%")
    m2.metric("Pass", str(k["pass"]))
    m3.metric("Fail", str(k["fail"]))
    m4.metric("Unknown", str(k["unknown"]))
    st.caption("Requirement extraction focus: Section L/M (best-effort) → matrix → gate → export")

    st.markdown("---")

    # B) Missing info alerts
    st.subheader("B) Missing Info Alerts (fix before submission)")
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

    # C) Submission package checklist
    st.subheader("C) Submission Package Checklist (Detected-Only)")
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
        st.info("No submission package items detected yet. Upload/paste more of Section L/M and click Analyze.")
    else:
        # FIX: index-based keys to avoid collisions
        for bucket, items in submission_pkg.items():
            with st.expander(bucket, expanded=("Submission Instructions" in bucket)):
                for idx, it in enumerate(items):
                    st.checkbox(it, value=False, key=f"pkg_{bucket}_{idx}")

    st.markdown("---")

    # D) Validation Lock
    st.subheader("D) Validation Lock (Pre-Submit Gate)")
    deadline_detected = bool(rules.get("Due Date/Deadline"))

    if deadline_detected:
        st.session_state.deadline_ack = st.checkbox(
            "I acknowledge the detected submission deadline is correct (verify Section L and cover page).",
            value=st.session_state.deadline_ack
        )
    else:
        st.caption("No deadline detected. Gate will not require deadline acknowledgement (but you should still verify manually).")

    if st.button("Run Pre-Submission Check"):
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

    # E) Matrix
    st.subheader("E) Compliance Matrix v2")
    if not matrix_rows:
        st.warning("No requirements extracted yet. Try uploading/pasting Section L/M content and re-run Analyze.")
    else:
        section_options = DEFAULT_SECTIONS.copy()
        for kname in (drafts or {}).keys():
            if kname not in section_options:
                section_options.insert(-1, kname)

        for row in matrix_rows[:50]:
            with st.expander(f"{row['id']} — {row['requirement'][:90]}{'...' if len(row['requirement'])>90 else ''}"):
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

    st.session_state.matrix_rows = matrix_rows

    st.markdown("---")

    # J) Drafts
    st.subheader("J) Draft Proposal Sections (template-based)")
    kws = st.session_state.keywords or []
    if st.button("Generate Draft Sections"):
        st.session_state.drafts = generate_drafts(
            sow_snips=st.session_state.sow_snips or [],
            keywords=kws,
            rules=rules,
            forms=forms,
            attachments=attachments,
            company=c
        )
        st.success("Draft generated.")

    drafts = st.session_state.drafts or {}
    if drafts:
        for title, body in drafts.items():
            with st.expander(title, expanded=(title in ["Executive Summary", "Technical Approach"])):
                st.text_area(label="", value=body, height=260)

    st.markdown("---")

    # K) Export
    st.subheader("K) Export (Professional Word Proposal Package)")
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
            warnings=compliance_warnings(rules, forms, amendments, separate),
            checklist_items=build_checklist_items(rules, forms, attachments, amendments, separate, required_certs),
            matrix_rows=st.session_state.matrix_rows or [],
            drafts=drafts,
            validation_result=st.session_state.validation_last,
            submission_pkg=submission_pkg,
        )
        st.download_button(
            label="Download Proposal Package (.docx)",
            data=doc_bytes,
            file_name="proposal_package.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        st.caption("In Word: right-click the Table of Contents → Update Field → Update entire table.")
    else:
        st.info("Generate draft sections first, then export.")