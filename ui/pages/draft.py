from __future__ import annotations

import streamlit as st

from core.scoring import compute_scores
from ui.components import ui_notice


def page_draft():
    ss = st.session_state

    st.markdown("## Draft Proposal")
    st.caption("Build your cover page, outline, and narrative. Path.ai scores and flags issues inline.")

    # Compute live scores
    scores = compute_scores(ss)

    # --- Eligibility + compliance warnings (inline, not blocking) ---
    warnings = scores.get("warnings", []) or []
    for w in warnings:
        st.warning(w)

    draft = ss.get("draft", {}) or {}
    company = ss.get("company", {}) or {}

    # --- Cover Page ---
    st.markdown("### Cover Page")

    left, right = st.columns([0.7, 1.3], gap="large")

    with left:
        if company.get("logo_bytes"):
            st.image(company["logo_bytes"], width=200)
        else:
            st.info("Upload a logo in Company Info to show it here.")

    with right:
        c1, c2 = st.columns(2)
        with c1:
            draft["cover_title"] = st.text_input("Proposal Title", value=draft.get("cover_title", ""))
            draft["cover_contract"] = st.text_input("Contract / Opportunity Name", value=draft.get("cover_contract", ""))
            draft["cover_solicitation"] = st.text_input("Solicitation #", value=draft.get("cover_solicitation", ""))
        with c2:
            draft["cover_agency"] = st.text_input("Agency", value=draft.get("cover_agency", ""))
            draft["cover_due_date"] = st.text_input("Due Date", value=draft.get("cover_due_date", ""))

    st.markdown("---")

    # --- AI Drafting Control ---
    st.markdown("### AI Drafting")

    if not ss.get("ai_enabled"):
        st.info("AI is currently OFF. Enable it in the sidebar when your API key is configured.")

    colA, colB = st.columns([1, 1])

    with colA:
        if st.button("Generate Draft Sections (AI)", use_container_width=True, disabled=not ss.get("ai_enabled")):
            # Stub: you will wire this to core.ai later
            draft.setdefault("outline", "AI outline will appear here.")
            draft.setdefault("narrative", "AI-generated narrative will appear here.")
            ui_notice("AI DRAFT", "Draft sections generated.", tone="good")

    with colB:
        if st.button("Clear Draft", use_container_width=True):
            ss["draft"] = {
                "cover_title": "",
                "cover_contract": "",
                "cover_solicitation": "",
                "cover_agency":