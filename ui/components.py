from __future__ import annotations

import base64
import textwrap
from typing import Dict, Any, List, Optional, Tuple

import streamlit as st


# ----------------------------
# Styling
# ----------------------------
def _html(block: str):
    st.markdown(textwrap.dedent(block), unsafe_allow_html=True)


def apply_base_style():
    _html(
        """
        <style>
        :root{
          --bg: rgba(255,255,255,0.92);
          --bd: rgba(49,51,63,0.14);
          --tx: rgba(49,51,63,0.92);
          --mut: rgba(49,51,63,0.66);
          --good: rgba(34,197,94,0.18);
          --warn: rgba(234,179,8,0.20);
          --bad:  rgba(239,68,68,0.18);
          --neu:  rgba(92,124,250,0.14);
          --ink: rgba(20, 22, 30, 0.9);
        }

        .block-container { padding-top: 0.75rem; padding-bottom: 2.2rem; max-width: 1180px; }
        header[data-testid="stHeader"] { background: rgba(255,255,255,0.90); backdrop-filter: blur(8px); }

        /* System Banner */
        .sysbar{
          display:flex; align-items:center; justify-content:space-between;
          border: 1px solid var(--bd);
          border-radius: 14px;
          padding: 12px 14px;
          background: linear-gradient(135deg, rgba(92,124,250,0.10), rgba(20,22,30,0.04));
          margin-bottom: 12px;
          gap: 12px;
        }
        .sys-left{display:flex; gap:12px; align-items:flex-start; min-width: 0;}
        .sys-dot{
          width: 10px; height: 10px; border-radius: 999px;
          background: radial-gradient(circle at 30% 30%, #22c55e, #5c7cfa);
          margin-top: 6px;
          flex: 0 0 auto;
        }
        .sys-title{
          font-weight: 900;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          font-size: 0.84rem;
          color: rgba(20,22,30,0.88);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 64vw;
        }
        .sys-quote{
          font-weight: 900;
          letter-spacing: 0.02em;
          font-size: 1.05rem;
          color: rgba(20,22,30,0.92);
          margin-top: 2px;
        }
        .sys-sub{
          font-size: 0.90rem;
          color: var(--mut);
          margin-top: 2px;
        }

        /* Console */
        .console{
          border: 1px solid var(--bd);
          border-radius: 16px;
          padding: 14px 14px 12px 14px;
          background: var(--bg);
          margin-bottom: 12px;
        }
        .console h4{
          margin: 0;
          font-size: 0.92rem;
          font-weight: 900;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: rgba(20,22,30,0.86);
        }
        .console-sub{
          margin-top: 4px;
          color: var(--mut);
          font-size: 0.90rem;
        }
        .divider{ height: 1px; background: rgba(49,51,63,0.10); margin: 10px 0; }

        /* Bars */
        .barrow{ display:flex; align-items:center; justify-content:space-between; gap: 10px; margin: 10px 0 6px 0; }
        .barlabel{
          font-weight: 900;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          font-size: 0.78rem;
          color: rgba(20,22,30,0.86);
          white-space: nowrap;
        }
        .barmeta{
          font-size: 0.84rem;
          color: var(--mut);
          white-space: nowrap;
        }
        .barwrap{
          position: relative;
          height: 12px;
          border-radius: 999px;
          border: 1px solid rgba(49,51,63,0.18);
          background: rgba(20,22,30,0.04);
          overflow: hidden;
        }
        .barfill{
          height: 100%;
          border-radius: 999px;
        }

        /* Walker */
        .walker{
          position:absolute;
          top: -14px;
          width: 24px;
          height: 24px;
          transform: translateX(-50%);
          display:flex;
          align-items:center;
          justify-content:center;
          pointer-events: none;
        }
        .walker svg{ width: 22px; height: 22px; }

        /* Chips */
        .chip{
          display:inline-block;
          border: 1px solid rgba(49,51,63,0.18);
          border-radius: 999px;
          padding: 6px 10px;
          font-size: 0.82rem;
          font-weight: 900;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          margin-right: 8px;
          margin-top: 6px;
          color: rgba(20,22,30,0.86);
          background: rgba(255,255,255,0.9);
        }
        .chip-good{ background: var(--good); }
        .chip-warn{ background: var(--warn); }
        .chip-bad{  background: var(--bad);  }
        .chip-neu{  background: var(--neu);  }

        /* Notices */
        .notice{
          border-radius: 14px;
          padding: 11px 12px;
          border: 1px solid var(--bd);
          background: var(--bg);
          margin: 10px 0 12px 0;
        }
        .notice-title{ font-weight: 900; letter-spacing:0.04em; text-transform:uppercase; margin: 0 0 4px 0; font-size: 0.80rem; color: rgba(20,22,30,0.86); }
        .notice-body{ margin: 0; font-size: 0.93rem; color: rgba(20,22,30,0.80); }

        .tone-good { background: var(--good); }
        .tone-warn { background: var(--warn); }
        .tone-bad  { background: var(--bad); }
        .tone-neutral { background: var(--neu); }

        /* Buttons */
        .stButton>button {
          border-radius: 12px !important;
          padding: 0.68rem 0.95rem !important;
          font-weight: 900 !important;
          letter-spacing: 0.02em !important;
        }

        @media (max-width: 700px){
          .block-container { padding-left: 0.7rem; padding-right: 0.7rem; }
          .sysbar{ flex-direction: column; align-items: stretch; }
          .sys-title{ max-width: 100%; }
        }
        </style>
        """
    )


