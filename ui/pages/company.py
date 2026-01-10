from __future__ import annotations

import streamlit as st

from core.state import get_company, set_company, CompanyProfile, get_rfp, set_current_step
from core.scoring import compute_all_scores
from ui.components import section_header, warn_box, ok_box


CERT_OPTIONS = [
    "SDVOSB",
    "VOSB",
    "8(a)",
    "WOSB",
    "EDWOSB",
    "HUBZone",
    "Small Business",
    "Other",
]


def render() -> None:
    rfp = get_rfp()
    company = get_company()

    st.title("Company Info")
    st.markdown("<div class='path-muted'>This powers eligibility checks, cover page branding, and proposal tailoring.</div>", unsafe_allow_html=True)

    section_header("Company Profile", "Step 3 of 6")

    with st.form("company_form", clear_on_submit=False):
        name = st.text_input("Company name", value=company.name)
        col1, col2 = st.columns(2)
        with col1:
            uei = st.text_input("UEI", value=company.uei)
        with col2:
            cage = st.text_input("CAGE", value=company.cage)

        address = st.text_area("Address", value=company.address, height=80)
        naics = st.text_input("Primary NAICS", value=company.naics)

        certifications = st.multiselect("Certifications", options=CERT_OPTIONS, default=company.certifications or [])

        differentiators = st.text_area("Differentiators (what makes you stand out)", value=company.differentiators, height=120)
        past_performance = st.text_area("Past performance (brief)", value=company.past_performance, height=120)

        logo = st.file_uploader("Company logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
        logo_bytes = company.logo_bytes
        logo_mime = company.logo_mime

        if logo is not None:
            logo_bytes = logo.getvalue()
            logo_mime = logo.type or ""

        saved = st.form_submit_button("Save Company Info", type="primary")

    if saved:
        updated = CompanyProfile(
            name=name.strip(),
            uei=uei.strip(),
            cage=cage.strip(),
            address=address.strip(),
            naics=naics.strip(),
            certifications=certifications,
            differentiators=differentiators.strip(),
            past_performance=past_performance.strip(),
            logo_bytes=logo_bytes,
            logo_mime=logo_mime,
        )
        set_company(updated)
        compute_all_scores()
        st.success("Saved.")

    # Eligibility warnings (warnings only, never blocks)
    scores = compute_all_scores()
    flags = st.session_state.get("eligibility_flags", []) or []
    if flags:
        warn_box("<br/>".join(flags))
    else:
        ok_box("No eligibility warnings detected so far.")

    # Show RFP’s detected certification mentions, if any
    if rfp.certifications_required:
        st.markdown(f"**RFP mentions certifications:** {', '.join(rfp.certifications_required)}")

    st.write("")
    if st.button("Continue to Draft Proposal", type="primary", use_container_width=True):
        set_current_step("draft")
        st.rerun()