from __future__ import annotations

from typing import Dict, Any, List
import streamlit as st


# -----------------------------
# Notices
# -----------------------------

def ui_notice(msg: str, kind: str = "info") -> None:
    kind = (kind or "info").lower().strip()
    if kind == "success":
        st.success(msg)
    elif kind == "warning":
        st.warning(msg)
    elif kind == "error":
        st.error(msg)
    else:
        st.info(msg)


# -----------------------------
# Sidebar Progress
# -----------------------------

def render_sidebar_progress() -> None:
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

    has_key = bool(st.secrets.get("OPENAI_API_KEY", ""))
    st.sidebar.caption(f"AI: {'enabled' if has_key else 'not detected'}")


# -----------------------------
# Certifications Dropdown
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
# Readiness Console
# -----------------------------

def render_readiness_console(scores: Dict[str, Any] | None = None) -> None:
    scores = scores or {}

    def clamp(v):
        try:
            return max(0, min(100, float(v)))
        except Exception:
            return 0

    compliance = clamp(scores.get("compliance", 0))
    company = clamp(scores.get("company", 0))
    win = clamp(scores.get("win", 0))

    overall = (compliance + company + win) / 3

    def grade(p):
        if p >= 90: return "A"
        if p >= 80: return "B"
        if p >= 70: return "C"
        if p >= 60: return "D"
        return "F"

    st.markdown("## Readiness Console")
    st.caption("Live proposal strength indicators")

    c1, c2 = st.columns([3, 1])
    with c2:
        st.markdown(f"### {int(overall)}% • Grade {grade(overall)}")

    st.markdown("**COMPLIANCE**")
    st.progress(compliance / 100)

    st.markdown("**COMPANY PROFILE**")
    st.progress(company / 100)

    st.markdown("**WIN STRENGTH**")
    st.progress(win / 100)

    st.markdown("---")