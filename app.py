import io
import json
import re
from dataclasses import dataclass, asdict
from typing import List, Dict

import streamlit as st
from pypdf import PdfReader
import docx  # python-docx

st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")


# =========================
# File text extraction
# =========================

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Text-based PDF extraction using pypdf."""
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()

def extract_text_from_docx(file_bytes: bytes) -> str:
    """DOCX extraction using python-docx."""
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

    # txt fallback
    try:
        return data.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


# =========================
# RFP intelligence
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
    (r"\bsubmit\b|\bsubmission\b|\be-?mail\b|\bemailed\b|\bportal\b|\bupload\b|\bSam\.gov\b|\beBuy\b|\bPIEE\b|\bFedConnect\b", "Submission Method"),
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

def scan_lines(text: str, max_lines: int = 6000) -> List[str]:
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

    out = []
    seen = set()
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

def compliance_warnings(rules: Dict[str, List[str]], forms: List[str], amendments: List[str], separate: List[str], rfp_text: str) -> List[str]:
    warnings = []

    if not rules:
        warnings.append("No submission rules detected. If you pasted partial text, try uploading the full (text-based) PDF.")
    else:
        if "Due Date/Deadline" not in rules:
            warnings.append("Due date/deadline not clearly detected. Verify Section L and the cover page.")
        if "Submission Method" not in rules:
            warnings.append("Submission method not clearly detected (email/portal/etc.). Verify exactly how/where to submit.")
        if any(k in rules for k in ["Page Limit", "Font Requirement", "Margin Requirement"]):
            warnings.append("Formatting rules detected (page/font/margins). Violations can lead to rejection as non-compliant.")

    if forms:
        warnings.append("SF/DD forms detected. Many require signatures or specific fields—confirm each required form is completed.")
    if amendments:
        warnings.append("Amendments/modifications referenced. Ensure all amendments are acknowledged and instructions updated.")
    if separate:
        warnings.append("Some items appear to require separate files/completions (signed forms, spreadsheets, attachments). Review the separate-submission list below.")

    if not warnings:
        warnings.append("No major warnings detected by starter logic. Still verify Section L/M and all attachments manually.")
    return warnings


# =========================
# Company info + Draft generator
# =========================

@dataclass
class CompanyInfo:
    legal_name: str = ""
    dba: str = ""
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

    def to_dict(self):
        d = asdict(self)
        if d["certifications"] is None:
            d["certifications"] = []
        return d


def generate_drafts(
    rfp_text: str,
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
    certs = ", ".join(company.certifications or []) if (company.certifications and len(company.certifications) > 0) else "—"

    cover = f"""COVER LETTER (DRAFT)

{company.legal_name or "[Company Name]"}
{company.address or "[Address]"}
UEI: {company.uei or "[UEI]"} | CAGE: {company.cage or "[CAGE]"}
POC: {company.poc_name or "[POC]"} | {company.poc_email or "[email]"} | {company.poc_phone or "[phone]"}
Certifications: {certs}

Subject: Proposal Submission

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

    sow_block = "\n".join([f"- {s}" for s in sow_snips[:3]]) if sow_snips else "- [No SOW snippets detected]"
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
# DOCX Export
# =========================

def doc_add_heading(doc, text, level=1):
    doc.add_heading(text, level=level)

def doc_add_paragraph_lines(doc, text: str):
    # Keep line breaks readable
    for line in text.splitlines():
        doc.add_paragraph(line)

