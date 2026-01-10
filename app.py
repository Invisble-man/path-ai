import streamlit as st

from core.state import (
    init_app_state,
    set_current_step,
    get_step_status_map,
    step_order,
)

from ui.pages.home import render as render_home
from ui.pages.dashboard import render as render_dashboard
from ui.pages.company import render as render_company
from ui.pages.draft import render as render_draft
from ui.pages.compatibility import render as render_compatibility
from ui.pages.export import render as render_export


APP_TITLE = "Path.AI"


def _inject_global_css() -> None:
    st.markdown(
        """
        <style>
          /* Slightly rugged/futuristic: dark-friendly but not harsh */
          .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1100px; }
          h1, h2, h3 { letter-spacing: -0.02em; }
          .path-badge {
            display:inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            font-size: 0.82rem;
            border: 1px solid rgba(255,255,255,0.18);
            background: rgba(255,255,255,0.06);
          }
          .path-muted { opacity: 0.85; }
          .path-warn {
            border-left: 4px solid #f59e0b;
            padding: 0.75rem 0.9rem;
            background: rgba(245,158,11,0.08);
            border-radius: 0.4rem;
          }
          .path-ok {
            border-left: 4px solid #22c55e;
            padding: 0.75rem 0.9rem;
            background: rgba(34,197,94,0.08);
            border-radius: 0.4rem;
          }
          .path-danger {
            border-left: 4px solid #ef4444;
            padding: 0.75rem 0.9rem;
            background: rgba(239,68,68,0.08);
            border-radius: 0.4rem;
          }
          /* Make sidebar feel like a guide, not dev UI */
          section[data-testid="stSidebar"] { border-right: 1px solid rgba(255,255,255,0.10); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _sidebar_nav() -> None:
    st.sidebar.markdown(f"## {APP_TITLE}")
    st.sidebar.markdown(
        "<div class='path-muted'>TurboTax-style guidance for federal proposals.</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.markdown("---")

    status_map = get_step_status_map()

    # Color key:
    # ✅ done, 🟧 in-progress, ⬜ not started
    labels = {
        "done": "✅",
        "in_progress": "🟧",
        "not_started": "⬜",
    }

    for step_id, step_label in step_order:
        status = status_map.get(step_id, "not_started")
        icon = labels.get(status, "⬜")

        # We allow navigating anywhere EXCEPT Draft is “recommended” gated by progress in later step logic.
        # Here we always allow clicking; the page itself will warn if prerequisites aren't met.
        if st.sidebar.button(f"{icon} {step_label}", use_container_width=True):
            set_current_step(step_id)
            st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "<span class='path-badge'>Export is always unlocked</span>",
        unsafe_allow_html=True,
    )


def _route() -> None:
    step = st.session_state.get("current_step", "home")

    if step == "home":
        render_home()
    elif step == "dashboard":
        render_dashboard()
    elif step == "company":
        render_company()
    elif step == "draft":
        render_draft()
    elif step == "compatibility":
        render_compatibility()
    elif step == "export":
        render_export()
    else:
        # Safety fallback
        set_current_step("home")
        render_home()


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _inject_global_css()
    init_app_state()
    _sidebar_nav()
    _route()


if __name__ == "__main__":
    main()