import io
import json
import re
import streamlit as st
from pypdf import PdfReader
import docx

st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")

# =========================
# Text extraction
# =========================

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
        text += "\n"
    return text

def extract_text_from_docx(file_bytes: bytes) -> str:
    document = docx.Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in document.paragraphs)

def safe_len(s: str) -> int:
    return len(s) if s else 0

# =========================
# RFP intelligence (starter but smarter)
# =========================

FORM_PATTERNS = [
    (r"\bSF[-\s]?1449\b", "SF 1449 (Solicitation/Contract/Order for Commercial Items)"),
    (r"\bSF[-\s]?33\b", "SF 33 (Solicitation/Offer and Award)"),
    (r"\bSF[-\s]?30\b", "SF 30 (Amendment of Solicitation/Modification of Contract)"),
    (r"\bSF[-\s]?18\b", "SF 18 (Request for Quotations)"),
    (r"\bDD[-\s]?1155\b", "DD 1155 (Order for Supplies or Services)"),
    (r"\bSF[-\s]?26\b", "SF 26 (Award/Contract)"),
    (r"\bSF[-\s]?34\b", "SF 34 (Annual Bid Bond)"),
    (r"\bSF[-\s]?28\b", "SF 28 (Affidavit of Individual Surety)"),
]

ATTACHMENT_PATTERNS = [
    (r"\battachment\s+[a-z0-9]+\b", "Attachment"),
    (r"\bappendix\s+[a-z0-9]+\b", "Appendix"),
    (r"\bexhibit\s+[a-z0-9]+\b", "Exhibit"),
    (r"\benclosure\s+[a-z0-9]+\b", "Enclosure"),
    (r"\bannex\s+[a-z0-9]+\b", "Annex"),
    (r"\btab\s+[a-z0-9]+\b", "Tab"),
]

SUBMISSION_PATTERNS = [
    (r"\bpage limit\b|\bpages maximum\b|\bnot exceed\s+\d+\s+pages\b", "Page Limit"),
    (r"\bfont\b|\b12[-\s]?point\b|\b11[-\s]?point\b|\bTimes New Roman\b|\bArial\b", "Font Requirement"),
    (r"\bmargins?\b|\b1 inch\b|\bone inch\b", "Margin Requirement"),
    (r"\bdue\b|\bdue date\b|\bno later than\b|\bdeadline\b", "Due Date/Deadline"),
    (r"\bsubmit\b|\bsubmission\b|\be-?mail\b|\bportal\b|\bSam\.gov\b|\beBuy\b|\bPIEE\b", "Submission Method"),
    (r"\bsection\s+l\b|\bsection\s+m\b", "Sections L/M referenced"),
]

AMENDMENT_PATTERN = r"\bamendment\b|\bamendments\b|\ba0{2,}\d+\b|\bmodification\b"

SEPARATE_SUBMIT_HINTS = [
    r"\bsigned\b",
    r"\bsignature\b",
    r"\bcomplete and return\b",
    r"\bfill(?:ed)? out\b",
    r"\bsubmit separately\b",
    r"\bseparate file\b",
    r"\binclude as an attachment\b",
    r"\bexcel\b|\bspreadsheet\b",
]

def normalize_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    return line

def unique_keep_order(items):
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def scan_lines(text: str, max_lines=5000):
    lines = []
    for raw in text.splitlines():
        s = normalize_line(raw)
        if s:
            lines.append(s)
        if len(lines) >= max_lines:
            break
    return lines

