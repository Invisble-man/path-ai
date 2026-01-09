import io
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from pypdf import PdfReader

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


# =========================
# Path.ai — Single File App
# =========================

APP_NAME = "Path.ai"
APP_VERSION = "v1.3.0"
BUILD_DATE = "Jan 09, 2026"

PAGES = ["Task List", "Intake", "Company", "Compliance", "Draft", "Export"]

GATING_ACTIONABLE = "ACTIONABLE"
GATING_INFO = "INFORMATIONAL"
GATING_IRRELEVANT = "IRRELEVANT"
GATING_AUTO = "AUTO_RESOLVED"

STATUS_UNKNOWN = "Unknown"
STATUS_PASS = "Pass"
STATUS_FAIL = "Fail"

BUCKETS = [
    "Submission & Format",
    "Required Forms",
    "Volume I – Technical",
    "Volume III – Price/Cost",
    "Attachments / Exhibits",
    "Other",
]


# -------------------------
# Data Model
# -------------------------
@dataclass
class Item:
    item_id: str
    requirement: str
    source: str  # e.g., "PDF", "Paste"
    section_hint: str  # rough location hint
    bucket: str
    gating_label: str
    confidence: int  # 0-100
    status: str = STATUS_UNKNOWN
    done: bool = False
    notes: str = ""
    created_ts: str = ""


def now_iso() -> str:
    return datetime.utcnow().isoformat()


