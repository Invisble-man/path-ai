import streamlit as st

from core.state import init_state
from ui.pages.home import page_home
from ui.pages.company import page_company
from ui.pages.draft import page_draft
from ui.pages.export import page_export
from core.scoring import compute_progress

# MUST be first Streamlit command
st.set_page_config(
    page_title="Path.ai — Federal Proposal Prep",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_NAME = "Path.ai"
TAGLINE = "You’re on the right path to success."

init_state()

# --- Sidebar: TurboTax-style progress (no “Fixes” page) ---
progress = compute_progress(st.session_state)

st.sidebar.markdown(f"## {APP_NAME}")
st.sidebar.caption(TAGLINE)
st.sidebar.markdown("---")

def step_color(step_key: str) -> str:
    # green = complete, orange = started, red = not started
    s = progress["steps"].get(step_key, {})
    return s.get("color", "red")

def step_badge(label: str, color: str) -> str:
    dot = {"green": "🟢", "orange": "🟠", "red": "🔴"}.get(color, "⚪")
    return f"{dot} {label}"

step_labels = {
    "home": "Upload RFP",
    "company": "Company Info",
    "draft": "Draft Proposal",
    "export": "Export",
}

st.sidebar.markdown("### Your Path")
st.sidebar.write(step_badge(step_labels["home"], step_color("home")))
st.sidebar.write(step_badge(step_labels["company"], step_color("company")))
st.sidebar.write(step_badge(step_labels["draft"], step_color("draft")))
st.sidebar.write(step_badge(step_labels["export"], step_color("export")))
st.sidebar.markdown("---")

st.sidebar.metric("Compliance", f'{progress["compliance_pct"]:.0f}%')
st.sidebar.metric("Win Strength", f'{progress["win_strength_pct"]:.0f}%')
st.sidebar.progress(progress["overall_progress_pct"] / 100.0)

# Navigation
page = st.sidebar.radio(
    "Navigate",
    options=["Upload RFP", "Company Info", "Draft Proposal", "Export"],
    index=0,
)

if page == "Upload RFP":
    page_home()
elif page == "Company Info":
    page_company_info()
elif page == "Draft Proposal":
    page_draft()
elif page == "Export":
    page_export()