def detect_forms_and_attachments(text: str):
    lines = scan_lines(text)

    forms_found = []
    attachments_found = []
    amendment_hits = []
    separate_submit_hits = []

    # Look for form IDs and attachment-ish references
    for line in lines:
        low = line.lower()

        # Forms
        for pat, label in FORM_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                forms_found.append(label)

        # Attachments/appendices/exhibits
        for pat, label in ATTACHMENT_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                attachments_found.append(line)

        # Amendments
        if re.search(AMENDMENT_PATTERN, line, re.IGNORECASE):
            amendment_hits.append(line)

        # "Submit separately" hints
        if any(re.search(h, low, re.IGNORECASE) for h in SEPARATE_SUBMIT_HINTS):
            # Only keep the lines that also mention a likely artifact/form/attachment
            if ("sf " in low or "sf-" in low or "attachment" in low or "appendix" in low or "exhibit" in low
                or "amendment" in low or "pricing" in low or "price" in low or "spreadsheet" in low):
                separate_submit_hits.append(line)

    forms_found = unique_keep_order(forms_found)
    attachments_found = unique_keep_order(attachments_found)
    amendment_hits = unique_keep_order(amendment_hits)
    separate_submit_hits = unique_keep_order(separate_submit_hits)

    return {
        "forms": forms_found,
        "attachments_lines": attachments_found,
        "amendment_lines": amendment_hits,
        "separate_submit_lines": separate_submit_hits
    }

def detect_submission_rules(text: str):
    lines = scan_lines(text)
    found = []

    for line in lines:
        for pat, label in SUBMISSION_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                # keep the specific line for context
                found.append((label, line))

    # group by label
    grouped = {}
    for label, line in found:
        grouped.setdefault(label, [])
        grouped[label].append(line)

    # dedupe each group
    for k in list(grouped.keys()):
        grouped[k] = unique_keep_order(grouped[k])[:10]

    return grouped

def generate_compliance_warnings(rfp_text: str, intel: dict, rules: dict):
    warnings = []

    if not rfp_text.strip():
        warnings.append("No RFP text saved yet. Go to 'RFP Intake' and click Analyze.")
        return warnings

    # If amendments are mentioned, warn to acknowledge all amendments
    if intel["amendment_lines"]:
        warnings.append("Amendments are referenced. Make sure you acknowledge/sign all amendments and include them in your submission package.")

    # If forms found, warn about signatures/completions
    if intel["forms"]:
        warnings.append("Standard forms were detected (SF/DD forms). Many require signatures or specific blocks completed—confirm each one.")

    # If page/font/margins show up, warn to follow formatting
    if any(k in rules for k in ["Page Limit", "Font Requirement", "Margin Requirement"]):
        warnings.append("Formatting rules detected (page limit/font/margins). If you violate these, you can be eliminated as non-compliant.")

    # If submission method shows up, warn to follow method exactly
    if "Submission Method" in rules:
        warnings.append("Submission instructions detected (email/portal). Follow the method exactly, including file naming and deadline time zone.")

    # If we see “submit separately” lines, warn to separate forms/price files
    if intel["separate_submit_lines"]:
        warnings.append("Some items appear to require separate completion/submission (signed forms, spreadsheets, separate files). Review the checklist below.")

    # If nothing detected at all, warn that RFP may be incomplete/poorly pasted
    if (not intel["forms"] and not intel["attachments_lines"] and not intel["amendment_lines"] and not rules):
        warnings.append("No obvious compliance markers detected. The RFP text may be incomplete (try uploading the PDF instead of copying sections).")

    return warnings

# =========================
# Session state
# =========================

if "company" not in st.session_state:
    st.session_state.company = {
        "legal_name": "",
        "dba": "",
        "uei": "",
        "cage": "",
        "address": "",
        "poc_name": "",
        "poc_email": "",
        "poc_phone": "",
        "certifications": [],
        "naics": "",
        "capabilities": "",
        "past_performance": "",
    }

if "rfp_text" not in st.session_state:
    st.session_state.rfp_text = ""

if "rfp_intel" not in st.session_state:
    st.session_state.rfp_intel = None

if "rfp_rules" not in st.session_state:
    st.session_state.rfp_rules = None

# =========================
# Navigation
# =========================

st.sidebar.title("Path")
page = st.sidebar.radio("Go to", ["RFP Intake", "Company Info", "Proposal Output"])
st.sidebar.caption("Tip: Build this in small steps. You're doing great.")

# =========================
# Page: RFP Intake
# =========================

