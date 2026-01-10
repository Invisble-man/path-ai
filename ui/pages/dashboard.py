from __future__ import annotations

import streamlit as st

from core.state import get_rfp, set_current_step
from core.scoring import compute_all_scores
from ui.components import section_header, walking_progress, warn_box, ok_box, badge


def render() -> None:
    rfp = get_rfp()
    scores = compute_all_scores()

    st.title("Dashboard")
    st.markdown("<div class='path-muted'>You’re on the right path to success.</div>", unsafe_allow_html=True)
    st.write("")
    badge("Readiness Console")

    # Debug snapshot (helps you instantly see what's missing)
    with st.expander("Debug snapshot (what the app sees)", expanded=False):
        st.write(
            {
                "rfp.filename": rfp.filename,
                "rfp.pages": rfp.pages,
                "rfp.extracted": rfp.extracted,
                "rfp.text_length": len(rfp.text or ""),
                "has_rfp_file_bytes": "rfp_file_bytes" in st.session_state,
            }
        )

    if not (rfp.extracted and (rfp.text or "").strip()):
        warn_box(
            "Dashboard can’t find extracted RFP text. "
            "This usually means the PDF is scanned/image-based or extraction failed. "
            "Go back to Upload RFP and try another PDF."
        )
        if st.button("Go to Upload RFP", type="primary"):
            set_current_step("home")
            st.rerun()
        return

    section_header("Readiness Overview", "Step 2 of 6")

    c1, c2, c3 = st.columns(3)
    with c1:
        walking_progress("Compliance", scores["compliance_pct"], "Based on your Compatibility Matrix.")
    with c2:
        walking_progress("Completion", scores["completion_pct"], "Based on how much info is filled out.")
    with c3:
        walking_progress("Win Probability", scores["win_probability_pct"], "Heuristic estimate (not a guarantee).")

    st.write("")
    section_header("RFP Snapshot")

    left, right = st.columns([2, 1])
    with left:
        st.markdown(f"**File:** {rfp.filename}")
        st.markdown(f"**Pages:** {rfp.pages}")
        st.markdown(f"**Due date detected:** {rfp.due_date or 'Not detected'}")
        st.markdown(f"**Submission email detected:** {rfp.submission_email or 'Not detected'}")

        if rfp.certifications_required:
            st.markdown(f"**Certifications mentioned:** {', '.join(rfp.certifications_required)}")
        else:
            st.markdown("**Certifications mentioned:** None detected")

    with right:
        flags = st.session_state.get("eligibility_flags", []) or []
        if flags:
            warn_box("<br/>".join(flags))
        else:
            ok_box("No eligibility warnings detected so far.")

    st.write("")
    section_header("Next Step")
    if st.button("Continue to Company Info", type="primary", use_container_width=True):
        set_current_step("company")
        st.rerun()