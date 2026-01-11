from __future__ import annotations

import streamlit as st

from core.state import ensure_state, get_current_step, set_current_step
from ui.pages.home import render as render_home
from ui.pages.dashboard import render as render_dashboard
from ui.pages.company import render as render_company
from ui.pages.draft import render as render_draft
from ui.pages.export import render as render_export


PAGES = {
    "home": ("Upload", render_home),
    "dashboard": ("Dashboard", render_dashboard),
    "company": ("Company Info", render_company),
    "draft": ("Draft", render_draft),
    "export": ("Export", render_export),
}

ORDER = ["home", "dashboard", "company", "draft", "export"]


def _status_color(step: str, current: str, completion: dict) -> str:
    # Green = complete, Orange = started, Gray = not started, Blue = current
    if step == current:
        return "🟦"
    if completion.get(step) == "complete":
        return "🟩"
    if completion.get(step) == "started":
        return "🟧"
    return "⬜️"


def _sidebar_nav() -> None:
    current = get_current_step()
    completion = st.session_state.get("completion", {})

    st.sidebar.markdown("## Path.AI")
    st.sidebar.markdown("<div style='opacity:0.85;'>You are now on the Path to success.</div>", unsafe_allow_html=True)
    st.sidebar.write("")

    for key in ORDER:
        label, _ = PAGES[key]
        icon = _status_color(key, current, completion)
        if st.sidebar.button(f"{icon} {label}", use_container_width=True):
            set_current_step(key)
            st.rerun()

    st.sidebar.write("---")
    st.sidebar.caption("FASTER PROPOSALS | WIN MORE CONTRACTS.")


def main() -> None:
    st.set_page_config(page_title="Path.AI", layout="wide")
    ensure_state()
    _sidebar_nav()

    step = get_current_step()
    step = step if step in PAGES else "home"
    _, renderer = PAGES[step]
    renderer()


if __name__ == "__main__":
    main()