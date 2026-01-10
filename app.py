# ==============================
# Path.ai — Federal Proposal Prep
# Single-file Streamlit MVP
# Pages: Dashboard, Upload RFP, Company Info, Fixes, Draft Proposal, Export
# ==============================

import os
import re
import io
import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple

import streamlit as st

# MUST be first Streamlit command
st.set_page_config(
    page_title="Path.ai — Federal Proposal Prep",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Optional deps used by features (keep in requirements.txt):
#   openai
#   pypdf
#   python-docx
#   openpyxl
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    import docx  # python-docx
    from docx.shared import Inches
except Exception:
    docx = None
    Inches = None

try:
    import openpyxl
    from openpyxl.utils import get_column_letter
except Exception:
    openpyxl = None
    get_column_letter = None


# ------------------------------
# Models
# ------------------------------
@dataclass
class RequirementItem:
    id: str
    text: str
    status: str = "Unknown"  # "Unknown" | "Pass" | "Fail"
    notes: str = ""
    source: str = "RFP"      # "RFP" | "User"
    category: str = "General"


@dataclass
class CompanyInfo:
    legal_name: str = ""
    duns_or_uei: str = ""
    cage: str = ""
    address: str = ""
    website: str = ""
    naics: str = ""
    set_asides: str = ""
    capability_summary: str = ""
    differentiators: str = ""
    past_performance: str = ""
    key_personnel: str = ""
    subcontractors: str = ""


# ------------------------------
# Session State
# ------------------------------
def init_state():
    if "page" not in st.session_state:
        st.session_state.page = "Dashboard"

    if "rfp_text" not in st.session_state:
        st.session_state.rfp_text = ""

    if "requirements" not in st.session_state:
        st.session_state.requirements: List[RequirementItem] = []

    if "company" not in st.session_state:
        st.session_state.company = CompanyInfo()

    if "draft" not in st.session_state:
        st.session_state.draft = {
            "outline": "",
            "narrative": "",
            "executive_summary": "",
            "compliance_matrix": [],
        }

    if "ai_settings" not in st.session_state:
        st.session_state.ai_settings = {
            "enabled": True,
            "model": "gpt-4o-mini",
        }

    if "last_analysis" not in st.session_state:
        st.session_state.last_analysis = {
            "ai_used": False,
            "error": "",
        }


init_state()


# ------------------------------
# Helpers
# ------------------------------
def get_openai_client() -> Optional["OpenAI"]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or not OpenAI:
        return None
    try:
        return OpenAI(api_key=key)
    except Exception:
        return None


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    if not PdfReader:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for p in reader.pages:
            try:
                parts.append(p.extract_text() or "")
            except Exception:
                parts.append("")
        return normalize_whitespace("\n".join(parts))
    except Exception:
        return ""


def simple_requirements_from_text(text: str) -> List[RequirementItem]:
    """
    Non-AI fallback requirement extraction.
    Looks for bullets / numbered lines / SHALL / MUST lines.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    picks: List[str] = []

    for l in lines:
        if re.search(r"\b(SHALL|MUST|required|requirement|will provide)\b", l, re.IGNORECASE):
            picks.append(l)
        elif re.match(r"^(\d+\.|\(\d+\)|[•\-])\s+", l):
            picks.append(l)

    # de-dupe + keep reasonable count
    seen = set()
    cleaned = []
    for p in picks:
        k = re.sub(r"\W+", "", p.lower())[:120]
        if k in seen:
            continue
        seen.add(k)
        cleaned.append(p)
        if len(cleaned) >= 40:
            break

    items = []
    for i, t in enumerate(cleaned, start=1):
        items.append(RequirementItem(
            id=f"R{i:03d}",
            text=t[:800],
            status="Unknown",
            source="RFP",
            category="General"
        ))
    return items


def ai_extract_requirements(rfp_text: str) -> List[RequirementItem]:
    """
    Uses OpenAI to extract requirements in a structured list.
    If AI not available, falls back to heuristic extraction.
    """
    client = get_openai_client()
    if not (st.session_state.ai_settings["enabled"] and client):
        st.session_state.last_analysis = {"ai_used": False, "error": ""}
        return simple_requirements_from_text(rfp_text)

    model = st.session_state.ai_settings["model"]
    prompt = f"""
You are a federal proposal compliance assistant.

Task:
Extract the key compliance requirements from the RFP text below.

Return STRICT JSON with this schema:
{{
  "requirements": [
    {{
      "id": "R001",
      "category": "Submission|Technical|Management|Past Performance|Pricing|Security|Other",
      "text": "requirement statement (short, specific, testable)"
    }}
  ]
}}

Rules:
- No commentary. JSON only.
- Prefer fewer, higher-quality, testable requirements.
- Do not invent requirements not present in the text.

RFP TEXT:
{rfp_text[:18000]}
"""

    try:
        resp = client.responses.create(
            model=model,
            input=prompt,
        )
        raw = resp.output_text
        # Try to find JSON object in response
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        payload = json.loads(m.group(0) if m else raw)

        reqs = []
        for idx, r in enumerate(payload.get("requirements", []), start=1):
            rid = r.get("id") or f"R{idx:03d}"
            cat = r.get("category") or "Other"
            txt = (r.get("text") or "").strip()
            if not txt:
                continue
            reqs.append(RequirementItem(
                id=rid,
                text=txt[:800],
                status="Unknown",
                notes="",
                source="RFP",
                category=cat
            ))

        st.session_state.last_analysis = {"ai_used": True, "error": ""}
        return reqs or simple_requirements_from_text(rfp_text)

    except Exception as e:
        st.session_state.last_analysis = {"ai_used": True, "error": str(e)}
        return simple_requirements_from_text(rfp_text)


def company_completion_pct(c: CompanyInfo) -> int:
    fields = [
        c.legal_name, c.duns_or_uei, c.cage, c.address, c.website, c.naics,
        c.set_asides, c.capability_summary, c.differentiators, c.past_performance,
        c.key_personnel
    ]
    filled = sum(1 for f in fields if (f or "").strip())
    return int(round((filled / len(fields)) * 100))


def compliance_pct(items: List[RequirementItem]) -> int:
    if not items:
        return 0
    # Score: Pass=1, Unknown=0.5, Fail=0
    score = 0.0
    for it in items:
        if it.status == "Pass":
            score += 1.0
        elif it.status == "Unknown":
            score += 0.5
        else:
            score += 0.0
    return int(round((score / len(items)) * 100))


def win_strength_pct(c: CompanyInfo, draft: Dict) -> int:
    # Simple heuristic: differentiators + past performance + exec summary + narrative
    pts = 0
    total = 4
    if (c.differentiators or "").strip():
        pts += 1
    if (c.past_performance or "").strip():
        pts += 1
    if (draft.get("executive_summary") or "").strip():
        pts += 1
    if (draft.get("narrative") or "").strip():
        pts += 1
    return int(round((pts / total) * 100))


def overall_progress(comp: int, company: int, win: int) -> int:
    # Weighted: compliance 45%, company 35%, win 20%
    return int(round(comp * 0.45 + company * 0.35 + win * 0.20))


def grade_from_pct(p: int) -> str:
    if p >= 90:
        return "A"
    if p >= 80:
        return "B"
    if p >= 70:
        return "C"
    if p >= 60:
        return "D"
    return "F"


def status_badge(p: int) -> str:
    # text-only badge to keep stable across devices
    if p >= 80:
        return "✅ Ready"
    if p >= 50:
        return "🟠 In Progress"
    return "🔴 Not Ready"


def set_item_status(item_id: str, new_status: str):
    for it in st.session_state.requirements:
        if it.id == item_id:
            it.status = new_status
            return


def unresolved_items(items: List[RequirementItem]) -> List[RequirementItem]:
    return [i for i in items if i.status != "Pass"]


def safe_trim(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


# ------------------------------
# AI Draft Helpers
# ------------------------------
def ai_generate_draft(rfp_text: str, items: List[RequirementItem], company: CompanyInfo) -> Dict:
    client = get_openai_client()
    if not (st.session_state.ai_settings["enabled"] and client):
        return {
            "outline": "AI not enabled or OPENAI_API_KEY missing. Add your key to use Draft Proposal generation.",
            "executive_summary": "",
            "narrative": "",
            "compliance_matrix": [],
        }

    model = st.session_state.ai_settings["model"]

    req_lines = "\n".join([f"- [{r.id}] ({r.category}) {r.text}" for r in items[:60]])
    company_blob = json.dumps(asdict(company), indent=2)

    prompt = f"""
You are a federal proposal writer. Create a strong, compliant draft based on:
- RFP text
- extracted requirements
- company information

Return STRICT JSON:
{{
  "executive_summary": "...",
  "outline": "...",
  "narrative": "...",
  "compliance_matrix": [
    {{"requirement_id":"R001","status":"Pass|Partial|Gap","response_location":"Section X.Y","notes":"..."}}
  ]
}}

Rules:
- Keep it submission-ready tone.
- Don't invent certifications or past performance; use placeholders if missing.
- Make the compliance matrix honest.
- JSON only.

COMPANY:
{company_blob}

REQUIREMENTS:
{req_lines}

RFP TEXT (truncated):
{rfp_text[:12000]}
"""
    try:
        resp = client.responses.create(model=model, input=prompt)
        raw = resp.output_text
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        payload = json.loads(m.group(0) if m else raw)

        return {
            "executive_summary": (payload.get("executive_summary") or "").strip(),
            "outline": (payload.get("outline") or "").strip(),
            "narrative": (payload.get("narrative") or "").strip(),
            "compliance_matrix": payload.get("compliance_matrix") or [],
        }
    except Exception as e:
        return {
            "outline": "",
            "executive_summary": "",
            "narrative": f"AI draft failed: {e}",
            "compliance_matrix": [],
        }


# ------------------------------
# Sidebar (Navigation + Quick Stats)
# ------------------------------
def sidebar():
    items = st.session_state.requirements
    c: CompanyInfo = st.session_state.company
    d = st.session_state.draft

    comp = compliance_pct(items)
    company = company_completion_pct(c)
    win = win_strength_pct(c, d)
    overall = overall_progress(comp, company, win)

    st.sidebar.title("Path.ai")
    st.sidebar.caption("Federal Proposal Prep — MVP")

    # Quick stats
    st.sidebar.markdown("### Quick Stats")
    st.sidebar.metric("Overall", f"{overall}%", delta=f"Grade {grade_from_pct(overall)}")
    st.sidebar.progress(overall / 100)

    col1, col2 = st.sidebar.columns(2)
    col1.metric("Compliance", f"{comp}%")
    col2.metric("Company", f"{company}%")
    st.sidebar.metric("Win Strength", f"{win}%")

    st.sidebar.markdown("---")

    # AI controls
    st.sidebar.markdown("### AI")
    key_present = bool(os.getenv("OPENAI_API_KEY", "").strip())
    st.sidebar.caption(f"API Key: {'✅ detected' if key_present else '❌ missing'}")

    st.session_state.ai_settings["enabled"] = st.sidebar.toggle(
        "Enable AI features",
        value=st.session_state.ai_settings["enabled"],
        help="AI helps extract requirements and draft proposal sections.",
    )
    st.session_state.ai_settings["model"] = st.sidebar.text_input(
        "Model",
        value=st.session_state.ai_settings["model"],
        help="Example: gpt-4o-mini",
    )

    st.sidebar.markdown("---")

    pages = [
        "Dashboard",
        "Upload RFP",
        "Company Info",
        "Fixes",
        "Draft Proposal",
        "Export",
    ]

    st.sidebar.markdown("### Navigate")
    st.session_state.page = st.sidebar.radio(
        "Go to",
        pages,
        index=pages.index(st.session_state.page) if st.session_state.page in pages else 0,
        label_visibility="collapsed",
    )


# ------------------------------
# Pages
# ------------------------------
def page_dashboard():
    st.title("Readiness Console")
    st.caption("A dashboard view of your proposal readiness. No gates. No locking. Just progress.")

    items = st.session_state.requirements
    c: CompanyInfo = st.session_state.company
    d = st.session_state.draft

    comp = compliance_pct(items)
    company = company_completion_pct(c)
    win = win_strength_pct(c, d)
    overall = overall_progress(comp, company, win)

    top1, top2, top3, top4 = st.columns([1.2, 1, 1, 1])
    top1.metric("Overall Progress", f"{overall}%", delta=f"Grade {grade_from_pct(overall)}")
    top2.metric("Compliance", f"{comp}%")
    top3.metric("Company Profile", f"{company}%")
    top4.metric("Win Strength", f"{win}%")

    st.progress(overall / 100)

    st.markdown("---")

    left, right = st.columns([1.2, 0.8], gap="large")

    with left:
        st.subheader("Readiness Snapshot")
        st.write(f"**Status:** {status_badge(overall)}")
        st.write("Only unresolved items that affect readiness are shown below.")

        if not items:
            st.info("No RFP loaded yet. Go to **Upload RFP** to add an RFP and extract requirements.")
            return

        unresolved = unresolved_items(items)
        if not unresolved:
            st.success("All requirements are currently marked as Pass. Nice.")
        else:
            st.write(f"Unresolved items: **{len(unresolved)}**")
            for it in unresolved[:12]:
                st.markdown(f"- **[{it.id}]** ({it.category}) {safe_trim(it.text, 140)} — *{it.status}*")
            if len(unresolved) > 12:
                st.caption(f"+ {len(unresolved) - 12} more in **Fixes**")

    with right:
        st.subheader("What to do next")
        bullets = []
        if not st.session_state.rfp_text.strip():
            bullets.append("Upload an RFP (PDF or text).")
        if items and comp < 80:
            bullets.append("Mark requirements as Pass/Fail and add notes in Fixes.")
        if company < 60:
            bullets.append("Fill out Company Info so the draft is accurate.")
        if not (d.get("narrative") or "").strip():
            bullets.append("Generate a Draft Proposal (AI optional).")
        if not bullets:
            bullets.append("Export your DOCX and Excel compliance matrix.")

        for b in bullets:
            st.write(f"• {b}")

        st.markdown("---")
        st.subheader("System Notes")
        la = st.session_state.last_analysis
        if la.get("ai_used"):
            if la.get("error"):
                st.warning(f"AI attempted but failed: {la['error']}")
            else:
                st.success("AI last run succeeded.")
        else:
            st.info("AI not used for last extraction (either disabled or missing key).")


def page_upload_rfp():
    st.title("Upload RFP")
    st.caption("Upload a PDF or paste text. Then extract requirements (AI or non-AI fallback).")

    colA, colB = st.columns([1, 1], gap="large")

    with colA:
        st.subheader("Upload PDF")
        pdf = st.file_uploader("Choose an RFP PDF", type=["pdf"])
        if pdf:
            if not PdfReader:
                st.error("PDF parsing library not available. Add `pypdf` to requirements.txt.")
            else:
                text = extract_text_from_pdf_bytes(pdf.read())
                if text:
                    st.success(f"Extracted text from PDF ({len(text):,} chars).")
                    st.session_state.rfp_text = text
                else:
                    st.error("Could not extract text from that PDF (might be scanned). Try pasting text.")

    with colB:
        st.subheader("Or paste text")
        st.session_state.rfp_text = st.text_area(
            "RFP text",
            value=st.session_state.rfp_text,
            height=320,
            placeholder="Paste RFP/RFI content here...",
        )

    st.markdown("---")
    st.subheader("Extract Requirements")

    c1, c2, c3 = st.columns([0.9, 1.1, 1.0])
    with c1:
        run = st.button("Extract requirements now", type="primary", use_container_width=True)
    with c2:
        st.caption("AI will be used if enabled and OPENAI_API_KEY is present.")
    with c3:
        st.caption(f"Current requirements: **{len(st.session_state.requirements)}**")

    if run:
        txt = normalize_whitespace(st.session_state.rfp_text)
        if not txt:
            st.error("Add RFP text first (upload PDF or paste).")
        else:
            reqs = ai_extract_requirements(txt)
            st.session_state.requirements = reqs
            st.success(f"Extracted {len(reqs)} requirements.")
            st.session_state.page = "Dashboard"
            st.rerun()

    if st.session_state.requirements:
        st.markdown("### Preview")
        for it in st.session_state.requirements[:12]:
            st.write(f"**[{it.id}]** ({it.category}) {safe_trim(it.text, 180)}")
        if len(st.session_state.requirements) > 12:
            st.caption(f"+ {len(st.session_state.requirements)-12} more")


def page_company_info():
    st.title("Company Info")
    st.caption("This improves draft accuracy and win strength scoring.")

    c: CompanyInfo = st.session_state.company

    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        c.legal_name = st.text_input("Legal business name", value=c.legal_name)
        c.duns_or_uei = st.text_input("UEI (or DUNS if applicable)", value=c.duns_or_uei)
        c.cage = st.text_input("CAGE", value=c.cage)
        c.address = st.text_input("Address", value=c.address)
        c.website = st.text_input("Website", value=c.website)
        c.naics = st.text_input("NAICS codes (comma-separated)", value=c.naics)
        c.set_asides = st.text_input("Set-asides (e.g., SDVOSB)", value=c.set_asides)

    with col2:
        c.capability_summary = st.text_area("Capability summary", value=c.capability_summary, height=120)
        c.differentiators = st.text_area("Differentiators", value=c.differentiators, height=120)
        c.past_performance = st.text_area("Past performance (no inventions)", value=c.past_performance, height=120)
        c.key_personnel = st.text_area("Key personnel", value=c.key_personnel, height=90)
        c.subcontractors = st.text_area("Subcontractors / partners", value=c.subcontractors, height=90)

    st.session_state.company = c

    pct = company_completion_pct(c)
    st.markdown("---")
    st.subheader("Company Profile Completeness")
    st.progress(pct / 100)
    st.write(f"**{pct}%** complete")


def page_fixes():
    st.title("Fixes")
    st.caption("Mark requirements Pass/Fail and add notes. This drives your compliance score.")

    items = st.session_state.requirements
    if not items:
        st.info("No requirements yet. Go to **Upload RFP** to extract them first.")
        return

    # Filters
    colF1, colF2, colF3 = st.columns([1, 1, 1])
    with colF1:
        status_filter = st.selectbox("Status", ["All", "Unknown", "Fail", "Pass"])
    with colF2:
        cat_filter = st.selectbox("Category", ["All"] + sorted(list({i.category for i in items})))
    with colF3:
        search = st.text_input("Search text", value="")

    def match(it: RequirementItem) -> bool:
        if status_filter != "All" and it.status != status_filter:
            return False
        if cat_filter != "All" and it.category != cat_filter:
            return False
        if search.strip():
            s = search.lower().strip()
            if s not in it.text.lower() and s not in it.id.lower():
                return False
        return True

    view = [i for i in items if match(i)]
    st.write(f"Showing **{len(view)}** of **{len(items)}** requirements")

    st.markdown("---")

    for it in view:
        with st.expander(f"[{it.id}] ({it.category}) — {it.status}", expanded=False):
            st.write(it.text)

            c1, c2, c3 = st.columns([0.9, 0.9, 2.2])
            with c1:
                new_status = st.selectbox(
                    "Set status",
                    ["Unknown", "Pass", "Fail"],
                    index=["Unknown", "Pass", "Fail"].index(it.status),
                    key=f"status_{it.id}",
                )
            with c2:
                if st.button("Apply", key=f"apply_{it.id}"):
                    set_item_status(it.id, new_status)
                    st.rerun()
            with c3:
                it.notes = st.text_area("Notes / fix plan", value=it.notes, key=f"notes_{it.id}", height=80)

    st.session_state.requirements = items


def page_draft_proposal():
    st.title("Draft Proposal")
    st.caption("Generate an outline + narrative using your RFP + requirements + company info. AI optional.")

    if not st.session_state.rfp_text.strip():
        st.info("Upload RFP text first in **Upload RFP**.")
        return
    if not st.session_state.requirements:
        st.info("Extract requirements first in **Upload RFP**.")
        return

    c: CompanyInfo = st.session_state.company

    st.subheader("Generate Draft")
    col1, col2 = st.columns([1, 1])
    with col1:
        st.write("This will overwrite your existing draft content.")
    with col2:
        gen = st.button("Generate draft now", type="primary", use_container_width=True)

    if gen:
        with st.spinner("Generating draft..."):
            st.session_state.draft = ai_generate_draft(
                st.session_state.rfp_text,
                st.session_state.requirements,
                c
            )
        st.success("Draft generated.")
        st.rerun()

    d = st.session_state.draft

    st.markdown("---")
    st.subheader("Executive Summary")
    d["executive_summary"] = st.text_area(
        "Edit executive summary",
        value=d.get("executive_summary", ""),
        height=160
    )

    st.subheader("Outline")
    d["outline"] = st.text_area("Edit outline", value=d.get("outline", ""), height=180)

    st.subheader("Narrative")
    d["narrative"] = st.text_area("Edit narrative", value=d.get("narrative", ""), height=320)

    st.session_state.draft = d

    # Compliance matrix preview
    st.markdown("---")
    st.subheader("Compliance Matrix (preview)")
    cm = d.get("compliance_matrix") or []
    if not cm:
        st.caption("No matrix generated yet.")
    else:
        st.dataframe(cm, use_container_width=True)


def build_docx_bytes(company: CompanyInfo, draft: Dict, reqs: List[RequirementItem]) -> bytes:
    if not docx:
        return b""
    doc = docx.Document()
    doc.add_heading("Proposal Draft — Path.ai", level=1)

    doc.add_heading("Company", level=2)
    for k, v in asdict(company).items():
        if (v or "").strip():
            p = doc.add_paragraph()
            p.add_run(f"{k.replace('_',' ').title()}: ").bold = True
            p.add_run(v.strip())

    doc.add_heading("Executive Summary", level=2)
    doc.add_paragraph((draft.get("executive_summary") or "").strip())

    doc.add_heading("Outline", level=2)
    doc.add_paragraph((draft.get("outline") or "").strip())

    doc.add_heading("Narrative", level=2)
    doc.add_paragraph((draft.get("narrative") or "").strip())

    doc.add_heading("Requirements Snapshot", level=2)
    for r in reqs[:80]:
        doc.add_paragraph(f"[{r.id}] ({r.category}) {r.status} — {r.text}")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_xlsx_bytes(reqs: List[RequirementItem], matrix: List[Dict]) -> bytes:
    if not openpyxl:
        return b""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Compliance Matrix"

    headers = ["Requirement ID", "Category", "Requirement Text", "Status", "Notes"]
    ws.append(headers)

    # Create lookup from matrix if present
    m_by_id = {}
    for row in (matrix or []):
        rid = (row.get("requirement_id") or "").strip()
        if rid:
            m_by_id[rid] = row

    for r in reqs:
        m = m_by_id.get(r.id, {})
        status = m.get("status") or r.status
        notes = m.get("notes") or r.notes
        ws.append([r.id, r.category, r.text, status, notes])

    # Auto width (simple)
    for col_idx in range(1, len(headers) + 1):
        col = get_column_letter(col_idx)
        ws.column_dimensions[col].width = 22 if col_idx != 3 else 60

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def page_export():
    st.title("Export")
    st.caption("Download DOCX and Excel. No gating. No locking.")

    if not st.session_state.requirements:
        st.info("You need requirements first. Go to **Upload RFP**.")
        return

    c: CompanyInfo = st.session_state.company
    d = st.session_state.draft
    reqs = st.session_state.requirements

    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        st.subheader("DOCX Proposal Draft")
        if not docx:
            st.error("DOCX export unavailable. Add `python-docx` to requirements.txt.")
        else:
            doc_bytes = build_docx_bytes(c, d, reqs)
            st.download_button(
                "Download Proposal Draft (DOCX)",
                data=doc_bytes,
                file_name="PathAI_Proposal_Draft.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )

    with col2:
        st.subheader("Compliance Matrix (Excel)")
        if not openpyxl:
            st.error("Excel export unavailable. Add `openpyxl` to requirements.txt.")
        else:
            xlsx_bytes = build_xlsx_bytes(reqs, d.get("compliance_matrix") or [])
            st.download_button(
                "Download Compliance Matrix (XLSX)",
                data=xlsx_bytes,
                file_name="PathAI_Compliance_Matrix.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.markdown("---")
    st.subheader("Export Notes")
    st.write("• If AI draft is empty, fill in Draft Proposal manually, then export again.")
    st.write("• If PDF text extraction fails, paste text in Upload RFP.")


# ------------------------------
# App Router
# ------------------------------
def main():
    sidebar()

    page = st.session_state.page

    if page == "Dashboard":
        page_dashboard()
    elif page == "Upload RFP":
        page_upload_rfp()
    elif page == "Company Info":
        page_company_info()
    elif page == "Fixes":
        page_fixes()
    elif page == "Draft Proposal":
        page_draft_proposal()
    elif page == "Export":
        page_export()
    else:
        page_dashboard()


main()