def ui_notice(title: str, body: str, tone: str = "neutral"):
    tone_class = {
        "neutral": "tone-neutral",
        "good": "tone-good",
        "warn": "tone-warn",
        "bad": "tone-bad",
    }.get(tone, "tone-neutral")

    _html(
        f"""
        <div class="notice {tone_class}">
          <div class="notice-title">{title}</div>
          <p class="notice-body">{body}</p>
        </div>
        """
    )


# ----------------------------
# Helpers
# ----------------------------
def pct_color(p: float) -> Tuple[str, str]:
    p = float(max(0.0, min(100.0, p)))
    if p < 50:
        return "#ef4444", "chip-bad"
    if p < 70:
        return "#f59e0b", "chip-warn"
    if p < 85:
        return "#eab308", "chip-warn"
    return "#22c55e", "chip-good"


def grade_from_pct(p: float) -> str:
    p = float(p)
    if p >= 90:
        return "A"
    if p >= 80:
        return "B"
    if p >= 70:
        return "C"
    if p >= 60:
        return "D"
    return "F"


def _walker_svg(color: str) -> str:
    return f"""
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="12" cy="5.5" r="2.5" fill="{color}"/>
      <path d="M9.3 22V12.2c0-1.2.7-2.3 1.8-2.8l.2-.1c.9-.4 2-.4 2.9 0l.2.1c1.1.5 1.8 1.6 1.8 2.8V22"
            stroke="{color}" stroke-width="2" stroke-linecap="round"/>
      <path d="M8 14.5h8" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
      <path d="M11.2 22v-5.2" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
      <path d="M12.8 22v-5.2" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
    </svg>
    """


