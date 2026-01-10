import os
import io
import re
import json
import textwrap
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple

import streamlit as st
from pypdf import PdfReader

# Optional: OpenAI (works if OPENAI_API_KEY is set in Render env vars)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# ----------------------------
# MUST be first Streamlit command
# ----------------------------
st.set_page_config(
    page_title="Path.ai — Federal Proposal Prep",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_NAME = "Path.ai"
BUILD_VERSION = "v1.1.0"

# ----------------------------
# Helpers
# ----------------------------

def get_openai_client() -> Optional["OpenAI"]:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key or not OpenAI:
        return None
    return OpenAI(api_key=key)

def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for p in reader.pages:
            pages.append(p.extract_text() or "")
        return "\n".join(pages).strip()
    except Exception as e:
        return f"[PDF extract failed: {e}]"

def clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))

def pct(numer: float, denom: float) -> int:
    if denom <= 0:
        return 0
    return int(round((numer / denom) * 100))

def ui_html(html: str):
    st.markdown(textwrap.dedent(html), unsafe_allow_html=True)

def status_color(state: str) -> str:
    # state: NOT_STARTED | IN_PROGRESS | DONE
    if state == "DONE":
        return "#22c55e"  # green
    if state == "IN_PROGRESS":
        return "#f59e0b"  # orange
    return "#ef4444"      # red

def pill(text: str, bg: str, fg: str = "white") -> str:
    return f"""
    <span style="
      display:inline-block;
      padding:6px 10px;
      border-radius:999px;
      font-size:12px;
      font-weight:700;
      background:{bg};
      color:{fg};
      margin-left:8px;
    ">{text}</span>
    """

@dataclass
class RequirementItem:
    id: str
    text: str
    status: str = "Unknown"  # Pass | Fail | Unknown
    notes: str = ""

def init_state():
    if "nav" not in st.session_state:
        st.session_state.nav = "Intake"

    if "intake_text" not in st.session_state:
        st.session_state.intake_text = ""

    if "requirements" not in st.session_state:
        st.session_state.requirements: List[RequirementItem] = []

    if "company" not in st.session_state:
        st.session_state.company = {
            "legal_name": "",
            "duns_uei": "",
            "cage": "",
            "naics": "",
            "address": "",
            "capabilities": "",
            "past_performance": "",
        }

    if "draft" not in st.session_state:
        st.session_state.draft = ""  # proposal draft text

init_state()


# ----------------------------
# Scoring + gating
# ----------------------------

def compliance_score(items: List[RequirementItem]) -> int:
    # Only count items that have a known status
    known = [i for i in items if i.status in ("Pass", "Fail")]
    if not known:
        return 0
    passed = sum(1 for i in known if i.status == "Pass")
    return pct(passed, len(known))

def company_profile_score(company: Dict) -> int:
    fields = ["legal_name", "duns_uei", "cage", "naics", "address", "capabilities"]
    filled = sum(1 for f in fields if (company.get(f) or "").strip())
    return pct(filled, len(fields))

def win_strength_score(company: Dict, items: List[RequirementItem]) -> int:
    # simple heuristic
    comp = compliance_score(items)
    prof = company_profile_score(company)
    return int(round((comp * 0.6) + (prof * 0.4)))

def overall_progress_score(company: Dict, items: List[RequirementItem], draft: str) -> int:
    # 3 buckets: intake, company, checks/draft
    intake_done = 1 if (st.session_state.intake_text.strip()) else 0
    company_done = 1 if company_profile_score(company) >= 60 else 0
    checks_done = 1 if compliance_score(items) >= 30 else 0
    draft_done = 1 if draft.strip() else 0

    # Weighted
    score = (
        intake_done * 20 +
        company_done * 25 +
        checks_done * 25 +
        draft_done * 30
    )
    return int(clamp(score, 0, 100))

def export_allowed(overall: int) -> bool:
    # Your rule: need at least 60% to export/generate final
    return overall >= 60


# ----------------------------
# Sidebar Wizard (red/orange/green)
# ----------------------------

def section_state_intake() -> str:
    if st.session_state.intake_text.strip():
        return "DONE"
    return "NOT_STARTED"

def section_state_company() -> str:
    s = company_profile_score(st.session_state.company)
    if s >= 80:
        return "DONE"
    if s > 0:
        return "IN_PROGRESS"
    return "NOT_STARTED"

def section_state_fix() -> str:
    s = compliance_score(st.session_state.requirements)
    if s >= 80 and len(st.session_state.requirements) > 0:
        return "DONE"
    if len(st.session_state.requirements) > 0:
        return "IN_PROGRESS"
    return "NOT_STARTED"

def section_state_draft() -> str:
    if st.session_state.draft.strip():
        return "DONE"
    # if they have anything started (intake/company/reqs) consider in progress
    if st.session_state.intake_text.strip() or len(st.session_state.requirements) > 0:
        return "IN_PROGRESS"
    return "NOT_STARTED"

