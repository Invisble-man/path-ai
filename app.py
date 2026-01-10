import streamlit as st

from ui.components import inject_css, sidebar_nav
from ui.pages.home import page_home
from ui.pages.company import page_company
from ui.pages.draft import page_draft
from ui.pages.export import page_export

APP_NAME = "Path.ai"
BUILD_VERSION = "v1.2.0"

st.set_page_config(
    page_title=f"{APP_NAME} – Federal Proposal Prep",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()

# ---- Session defaults ----
if "route" not in st.session_state:
    st.session_state.route = "Dashboard"
if "rfp" not in st.session_state:
    st.session_state.rfp = {"text": "", "pages": 0, "filename": None}
if "analysis" not in st.session_state:
    st.session_state.analysis = {
        "requirements": [],
        "compat_rows": [],
        "diagnostics": {"due_date": "", "submit_email": "", "notes": ""},
        "scores": {"compliance": 0, "company": 0, "win": 0, "overall": 0},
        "suggestions": [],
        "eligibility": {"ok": True, "warnings": []},
    }
if "company" not in st.session_state:
    st.session_state.company = {}
if "draft" not in st.session_state:
    st.session_state.draft = {"cover": "", "narrative": "", "outline": ""}

# ---- Sidebar ----
sidebar_nav(APP_NAME, BUILD_VERSION)

# ---- Route ----
route = st.session_state.route
if route == "Dashboard":
    page_home()
elif route == "Company Info":
    page_company()
elif route == "Draft Proposal":
    page_draft()
elif route == "Export":
    page_export()
else:
    st.session_state.route = "Dashboard"
    st.rerun()