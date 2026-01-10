import streamlit as st

from ui.company_info import render_company_info

# ----------------------------
# MUST be first Streamlit command
# ----------------------------
st.set_page_config(
    page_title="Path.ai – Federal Proposal Prep",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

def get_state() -> dict:
    if "state" not in st.session_state:
        st.session_state.state = {}
    return st.session_state.state


def sidebar_nav(state: dict) -> str:
    st.sidebar.title("Path.ai")
    st.sidebar.caption("Navigate")

    pages = ["Dashboard", "Upload RFP", "Company Info", "Draft Proposal", "Export"]
    choice = st.sidebar.radio("Section", pages, index=0)
    return choice


def dashboard_page(state: dict):
    st.title("Readiness Console")
    st.write("This is your dashboard (readiness + compliance + win strength).")

    st.metric("Compliance", f'{state.get("compliance_pct", 0)}%')
    st.metric("Company Profile", f'{state.get("company_pct", 0)}%')
    st.metric("Win Strength", f'{state.get("win_pct", 0)}%')

    st.info("Next: Upload an RFP to extract requirements.")


def upload_rfp_page(state: dict):
    st.title("Upload RFP")
    st.write("Upload PDF or paste text.")

    pdf = st.file_uploader("Upload RFP PDF", type=["pdf"])
    pasted = st.text_area("Or paste RFP text", height=220)

    if pdf is not None:
        state["rfp_pdf_bytes"] = pdf.getvalue()
        state["rfp_pdf_name"] = pdf.name
        st.success(f"Uploaded: {pdf.name}")

    if pasted.strip():
        state["rfp_text"] = pasted.strip()
        st.success("RFP text saved.")


def draft_page(state: dict):
    st.title("Draft Proposal")
    st.write("Draft content will go here + inline AI fixes (no separate Fixes tab).")
    st.text_area("Outline", value=state.get("outline", ""), height=160, key="outline")
    st.text_area("Narrative", value=state.get("narrative", ""), height=240, key="narrative")


def export_page(state: dict):
    st.title("Export")
    st.caption("Export is always unlocked.")

    st.write("DOCX download will go here.")
    st.write("Compatibility Matrix (Excel) download will go here.")

    # Placeholder: You’ll wire build/download next
    st.info("Next step: wire DOCX + Excel exporters into real download buttons.")


def main():
    state = get_state()
    page = sidebar_nav(state)

    if page == "Dashboard":
        dashboard_page(state)
    elif page == "Upload RFP":
        upload_rfp_page(state)
    elif page == "Company Info":
        render_company_info(state)
    elif page == "Draft Proposal":
        draft_page(state)
    elif page == "Export":
        export_page(state)

if __name__ == "__main__":
    main()