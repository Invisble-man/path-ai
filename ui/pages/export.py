import streamlit as st

def page_export():
    st.header("Export")

    st.write("Download your proposal and compliance files.")

    st.subheader("DOCX Proposal Draft")
    st.button("Download Proposal Draft (DOCX)")

    st.subheader("Compliance Matrix (Excel)")
    st.info("Excel export will appear here once matrix is generated.")

    st.divider()

    st.caption("If AI draft is empty, fill in Draft Proposal manually, then export again.")