# -------------------------
# Styling
# -------------------------
def inject_css():
    st.markdown(
        """
        <style>
        /* Page width + typography */
        .block-container { padding-top: 1.4rem; max-width: 1040px; }
        h1, h2, h3 { letter-spacing: -0.02em; }

        /* Top brand bar */
        .brandbar {
            display:flex; align-items:center; justify-content:space-between;
            padding: 10px 14px;
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 14px;
            background: rgba(255,255,255,0.75);
            backdrop-filter: blur(6px);
            margin-bottom: 12px;
        }
        .brand-left { display:flex; align-items:center; gap:10px; }
        .logo-dot {
            width: 28px; height: 28px; border-radius: 999px;
            background: linear-gradient(135deg, #2F80ED, #27AE60);
            display:inline-block;
        }
        .brand-name { font-weight: 800; font-size: 22px; }
        .brand-meta { color: rgba(0,0,0,0.55); font-size: 13px; }

        /* Nav tabs */
        .navwrap {
            display:flex; gap: 10px; flex-wrap: wrap;
            padding: 8px 10px;
            border-radius: 14px;
            border: 1px solid rgba(0,0,0,0.08);
            background: rgba(255,255,255,0.65);
        }
        .navpill {
            padding: 10px 14px;
            border-radius: 999px;
            border: 1px solid rgba(0,0,0,0.10);
            font-weight: 700;
            cursor: pointer;
            user-select: none;
            background: white;
        }
        .navpill-active {
            background: linear-gradient(135deg, rgba(47,128,237,0.16), rgba(39,174,96,0.16));
            border: 1px solid rgba(47,128,237,0.40);
        }

        /* KPI chips */
        .chiprow { display:flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
        .chip {
            display:inline-flex; align-items:center; gap:10px;
            padding: 10px 14px;
            border-radius: 999px;
            border: 1px solid rgba(0,0,0,0.10);
            font-weight: 800;
            background: white;
        }
        .dot { width:10px; height:10px; border-radius:999px; display:inline-block; }
        .chip-green { background: rgba(39,174,96,0.10); border-color: rgba(39,174,96,0.35); }
        .chip-yellow { background: rgba(242,153,74,0.12); border-color: rgba(242,153,74,0.40); }
        .chip-red { background: rgba(235,87,87,0.10); border-color: rgba(235,87,87,0.35); }

        /* Progress bar */
        .progress-shell {
            width: 100%;
            height: 12px;
            background: rgba(0,0,0,0.06);
            border-radius: 999px;
            overflow: hidden;
            margin: 12px 0 4px 0;
        }
        .progress-fill {
            height: 12px;
            background: linear-gradient(90deg, #2F80ED, #27AE60);
        }
        .muted { color: rgba(0,0,0,0.55); }

        /* Big friendly buttons */
        .stButton button {
            border-radius: 12px !important;
            padding: 0.7rem 1rem !important;
            font-weight: 800 !important;
        }

        /* Cards */
        .card {
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 16px;
            padding: 14px 14px;
            background: rgba(255,255,255,0.70);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -------------------------
# State
# -------------------------
def init_state():
    if "page" not in st.session_state:
        st.session_state.page = "Task List"

    if "run_id" not in st.session_state:
        st.session_state.run_id = f"run_{int(time.time())}"

    if "items" not in st.session_state:
        st.session_state.items: List[Dict] = []

    if "raw_text" not in st.session_state:
        st.session_state.raw_text = ""

    if "source_name" not in st.session_state:
        st.session_state.source_name = ""

    if "company" not in st.session_state:
        st.session_state.company = {
            "legal_name": "",
            "duns_or_uei": "",
            "cage": "",
            "address": "",
            "poc_name": "",
            "poc_email": "",
            "poc_phone": "",
            "naics": "",
            "capabilities": "",
            "past_performance": "",
        }

    if "gate_status" not in st.session_state:
        st.session_state.gate_status = "GATE NOT RUN"

    if "draft_text" not in st.session_state:
        st.session_state.draft_text = ""


# -------------------------
# Utilities
# -------------------------
def safe_id(prefix: str, n: int) -> str:
    return f"{prefix}{n:03d}"


def pdf_to_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    chunks = []
    for page in reader.pages:
        txt = page.extract_text() or ""
        txt = txt.replace("\u00a0", " ")
        chunks.append(txt)
    return "\n".join(chunks).strip()


def normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_candidate_requirements(text: str) -> List[str]:
    """
    Heuristic extraction: grab lines/sentences likely to be requirements.
    We prefer to under-extract than flood the UI.
    """
    text = normalize_text(text)

    # Break into candidate sentences/lines
    lines = []
    for block in text.split("\n"):
        block = block.strip()
        if not block:
            continue
        # further split very long lines into sentences
        if len(block) > 220 and "." in block:
            parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", block) if p.strip()]
            lines.extend(parts)
        else:
            lines.append(block)

    # Filter only likely requirements
    req_lines = []
    req_pattern = re.compile(
        r"\b(shall|must|will|required|requirement|offeror|contractor|submit|provide|deliver|format|deadline|due date|attachment|exhibit|price|pricing|cost|volume)\b",
        re.IGNORECASE,
    )

    for ln in lines:
        if len(ln) < 20:
            continue
        if req_pattern.search(ln):
            req_lines.append(ln)

    # De-duplicate aggressively
    seen = set()
    cleaned = []
    for ln in req_lines:
        key = re.sub(r"[^a-z0-9]+", "", ln.lower())[:180]
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(ln)

    return cleaned[:250]  # hard cap to keep app fast


def infer_section_hint(req: str) -> str:
    r = req.lower()
    if "sf1449" in r or "sf 1449" in r:
        return "SF1449 / Forms"
    if "volume i" in r or "technical" in r:
        return "Volume I – Technical"
    if "volume iii" in r or "price" in r or "pricing" in r or "cost" in r:
        return "Volume III – Price/Cost"
    if "attachment" in r or "exhibit" in r:
        return "Attachments / Exhibits"
    if "deadline" in r or "due date" in r or "submit" in r or "format" in r:
        return "Submission Instructions"
    return "General"


def bucketize(req: str) -> str:
    r = req.lower()
    if any(k in r for k in ["deadline", "due date", "submit", "format", "font", "margin", "file name", "page limit"]):
        return "Submission & Format"
    if any(k in r for k in ["sf1449", "sf 1449", "sam", "uei", "cage", "representations", "certifications", "forms"]):
        return "Required Forms"
    if any(k in r for k in ["volume i", "technical approach", "management approach", "past performance", "staffing"]):
        return "Volume I – Technical"
    if any(k in r for k in ["pricing", "price", "cost", "excel", "spreadsheet", "rate", "labor category"]):
        return "Volume III – Price/Cost"
    if any(k in r for k in ["attachment", "exhibit", "appendix", "resume", "org chart", "sow"]):
        return "Attachments / Exhibits"
    return "Other"


# -------------------------
# Relevance Gating Classifier (Rules + Confidence)
# -------------------------
def classify_gating(req: str) -> Tuple[str, int]:
    """
    RULES:
      ACTIONABLE = user can complete/verify/produce something.
      INFORMATIONAL = reference info; not a task.
      IRRELEVANT = clearly not needed for proposal submission flow.
      AUTO_RESOLVED = true/statement-of-fact that doesn't require user action.
    """
    r = req.lower()

    # Auto-resolved statements (no action possible)
    if any(k in r for k in ["government shall not be liable", "the government is not", "notwithstanding", "reserved rights"]):
        return (GATING_AUTO, 85)

    # Obvious informational references
    if any(k in r for k in ["see attachment", "see exhibit", "refer to", "as defined", "definitions", "background"]):
        return (GATING_INFO, 70)

    # Actionable triggers
    actionable_triggers = [
        "shall submit",
        "must submit",
        "offeror shall",
        "contractor shall",
        "shall provide",
        "must provide",
        "shall include",
        "must include",
        "deadline",
        "due date",
        "file format",
        "page limit",
        "font",
        "margin",
        "pricing",
        "excel spreadsheet",
        "editable spreadsheet",
        "sf1449",
        "sign",
        "initial",
        "complete",
        "fill in",
    ]
    if any(t in r for t in actionable_triggers):
        # confidence boost if it's directive language
        directive = 75
        if "shall" in r or "must" in r:
            directive += 10
        if "submit" in r or "include" in r:
            directive += 5
        return (GATING_ACTIONABLE, min(directive, 95))

    # Irrelevant (rare, but avoid clutter)
    if len(r) < 25:
        return (GATING_IRRELEVANT, 60)

    # Default: informational but lower confidence
    return (GATING_INFO, 55)


# -------------------------
# Missing Critical Fields Engine (Top Priority Tasks)
# -------------------------
def build_critical_tasks(text: str) -> List[str]:
    """
    Creates high-value actionable tasks if we can’t confidently find them in the doc.
    These tasks are ALWAYS useful and keep users from missing submission killers.
    """
    t = text.lower()

    critical = []

    # Submission deadline
    if not any(k in t for k in ["offer due", "due date", "deadline", "offers are due", "proposal due"]):
        critical.append("Confirm the proposal submission DEADLINE (date + time + time zone) from the solicitation.")

    # Submission method
    if not any(k in t for k in ["submit via", "email to", "uploaded to", "submission method", "portal", "eoffer"]):
        critical.append("Confirm the SUBMISSION METHOD (email/portal/address) and where the proposal must be sent.")

    # File format rules
    if not any(k in t for k in ["pdf", "file format", "electronic format", "font", "margins", "page limit"]):
        critical.append("Confirm FILE FORMAT rules (PDF/Word), page limits, font, and margin requirements.")

    # SF1449 / forms
    if not any(k in t for k in ["sf1449", "sf 1449", "standard form 1449"]):
        critical.append("Confirm whether SF1449 (or other required forms) must be completed and included.")

    # Pricing spreadsheet
    if not any(k in t for k in ["excel", "spreadsheet", "price sheet", "editable spreadsheet"]):
        critical.append("Confirm whether pricing must be submitted on an EDITABLE Excel spreadsheet (price sheet).")

    # Required attachments
    if not any(k in t for k in ["attachment", "exhibit", "appendix", "resume", "org chart"]):
        critical.append("Identify REQUIRED attachments/exhibits (SOW, resumes, org chart, past performance, etc.).")

    return critical


# -------------------------
# Build Items From Source
# -------------------------
def generate_items_from_text(text: str, source: str) -> List[Item]:
    candidates = split_candidate_requirements(text)

    items: List[Item] = []
    n = 1

    # Add critical tasks first (high priority)
    critical_tasks = build_critical_tasks(text)
    for ct in critical_tasks:
        items.append(
            Item(
                item_id=safe_id("CRIT_", n),
                requirement=ct,
                source=source,
                section_hint="Critical",
                bucket="Submission & Format",
                gating_label=GATING_ACTIONABLE,
                confidence=92,
                status=STATUS_UNKNOWN,
                done=False,
                notes="",
                created_ts=now_iso(),
            )
        )
        n += 1

    for c in candidates:
        gating, conf = classify_gating(c)
        sec = infer_section_hint(c)
        bucket = bucketize(c)

        # Auto-resolved should be silently marked done
        done = True if gating == GATING_AUTO else False

        items.append(
            Item(
                item_id=safe_id("R", n),
                requirement=c,
                source=source,
                section_hint=sec,
                bucket=bucket,
                gating_label=gating,
                confidence=conf,
                status=STATUS_UNKNOWN if gating == GATING_ACTIONABLE else STATUS_UNKNOWN,
                done=done,
                notes="",
                created_ts=now_iso(),
            )
        )
        n += 1

    return items


# -------------------------
# KPI + Gate Logic
# -------------------------
def get_actionable_items(items: List[Dict]) -> List[Dict]:
    return [i for i in items if i.get("gating_label") == GATING_ACTIONABLE]


def kpi_counts(actionable: List[Dict]) -> Dict[str, int]:
    pass_ct = sum(1 for i in actionable if i.get("status") == STATUS_PASS)
    fail_ct = sum(1 for i in actionable if i.get("status") == STATUS_FAIL)
    unk_ct = sum(1 for i in actionable if i.get("status") == STATUS_UNKNOWN)
    done_ct = sum(1 for i in actionable if i.get("done") is True)
    total = len(actionable)
    return {
        "pass": pass_ct,
        "fail": fail_ct,
        "unknown": unk_ct,
        "done": done_ct,
        "total": total,
    }


def completion_pct(actionable: List[Dict]) -> int:
    if not actionable:
        return 0
    done_ct = sum(1 for i in actionable if i.get("done") is True)
    return int(round((done_ct / len(actionable)) * 100))


def gate_eval(actionable: List[Dict]) -> Tuple[str, str]:
    """
    Strict but usable gate.
    - NOT READY: any Fail > 0
    - AT RISK: Fail == 0 but Unknown > 2 or completion < 90%
    - READY: Fail == 0, Unknown <= 2, completion >= 90%
    """
    c = kpi_counts(actionable)
    comp = completion_pct(actionable)

    if c["total"] == 0:
        return ("GATE NOT RUN", "No actionable tasks exist yet.")

    if c["fail"] > 0:
        return ("NOT READY", "One or more actionable items are marked Fail. Resolve Fail items first.")

    if c["unknown"] > 2 or comp < 90:
        return ("AT RISK", "Unknown items still exist or completion is below 90%. You can proceed, but it’s risky.")

    return ("READY", "Fail = 0, Unknown <= 2, and completion >= 90%. You’re in good shape to submit.")


def chip_style(label: str) -> str:
    if label in ["READY"]:
        return "chip-green"
    if label in ["AT RISK"]:
        return "chip-yellow"
    if label in ["NOT READY"]:
        return "chip-red"
    return "chip-yellow"


# -------------------------
# Exports
# -------------------------
def export_excel(actionable: List[Dict]) -> bytes:
    df = pd.DataFrame(actionable)
    keep_cols = [
        "item_id", "bucket", "section_hint", "requirement",
        "status", "done", "confidence", "notes", "source"
    ]
    for col in keep_cols:
        if col not in df.columns:
            df[col] = ""
    df = df[keep_cols]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Compliance Matrix")
    return output.getvalue()


def export_checklist_pdf(actionable: List[Dict], run_id: str) -> bytes:
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=LETTER)
    width, height = LETTER

    margin = 50
    y = height - margin

    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, f"{APP_NAME} — Submission Checklist")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(margin, y, f"Run: {run_id}    Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    y -= 22

    # Group by bucket
    buckets = {}
    for it in actionable:
        buckets.setdefault(it.get("bucket", "Other"), []).append(it)

    for b in BUCKETS:
        group = buckets.get(b, [])
        if not group:
            continue

        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, y, b)
        y -= 16

        c.setFont("Helvetica", 10)
        for it in group:
            status = it.get("status", STATUS_UNKNOWN)
            done = "✓" if it.get("done") else " "
            text = it.get("requirement", "")
            line = f"[{done}] ({status}) {text}"

            # Wrap lines
            wrap = wrap_text(line, 95)
            for wline in wrap:
                if y < margin + 40:
                    c.showPage()
                    y = height - margin
                    c.setFont("Helvetica", 10)
                c.drawString(margin, y, wline)
                y -= 12

        y -= 10

    c.showPage()
    c.save()
    return output.getvalue()


def wrap_text(text: str, max_chars: int) -> List[str]:
    words = text.split(" ")
    lines = []
    buf = ""
    for w in words:
        if len(buf) + len(w) + 1 <= max_chars:
            buf = (buf + " " + w).strip()
        else:
            if buf:
                lines.append(buf)
            buf = w
    if buf:
        lines.append(buf)
    return lines


def export_state_json() -> bytes:
    payload = {
        "run_id": st.session_state.run_id,
        "page": st.session_state.page,
        "gate_status": st.session_state.gate_status,
        "raw_text": st.session_state.raw_text,
        "source_name": st.session_state.source_name,
        "company": st.session_state.company,
        "items": st.session_state.items,
        "exported_at": now_iso(),
        "app_version": APP_VERSION,
    }
    return json.dumps(payload, indent=2).encode("utf-8")


def import_state_json(file_bytes: bytes):
    payload = json.loads(file_bytes.decode("utf-8"))
    st.session_state.run_id = payload.get("run_id", st.session_state.run_id)
    st.session_state.page = payload.get("page", "Task List")
    st.session_state.gate_status = payload.get("gate_status", "GATE NOT RUN")
    st.session_state.raw_text = payload.get("raw_text", "")
    st.session_state.source_name = payload.get("source_name", "")
    st.session_state.company = payload.get("company", st.session_state.company)
    st.session_state.items = payload.get("items", [])


# -------------------------
# UI Components
# -------------------------
def render_brandbar():
    st.markdown(
        f"""
        <div class="brandbar">
          <div class="brand-left">
            <span class="logo-dot"></span>
            <div>
              <div class="brand-name">{APP_NAME}</div>
              <div class="brand-meta">{APP_VERSION} • {BUILD_DATE}</div>
            </div>
          </div>
          <div class="brand-meta">Run: {st.session_state.run_id}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_nav():
    current = st.session_state.page
    cols = st.columns(len(PAGES))
    for idx, p in enumerate(PAGES):
        with cols[idx]:
            if st.button(p, use_container_width=True, key=f"nav_{p}"):
                st.session_state.page = p


def render_kpis():
    actionable = get_actionable_items(st.session_state.items)
    counts = kpi_counts(actionable)
    comp = completion_pct(actionable)
    gate_label = st.session_state.gate_status

    # Gate color (READY/AT RISK/NOT READY/GATE NOT RUN)
    gate_class = chip_style(gate_label if gate_label != "GATE NOT RUN" else "AT RISK")

    st.markdown(
        f"""
        <div class="progress-shell">
          <div class="progress-fill" style="width:{comp}%;"></div>
        </div>
        <div class="muted">Progress: {comp}% (Actionable tasks completed)</div>

        <div class="chiprow">
          <div class="chip chip-yellow"><span class="dot" style="background:#2F80ED;"></span> Completion: {comp}%</div>
          <div class="chip chip-green"><span class="dot" style="background:#27AE60;"></span> Pass: {counts['pass']}</div>
          <div class="chip chip-red"><span class="dot" style="background:#EB5757;"></span> Fail: {counts['fail']}</div>
          <div class="chip chip-yellow"><span class="dot" style="background:#F2994A;"></span> Unknown: {counts['unknown']}</div>
          <div class="chip {gate_class}"><span class="dot" style="background:#111;"></span> Gate: {gate_label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def ensure_sequence_guard():
    """
    Soft lock sequencing:
    - You can always visit Task List
    - Intake must happen before meaningful Compliance/Draft/Export
    """
    if st.session_state.page in ["Compliance", "Draft", "Export", "Company"] and not st.session_state.items:
        st.info("No items yet. Go to Intake first and upload/paste your solicitation to generate tasks.")
        st.session_state.page = "Intake"


# -------------------------
# Page: Task List (Home Screen)
# -------------------------
def page_task_list():
    st.subheader("Task List (Home Screen)")
    st.caption("Only ACTIONABLE tasks appear here. Everything else is automatically hidden or moved to Reference.")

    actionable = get_actionable_items(st.session_state.items)

    if not actionable:
        st.info("No actionable tasks yet. Go to Intake and paste/upload solicitation text to generate items.")
        return

    # Group by bucket
    by_bucket: Dict[str, List[Dict]] = {}
    for it in actionable:
        by_bucket.setdefault(it.get("bucket", "Other"), []).append(it)

    for b in BUCKETS:
        group = by_bucket.get(b, [])
        if not group:
            continue

        with st.expander(f"{b} ({len(group)})", expanded=(b in ["Submission & Format", "Required Forms"])):
            for i, it in enumerate(group):
                idx = find_item_index(it["item_id"])
                if idx is None:
                    continue

                cols = st.columns([0.08, 0.62, 0.15, 0.15])
                with cols[0]:
                    done = st.checkbox(
                        "",
                        value=st.session_state.items[idx].get("done", False),
                        key=f"done_{it['item_id']}",
                    )
                    st.session_state.items[idx]["done"] = done
                with cols[1]:
                    st.markdown(f"**{it['item_id']}** — {it['requirement']}")
                    st.caption(f"{it.get('section_hint','')} • Confidence: {it.get('confidence',0)}%")
                with cols[2]:
                    status = st.selectbox(
                        "Status",
                        [STATUS_UNKNOWN, STATUS_PASS, STATUS_FAIL],
                        index=[STATUS_UNKNOWN, STATUS_PASS, STATUS_FAIL].index(st.session_state.items[idx].get("status", STATUS_UNKNOWN)),
                        key=f"status_{it['item_id']}",
                        label_visibility="collapsed",
                    )
                    st.session_state.items[idx]["status"] = status
                with cols[3]:
                    notes = st.text_input(
                        "Notes",
                        value=st.session_state.items[idx].get("notes", ""),
                        key=f"notes_{it['item_id']}",
                        label_visibility="collapsed",
                        placeholder="Notes…",
                    )
                    st.session_state.items[idx]["notes"] = notes

    st.divider()

    # Reference Drawer (Informational)
    with st.expander("Reference (collapsed by default)", expanded=False):
        ref = [i for i in st.session_state.items if i.get("gating_label") == GATING_INFO]
        st.caption("Search informational items (no checkboxes).")
        q = st.text_input("Search reference", value="", placeholder="Search keywords…")
        if q.strip():
            ref = [r for r in ref if q.lower() in r.get("requirement", "").lower()]

        if not ref:
            st.info("No informational items available.")
        else:
            for r in ref[:200]:
                st.markdown(f"**{r.get('item_id')}** — {r.get('requirement')}")
                st.caption(f"{r.get('bucket')} • {r.get('section_hint')} • Confidence: {r.get('confidence')}%")
                st.divider()


# -------------------------
# Page: Intake
# -------------------------
def page_intake():
    st.subheader("Intake")
    st.caption("Upload a PDF or paste text. Path.ai will extract requirements, classify relevance, and generate your task list.")

    with st.container(border=True):
        up = st.file_uploader("Upload solicitation PDF", type=["pdf"])
        pasted = st.text_area("Or paste solicitation text", height=200, value=st.session_state.raw_text)

        colA, colB = st.columns([0.5, 0.5])
        with colA:
            do_extract = st.button("Generate Tasks", use_container_width=True)
        with colB:
            reset = st.button("Reset Run", use_container_width=True)

    if reset:
        st.session_state.run_id = f"run_{int(time.time())}"
        st.session_state.items = []
        st.session_state.raw_text = ""
        st.session_state.source_name = ""
        st.session_state.gate_status = "GATE NOT RUN"
        st.session_state.draft_text = ""
        st.success("Run reset.")
        return

    if do_extract:
        text = ""
        source = ""

        if up is not None:
            file_bytes = up.read()
            text = pdf_to_text(file_bytes)
            source = "PDF"
            st.session_state.source_name = up.name
        elif pasted.strip():
            text = pasted.strip()
            source = "Paste"
            st.session_state.source_name = "Pasted text"
        else:
            st.warning("Upload a PDF or paste text first.")
            return

        st.session_state.raw_text = text

        items = generate_items_from_text(text, source=source)
        st.session_state.items = [asdict(i) for i in items]
        st.session_state.gate_status = "GATE NOT RUN"
        st.success(f"Generated {len(st.session_state.items)} items. Go to Task List.")
        st.session_state.page = "Task List"


# -------------------------
# Page: Company
# -------------------------
def page_company():
    st.subheader("Company")
    st.caption("Store your company details once — Path.ai can reuse them across proposals.")

    c = st.session_state.company

    c["legal_name"] = st.text_input("Legal company name", value=c["legal_name"])
    c["duns_or_uei"] = st.text_input("UEI (or DUNS)", value=c["duns_or_uei"])
    c["cage"] = st.text_input("CAGE", value=c["cage"])
    c["address"] = st.text_area("Address", value=c["address"], height=80)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        c["poc_name"] = st.text_input("POC name", value=c["poc_name"])
        c["poc_email"] = st.text_input("POC email", value=c["poc_email"])
    with col2:
        c["poc_phone"] = st.text_input("POC phone", value=c["poc_phone"])
        c["naics"] = st.text_input("NAICS codes", value=c["naics"])

    st.divider()
    c["capabilities"] = st.text_area("Core capabilities (short)", value=c["capabilities"], height=120)
    c["past_performance"] = st.text_area("Past performance highlights (short)", value=c["past_performance"], height=120)

    st.session_state.company = c


# -------------------------
# Page: Compliance (Matrix + Gate)
# -------------------------
def page_compliance():
    st.subheader("Compliance")
    st.caption("Mark actionable requirements Pass/Fail/Unknown. This drives the Gate and exports.")

    actionable = get_actionable_items(st.session_state.items)
    if not actionable:
        st.info("No actionable tasks exist yet. Go to Intake first.")
        return

    # Quick table (editable via controls below)
    st.markdown("#### Actionable Compliance Matrix (editable)")
    for it in actionable[:250]:
        idx = find_item_index(it["item_id"])
        if idx is None:
            continue

        with st.container(border=True):
            st.markdown(f"**{it['item_id']}** — {it['requirement']}")
            st.caption(f"{it.get('bucket')} • {it.get('section_hint')} • Confidence: {it.get('confidence')}%")

            c1, c2, c3 = st.columns([0.18, 0.22, 0.60])
            with c1:
                st.session_state.items[idx]["done"] = st.checkbox(
                    "Done",
                    value=st.session_state.items[idx].get("done", False),
                    key=f"cmp_done_{it['item_id']}",
                )
            with c2:
                st.session_state.items[idx]["status"] = st.selectbox(
                    "Status",
                    [STATUS_UNKNOWN, STATUS_PASS, STATUS_FAIL],
                    index=[STATUS_UNKNOWN, STATUS_PASS, STATUS_FAIL].index(st.session_state.items[idx].get("status", STATUS_UNKNOWN)),
                    key=f"cmp_status_{it['item_id']}",
                )
            with c3:
                st.session_state.items[idx]["notes"] = st.text_input(
                    "Notes",
                    value=st.session_state.items[idx].get("notes", ""),
                    key=f"cmp_notes_{it['item_id']}",
                    placeholder="Optional notes…",
                )

    st.divider()

    colA, colB = st.columns([0.5, 0.5])
    with colA:
        run_gate = st.button("Run Gate Check", use_container_width=True)
    with colB:
        st.download_button(
            "Download current state (JSON)",
            data=export_state_json(),
            file_name=f"{APP_NAME}_{st.session_state.run_id}.json",
            mime="application/json",
            use_container_width=True,
        )

    if run_gate:
        label, reason = gate_eval(actionable)
        st.session_state.gate_status = label
        if label == "READY":
            st.success(f"Gate: {label} — {reason}")
        elif label == "AT RISK":
            st.warning(f"Gate: {label} — {reason}")
        elif label == "NOT READY":
            st.error(f"Gate: {label} — {reason}")
        else:
            st.info(f"Gate: {label} — {reason}")


# -------------------------
# Page: Draft (simple + safe)
# -------------------------
def page_draft():
    st.subheader("Draft")
    st.caption("Creates a clean, structured starting draft from your company profile + task buckets.")

    actionable = get_actionable_items(st.session_state.items)
    if not actionable:
        st.info("No tasks yet. Go to Intake first.")
        return

    if st.button("Generate Draft Outline", use_container_width=True):
        c = st.session_state.company
        by_bucket: Dict[str, List[Dict]] = {}
        for it in actionable:
            by_bucket.setdefault(it.get("bucket", "Other"), []).append(it)

        lines = []
        lines.append(f"# Proposal Draft (Outline) — {APP_NAME}")
        lines.append("")
        lines.append("## Company Overview")
        lines.append(f"- Legal Name: {c.get('legal_name','')}")
        lines.append(f"- UEI/DUNS: {c.get('duns_or_uei','')}")
        lines.append(f"- CAGE: {c.get('cage','')}")
        lines.append(f"- POC: {c.get('poc_name','')} • {c.get('poc_email','')} • {c.get('poc_phone','')}")
        lines.append("")
        lines.append("## Capabilities")
        lines.append(c.get("capabilities","").strip() or "- (Add capabilities)")
        lines.append("")
        lines.append("## Past Performance")
        lines.append(c.get("past_performance","").strip() or "- (Add past performance)")
        lines.append("")
        lines.append("## Compliance Task Buckets (to resolve)")
        for b in BUCKETS:
            group = by_bucket.get(b, [])
            if not group:
                continue
            lines.append(f"### {b}")
            for it in group[:50]:
                status = it.get("status", STATUS_UNKNOWN)
                done = "DONE" if it.get("done") else "OPEN"
                lines.append(f"- [{done} / {status}] {it.get('requirement','')}")
            lines.append("")

        st.session_state.draft_text = "\n".join(lines)

    if st.session_state.draft_text:
        st.markdown(st.session_state.draft_text)


# -------------------------
# Page: Export
# -------------------------
def page_export():
    st.subheader("Export")
    st.caption("Export only what matters: actionable tasks + compliance matrix + checklist PDF.")

    actionable = get_actionable_items(st.session_state.items)
    if not actionable:
        st.info("No actionable tasks exist yet. Go to Intake first.")
        return

    # Excel export
    xlsx = export_excel(actionable)
    st.download_button(
        "Download Compliance Matrix (XLSX)",
        data=xlsx,
        file_name=f"{APP_NAME}_{st.session_state.run_id}_matrix.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    # PDF export
    pdf_bytes = export_checklist_pdf(actionable, st.session_state.run_id)
    st.download_button(
        "Download Submission Checklist (PDF)",
        data=pdf_bytes,
        file_name=f"{APP_NAME}_{st.session_state.run_id}_checklist.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

    st.divider()

    colA, colB = st.columns([0.5, 0.5])
    with colA:
        st.download_button(
            "Download Run State (JSON)",
            data=export_state_json(),
            file_name=f"{APP_NAME}_{st.session_state.run_id}.json",
            mime="application/json",
            use_container_width=True,
        )
    with colB:
        up = st.file_uploader("Upload a saved JSON to restore", type=["json"])
        if up is not None:
            import_state_json(up.read())
            st.success("State restored. Go to Task List.")
            st.session_state.page = "Task List"


# -------------------------
# Helpers
# -------------------------
def find_item_index(item_id: str) -> Optional[int]:
    for i, it in enumerate(st.session_state.items):
        if it.get("item_id") == item_id:
            return i
    return None


# -------------------------
# Main
# -------------------------
def main():
    st.set_page_config(page_title=APP_NAME, page_icon="✅", layout="centered")
    inject_css()
    init_state()

    render_brandbar()
    render_kpis()
    render_nav()
    ensure_sequence_guard()

    # Route
    page = st.session_state.page

    if page == "Task List":
        page_task_list()
    elif page == "Intake":
        page_intake()
    elif page == "Company":
        page_company()
    elif page == "Compliance":
        page_compliance()
    elif page == "Draft":
        page_draft()
    elif page == "Export":
        page_export()
    else:
        st.session_state.page = "Task List"


if __name__ == "__main__":
    main()