if page == "RFP Intake":
    st.title("1) RFP Intake")

    uploaded_file = st.file_uploader("Upload RFP (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"])

    rfp_text = st.session_state.rfp_text

    if uploaded_file:
        name = uploaded_file.name.lower()
        data = uploaded_file.read()
        if name.endswith(".pdf"):
            rfp_text = extract_text_from_pdf(data)
        elif name.endswith(".docx"):
            rfp_text = extract_text_from_docx(data)
        else:
            rfp_text = data.decode("utf-8", errors="ignore")

    rfp_text = st.text_area("Or paste RFP / RFI text", value=rfp_text, height=320)

    if st.button("Analyze"):
        if not rfp_text.strip():
            st.warning("Please upload or paste an RFP first.")
        else:
            st.session_state.rfp_text = rfp_text

            # NEW: create intelligence on analyze
            intel = detect_forms_and_attachments(rfp_text)
            rules = detect_submission_rules(rfp_text)

            st.session_state.rfp_intel = intel
            st.session_state.rfp_rules = rules

            st.success("Analysis saved. Go to 'Proposal Output' to see the checklist + warnings.")

    st.markdown("---")
    st.subheader("Quick Stats (preview)")
    st.write("Characters:", safe_len(rfp_text))
    st.write("First 300 chars:")
    st.code((rfp_text[:300] if rfp_text else ""), language="text")

# =========================
# Page: Company Info
# =========================

elif page == "Company Info":
    st.title("2) Company Info")
    st.caption("Fill this out once. We will reuse it for every proposal.")

    c = st.session_state.company

    colA, colB = st.columns(2)

    with colA:
        c["legal_name"] = st.text_input("Legal Company Name", value=c["legal_name"])
        c["dba"] = st.text_input("DBA (optional)", value=c["dba"])
        c["uei"] = st.text_input("UEI", value=c["uei"])
        c["cage"] = st.text_input("CAGE (optional)", value=c["cage"])
        c["naics"] = st.text_input("Primary NAICS (optional)", value=c["naics"])

    with colB:
        c["address"] = st.text_area("Business Address", value=c["address"], height=120)
        c["poc_name"] = st.text_input("Point of Contact Name", value=c["poc_name"])
        c["poc_email"] = st.text_input("Point of Contact Email", value=c["poc_email"])
        c["poc_phone"] = st.text_input("Point of Contact Phone", value=c["poc_phone"])

    st.markdown("### Certifications / Socioeconomic Status")
    options = ["SDVOSB", "VOSB", "8(a)", "WOSB/EDWOSB", "HUBZone", "SBA Small Business", "ISO 9001", "None"]
    selected = st.multiselect("Select all that apply", options=options, default=c.get("certifications", []))
    c["certifications"] = selected

    st.markdown("### Capabilities Statement (short)")
    c["capabilities"] = st.text_area("One paragraph describing what you do", value=c["capabilities"], height=140)

    st.markdown("### Past Performance (starter)")
    st.caption("If you have none, write what you HAVE done (commercial work, internal projects, subcontract work).")
    c["past_performance"] = st.text_area("Paste past performance notes", value=c["past_performance"], height=160)

    st.session_state.company = c

    st.markdown("---")
    colS1, colS2 = st.columns([1, 1])

    with colS1:
        if st.button("Download Company Info (JSON backup)"):
            backup = json.dumps(st.session_state.company, indent=2)
            st.download_button(
                label="Click to download",
                data=backup,
                file_name="company_profile.json",
                mime="application/json"
            )

    with colS2:
        uploaded_profile = st.file_uploader("Upload Company Info (JSON)", type=["json"])
        if uploaded_profile:
            try:
                loaded = json.loads(uploaded_profile.read().decode("utf-8"))
                if isinstance(loaded, dict):
                    st.session_state.company.update(loaded)
                    st.success("Loaded company profile.")
                else:
                    st.error("That JSON file doesn't look like a company profile.")
            except Exception as e:
                st.error(f"Could not load JSON: {e}")

# =========================
# Page: Proposal Output
# =========================

