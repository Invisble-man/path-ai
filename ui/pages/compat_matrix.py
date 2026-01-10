from __future__ import annotations

import pandas as pd
import streamlit as st

from core.state import get_rfp, set_current_step
from core.scoring import compute_all_scores
from ui.components import section_header, warn_box


STATUS_OPTIONS = ["Met", "Partial", "Missing"]


def render() -> None:
    rfp = get_rfp()
    st.title("Compatibility Matrix")
    st.markdown("<div class='path-muted'>Map every RFP requirement → your response. This drives compliance scoring.</div>", unsafe_allow_html=True)

    section_header("Matrix", "Step 5 of 6")

    if not (rfp.extracted and rfp.text.strip()):
        warn_box("Upload and analyze an RFP first.")
        if st.button("Go to Upload RFP", type="primary"):
            set_current_step("home")
            st.rerun()
        return

    rows = st.session_state.get("compatibility_rows", []) or []
    if not rows and rfp.requirements:
        rows = [{"requirement": r, "response": "", "status": "Missing"} for r in rfp.requirements]
        st.session_state.compatibility_rows = rows

    if not rows:
        warn_box("No requirements were detected yet. You can still proceed, but compliance scoring will remain low.")
        # allow manual add
        if st.button("Add a blank requirement"):
            st.session_state.compatibility_rows = [{"requirement": "", "response": "", "status": "Missing"}]
            st.rerun()
        return

    df = pd.DataFrame(rows)
    if "requirement" not in df.columns:
        df["requirement"] = ""
    if "response" not in df.columns:
        df["response"] = ""
    if "status" not in df.columns:
        df["status"] = "Missing"

    edited = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "requirement": st.column_config.TextColumn("RFP Requirement", width="large"),
            "response": st.column_config.TextColumn("Your Response", width="large"),
            "status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, width="small"),
        },
        hide_index=True,
        height=520,
    )

    st.session_state.compatibility_rows = edited.to_dict(orient="records")
    compute_all_scores()

    st.write("")
    if st.button("Continue to Export", type="primary", use_container_width=True):
        set_current_step("export")
        st.rerun()