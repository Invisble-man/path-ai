from __future__ import annotations

import streamlit as st

from core.state import get_rfp, get_company, set_current_step, mark_complete
from exporters.docx_export import build_docx_bytes
from ui.components import section_header, warn_box, badge


def render() -> None:
    rfp = get_rfp()
    company = get_company()

    st.title("Export")
    st.markdown("<div class='path-muted'>Export is always unlocked.</div>", unsafe_allow_html=True)
    st.write("")

    badge("Export Center")
    section_header("Documents", "Step 5 of 5")

    cover = ((st.session_state.get("final_cover_letter") or "").strip()
             or (st.session_state.get("draft_cover_letter") or "").strip())
    body = ((st.session_state.get("final_body") or "").strip()
            or (st.session_state.get("draft_body") or "").strip())

    if not cover or not body:
        warn_box("No proposal content found. Go to Draft and generate + optimize first.")
        if st.button("Go to Draft", type="primary", use_container_width=True):
            set_current_step("draft")
            st.rerun()
        return

    docx_bytes = build_docx_bytes(
        rfp=rfp.__dict__,
        company=company.__dict__,
        cover_letter=cover,
        proposal_body=body,
        logo_bytes=st.session_state.get("company_logo_bytes"),
    )

    st.download_button(
        "Download Proposal (DOCX)",
        data=docx_bytes,
        file_name="PathAI_Proposal.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True,
    )

    st.write("")
    if st.button("Back to Dashboard", use_container_width=True):
        mark_complete("export")
        set_current_step("dashboard")
        st.rerun()