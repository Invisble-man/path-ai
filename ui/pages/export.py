from __future__ import annotations

import streamlit as st

from core.state import get_rfp, get_company, set_current_step
from core.scoring import compute_scores
from exporters.docx_export import build_docx
from exporters.excel_export import build_matrix_xlsx
from ui.components import section_header, warn_box, ok_box


def render() -> None:
    st.title("Export")
    st.markdown("<div class='path-muted'>Export is always unlocked.</div>", unsafe_allow_html=True)

    section_header("Downloads", "Step 6 of 6")

    rfp = get_rfp()
    company = get_company()
    compute_scores()

    # Always allow exports, but warn if missing
    warnings = []
    if not (rfp.extracted and rfp.text.strip()):
        warnings.append("No RFP uploaded yet. Exports will be mostly empty.")
    if not company.name.strip():
        warnings.append("Company name missing. Cover page will be generic.")
    if warnings:
        warn_box("<br/>".join(warnings))
    else:
        ok_box("Ready to export.")

    compatibility_rows = st.session_state.get("compatibility_rows", []) or []
    cover = st.session_state.get("draft_cover_letter", "")
    body = st.session_state.get("draft_body", "")

    # Build files
    docx_bytes = build_docx(
        rfp=rfp.to_dict(),
        company=company.to_dict(),
        draft_cover_letter=cover,
        draft_body=body,
        compatibility_rows=compatibility_rows,
    )
    xlsx_bytes = build_matrix_xlsx(compatibility_rows)

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download Proposal (DOCX)",
            data=docx_bytes,
            file_name="PathAI_Proposal.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
            type="primary",
        )

    with col2:
        st.download_button(
            "Download Compatibility Matrix (XLSX)",
            data=xlsx_bytes,
            file_name="PathAI_Compatibility_Matrix.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.write("")
    if st.button("Back to Dashboard", use_container_width=True):
        set_current_step("dashboard")
        st.rerun()