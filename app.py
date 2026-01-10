import streamlit as st

from ui.components import ensure_state, inject_global_css, nav_sidebar, top_brand_bar
from ui.pages.home import page_home
from ui.pages.company import page_company
from ui.pages.draft import page_draft
from ui.pages.export import page_export


# MUST be first Streamlit command
st.set_page_config(
    page_title="Path.ai – Federal Proposal Prep",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",  # keeps landing page clean
)

APP_NAME = "Path.ai"
BUILD_VERSION = "v1.3.0"

ensure_state()
inject_global_css()

top_brand_bar()

# Landing page until analyzed
if not st.session_state.get("analyzed", False):
    page_home()
    st.stop()

# Guided flow after analyze
page = nav_sidebar(APP_NAME, BUILD_VERSION)

if page == "Company Info":
    page_company()
elif page == "Draft Proposal":
    page_draft()
elif page == "Export":
    page_export()
else:
    # Default “Dashboard” view = diagnostics + scoring summary
    page_home(show_results_only=True)