def section_state_export() -> str:
    overall = overall_progress_score(st.session_state.company, st.session_state.requirements, st.session_state.draft)
    if export_allowed(overall) and st.session_state.draft.strip():
        return "DONE"
    if overall > 0:
        return "IN_PROGRESS"
    return "NOT_STARTED"

def nav_button(label: str, key: str, state: str):
    color = status_color(state)
    active = (st.session_state.nav == key)
    ui_html(f"""
    <div style="display:flex;align-items:center;gap:10px;margin:6px 0;">
      <div style="width:12px;height:12px;border-radius:999px;background:{color};"></div>
      <div style="flex:1;font-weight:{700 if active else 500};">{label}</div>
    </div>
    """)
    if st.button(f"Go to {label}", use_container_width=True, key=f"nav_{key}"):
        st.session_state.nav = key
        st.rerun()

with st.sidebar:
    st.markdown(f"### {APP_NAME}")
    st.caption(f"{BUILD_VERSION}")

    # Optional ENV debug (safe, doesn’t reveal key)
    key = os.getenv("OPENAI_API_KEY", "")
    ui_html(f"""
    <div style="margin:10px 0 14px 0;padding:10px;border:1px solid #e5e7eb;border-radius:12px;">
      <div style="font-weight:700;margin-bottom:6px;">AI status</div>
      <div style="font-size:13px;">
        has_openai_api_key: <b>{'true' if bool(key) else 'false'}</b><br/>
        key_prefix: <b>{key[:3] if key else 'None'}</b><br/>
        key_length: <b>{len(key) if key else 0}</b>
      </div>
    </div>
    """)

    st.markdown("### Navigate")

    nav_button("Intake", "Intake", section_state_intake())
    nav_button("Company", "Company", section_state_company())
    nav_button("Fix", "Fix", section_state_fix())
    nav_button("Draft", "Draft", section_state_draft())
    nav_button("Export", "Export", section_state_export())


# ----------------------------
# Header + Scores
# ----------------------------

items = st.session_state.requirements
company = st.session_state.company
draft = st.session_state.draft

comp_pct = compliance_score(items)
company_pct = company_profile_score(company)
win_pct = win_strength_score(company, items)
overall_pct = overall_progress_score(company, items, draft)

colA, colB, colC, colD = st.columns([2, 1, 1, 1])
with colA:
    st.title("Path.ai — Readiness Console")
    st.caption("Only unresolved items that affect readiness are shown (based on what you've entered).")
with colB:
    st.metric("Compliance", f"{comp_pct}%")
with colC:
    st.metric("Company Profile", f"{company_pct}%")
with colD:
    st.metric("Overall Progress", f"{overall_pct}%")

st.divider()


# ----------------------------
# Pages
# ----------------------------

def page_intake():
    st.subheader("Intake")
    st.write("Upload the RFP/RFI PDF and/or paste text. Then run AI extraction to generate requirements.")

    left, right = st.columns([1, 1])

    with left:
        pdf = st.file_uploader("Upload PDF (optional)", type=["pdf"])
        if pdf is not None:
            raw = pdf.read()
            extracted = extract_pdf_text(raw)
            if extracted and not extracted.startswith("[PDF extract failed"):
                st.success("PDF text extracted. It has been added to the intake text box.")
                # Append (don’t overwrite)
                if extracted not in st.session_state.intake_text:
                    st.session_state.intake_text = (st.session_state.intake_text + "\n\n" + extracted).strip()
            else:
                st.error(extracted)

    with right:
        st.session_state.intake_text = st.text_area(
            "Paste RFP/RFI text here",
            value=st.session_state.intake_text,
            height=320,
        )

    st.divider()

    client = get_openai_client()
    can_ai = client is not None

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("Run AI → Extract Requirements", use_container_width=True, disabled=not can_ai):
            if not st.session_state.intake_text.strip():
                st.error("Paste or upload RFP text first.")
                return

            # Minimal extraction prompt
            prompt = f"""
You are extracting proposal compliance requirements from a government RFP/RFI.

Return JSON ONLY with this shape:
{{
  "requirements": [
    {{
      "id": "REQ-001",
      "text": "requirement statement"
    }}
  ]
}}

RFP TEXT:
{st.session_state.intake_text[:120000]}
""".strip()

            try:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You extract compliance requirements and return strict JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
                content = resp.choices[0].message.content.strip()

                # Best-effort JSON parse
                m = re.search(r"\{.*\}", content, re.S)
                if not m:
                    raise ValueError("AI did not return JSON.")
                data = json.loads(m.group(0))

                reqs = []
                for r in data.get("requirements", []):
                    rid = (r.get("id") or "").strip() or f"REQ-{len(reqs)+1:03d}"
                    txt = (r.get("text") or "").strip()
                    if txt:
                        reqs.append(RequirementItem(id=rid, text=txt))

                st.session_state.requirements = reqs
                st.success(f"Extracted {len(reqs)} requirements. Go to Fix.")
                st.session_state.nav = "Fix"
                st.rerun()

            except Exception as e:
                st.error(f"AI extraction failed: {e}")

    with col2:
        if not can_ai:
            st.warning("AI is disabled because OPENAI_API_KEY is not available in runtime.")
        else:
            st.caption("AI is enabled. Your key is present in the environment (prefix shown in sidebar).")

