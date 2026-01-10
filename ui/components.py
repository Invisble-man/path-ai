from __future__ import annotations

from typing import Dict, Any, List
import streamlit as st


# -----------------------------
# Simple UI Helpers
# -----------------------------

def ui_notice(msg: str, kind: str = "info") -> None:
    """
    kind: "info" | "success" | "warning" | "error"
    """
    kind = (kind or "info").lower().strip()
    if kind == "success":
        st.success(msg)
    elif kind == "warning":
        st.warning(msg)
    elif kind == "error":
        st.error(msg)
    else:
        st.info(msg)


def _grade_from_pct(pct: float) -> str:
    pct = max(0.0, min(100.0, pct))
    if pct >= 90:
        return "A"
    if pct >= 80:
        return "B"
    if pct >= 70:
        return "C"
    if pct >= 60:
        return "D"
    return "F"


def _safe_pct(value: Any) -> float:
    try:
        v = float(value)
    except Exception:
        v = 0.0
    return max(0.0, min(100.0, v))


# -----------------------------
# Sidebar Progress (TurboTax-like)
# -----------------------------

def render_sidebar_progress() -> None:
    """
    Expects st.session_state["steps"] = {
      "home": {"status": "green|orange|red"},
      "company": {...},
      "draft": {...},
      "compat": {...},
      "export": {...}
    }
    """
    st.sidebar.markdown("## Path.AI Progress")
    st.sidebar.caption("Green = complete • Orange = in progress • Red = not started")

    steps = st.session_state.get("steps", {}) or {}

    def badge(label: str, status: str) -> None:
        status = (status or "red").lower()
        dot = {"green": "🟢", "orange": "🟠", "red": "🔴"}.get(status, "🔴")
        st.sidebar.write(f"{dot} {label}")

    badge("Upload RFP", (steps.get("home", {}) or {}).get("status", "red"))
    badge("Company Info", (steps.get("company", {}) or {}).get("status", "red"))
    badge("Draft Proposal", (steps.get("draft", {}) or {}).get("status", "red"))
    badge("Compatibility", (steps.get("compat", {}) or {}).get("status", "red"))
    badge("Export", (steps.get("export", {}) or {}).get("status", "red"))

    st.sidebar.markdown("---")

    # show AI enabled status without breaking anything
    has_key = bool(st.secrets.get("OPENAI_API_KEY", "") or "")
    st.sidebar.caption(f"AI: {'enabled' if has_key else 'not detected'}")


# -----------------------------
# Certifications Dropdown Options
# -----------------------------

def certification_options() -> List[str]:
    return [
        "SDVOSB (Service-Disabled Veteran-Owned Small Business)",
        "VOSB (Veteran-Owned Small Business)",
        "8(a)",
        "HUBZone",
        "WOSB (Women-Owned Small Business)",
        "EDWOSB (Economically Disadvantaged WOSB)",
        "Small Disadvantaged Business (SDB)",
        "Minority-Owned Business",
        "Native American-Owned Business",
        "Alaska Native-Owned Business",
        "Tribal-Owned Business",
        "AbilityOne",
        "ISO 9001",
        "ISO 27001",
        "CMMI",
        "SOC 2",
        "FedRAMP",
        "None",
    ]


# -----------------------------
# Readiness Console (Dashboard widget)
# -----------------------------

def render_readiness_console(scores: Dict[str, Any] | None = None) -> None:
    """
    scores example:
      {
        "compliance": 62,
        "company": 40,
        "win": 55
      }
    """
    scores = scores or {}
    compliance = _safe_pct(scores.get("compliance", 0))
    company = _safe_pct(scores.get("company", 0))
    win = _safe_pct(scores.get("win", 0))

    overall = (compliance + company + win) / 3.0
    grade = _grade_from_pct(overall)

    st.markdown("## Readiness Console")
    st.caption("Only unresolved items that affect readiness are shown.")

    c1, c2 = st.columns([3, 1])
    with c2:
        st.markdown(f"### {int(overall)}% • Grade {grade}")

    st.markdown("**COMPLIANCE**")
    st.progress(compliance / 100)

    st.markdown("**COMPANY PROFILE**")
    st.progress(company / 100)

    st.markdown("**WIN STRENGTH**")
    st.progress(win / 100)

    st.markdown("---")