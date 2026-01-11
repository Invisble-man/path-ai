from __future__ import annotations

import streamlit as st

from core.state import get_rfp, set_current_step, mark_complete
from core.scoring import compute_scores
from ui.components import section_header, walking_progress, warn_box, badge, evaluator_panel


def render() -> None:
    rfp = get_rfp()
    scores = compute_scores()

    st.title("Dashboard")
    st.markdown("<div class='path-muted'>You are now on the Path to success.</div>", unsafe_allow_html=True)
    st.write("")

    badge("Readiness Console")
    section_header("Overview", "Step 2 of 5")

    if not (rfp.extracted and (rfp.text or "").strip()):
        warn_box("Dashboard can’t find extracted RFP text. Go back to Upload and analyze again (or paste text).")
        if st.button("Go to Upload", type="primary", use_container_width=True):
            set_current_step("home")
            st.rerun()
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compliance", f"{scores['compliance_pct']}%")
    c2.metric("Grade", scores["compliance_grade"])
    c3.metric("Win Probability", f"{scores['win_probability_pct']}%")
    c4.metric("Progress", f"{scores['progress_pct']}%")

    st.write("")
    walking_progress("Overall Progress", int(scores["progress_pct"]), "Complete each step to improve your score.")
    walking_progress("Compliance", int(scores["compliance_pct"]), "Evaluator-style readiness based on what’s entered.")

    # Eligibility warning (not a block)
    elig = scores.get("eligibility", {})
    if elig and not elig.get("is_eligible", True):
        with st.expander("Eligibility Warnings (not a block)", expanded=True):
            for r in elig.get("reasons", []):
                st.warning(r)

    st.write("")
    evaluator_panel(scores.get("diagnostics", {}))

    st.write("")
    if st.button("Continue to Company Info", type="primary", use_container_width=True):
        mark_complete("dashboard")
        set_current_step("company")
        st.rerun()