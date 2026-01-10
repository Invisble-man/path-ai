from __future__ import annotations

import streamlit as st

from ui.components import ui_notice
from exporters.excel_export import build_compatibility_matrix_xlsx
from exporters.docx_export import build_proposal_docx


def page_export():
    ss = st.session_state

    st.markdown("## Export")
    st.caption("Exports are always unlocked. Download your Compatibility Matrix and Proposal Package.")

    rfp_text = ss.get("rfp_text", "") or ""
    company = ss.get("company", {}) or {}
    draft = ss.get("draft", {}) or {}
    meta = ss.get("rfp_meta", {}) or {}

    if not rfp_text.strip():
        ui_notice("MISSING RFP", "Go back to Upload RFP and analyze a file first.", tone="warn")
        st.stop()

    if not company.get("legal_name") and not company.get("uei"):
        ui_notice("WEAK COMPANY INFO", "Company Info is mostly blank. Export still works, but your proposal will be thin.", tone="warn")

    if not (draft.get("outline") or "").strip() and not (draft.get("narrative") or "").strip():
        ui_notice("WEAK DRAFT", "Draft content is mostly blank. Export still works, but output will be minimal.", tone="warn")

    st.markdown("---")

    # Build files
    try:
        xlsx_bytes = build_compatibility_matrix_xlsx(
            rfp_text=rfp_text,
            company=company,
            meta=meta,
        )
    except Exception as e:
        xlsx_bytes = None
        ui_notice("MATRIX ERROR", f"Could not build compatibility matrix: {e}", tone="bad")

    try:
        docx_bytes = build_proposal_docx(
            company=company,
            meta=meta,
            draft=draft,
        )
    except Exception as e:
        docx_bytes = None
        ui_notice("DOCX ERROR", f"Could not build DOCX: {e}", tone="bad")

    c1, c2 = st.columns([1, 1], gap="large")

    with c1:
        st.markdown("### Compatibility Matrix (XLSX)")
        st.caption("Tracks requirements → response mapping → status → notes.")
        if xlsx_bytes:
            st.download_button(
                "Download Compatibility Matrix",
                data=xlsx_bytes,
                file_name="PathAI_Compatibility_Matrix.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.info("Matrix not available yet (error above).")

    with c2:
        st.markdown("### Proposal Package (DOCX)")
        st.caption("Cover page + cover letter + outline + narrative.")
        if docx_bytes:
            st.download_button(
                "Download Proposal Package",
                data=docx_bytes,
                file_name="PathAI_Proposal_Package.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        else:
            st.info("DOCX not available yet (error above).")

    st.markdown("---")
    if st.button("Back to Draft Proposal", use_container_width=True):
        ss["current_page"] = "Draft Proposal"
        st.rerun()