def page_company():
    st.subheader("Company Profile")
    st.write("Fill what you want the proposal generator to use as your company baseline.")

    c = st.session_state.company

    c["legal_name"] = st.text_input("Legal Business Name", value=c.get("legal_name", ""))
    c["duns_uei"] = st.text_input("UEI (or DUNS if applicable)", value=c.get("duns_uei", ""))
    c["cage"] = st.text_input("CAGE", value=c.get("cage", ""))
    c["naics"] = st.text_input("NAICS", value=c.get("naics", ""))
    c["address"] = st.text_input("Address", value=c.get("address", ""))

    c["capabilities"] = st.text_area("Capabilities Summary", value=c.get("capabilities", ""), height=140)
    c["past_performance"] = st.text_area("Past Performance (brief)", value=c.get("past_performance", ""), height=140)

    st.session_state.company = c

def page_fix():
    st.subheader("Fix — Requirements Checklist")
    if not st.session_state.requirements:
        st.info("No requirements yet. Go to Intake and run AI extraction.")
        return

    st.write("Mark each requirement Pass/Fail/Unknown and add notes. Compliance % updates automatically.")

    for idx, item in enumerate(st.session_state.requirements):
        with st.expander(f"{item.id} — {item.text[:80]}{'...' if len(item.text) > 80 else ''}", expanded=False):
            st.write(item.text)
            cols = st.columns([1, 2])
            with cols[0]:
                item.status = st.selectbox(
                    "Status",
                    ["Unknown", "Pass", "Fail"],
                    index=["Unknown", "Pass", "Fail"].index(item.status if item.status in ("Unknown", "Pass", "Fail") else "Unknown"),
                    key=f"status_{item.id}_{idx}",
                )
            with cols[1]:
                item.notes = st.text_area("Notes / What you need to add", value=item.notes, key=f"notes_{item.id}_{idx}")

    st.session_state.requirements = st.session_state.requirements

def page_draft():
    st.subheader("Draft Proposal")
    st.write("This generates a starter draft. You can edit it after generation.")

    client = get_openai_client()
    can_ai = client is not None

    overall = overall_progress_score(st.session_state.company, st.session_state.requirements, st.session_state.draft)

    if st.button("Generate Draft (AI)", use_container_width=True, disabled=not can_ai):
        if not st.session_state.intake_text.strip():
            st.error("Need intake text first.")
            return

        # Draft generation uses everything known so far (but does NOT gate navigation)
        req_list = "\n".join([f"- {r.id}: {r.text} (status={r.status})" for r in st.session_state.requirements])

        prompt = f"""
You are drafting a compliant, structured proposal response.

Use:
- RFP text
- extracted requirements list
- company profile

Output a well-structured proposal draft with headings:
1. Executive Summary
2. Technical Approach
3. Management Plan
4. Staffing
5. Past Performance
6. Compliance Matrix (table-like markdown)

COMPANY PROFILE:
{json.dumps(st.session_state.company, indent=2)}

REQUIREMENTS:
{req_list}

RFP TEXT:
{st.session_state.intake_text[:120000]}
""".strip()

        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Write proposals in clear government style. No fluff. Be specific."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            st.session_state.draft = resp.choices[0].message.content.strip()
            st.success("Draft created. You can edit below.")
            st.rerun()
        except Exception as e:
            st.error(f"Draft generation failed: {e}")

    st.caption(f"Overall progress is {overall}%. (Export unlocks at 60% + draft exists.)")

    st.session_state.draft = st.text_area("Draft content", value=st.session_state.draft, height=420)

def page_export():
    st.subheader("Export")
    overall = overall_progress_score(st.session_state.company, st.session_state.requirements, st.session_state.draft)
    allowed = export_allowed(overall)

    if not st.session_state.draft.strip():
        st.warning("Generate a draft first (Draft tab).")
        return

    if not allowed:
        st.error(f"EXPORT LOCKED — Need Overall Progress ≥ 60%. Current: {overall}%")
        st.write("Do more in Intake / Company / Fix / Draft to raise progress.")
        return

    st.success("EXPORT UNLOCKED ✅")

    # Simple export options (text download)
    st.download_button(
        "Download Draft as .txt",
        data=st.session_state.draft.encode("utf-8"),
        file_name="path-ai-draft.txt",
        mime="text/plain",
        use_container_width=True,
    )

    # If you want docx export next, we can add python-docx generation here.

# Route
if st.session_state.nav == "Intake":
    page_intake()
elif st.session_state.nav == "Company":
    page_company()
elif st.session_state.nav == "Fix":
    page_fix()
elif st.session_state.nav == "Draft":
    page_draft()
elif st.session_state.nav == "Export":
    page_export()
else:
    page_intake()