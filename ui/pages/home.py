from __future__ import annotations

import streamlit as st

from core.rfp import parse_rfp_from_pdf_bytes, extract_fields_from_text
from core.state import get_rfp, set_rfp, set_current_step, mark_complete
from ui.components import section_header, warn_box, ok_box, badge


def render() -> None:
    st.title("Path.AI")
    st.markdown("<div class='path-muted'>Upload your RFP/RFI → Analyze → proceed step-by-step.</div>", unsafe_allow_html=True)
    st.write("")

    badge("Upload Center")
    section_header("Upload RFP", "Step 1 of 5")

    rfp = get_rfp()

    uploaded = st.file_uploader("Upload PDF (RFP/RFI)", type=["pdf"], accept_multiple_files=False)

    st.write("")
    st.caption("If your PDF is scanned and text extraction fails, you can paste the RFP text below as a fallback.")

    pasted_text = st.text_area("Paste RFP text (optional fallback)", value="", height=160)

    analyze = st.button("Analyze", type="primary", use_container_width=True)

    if analyze:
        if uploaded is None and not pasted_text.strip():
            warn_box("Upload a PDF or paste RFP text to analyze.")
            return

        # Build bytes and filename
        pdf_bytes = uploaded.getvalue() if uploaded is not None else None
        filename = uploaded.name if uploaded is not None else "Pasted_RFP_Text"

        pages_total = 0
        text = ""

        if pdf_bytes:
            with st.spinner("Reading PDF and extracting text..."):
                pages_total, text = parse_rfp_from_pdf_bytes(pdf_bytes, max_pages_to_read=60)

        if not text.strip() and pasted_text.strip():
            text = pasted_text.strip()

        fields = extract_fields_from_text(text)

        # Update state
        rfp.filename = filename
        rfp.pdf_bytes = pdf_bytes
        rfp.pages = pages_total
        rfp.text = text
        rfp.extracted = bool(text.strip())
        rfp.due_date = fields.get("due_date", "") or ""
        rfp.submission_email = fields.get("submission_email", "") or ""
        rfp.certifications_required = fields.get("certifications_required", []) or []
        rfp.naics = fields.get("naics", "") or ""

        set_rfp(rfp)
        mark_complete("home")

        # Diagnostics window
        with st.expander("Diagnostics (what Path.AI sees)", expanded=True):
            st.json(
                {
                    "filename": rfp.filename,
                    "pages_detected": rfp.pages,
                    "text_length": len(rfp.text or ""),
                    "extracted": rfp.extracted,
                    "due_date": rfp.due_date,
                    "submission_email": rfp.submission_email,
                    "certs_detected": rfp.certifications_required,
                    "naics_detected": rfp.naics,
                }
            )

        if not rfp.extracted:
            warn_box("No extractable text found. This PDF may be scanned/image-based. Use the paste-text fallback.")
            return

        ok_box("Analysis complete. Proceeding to Dashboard.")
        set_current_step("dashboard")
        st.rerun()