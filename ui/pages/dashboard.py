from __future__ import annotations

import streamlit as st

from core.state import get_rfp, set_current_step
from core.scoring import compute_scores
from ui.components import section_header, walking_progress, warn_box, ok_box, badge, evaluator_panel


def render() -> None:
    rfp = get_rfp()
    scores = compute_scores()

    st.title("Dashboard")
    st.markdown("<div class='path-muted'>You’re on the right path to success.</div>", unsafe_allow_html=True)
    st.write("")
    badge("Readiness Console")

    section_header("Overview", "Step 2 of 5")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        walking_progress("Progress", scores["progress_pct"], "Overall completion across required inputs.")
    with c2:
        walking_progress("Compliance", scores["compliance_pct"], "Submission readiness compliance (no mapping).")
    with c3:
        walking_progress("Win Probability", scores["win_probability_pct"], "Heuristic estimate (not a guarantee).")
    with c4:
        st.markdown("### Grade")
        st.markdown(
            f"<div style='font-size:54px; font-weight:900; line-height:1;'>{scores['grade']}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div class='path-muted'>Based on compliance.</div>", unsafe_allow_html=True)

    st.write("")
    section_header("Diagnostics")

    diagnostics = st.session_state.get("diagnostics", {"passed": [], "missing": []})
    flags = st.session_state.get("eligibility_flags", []) or []

    left, right = st.columns(2)
    with left:
        passed = diagnostics.get("passed", [])
        if passed:
            ok_box("<b>Good:</b><br/>" + "<br/>".join(passed))
        else:
            ok_box("No readiness checks passed yet. Start by uploading an RFP.")

    with right:
        missing = diagnostics.get("missing", [])
        issues_lines = []
        for label, hint in missing:
            issues_lines.append(f"<b>{label}</b><br/><span class='path-muted'>{hint}</span>")
        issues_lines.extend([f"<b>{f}</b>" for f in flags])

        if issues_lines:
            warn_box("<br/><br/>".join(issues_lines))
        else:
            ok_box("No issues detected so far.")

    st.write("")
    section_header("Next Step")
    if not (rfp.extracted and (rfp.text or "").strip()):
        warn_box("Upload and analyze an RFP to unlock meaningful diagnostics.")
        if st.button("Go to Upload RFP", type="primary", use_container_width=True):
            set_current_step("home")
            st.rerun()
        return

    if st.button("Continue to Company Info", type="primary", use_container_width=True):
        set_current_step("company")
        st.rerun()