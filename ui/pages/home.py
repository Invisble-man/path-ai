from __future__ import annotations

import streamlit as st
from core.rfp import extract_rfp_text
from ui.components import ui_notice, render_readiness_console


def page_home():
    st.markdown("## You’re on the right path to success.")
    st.caption("Upload an RFP/RFI, analyze it, and Path.ai will guide you step by step.")

    ss = st.session_state

    col1, col2 = st.columns([1.2, 0.8], gap="large")

    with col1:
        uploaded = st.file_uploader(
            "Upload RFP (PDF or TXT)",
            type=["pdf", "txt"],
            accept_multiple_files=False,
        )

        pasted = st.text_area(
            "Or paste RFP text",
            height=200,
            placeholder="Paste solicitation text here if PDF extraction fails.",
        )

        analyze_clicked = st.button("Analyze", use_container_width=True)

    with col2:
        if ss.get("rfp_text"):
            st.markdown("### Diagnostics")

            st.metric("File", ss.get("rfp_filename") or "—")
            st.metric("Pages (est.)", ss.get("rfp_pages") or 0)
            st.metric("Characters", len(ss.get("rfp_text") or ""))

            meta = ss.get("rfp_meta", {}) or {}
            st.markdown("#### Key Fields")
            st.write("**Title:**", meta.get("title") or "—")
            st.write("**Solicitation:**", meta.get("solicitation") or "—")
            st.write("**Agency:**", meta.get("agency") or "—")
            st.write("**Due Date:**", meta.get("due_date") or "—")
            st.write("**Submit Email:**", meta.get("submit_email") or "—")

    if analyze_clicked:
        # Priority: pasted text overrides file
        if pasted and pasted.strip():
            ss["rfp_text"] = pasted.strip()
            ss["rfp_filename"] = "Pasted Text"
            ss["rfp_pages"] = max(1, len(ss["rfp_text"]) // 1800)
            ss["current_page"] = "Company Info"
            ui_notice("ANALYZED", "RFP text loaded from pasted content.", tone="good")
            st.rerun()

        if not uploaded:
            ui_notice("MISSING INPUT", "Upload a file or paste text first.", tone="bad")
            st.stop()

        data = extract_rfp_text(uploaded)

        text = (data.get("text") or "").strip()
        if not text:
            ui_notice("ERROR", "Could not extract readable text. Try pasting it manually.", tone="bad")
            st.stop()

        ss["rfp_text"] = text
        ss["rfp_pages"] = int(data.get("pages") or 0)
        ss["rfp_filename"] = data.get("filename") or "Uploaded File"

        # Stub meta fields (AI can later enhance these)
        ss["rfp_meta"] = {
            "title": "",
            "solicitation": "",
            "agency": "",
            "due_date": "",
            "submit_email": "",
            "submission_method": "",
        }

        ss["current_page"] = "Company Info"
        ui_notice("ANALYZED", "RFP successfully analyzed.", tone="good")
        st.rerun()

    st.markdown("---")
    render_readiness_console(st.session_state.get("scores", {}))