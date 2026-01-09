import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple

import streamlit as st

# Optional: PDF/DOCX parsing (safe if installed)
try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    import docx  # python-docx
except Exception:
    docx = None


# -----------------------------
# Helpers: file text extraction
# -----------------------------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    if not pdfplumber:
        return ""
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                text_parts.append(t)
    return "\n\n".join(text_parts)


def extract_text_from_docx(file_bytes: bytes) -> str:
    if not docx:
        return ""
    import io
    f = io.BytesIO(file_bytes)
    d = docx.Document(f)
    return "\n".join([p.text for p in d.paragraphs if p.text])


def read_uploaded_file(uploaded_file) -> str:
    if not uploaded_file:
        return ""
    name = uploaded_file.name.lower()
    data = uploaded_file.read()
    # Reset pointer not needed in Streamlit (we already read bytes)

    if name.endswith(".pdf"):
        if not pdfplumber:
            return ""
        import io
        text_parts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    text_parts.append(t)
        return "\n\n".join(text_parts)

    if name.endswith(".docx"):
        if not docx:
            return ""
        import io
        d = docx.Document(io.BytesIO(data))
        return "\n".join([p.text for p in d.paragraphs if p.text])

    # txt or anything else: best effort decode
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


# -----------------------------
# Parsing: rules, forms, SOW
# -----------------------------
FORM_PATTERNS = [
    (r"\bSF\s?1449\b", "SF 1449 (Solicitation/Contract/Order for Commercial Items)"),
    (r"\bSF\s?33\b", "SF 33 (Solicitation, Offer and Award)"),
    (r"\bSF\s?30\b", "SF 30 (Amendment of Solicitation/Modification of Contract)"),
    (r"\bSF\s?18\b", "SF 18 (Request for Quotations)"),
    (r"\bSF\s?26\b", "SF 26 (Award/Contract)"),
    (r"\bDD\s?254\b", "DD 254 (Contract Security Classification Spec)"),
    (r"\bDD\s?1155\b", "DD 1155 (Order for Supplies or Services)"),
    (r"\bSF\s?1408\b", "SF 1408 (Preaward Survey of Prospective Contractor)"),
    (r"\bSF\s?1423\b", "SF 1423 (Contract Data Requirements List - CDRL)"),
]

ATTACHMENT_HINTS = [
    r"\battachment\b",
    r"\bappendix\b",
    r"\bexhibit\b",
    r"\bannex\b",
    r"\benclosure\b",
    r"\baddendum\b",
    r"\bamendment\b",
]


def find_forms(text: str) -> List[str]:
    found = []
    for pat, label in FORM_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            found.append(label)
    return sorted(set(found))


def find_attachments_mentions(text: str) -> List[str]:
    # Simple: grab lines mentioning attachment/appendix/exhibit/etc.
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    hits = []
    for l in lines:
        if any(re.search(p, l, flags=re.IGNORECASE) for p in ATTACHMENT_HINTS):
            # Keep only likely meaningful lines
            if len(l) < 200:
                hits.append(l)
    # Deduplicate but keep order
    seen = set()
    out = []
    for h in hits:
        key = h.lower()
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out[:30]


