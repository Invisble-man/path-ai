from __future__ import annotations

import streamlit as st

from core.state import get_rfp, get_company, set_current_step
from core.ai import generate_proposal_draft, has_openai_key
from core.scoring import compute_scores
from ui.components import section_header, warn_box, badge


def render() -> None:
    rfp = get_rfp()
    company = get_company()

    st.title("Draft Proposal")
    st.markdown("<div class='path-muted'>Generate a clean proposal draft synced to your RFP and company profile.</div>", unsafe_allow_html=True)

    section_header("Draft Generator", "Step 4 of 6")

    if not (rfp.extracted and rfp.text.strip()):
        warn_box("Upload and analyze an RFP first.")
        if st.button("Go to Upload RFP", type="primary"):
            set_current_step("home")
            st.rerun()
        return

    if not company.name.strip():
        warn_box("Company name is missing. You can still draft, but your cover page/letter will be generic.")

    if not (company.uei.strip() or company.cage.strip()):
        warn_box("UEI/CAGE missing. Not blocking, but your proposal will look incomplete.")

    st.write("")
    badge("AI is optional • App runs without a key")

    colA, colB = st.columns([1, 1])
    with colA:
        st.markdown(f"**AI Status:** {'Enabled' if has_openai_key() else 'Disabled (no key found)'}")
    with colB:
        st.markdown(f"**RFP file:** {rfp.filename}")

    st.write("")
    if st.button("Generate / Refresh Draft", type="primary", use_container_width=True):
        with st.spinner("Generating draft..."):
            result = generate_proposal_draft(rfp.text, company.to_dict())
            st.session_state.draft_cover_letter = result["cover_letter"]
            st.session_state.draft_body = result["proposal_body"]
            compute_scores()
            st.success("Draft generated.")

    cover = st.session_state.get("draft_cover_letter", "")
    body = st.session_state.get("draft_body", "")

    st.write("")
    section_header("Cover Letter")
    st.session_state.draft_cover_letter = st.text_area("Edit cover letter", value=cover, height=260)

    st.write("")
    section_header("Proposal Body")
    st.session_state.draft_body = st.text_area("Edit proposal body", value=body, height=520)

    st.write("")
    if st.button("Continue to Compatibility Matrix", type="primary", use_container_width=True):
        set_current_step("compatibility")
        st.rerun()