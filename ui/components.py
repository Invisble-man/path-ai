from __future__ import annotations

import streamlit as st


def badge(text: str) -> None:
    st.markdown(f"<span class='path-badge'>{text}</span>", unsafe_allow_html=True)


def warn_box(text: str) -> None:
    st.markdown(f"<div class='path-warn'>{text}</div>", unsafe_allow_html=True)


def ok_box(text: str) -> None:
    st.markdown(f"<div class='path-ok'>{text}</div>", unsafe_allow_html=True)


def danger_box(text: str) -> None:
    st.markdown(f"<div class='path-danger'>{text}</div>", unsafe_allow_html=True)


def walking_progress(label: str, pct: int, subtitle: str = "") -> None:
    """
    A simple “walking man” indicator along a bar.
    Streamlit-safe (no JS). Uses HTML/CSS only.
    """
    pct = max(0, min(100, int(pct)))

    # Place the walker roughly at pct% but keep within edges
    left = max(0, min(96, pct))

    st.markdown(
        f"""
        <div style="margin: 0.35rem 0 0.2rem 0;">
          <div style="display:flex; justify-content:space-between; align-items:flex-end;">
            <div style="font-weight:700;">{label}</div>
            <div style="opacity:0.85;">{pct}%</div>
          </div>
          <div style="position:relative; height:14px; border-radius:999px; background:rgba(255,255,255,0.10); overflow:hidden; margin-top:0.35rem;">
            <div style="height:14px; width:{pct}%; background:rgba(34,197,94,0.35);"></div>
            <div style="position:absolute; top:-10px; left:{left}%; transform:translateX(-50%); font-size:18px;">🚶‍♂️</div>
          </div>
          <div style="opacity:0.75; font-size:0.9rem; margin-top:0.25rem;">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, hint: str = "") -> None:
    cols = st.columns([3, 2])
    with cols[0]:
        st.subheader(title)
    with cols[1]:
        if hint:
            st.markdown(f"<div class='path-muted' style='text-align:right; padding-top:0.25rem;'>{hint}</div>", unsafe_allow_html=True)
            import streamlit as st


def evaluator_panel(diagnostics: dict):
    """
    Displays an evaluator-style diagnostics checklist with R/Y/G status.
    """
    if not diagnostics:
        st.info("No diagnostics available yet.")
        return

    items = diagnostics.get("evaluator_items", [])
    counts = diagnostics.get("counts", {})

    st.markdown("### Evaluator Diagnostics")

    c1, c2, c3 = st.columns(3)
    c1.metric("Green", counts.get("green", 0))
    c2.metric("Yellow", counts.get("yellow", 0))
    c3.metric("Red", counts.get("red", 0))

    st.write("")

    for item in items:
        status = item.get("status", "yellow")
        label = item.get("label", "")
        hint = item.get("hint", "")

        if status == "green":
            icon = "🟢"
        elif status == "red":
            icon = "🔴"
        else:
            icon = "🟡"

        with st.expander(f"{icon} {label}", expanded=False):
            st.write(hint)