else:
    st.title("3) Proposal Output")

    rfp_text = st.session_state.rfp_text
    c = st.session_state.company

    if not rfp_text.strip():
        st.warning("No RFP saved yet. Go to 'RFP Intake' and click Analyze.")
        st.stop()

    # If user pasted RFP but never clicked Analyze, compute intel on the fly
    intel = st.session_state.rfp_intel or detect_forms_and_attachments(rfp_text)
    rules = st.session_state.rfp_rules or detect_submission_rules(rfp_text)

    # NEW SECTION: Submission rules found
    st.subheader("A) Submission Rules Found (starter)")
    if rules:
        for label, lines in rules.items():
            with st.expander(label, expanded=False):
                for ln in lines:
                    st.write("•", ln)
    else:
        st.write("No obvious submission rules detected yet (uploading the PDF usually works better than copy/paste).")

    st.markdown("---")

    # NEW SECTION: Forms & Attachments
    st.subheader("B) Forms & Attachments Detected (starter)")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Forms (SF/DD) Found**")
        if intel["forms"]:
            for f in intel["forms"]:
                st.write("•", f)
        else:
            st.write("No SF/DD forms detected.")

    with col2:
        st.markdown("**Amendments / Mods referenced**")
        if intel["amendment_lines"]:
            for a in intel["amendment_lines"][:15]:
                st.write("•", a)
            if len(intel["amendment_lines"]) > 15:
                st.caption(f"Showing 15 of {len(intel['amendment_lines'])}")
        else:
            st.write("No amendments detected.")

    st.markdown("**Attachment / Appendix / Exhibit lines**")
    if intel["attachments_lines"]:
        for a in intel["attachments_lines"][:25]:
            st.write("•", a)
        if len(intel["attachments_lines"]) > 25:
            st.caption(f"Showing 25 of {len(intel['attachments_lines'])}")
    else:
        st.write("No obvious attachment references detected.")

    st.markdown("---")

    # NEW SECTION: Compliance warnings
    st.subheader("C) Compliance Warnings (action items)")
    warnings = generate_compliance_warnings(rfp_text, intel, rules)
    for w in warnings:
        st.warning(w)

    if intel["separate_submit_lines"]:
        st.markdown("### Items that look like they must be completed/submitted separately")
        for ln in intel["separate_submit_lines"][:25]:
            st.write("•", ln)
        if len(intel["separate_submit_lines"]) > 25:
            st.caption(f"Showing 25 of {len(intel['separate_submit_lines'])}")

    st.markdown("---")
    st.subheader("D) Company Profile Snapshot")
    st.write("**Legal Name:**", c.get("legal_name") or "—")
    st.write("**UEI:**", c.get("uei") or "—")
    st.write("**POC:**", c.get("poc_name") or "—", "|", c.get("poc_email") or "—", "|", c.get("poc_phone") or "—")
    st.write("**Certifications:**", ", ".join(c.get("certifications", [])) or "—")
    st.write("**Capabilities:**")
    st.info(c.get("capabilities") or "—")

    st.markdown("---")
    st.subheader("E) Draft Skeleton (starter)")
    outline = f"""
1. Cover Letter
   - Company: {c.get("legal_name") or "[Company Name]"}
   - UEI: {c.get("uei") or "[UEI]"}
   - Point of Contact: {c.get("poc_name") or "[POC]"} ({c.get("poc_email") or "[email]"})
   - Certifications: {", ".join(c.get("certifications", [])) or "[certifications]"}

2. Executive Summary
   - We understand the requirement and will deliver on time and within scope.

3. Technical Approach
   - [Add approach aligned to the SOW / PWS]

4. Management Plan
   - [Staffing, schedule, risk management]

5. Past Performance
   - {c.get("past_performance")[:500] + ("..." if safe_len(c.get("past_performance")) > 500 else "") if c.get("past_performance") else "[Add past performance or narrative]"}

6. Compliance Checklist
   - Confirm all amendments acknowledged.
   - Confirm all required forms are signed/filled.
   - Confirm formatting rules (page limit / font / margins).
   - Confirm submission method and deadline.
"""
    st.code(outline, language="text")

    st.markdown("---")
    st.subheader("F) RFP Preview (first 1,500 chars)")
    st.code(rfp_text[:1500], language="text")