from __future__ import annotations

import streamlit as st


def _css_once() -> None:
    """
    Minimal UI styling. Safe for Streamlit + mobile.
    """
    if st.session_state.get("_path_css_loaded"):
        return
    st.session_state["_path_css_loaded"] = True

    st.markdown(
        """
        <style>
          .path-muted { opacity: 0.85; font-size: 0.98rem; }
          .path-badge {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            font-weight: 600;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.10);
          }
          .path-warn {
            border-left: 6px solid #f59e0b;
            background: rgba(245, 158, 11, 0.12);
            padding: 12px 12px;
            border-radius: 10px;
            margin: 8px 0;
          }
          .path-ok {
            border-left: 6px solid #22c55e;
            background: rgba(34, 197, 94, 0.12);
            padding: 12px 12px;
            border-radius: 10px;
            margin: 8px 0;
          }
          .path-danger {
            border-left: 6px solid #ef4444;
            background: rgba(239, 68, 68, 0.12);
            padding: 12px 12px;
            border-radius: 10px;
            margin: 8px 0;
          }
          .path-hr {
            height: 1px;
            border: 0;
            background: rgba(255,255,255,0.10);
            margin: 10px 0 14px 0;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str) -> None:
    _css_once()
    st.markdown(f"<span class='path-badge'>{text}</span>", unsafe_allow_html=True)


def warn_box(text: str) -> None:
    _css_once()
    st.markdown(f"<div class='path-warn'>{text}</div>", unsafe_allow_html=True)


def ok_box(text: str) -> None:
    _css_once()
    st.markdown(f"<div class='path-ok'>{text}</div>", unsafe_allow_html=True)


def danger_box(text: str) -> None:
    _css_once()
    st.markdown(f"<div class='path-danger'>{text}</div>", unsafe_allow_html=True)


def section_header(title: str, subtitle: str | None = None) -> None:
    _css_once()
    st.markdown(f"## {title}")
    if subtitle:
        st.markdown(f"<div class='path-muted'>{subtitle}</div>", unsafe_allow_html=True)
    st.markdown("<hr class='path-hr'/>", unsafe_allow_html=True)


def walking_progress(label: str, pct: int, subtitle: str | None = None) -> None:
    """
    Simple progress bar with a little "walker" emoji.
    Streamlit-safe HTML/CSS only (no JS).
    """
    _css_once()
    try:
        pct_int = int(pct)
    except Exception:
        pct_int = 0
    pct_int = max(0, min(100, pct_int))
    left = max(0, min(96, pct_int))

    sub = f"<div class='path-muted'>{subtitle}</div>" if subtitle else ""
    st.markdown(
        f"""
        <div style="margin: 0.35rem 0 0.2rem 0;">
          <div style="display:flex; justify-content:space-between;">
            <div style="font-weight:700;">{label}</div>
            <div style="opacity:0.85;">{pct_int}%</div>
          </div>
          {sub}
          <div style="position:relative; margin-top:10px; height:14px; border-radius:999px;
                      background: rgba(255,255,255,0.10); overflow:hidden;">
            <div style="height:100%; width:{pct_int}%; background: rgba(34,197,94,0.55);"></div>
            <div style="position:absolute; top:-16px; left:{left}%; transform: translateX(-50%); font-size:18px;">
              🚶🏾‍♂️
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def evaluator_panel(diagnostics: dict) -> None:
    """
    Evaluator-style checklist: red/yellow/green items + counts.
    Expected input:
      {
        "counts": {"green": 1, "yellow": 2, "red": 3},
        "evaluator_items": [{"status":"green|yellow|red","label":"...","hint":"..."}]
      }
    """
    _css_once()

    if not diagnostics:
        st.info("No diagnostics available yet.")
        return

    items = diagnostics.get("evaluator_items", []) or []
    counts = diagnostics.get("counts", {}) or {}

    st.markdown("### Evaluator Diagnostics")
    c1, c2, c3 = st.columns(3)
    c1.metric("Green", int(counts.get("green", 0)))
    c2.metric("Yellow", int(counts.get("yellow", 0)))
    c3.metric("Red", int(counts.get("red", 0)))

    for item in items:
        status = (item.get("status") or "yellow").lower()
        label = item.get("label") or "Check"
        hint = item.get("hint") or ""

        icon = "🟡"
        if status == "green":
            icon = "🟢"
        elif status == "red":
            icon = "🔴"

        with st.expander(f"{icon} {label}", expanded=False):
            st.write(hint or "No details provided.")