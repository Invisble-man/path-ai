from __future__ import annotations

import streamlit as st

from core.analyze import analyze_pdf
from core.state import RFPData, get_rfp, set_rfp, set_current_step
from core.scoring import compute_all_scores
from ui.components import section_header, warn_box


def render() -> None:
    st.title("Path.AI")
    st.markdown(
        "<div class='path-muted'>Upload your RFP/RFI → Analyze → proceed step-by-step.</div>",
        unsafe_allow_html=True,
    )

    section_header("Upload RFP", "Step 1 of 6")

    left, center, right = st.columns([1, 2, 1])
    with center:
        uploaded = st.file_uploader(
            "Upload RFP/RFI (PDF)",
            type=["pdf"],
            accept_multiple_files=False,
        )

        # Sampling control (prevents 502 on huge PDFs)
        max_pages = st.slider(
            "Pages to analyze (sample)",
            min_value=5,
            max_value=60,
            value=25,
            help="Large PDFs should use lower values to stay fast/stable.",
        )

        if uploaded is not None:
            st.session_state["rfp_file_name"] = uploaded.name
            st.session_state["rfp_file_bytes"] = uploaded.getvalue()

        analyze_disabled = "rfp_file_bytes" not in st.session_state
        analyze = st.button("Analyze", type="primary", use_container_width=True, disabled=analyze_disabled)

        if analyze and not analyze_disabled:
            with st.spinner("Analyzing RFP..."):
                pdf_bytes = st.session_state["rfp_file_bytes"]
                file_name = st.session_state.get("rfp_file_name", "uploaded.pdf")

                parsed, pdf_hash = analyze_pdf(pdf_bytes, max_pages_to_read=max_pages)

                # Store into canonical RFP state
                new_rfp = RFPData(
                    filename=file_name,
                    pages=parsed.pages,
                    text=parsed.text,
                    extracted=True,
                    due_date=parsed.due_date,
                    submission_email=parsed.submission_email,
                    certifications_required=parsed.certifications_required,
                    eligibility_rules=parsed.eligibility_rules,
                    past_performance_requirements=parsed.past_performance_requirements,
                    requirements=parsed.requirements,
                    flags=parsed.flags,
                )
                set_rfp(new_rfp)

                # Store meta for later
                st.session_state["rfp_pdf_hash"] = pdf_hash
                st.session_state["rfp_sample_pages"] = max_pages
                st.session_state["rfp_text_length"] = len(parsed.text or "")

                # Seed compatibility rows from requirements
                if parsed.requirements:
                    st.session_state.compatibility_rows = [
                        {"requirement": r, "response": "", "status": "Missing"} for r in parsed.requirements
                    ]
                else:
                    st.session_state.compatibility_rows = []

                compute_all_scores()

                # If we extracted requirements, send to Requirements Builder first
                if parsed.requirements:
                    set_current_step("compatibility")
                else:
                    set_current_step("dashboard")

                st.rerun()

        # Status preview
        stored = get_rfp()
        if stored.filename:
            st.write("")
            st.markdown(f"**Stored file:** {stored.filename}")
            st.markdown(f"**Pages detected:** {stored.pages}")
            st.markdown(f"**Extracted text:** {len(stored.text or '')} chars")
            if stored.flags:
                warn_box(" / ".join(stored.flags))