def render_readiness_console(scores: Dict[str, Any], build_version: str = "v1", build_date: str = ""):
    compliance = float(scores.get("compliance_pct", 0.0))
    win = float(scores.get("win_strength_pct", 0.0))
    overall = float(scores.get("overall_progress_pct", 0.0))
    grade = grade_from_pct(compliance)

    c_color, _ = pct_color(compliance)
    w_color, _ = pct_color(win)
    o_color, _ = pct_color(overall)

    # Export ALWAYS unlocked per your requirement
    export_chip = "chip-good"
    state_chip = "chip-warn" if overall < 85 else "chip-good"
    state_text = "IN PROGRESS" if overall < 85 else "READY"

    def bar_html(label: str, pct: float, meta: str, color: str, walker: bool = False) -> str:
        left = max(2, min(98, int(round(pct))))
        walker_block = ""
        if walker:
            walker_block = f"""
            <div class="walker" style="left:{left}%;">
              {_walker_svg(color)}
            </div>
            """
        return textwrap.dedent(
            f"""
            <div class="barrow">
              <div class="barlabel">{label}</div>
              <div class="barmeta">{meta}</div>
            </div>
            <div class="barwrap">
              <div class="barfill" style="width:{pct:.0f}%; background:{color};"></div>
              {textwrap.dedent(walker_block).strip()}
            </div>
            """
        )

    _html(
        f"""
        <div class="sysbar">
          <div class="sys-left">
            <div class="sys-dot"></div>
            <div>
              <div class="sys-title">PATH STATUS: ACTIVE • {build_version} • {build_date}</div>
              <div class="sys-quote">YOU ARE ON THE RIGHT PATH TO SUCCESS.</div>
              <div class="sys-sub">System-guided. Compliance-first. Submission-ready.</div>
            </div>
          </div>
          <div style="text-align:right;">
            <span class="chip {state_chip}">STATE: {state_text}</span>
            <span class="chip {export_chip}">EXPORT: UNLOCKED</span>
          </div>
        </div>
        """
    )

    _html(
        f"""
        <div class="console">
          <h4>Readiness Console</h4>
          <div class="console-sub">No clutter. Only what drives compliance and win probability.</div>
          <div class="divider"></div>

          {bar_html("Compliance", compliance, f"{compliance:.0f}% • Grade {grade}", c_color, walker=False)}
          {bar_html("Win Strength", win, f"{win:.0f}%", w_color, walker=False)}

          <div class="divider"></div>

          {bar_html("Overall Progress", overall, f"{overall:.0f}%", o_color, walker=True)}
        </div>
        """
    )

    # Warnings
    warnings = scores.get("warnings", []) or []
    if warnings:
        ui_notice("ELIGIBILITY WARNINGS", " • ".join(warnings), tone="warn")


# ----------------------------
# Sidebar + Navigation
# ----------------------------
def path_sidebar(scores: Dict[str, Any]):
    st.sidebar.title("Path.ai")

    # Simple nav
    pages = ["Upload RFP", "Company Info", "Draft Proposal", "Export"]
    current = st.session_state.get("current_page", "Upload RFP")
    if current not in pages:
        current = "Upload RFP"

    chosen = st.sidebar.radio("Navigate", pages, index=pages.index(current))
    st.session_state["current_page"] = chosen

    # Quick metrics
    st.sidebar.divider()
    st.sidebar.metric("Compliance", f'{float(scores.get("compliance_pct", 0)):.0f}%')
    st.sidebar.metric("Win Strength", f'{float(scores.get("win_strength_pct", 0)):.0f}%')
    st.sidebar.progress(float(scores.get("overall_progress_pct", 0.0)) / 100.0)

    # Step lights
    st.sidebar.divider()
    steps = scores.get("steps", {}) or {}

    def badge(label: str, color: str):
        dot = {"green": "🟢", "orange": "🟠", "red": "🔴"}.get(color, "⚪")
        st.sidebar.write(f"{dot} {label}")

    badge("Upload RFP", (steps.get("home") or {}).get("color", "red"))
    badge("Company Info", (steps.get("company") or {}).get("color", "red"))
    badge("Draft Proposal", (steps.get("draft") or {}).get("color", "red"))
    badge("Compatibility", (steps.get("requirements") or {}).get("color", "red"))
    badge("Export", (steps.get("export") or {}).get("color", "orange"))


# ----------------------------
# Certifications dropdown list
# ----------------------------
def certification_options() -> List