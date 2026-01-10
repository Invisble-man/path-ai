import streamlit as st

def render_company_info(state: dict):
    st.header("Company Info")

    col1, col2 = st.columns([2, 1])
    with col1:
        state["company_name"] = st.text_input("Company Name", value=state.get("company_name", ""))
        state["uei"] = st.text_input("UEI (optional)", value=state.get("uei", ""))
        state["cage"] = st.text_input("CAGE (optional)", value=state.get("cage", ""))

    with col2:
        st.subheader("Company Logo")
        logo = st.file_uploader("Upload logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
        if logo is not None:
            state["company_logo_bytes"] = logo.getvalue()
            state["company_logo_name"] = logo.name
            st.image(state["company_logo_bytes"], use_container_width=True)

    st.caption("Logo is stored in session only (not saved to disk).")