def extract_submission_rules(text: str) -> Dict[str, Any]:
    """
    Best-effort extraction. This is NOT perfect yet, but it makes it useful immediately.
    """
    rules = {
        "due_date_deadline": None,
        "submission_method": None,
        "page_limit": None,
        "font": None,
        "margins": None,
        "file_format": None,
        "volumes": [],
    }

    t = text

    # Due date: look for "due", "deadline", "offers are due", and a date-like pattern
    date_pat = r"((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})"
    m = re.search(rf"(due|deadline|offers?\s+are\s+due).{{0,80}}{date_pat}", t, flags=re.IGNORECASE)
    if m:
        rules["due_date_deadline"] = m.group(0).strip()

    # Submission method
    m = re.search(r"(submit|submission).{0,80}(email|emailed|e-mail|portal|sam\.gov|piee|wawf|fedconnect|upload|hand[- ]deliver|mail)", t, flags=re.IGNORECASE)
    if m:
        rules["submission_method"] = m.group(0).strip()

    # Page limit
    m = re.search(r"(\bpage limit\b|\bpages?\b).{0,30}(\d{1,3})", t, flags=re.IGNORECASE)
    if m:
        rules["page_limit"] = m.group(0).strip()

    # Font
    m = re.search(r"(font).{0,40}(arial|times new roman|calibri|courier).{0,20}(\d{1,2})\s?(pt|point)?", t, flags=re.IGNORECASE)
    if m:
        rules["font"] = m.group(0).strip()

    # Margins
    m = re.search(r"(margin|margins).{0,40}(\d(\.\d+)?\s?(inch|inches)|1\")", t, flags=re.IGNORECASE)
    if m:
        rules["margins"] = m.group(0).strip()

    # File format
    m = re.search(r"(pdf|docx|word document|excel|xlsx).{0,40}(format|file)", t, flags=re.IGNORECASE)
    if m:
        rules["file_format"] = m.group(0).strip()

    # Volumes (Volume I, II, etc.)
    vols = re.findall(r"\bVolume\s+(I|II|III|IV|V|VI|1|2|3|4|5|6)\b.{0,60}", t, flags=re.IGNORECASE)
    # re.findall returns only group; re-run for context
    vol_ctx = re.findall(r"\bVolume\s+(?:I|II|III|IV|V|VI|1|2|3|4|5|6)\b.{0,60}", t, flags=re.IGNORECASE)
    rules["volumes"] = list(dict.fromkeys([v.strip() for v in vol_ctx]))[:10]

    return rules


def extract_sow_snippets(text: str, max_snippets: int = 6) -> List[str]:
    """
    Pull lines/paragraphs that likely describe scope/SOW/PWS/tasks.
    """
    # Split into paragraphs
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    candidates = []
    key = re.compile(r"\b(statement of work|scope of work|sow|pws|performance work statement|tasks?|requirements?)\b", re.IGNORECASE)

    for p in paras:
        if key.search(p):
            # keep paragraph trimmed
            candidates.append(p[:800])

    # If none found, fallback to first few paragraphs (but skip obvious cover pages)
    if not candidates:
        candidates = paras[:max_snippets]

    # Dedup
    out = []
    seen = set()
    for c in candidates:
        k = c.lower()
        if k not in seen:
            seen.add(k)
            out.append(c)
        if len(out) >= max_snippets:
            break
    return out


def derive_tailor_keywords(sow_snippets: List[str]) -> List[str]:
    """
    Very simple keyword extraction (non-AI). Later we can replace with an LLM.
    """
    text = " ".join(sow_snippets).lower()
    # common gov words to ignore
    stop = set("""
        the a an and or to of for in on with by from as at is are be shall will may must
        offer proposal contractor government agency work statement performance requirement requirements
        services service task tasks provide providing include including
    """.split())

    words = re.findall(r"[a-z]{4,}", text)
    freq = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1

    top = sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:12]
    return [w for w, _ in top]


# -----------------------------
# Company info + draft generator
# -----------------------------
@dataclass
class CompanyInfo:
    company_name: str = ""
    dba: str = ""
    address: str = ""
    point_of_contact: str = ""
    email: str = ""
    phone: str = ""
    uei: str = ""
    cage: str = ""
    naics: str = ""
    psc: str = ""
    set_asides: str = ""  # e.g., SDVOSB, 8(a)
    capabilities: str = ""
    differentiators: str = ""
    past_performance: str = ""  # optional
    website: str = ""


