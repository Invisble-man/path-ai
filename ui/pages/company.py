from __future__ import annotations

import streamlit as st

from core.state import get_company, set_company, set_current_step, mark_complete
from core.scoring import compute_scores
from ui.components import section_header, warn_box, ok_box, badge


CERT_OPTIONS = ["SDVOSB", "8(a)", "WOSB", "HUBZone", "VOSB", "SDB", "ISO", "CMMC"]


def render() -> None:
    company = get_company()
    scores = compute_scores()

    st.title("Company Info")
    st.markdown("<div class='path-muted'>Enter your company info for maximum accuracy.</div>", unsafe_allow_html=True)
    st.write("")

    badge("Company Profile")
    section_header("Company Info", "Step 3 of 5")

    # Eligibility warnings shown here too
    elig = scores.get("eligibility", {})
    if elig and not elig.get("is_eligible", True):
        warn_box("Warning: Your company may not meet one or more eligibility signals. You can still proceed.")
        with st.expander("View eligibility reasons", expanded=False):
            for r in elig.get("reasons", []):
                st.warning(r)

    logo = st.file_uploader("Company Logo (used on cover page)", type=["png", "jpg", "jpeg"])
    if logo is not None:
        st.session_state["company_logo_bytes"] = logo.getvalue()
        ok_box("Logo uploaded.")

    company.name = st.text_input("Company Name", value=company.name)
    company.uei = st.text_input("UEI", value=company.uei)
    company.cage = st.text_input("CAGE", value=company.cage)
    company.address = st.text_input("Address", value=company.address)
    company.naics = st.text_input("NAICS", value=company.naics)

    company.certifications = st.multiselect(
        "Certifications",
        options=CERT_OPTIONS,
        default=company.certifications,
    )

    company.past_performance = st.text_area("Past Performance", value=company.past_performance, height=160)
    company.differentiators = st.text_area("Differentiators", value=company.differentiators, height=140)

    set_company(company)

    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Back to Dashboard", use_container_width=True):
            set_current_step("dashboard")
            st.rerun()
    with c2:
        if st.button("Continue to Draft", type="primary", use_container_width=True):
            mark_complete("company")
            set_current_step("draft")
            st.rerun()