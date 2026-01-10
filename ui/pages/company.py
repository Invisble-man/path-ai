import streamlit as st
from ui.components import get_certifications_list


def page_company():
    st.title("Company Info")
    st.caption("This data powers eligibility checks, cover page, cover letter, and proposal drafting.")

    c = st.session_state["company"]

    st.subheader("Identity")
    col1, col2, col3 = st.columns(3)
    with col1:
        c["legal_name"] = st.text_input("Legal Company Name", c.get("legal_name", ""))
        c["doing_business_as"] = st.text_input("DBA (if any)", c.get("doing_business_as", ""))
        c["website"] = st.text_input("Website", c.get("website", ""))
    with col2:
        c["uei"] = st.text_input("UEI", c.get("uei", ""))
        c["cage"] = st.text_input("CAGE", c.get("cage", ""))
        c["duns"] = st.text_input("DUNS (if used)", c.get("duns", ""))
    with col3:
        c["ein"] = st.text_input("EIN", c.get("ein", ""))
        c["naics_codes"] = st.text_input("NAICS Codes (comma-separated)", c.get("naics_codes", ""))
        c["phone"] = st.text_input("Main Phone", c.get("phone", ""))

    st.subheader("Address")
    a1, a2 = st.columns(2)
    with a1:
        c["address_line1"] = st.text_input("Address Line 1", c.get("address_line1", ""))
        c["address_line2"] = st.text_input("Address Line 2", c.get("address_line2", ""))
    with a2:
        c3, c4, c5 = st.columns(3)
        with c3:
            c["city"] = st.text_input("City", c.get("city", ""))
        with c4:
            c["state"] = st.text_input("State", c.get("state", ""))
        with c5:
            c["zip"] = st.text_input("ZIP", c.get("zip", ""))
        c["country"] = st.text_input("Country", c.get("country", "USA"))

    st.subheader("Certifications / Set-Asides")
    certs = get_certifications_list()
    c["certifications"] = st.multiselect(
        "Select all that apply",
        options=certs,
        default=c.get("certifications", ["None / Not sure"]),
    )

    st.subheader("Primary Point of Contact")
    p1, p2, p3 = st.columns(3)
    with p1:
        c["primary_poc_name"] = st.text_input("POC Name", c.get("primary_poc_name", ""))
        c["primary_poc_title"] = st.text_input("POC Title", c.get("primary_poc_title", ""))
    with p2:
        c["primary_poc_email"] = st.text_input("POC Email", c.get("primary_poc_email", ""))
        c["primary_poc_phone"] = st.text_input("POC Phone", c.get("primary_poc_phone", ""))
    with p3:
        c["capability_statement"] = st.text_area("1–2 sentence capability statement", c.get("capability_statement", ""), height=90)

    st.subheader("Cover Page Branding")
    logo = st.file_uploader("Upload Company Logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
    if logo is not None:
        c["logo_bytes"] = logo.read()
        c["logo_name"] = logo.name
        st.success("Logo saved for cover page / export.")

    if c.get("logo_bytes"):
        st.image(c["logo_bytes"], caption=c.get("logo_name", "logo"), use_container_width=True)

    st.session_state["company"] = c