def generate_draft_sections(
    rfp_text: str,
    rules: Dict[str, Any],
    forms: List[str],
    attachments: List[str],
    company: CompanyInfo,
    sow_snippets: List[str],
    tailor_keywords: List[str],
) -> Dict[str, str]:
    """
    Non-AI draft generator using templates + keyword tailoring.
    This gets you to 'usable in minutes'. We can add LLM later.
    """
    kw_line = ", ".join(tailor_keywords[:8]) if tailor_keywords else "scope, schedule, quality, reporting"
    due = rules.get("due_date_deadline") or "TBD"
    method = rules.get("submission_method") or "TBD"
    font = rules.get("font") or "TBD"
    margins = rules.get("margins") or "TBD"
    page_limit = rules.get("page_limit") or "TBD"

    company_block = f"""{company.company_name}
{company.address}
POC: {company.point_of_contact} | {company.email} | {company.phone}
UEI: {company.uei} | CAGE: {company.cage}
NAICS: {company.naics} | PSC: {company.psc}
Set-Asides/Certs: {company.set_asides}
Website: {company.website}
""".strip()

    cover_letter = f"""[COVER LETTER]

Date: {""}
To: Contracting Officer (TBD)

Subject: Proposal Submission – {company.company_name}

Dear Contracting Officer,

{company.company_name} submits this proposal in response to the referenced solicitation. We understand the Government’s objectives and have aligned our approach to deliver measurable outcomes across: {kw_line}.

Submission Summary (Best Effort Extracted):
- Due Date/Deadline: {due}
- Submission Method: {method}
- Page/Format Constraints: {page_limit} | Font: {font} | Margins: {margins}

We appreciate the opportunity to compete and are prepared to begin immediately upon award.

Sincerely,
{company.point_of_contact}
{company.company_name}
"""

    exec_summary = f"""[EXECUTIVE SUMMARY]

{company.company_name} proposes to deliver the required scope with a compliant, low-risk execution plan centered on:
1) On-time delivery aligned to the SOW/PWS
2) Clear governance and reporting
3) Proven operational discipline and quality control

Tailoring Notes (derived from SOW text):
- Key focus areas: {kw_line}

Company Snapshot:
{company_block}
"""

    tech_approach = f"""[TECHNICAL APPROACH]

Understanding of the Requirement (from SOW/PWS excerpts):
{chr(10).join([f"- {s}" for s in sow_snippets[:3]])}

Approach:
- Deliverables & Outcomes: We will map each requirement to a deliverable, acceptance criteria, and verification method.
- Execution: We will implement a step-by-step plan with weekly checkpoints, risk reviews, and documented approvals.
- Quality: We use standard operating procedures, peer review, and objective evidence to ensure quality and compliance.

Keywords we designed around:
{kw_line}
"""

    mgmt_staff = f"""[MANAGEMENT & STAFFING]

Program Management:
- Single accountable Program Manager (POC) responsible for schedule, quality, and communications.
- Weekly status updates; milestone tracking; issue/risk log management.

Staffing:
- Roles will be aligned to SOW tasks and deliverables.
- Surge support available for time-sensitive periods.

Communications:
- Standard cadence: kickoff, weekly status, ad hoc escalation as required.
"""

    # Past performance or capability-based substitute
    if company.past_performance.strip():
        pp = f"""[PAST PERFORMANCE]

Provided Past Performance:
{company.past_performance}

Relevance:
- Demonstrates delivery of similar scope, schedule, and quality requirements.
"""
    else:
        pp = f"""[PAST PERFORMANCE (CAPABILITY-BASED – NO DIRECT PAST PERFORMANCE PROVIDED)]

{company.company_name} is prepared to execute this requirement using established operational discipline, documented processes, and qualified personnel. While we may not have directly analogous past performance to cite, we will demonstrate responsibility and capability through:
- Clear management controls and reporting
- Defined QC checks
- Staffing aligned to task requirements
- Risk mitigation and escalation procedures

(When you add real references later, this section will auto-update.)
"""

    compliance = f"""[COMPLIANCE SNAPSHOT (STARTER)]

Rules (best-effort extraction):
- Due Date/Deadline: {due}
- Submission Method: {method}
- Page/Format: {page_limit}
- Font: {font}
- Margins: {margins}

Forms detected:
{chr(10).join([f"- {f}" for f in forms]) if forms else "- None detected (based on text provided)"}

Attachments/Appendices mentions:
{chr(10).join([f"- {a}" for a in attachments[:10]]) if attachments else "- None detected (based on text provided)"}
"""

    return {
        "Cover Letter": cover_letter,
        "Executive Summary": exec_summary,
        "Technical Approach": tech_approach,
        "Management & Staffing": mgmt_staff,
        "Past Performance": pp,
        "Compliance Snapshot": compliance,
    }


