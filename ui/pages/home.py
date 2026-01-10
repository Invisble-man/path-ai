from __future__ import annotations

import streamlit as st

from core.state import get_rfp, set_rfp, set_current_step, RFPData
from core.rfp import parse_rfp_from_pdf_bytes
from core.scoring import compute_all_scores
from ui.components import badge, warn_box, section_header


def render() -> None:
    # Minimal “Google-like” center layout
    st.title("Path.AI")
    st.markdown("<div class='path-muted'>Upload an RFP/RFI PDF → Analyze → build your proposal step-by-step.</div>", unsafe_allow_html=True)

    st.write("")
    badge("TurboTax-style guided flow • Export always unlocked")

    st.write("")
    section_header("Upload RFP", "Step 1 of 6")

    # Center the upload box
    left, center, right = st.columns([1, 2, 1])
    with center:
        uploaded = st.file_uploader(
            "Drag & drop your PDF here",
            type=["pdf"],
            accept_multiple_files=False,
            label_visibility="visible",
        )

        rfp_state = get_rfp()

        analyze = st.button("Analyze", type="primary", use_container_width=True, disabled=(uploaded is None))

        if analyze and uploaded is not None:
            with st.spinner("Extracting text and analyzing the RFP..."):
                pdf_bytes = uploaded.getvalue()
                parsed = parse_rfp_from_pdf_bytes(pdf_bytes)

                new_rfp = RFPData(
                    filename=uploaded.name,
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

                # Initialize compatibility rows from requirements (if any)
                if parsed.requirements:
                    st.session_state.compatibility_rows = [
                        {"requirement": r, "response": "", "status": "Missing"} for r in parsed.requirements
                    ]
                else:
                    st.session_state.compatibility_rows = []

                compute_all_scores()
                set_current_step("dashboard")
                st.rerun()

        # Show last uploaded info if exists
        if rfp_state.filename:
            st.write("")
            st.markdown(f"**Current file:** {rfp_state.filename}")
            st.markdown(f"**Pages detected:** {rfp_state.pages}")

            if rfp_state.flags:
                st.write("")
                warn_box(" / ".join(rfp_state.flags))