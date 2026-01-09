import io
import json
import re
import streamlit as st
from pypdf import PdfReader
import docx

st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")

# =========================
# Helpers
# =========================

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def extract_text_from_docx(file_bytes: bytes) -> str:
    document = docx.Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in document.paragraphs)

def find_attachments(text: str):
    """
    Simple attachment/form detector (starter version).
    We will improve this later.
    """
    keywords = [
        "attachment", "attachments",
        "appendix", "appendices",
        "exhibit", "exhibits",
        "annex", "enclosure",
        "sf-1449", "sf 1449",
        "sf-33", "sf 33",
        "sf-30", "sf 30",
        "sf-18", "sf 18",
        "dd-1155", "dd 1155",
        "reps and certs", "representations and certifications",
        "price schedule", "pricing", "cost proposal",
        "signature", "signed",
        "fill out", "complete and return",
        "amendment", "amendments"
    ]

    results = []
    for line in text.splitlines():
        clean = line.strip()
        if not clean:
            continue
        low = clean.lower()
        if any(k in low for k in keywords):
            # avoid super long lines
            results.append(clean[:300])
    # de-dup while keeping order
    seen = set()
    deduped = []
    for r in results:
        if r not in seen:
            seen.add(r)
            deduped.append(r)
    return deduped

def safe_len(s: str) -> int:
    return len(s) if s else 0

# =========================
# App State (saved per user browser session)
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
        "certifications": [],   # list of strings
        "naics": "",
        "capabilities": "",
        "past_performance": "", # simple text for now
    }

if "rfp_text" not in st.session_state:
    st.session_state.rfp_text = ""

# =========================
# Sidebar Navigation
# =========================

st.sidebar.title("Path")
page = st.sidebar.radio("Go to", ["1) RFP Intake", "2) Company Info", "3) Proposal Output"])

st.sidebar.caption("Tip: Build this in small steps. You're doing great.")

# =========================
# Page 1: RFP Intake
# =========================

if page == "1) RFP Intake":
    st.title("1) RFP Intake")

    uploaded_file = st.file_uploader("Upload RFP (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"])

    rfp_text = st.session_state.rfp_text

    if uploaded_file:
        if uploaded_file.name.lower().endswith(".pdf"):
            rfp_text = extract_text_from_pdf(uploaded_file.read())
        elif uploaded_file.name.lower().endswith(".docx"):
            rfp_text = extract_text_from_docx(uploaded_file.read())
        else:
            rfp_text = uploaded_file.read().decode("utf-8", errors="ignore")

    rfp_text = st.text_area("Or paste RFP / RFI text", value=rfp_text, height=320)

    col1, col2 = st.columns([1, 3])
    with col1:
        analyze = st.button("Analyze")
    with col2:
        st.write("")

    if analyze:
        if not rfp_text.strip():
            st.warning("Please upload or paste an RFP first.")
        else:
            st.session_state.rfp_text = rfp_text
            st.success("Saved. Go to '3) Proposal Output' to see results.")

    st.markdown("---")
    st.subheader("Quick Stats (preview)")
    st.write("Characters:", safe_len(rfp_text))
    st.write("First 300 chars:")
    st.code((rfp_text[:300] if rfp_text else ""), language="text")

# =========================
# Page 2: Company Info
# =========================

elif page == "2) Company Info":
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
    c["capabilities"] = st.text_area(
        "One paragraph describing what you do (we'll improve formatting later)",
        value=c["capabilities"],
        height=140
    )

    st.markdown("### Past Performance (starter)")
    st.caption("If you have none, just write what you *have done* (commercial work, internal projects, subcontract work).")
    c["past_performance"] = st.text_area("Paste past performance notes", value=c["past_performance"], height=160)

    # Save to session_state
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
                    st.success("Loaded company profile. You're good.")
                else:
                    st.error("That JSON file doesn't look like a company profile.")
            except Exception as e:
                st.error(f"Could not load JSON: {e}")

# =========================
# Page 3: Proposal Output
# =========================

else:
    st.title("3) Proposal Output")

    rfp_text = st.session_state.rfp_text
    c = st.session_state.company

    if not rfp_text.strip():
        st.warning("No RFP saved yet. Go to '1) RFP Intake' and click Analyze.")
        st.stop()

    st.subheader("A) Attachment / Form Checklist (starter)")
    attachments = find_attachments(rfp_text)

    if attachments:
        st.write("These lines look like they reference attachments/forms/amendments:")
        for a in attachments[:40]:
            st.write("•", a)
        if len(attachments) > 40:
            st.caption(f"Showing 40 of {len(attachments)} matches.")
    else:
        st.write("No obvious attachment references detected yet (we’ll improve this).")

    st.markdown("---")
    st.subheader("B) Company Profile Snapshot")
    st.write("**Legal Name:**", c.get("legal_name") or "—")
    st.write("**UEI:**", c.get("uei") or "—")
    st.write("**POC:**", c.get("poc_name") or "—", "|", c.get("poc_email") or "—", "|", c.get("poc_phone") or "—")
    st.write("**Certifications:**", ", ".join(c.get("certifications", [])) or "—")
    st.write("**Capabilities:**")
    st.info(c.get("capabilities") or "—")

    st.markdown("---")
    st.subheader("C) Draft Skeleton (starter)")
    st.caption("This is a starter proposal outline. Next we’ll make it match Section L/M and generate better content.")

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
   - Attachments/Forms: {len(attachments)} potential references detected.
   - Confirm all amendments acknowledged.
   - Confirm submission format (PDF, page limits, font, margins, etc).
"""
    st.code(outline, language="text")

    st.markdown("---")
    st.subheader("D) RFP Preview (first 1,500 chars)")
    st.code(rfp_text[:1500], language="text")