def build_compliance_warnings(rules: Dict[str, Any], forms: List[str], rfp_text: str) -> List[str]:
    warnings = []
    if not rules.get("due_date_deadline"):
        warnings.append("No clear due date/deadline detected. Verify Section L / submission instructions and any amendments.")
    if not rules.get("submission_method"):
        warnings.append("No clear submission method detected (email/portal/etc.). Verify where/how to submit.")
    # Common forms to double-check
    if "SF 1449 (Solicitation/Contract/Order for Commercial Items)" in forms:
        warnings.append("SF 1449 detected. Ensure blocks/signature sections are completed as required and amendments are acknowledged.")
    # Very rough: look for "amendment" mentions
    if re.search(r"\bamendment\b", rfp_text, flags=re.IGNORECASE):
        warnings.append("Amendment(s) mentioned. Confirm all amendments are acknowledged and any revised instructions are incorporated.")
    if not warnings:
        warnings.append("No major warnings detected by the starter logic. Still verify Section L/M and all attachments.")
    return warnings


# -----------------------------
# Streamlit App UI
# -----------------------------
st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")

# Session state init
if "rfp_text" not in st.session_state:
    st.session_state.rfp_text = ""
if "rules" not in st.session_state:
    st.session_state.rules = {}
if "forms" not in st.session_state:
    st.session_state.forms = []
if "attachments" not in st.session_state:
    st.session_state.attachments = []
if "sow_snippets" not in st.session_state:
    st.session_state.sow_snippets = []
if "tailor_keywords" not in st.session_state:
    st.session_state.tailor_keywords = []
if "drafts" not in st.session_state:
    st.session_state.drafts = {}
if "company" not in st.session_state:
    st.session_state.company = CompanyInfo()


st.sidebar.title("Path")
page = st.sidebar.radio("Go to", ["RFP Intake", "Company Info", "Proposal Output"])

st.sidebar.caption("Tip: Build this in small steps. You're doing great.")

# -----------------------------
# Page 1: RFP Intake
# -----------------------------
if page == "RFP Intake":
    st.markdown("# 1) RFP Intake")
    st.write("Upload RFP (PDF, DOCX, or TXT) or paste text.")

    uploaded = st.file_uploader("Upload RFP (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"])
    pasted = st.text_area("Or paste RFP / RFI text", value=st.session_state.rfp_text, height=280)

    col1, col2 = st.columns([1, 3])
    with col1:
        analyze = st.button("Analyze")

    if analyze:
        rfp_text = ""
        if uploaded:
            rfp_text = read_uploaded_file(uploaded)
            if not rfp_text.strip():
                st.warning("File uploaded, but no text could be extracted. If PDF is scanned, we’ll need OCR later.")
        if pasted.strip():
            # If user pasted, it overrides/extends
            rfp_text = pasted.strip()

        if not rfp_text.strip():
            st.error("Please upload a file or paste text.")
        else:
            st.session_state.rfp_text = rfp_text
            st.session_state.rules = extract_submission_rules(rfp_text)
            st.session_state.forms = find_forms(rfp_text)
            st.session_state.attachments = find_attachments_mentions(rfp_text)
            st.session_state.sow_snippets = extract_sow_snippets(rfp_text)
            st.session_state.tailor_keywords = derive_tailor_keywords(st.session_state.sow_snippets)

            st.success("Analysis complete. Go to Proposal Output.")

    st.divider()
    st.subheader("Preview (first 1,000 chars)")
    st.code((st.session_state.rfp_text or "")[:1000])