def build_proposal_docx_bytes(
    company: CompanyInfo,
    rules: Dict[str, List[str]],
    forms: List[str],
    attachments: List[str],
    amendments: List[str],
    separate: List[str],
    warnings: List[str],
    drafts: Dict[str, str]
) -> bytes:
    doc = docx.Document()

    # Title
    doc_add_heading(doc, "Proposal Draft Package", level=0)

    # Company snapshot
    doc_add_heading(doc, "Company Profile", level=1)
    certs = ", ".join(company.certifications or []) if company.certifications else "—"
    snapshot = f"""Company: {company.legal_name or "—"}
DBA: {company.dba or "—"}
Address: {company.address or "—"}
UEI: {company.uei or "—"} | CAGE: {company.cage or "—"}
NAICS: {company.naics or "—"} | PSC: {company.psc or "—"}
POC: {company.poc_name or "—"} | {company.poc_email or "—"} | {company.poc_phone or "—"}
Certifications/Set-Asides: {certs}
Website: {company.website or "—"}
"""
    doc_add_paragraph_lines(doc, snapshot)

    # Checklist
    doc_add_heading(doc, "Submission Checklist (Auto-Detected - Starter)", level=1)

    doc_add_heading(doc, "Submission Rules Found", level=2)
    if rules:
        for label, lines in rules.items():
            doc.add_paragraph(label, style="List Bullet")
            for ln in lines[:8]:
                doc.add_paragraph(ln, style="List Bullet 2")
    else:
        doc.add_paragraph("No submission rules detected.", style="List Bullet")

    doc_add_heading(doc, "Forms Detected", level=2)
    if forms:
        for f in forms:
            doc.add_paragraph(f, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc_add_heading(doc, "Attachments / Appendices / Exhibits Mentions", level=2)
    if attachments:
        for a in attachments[:15]:
            doc.add_paragraph(a, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc_add_heading(doc, "Amendments / Mods Referenced", level=2)
    if amendments:
        for a in amendments[:15]:
            doc.add_paragraph(a, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc_add_heading(doc, "Items That Look Like Separate Submission", level=2)
    if separate:
        for s in separate[:20]:
            doc.add_paragraph(s, style="List Bullet")
    else:
        doc.add_paragraph("None detected.", style="List Bullet")

    doc_add_heading(doc, "Compliance Warnings", level=2)
    if warnings:
        for w in warnings:
            doc.add_paragraph(w, style="List Bullet")
    else:
        doc.add_paragraph("None.", style="List Bullet")

    # Draft sections
    doc_add_heading(doc, "Draft Proposal Sections", level=1)
    if drafts:
        for title, body in drafts.items():
            doc_add_heading(doc, title, level=2)
            doc_add_paragraph_lines(doc, body)
    else:
        doc.add_paragraph("No draft sections generated yet.", style="List Bullet")

    # Return bytes
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# =========================
# Session State
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

if "sow_snips" not in st.session_state:
    st.session_state.sow_snips = []

if "keywords" not in st.session_state:
    st.session_state.keywords = []

if "drafts" not in st.session_state:
    st.session_state.drafts = {}

if "company" not in st.session_state:
    st.session_state.company = CompanyInfo(certifications=[])


# =========================
# UI Navigation
# =========================

st.sidebar.title("Path")
page = st.sidebar.radio("Go to", ["RFP Intake", "Company Info", "Proposal Output"])
st.sidebar.caption("Upload/paste RFP → Analyze → Proposal Output → Generate → Download")


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
            st.success("Analysis saved. Go to Proposal Output.")

    st.markdown("---")
    st.subheader("Preview (first 1200 characters)")
    st.code((st.session_state.rfp_text or "")[:1200], language="text")


# =========================
# Page 2: Company Info
# =========================

elif page == "Company Info":
    st.title("2) Company Info")
    st.caption("Fill this out once. Proposal drafts will auto-insert this information.")

    c: CompanyInfo = st.session_state.company

    col1, col2 = st.columns(2)
    with col1:
        c.legal_name = st.text_input("Legal Company Name", value=c.legal_name)
        c.dba = st.text_input("DBA (optional)", value=c.dba)
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
    st.caption("If you have none, leave blank and we’ll generate capability-based language.")
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
    c: CompanyInfo = st.session_state.company

    # A) Submission Rules
    st.subheader("A) Submission Rules Found (starter)")
    if rules:
        for label, lines in rules.items():
            with st.expander(label, expanded=False):
                for ln in lines:
                    st.write("•", ln)
    else:
        st.write("No obvious submission rules detected yet. (Try uploading the full text-based PDF.)")

    st.markdown("---")

    # B) Forms & Attachments
    st.subheader("B) Forms & Attachments Detected (starter)")

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

    # C) Compliance warnings
    st.subheader("C) Compliance Warnings (action items)")
    warns = compliance_warnings(rules, forms, amendments, separate, st.session_state.rfp_text)
    for w in warns:
        st.warning(w)

    if separate:
        st.markdown("### Items that look like they must be completed/submitted separately")
        for ln in separate[:25]:
            st.write("•", ln)
        if len(separate) > 25:
            st.caption(f"Showing 25 of {len(separate)}")

    st.markdown("---")

    # D) Draft generator
    st.subheader("D) Draft Proposal Sections (starter, template-based)")
    kws = st.session_state.keywords or []
    if kws:
        st.caption("Tailoring keywords (auto-extracted): " + ", ".join(kws[:10]))
    else:
        st.caption("Tailoring keywords: (none detected yet)")

    if not (c.legal_name or "").strip():
        st.info("Tip: Go to Company Info and enter at least your company name for better drafts.")

    colG, colD = st.columns([1, 1])
    with colG:
        if st.button("Generate Draft Sections"):
            st.session_state.drafts = generate_drafts(
                rfp_text=st.session_state.rfp_text,
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
        st.info("Generate drafts to enable Word download.")

    st.markdown("---")

    # NEW: Word Download
    st.subheader("E) Download Proposal Package")
    if drafts:
        doc_bytes = build_proposal_docx_bytes(
            company=c,
            rules=rules,
            forms=forms,
            attachments=attachments,
            amendments=amendments,
            separate=separate,
            warnings=warns,
            drafts=drafts
        )
        filename = "proposal_draft_package.docx"
        st.download_button(
            label="Download Proposal (.docx)",
            data=doc_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        st.write("Generate draft sections first, then download the Word file.")

    st.markdown("---")
    st.subheader("F) RFP Preview (first 1500 characters)")
    st.code(st.session_state.rfp_text[:1500], language="text")