# -----------------------------
# Page 2: Company Info
# -----------------------------
elif page == "Company Info":
    st.markdown("# 2) Company Info")
    st.write("Enter your company information once. It will auto-fill the draft proposal sections.")

    c = st.session_state.company

    c.company_name = st.text_input("Company Name", value=c.company_name)
    c.dba = st.text_input("DBA (optional)", value=c.dba)
    c.address = st.text_area("Address", value=c.address, height=90)

    st.subheader("Point of Contact")
    c.point_of_contact = st.text_input("POC Name", value=c.point_of_contact)
    c.email = st.text_input("POC Email", value=c.email)
    c.phone = st.text_input("POC Phone", value=c.phone)

    st.subheader("Identifiers")
    c.uei = st.text_input("UEI", value=c.uei)
    c.cage = st.text_input("CAGE", value=c.cage)
    c.naics = st.text_input("NAICS", value=c.naics)
    c.psc = st.text_input("PSC (optional)", value=c.psc)

    st.subheader("Certifications / Set-Asides")
    c.set_asides = st.text_input("e.g., SDVOSB, 8(a), WOSB, HUBZone, etc.", value=c.set_asides)

    st.subheader("Capabilities & Differentiators")
    c.capabilities = st.text_area("Capabilities (short bullets or paragraph)", value=c.capabilities, height=120)
    c.differentiators = st.text_area("Differentiators (why you)", value=c.differentiators, height=120)

    st.subheader("Past Performance (optional)")
    c.past_performance = st.text_area(
        "Paste past performance bullets OR leave blank to auto-generate capability-based language",
        value=c.past_performance,
        height=160,
    )

    c.website = st.text_input("Website (optional)", value=c.website)

    st.session_state.company = c
    st.success("Saved. Go to Proposal Output when ready.")

# -----------------------------
# Page 3: Proposal Output
# -----------------------------
else:
    st.markdown("# 3) Proposal Output")

    if not st.session_state.rfp_text.strip():
        st.warning("No RFP text found yet. Go to RFP Intake and click Analyze.")
        st.stop()

    # A) Submission Rules
    st.subheader("A) Submission Rules Found (starter)")
    rules = st.session_state.rules or {}
    with st.expander("Due Date/Deadline", expanded=False):
        st.write(rules.get("due_date_deadline") or "Not detected yet.")
    with st.expander("Submission Method", expanded=False):
        st.write(rules.get("submission_method") or "Not detected yet.")
    with st.expander("Font Requirement", expanded=False):
        st.write(rules.get("font") or "Not detected yet.")
    with st.expander("Margin Requirement", expanded=False):
        st.write(rules.get("margins") or "Not detected yet.")
    with st.expander("Page Limit", expanded=False):
        st.write(rules.get("page_limit") or "Not detected yet.")
    with st.expander("Volumes (if found)", expanded=False):
        vols = rules.get("volumes") or []
        if vols:
            for v in vols:
                st.write(f"- {v}")
        else:
            st.write("None detected yet.")

    st.divider()

    # B) Forms & Attachments
    st.subheader("B) Forms & Attachments Detected (starter)")
    st.markdown("**Forms (SF/DD) Found**")
    forms = st.session_state.forms or []
    if forms:
        for f in forms:
            st.write(f"- {f}")
    else:
        st.write("- None detected (based on provided text).")

    st.markdown("**Attachment / Appendix Mentions (first 10)**")
    attachments = st.session_state.attachments or []
    if attachments:
        for a in attachments[:10]:
            st.write(f"- {a}")
    else:
        st.write("- None detected (based on provided text).")

    st.divider()

    # C) Compliance Warnings
    st.subheader("C) Compliance Warnings (starter)")
    warnings = build_compliance_warnings(rules, forms, st.session_state.rfp_text)
    for w in warnings:
        st.warning(w)

    st.divider()

    # D) Draft Generator (template-based)
    st.subheader("D) Draft Proposal Sections (starter, template-based)")

    sow_snips = st.session_state.sow_snippets or []
    kws = st.session_state.tailor_keywords or []

    st.caption(f"Tailoring keywords (auto-extracted): {', '.join(kws[:10]) if kws else 'None'}")

    # Require at least company name to generate nicer output
    if not st.session_state.company.company_name.strip():
        st.info("Tip: Go to Company Info and add at least your company name for better auto-fill.")
    if st.button("Generate Draft Sections"):
        st.session_state.drafts = generate_draft_sections(
            rfp_text=st.session_state.rfp_text,
            rules=rules,
            forms=forms,
            attachments=attachments,
            company=st.session_state.company,
            sow_snippets=sow_snips,
            tailor_keywords=kws,
        )
        st.success("Draft generated. Scroll down.")

    drafts = st.session_state.drafts or {}
    if drafts:
        for title, body in drafts.items():
            with st.expander(title, expanded=(title in ["Executive Summary", "Technical Approach"])):
                st.text_area(label="", value=body, height=260)