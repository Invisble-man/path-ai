import streamlit as st
import re
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Tuple

import pandas as pd

# Exports
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO

APP_NAME = "Path.ai"
APP_VERSION = "v2.0.0"
APP_DATE = datetime.now().strftime("%b %d, %Y")

GATING = ["ACTIONABLE", "INFORMATIONAL", "IRRELEVANT", "AUTO_RESOLVED"]
STATUS = ["Unknown", "Pass", "Fail"]

BUCKETS = [
    "Submission & Format",
    "Required Forms",
    "Volume I – Technical",
    "Volume III – Price/Cost",
    "Attachments/Exhibits",
    "Other",
]

# -----------------------------
# UI Styling (calm + inviting)
# -----------------------------
CSS = """
<style>
.block-container { max-width: 1120px; padding-top: 1.2rem; }

.path-hero{
  border-radius: 18px;
  padding: 18px 18px;
  background: linear-gradient(180deg, rgba(59,130,246,0.10), rgba(34,197,94,0.08));
  border: 1px solid rgba(0,0,0,0.08);
}
.path-brand{
  display:flex; align-items:center; justify-content:space-between; gap:14px;
}
.path-title{ font-size: 40px; font-weight: 900; letter-spacing: -0.8px; }
.path-sub{ opacity: 0.75; margin-top: 6px; font-size: 16px; }
.path-meta{ opacity: 0.7; font-size: 13px; }

.big-btn .stButton button{
  width: 100%;
  padding: 14px 16px !important;
  font-size: 18px !important;
  font-weight: 800 !important;
  border-radius: 14px !important;
}

.chips{ display:flex; gap:10px; flex-wrap:wrap; margin-top: 12px; }
.chip{
  display:inline-flex; align-items:center; gap:8px;
  padding: 10px 14px; border-radius: 999px;
  font-weight: 800;
  border: 1px solid rgba(0,0,0,0.08);
}
.chip small{ font-weight: 700; opacity: 0.85; }
.green{ background: rgba(34,197,94,0.12); color: rgb(18,118,54); }
.yellow{ background: rgba(234,179,8,0.14); color: rgb(146,108,0); }
.red{ background: rgba(239,68,68,0.12); color: rgb(164,33,33); }
.blue{ background: rgba(59,130,246,0.12); color: rgb(20,71,158); }
.gray{ background: rgba(148,163,184,0.16); color: rgb(60,74,95); }

.h2{ font-size: 28px; font-weight: 900; margin-top: 12px; }
.subtle{ opacity: 0.75; }

.task{
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 16px;
  padding: 12px 12px;
  margin-bottom: 10px;
  background: rgba(255,255,255,0.65);
}
.task-top{ display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
.badge{
  font-size: 12px; font-weight: 900;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(0,0,0,0.08);
  background: rgba(59,130,246,0.08);
}
hr.soft{ border:none; border-top:1px solid rgba(0,0,0,0.08); margin: 12px 0; }

/* Tabs look like nav */
.stTabs [data-baseweb="tab-list"] button{
  font-size: 16px !important;
  padding: 12px 14px !important;
  font-weight: 800 !important;
}
</style>
"""

st.set_page_config(page_title=APP_NAME, layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

# -----------------------------
# State
# -----------------------------
def now_iso() -> str:
    return datetime.utcnow().isoformat()

def new_state() -> Dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4())[:8],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "intake": {
            "title": "",
            "agency": "",
            "rfp_number": "",
            "due_date": "",
            "submission_method": "",
            "submission_destination": "",
            "format_rules": "",
            "raw_text": "",
        },
        "company": {
            "name": "",
            "uei": "",
            "cage": "",
            "address": "",
            "poc_name": "",
            "poc_email": "",
            "poc_phone": "",
            "naics": "",
        },
        "items": [],
        "gate": {
            "status": "GATE NOT RUN",
            "last_run_at": None,
        },
    }

def get_state() -> Dict[str, Any]:
    if "state" not in st.session_state:
        st.session_state.state = new_state()
    return st.session_state.state

def save_state():
    st.session_state.state["updated_at"] = now_iso()

# -----------------------------
# Extraction (baseline)
# -----------------------------
REQ_PATTERNS = [
    r"\b(shall|must|required|will be rejected|offer due|proposal shall)\b",
    r"\b(SF ?1449|SF1449)\b",
    r"\b(attachment|exhibit|volume|section)\b",
]

def split_requirements(raw_text: str) -> List[str]:
    """
    Lightweight extraction:
    - split by newlines
    - keep lines with requirement-ish language
    - de-dupe
    """
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    candidates = []
    for l in lines:
        low = l.lower()
        if any(re.search(p, low) for p in REQ_PATTERNS):
            candidates.append(l)

    # de-dupe while preserving order
    seen = set()
    out = []
    for c in candidates:
        key = re.sub(r"\s+", " ", c).strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out[:250]  # safety cap

# -----------------------------
# Relevance gating classifier (rules-based v1)
# -----------------------------
def bucket_for(text: str) -> str:
    t = text.lower()
    if "sf1449" in t or "sf 1449" in t or "block" in t:
        return "Required Forms"
    if "price" in t or "pricing" in t or "cost" in t or "excel" in t or "spreadsheet" in t:
        return "Volume III – Price/Cost"
    if "volume i" in t or "technical" in t or "approach" in t:
        return "Volume I – Technical"
    if "attachment" in t or "exhibit" in t:
        return "Attachments/Exhibits"
    if "due date" in t or "offer due" in t or "deadline" in t or "submit" in t or "format" in t:
        return "Submission & Format"
    return "Other"

def classify_item(text: str) -> Tuple[str, float]:
    """
    Returns (gating_label, confidence).
    This is a strict + conservative first pass.
    """
    t = text.lower()

    # AUTO_RESOLVED: statements that don't require user action (policy/boilerplate)
    if "government shall not be liable" in t or "not liable" in t:
        return ("AUTO_RESOLVED", 0.85)

    # IRRELEVANT: ultra generic or not a requirement (very limited)
    if len(t) < 12:
        return ("IRRELEVANT", 0.75)

    # ACTIONABLE strong signals
    actionable_signals = [
        "shall submit",
        "must be filled",
        "offer due",
        "deadline",
        "submit invoices",
        "will be rejected",
        "proposal shall be submitted",
        "electronic format",
        "clearly marked",
        "attachment",
        "sf1449",
        "block",
        "pricing",
        "price sheet",
        "spreadsheet",
        "file format",
        "font",
        "margin",
    ]
    score = 0
    for s in actionable_signals:
        if s in t:
            score += 1

    # If it includes "shall/must" AND includes a noun target, it's likely actionable
    if ("shall" in t or "must" in t or "required" in t) and score >= 1:
        conf = min(0.55 + 0.08 * score, 0.95)
        return ("ACTIONABLE", conf)

    # INFORMATIONAL (reference only)
    if "shall" in t or "must" in t or "required" in t:
        return ("INFORMATIONAL", 0.55)

    return ("INFORMATIONAL", 0.45)

def build_items(reqs: List[str]) -> List[Dict[str, Any]]:
    items = []
    for i, r in enumerate(reqs, start=1):
        gating_label, conf = classify_item(r)
        b = bucket_for(r)

        # Only actionable needs user status; auto resolved considered "done"
        done = False
        if gating_label == "AUTO_RESOLVED":
            done = True

        items.append({
            "id": f"R{i:03d}",
            "text": r,
            "bucket": b,
            "gating_label": gating_label,
            "confidence": round(conf, 2),
            "status": "Unknown" if gating_label == "ACTIONABLE" else "Unknown",
            "done": done,
            "notes": "",
        })
    return items

# -----------------------------
# KPI + Gate logic
# -----------------------------
def actionable_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [x for x in state["items"] if x["gating_label"] == "ACTIONABLE"]

def counts(state: Dict[str, Any]) -> Dict[str, int]:
    a = actionable_items(state)
    pass_ct = sum(1 for x in a if x["status"] == "Pass")
    fail_ct = sum(1 for x in a if x["status"] == "Fail")
    unk_ct = sum(1 for x in a if x["status"] == "Unknown")
    done_ct = sum(1 for x in a if x.get("done"))
    total = len(a)
    return {"pass": pass_ct, "fail": fail_ct, "unknown": unk_ct, "done": done_ct, "total": total}

def completion_pct(state: Dict[str, Any]) -> float:
    c = counts(state)
    if c["total"] == 0:
        return 0.0
    # completion means: actionable items moved off Unknown OR manually checked done
    completed = sum(1 for x in actionable_items(state) if (x["status"] != "Unknown") or x.get("done"))
    return round(100.0 * completed / c["total"], 1)

def gate_status(state: Dict[str, Any]) -> str:
    c = counts(state)
    if c["total"] == 0:
        return "GATE NOT RUN"
    # strict rules:
    # - Fail must be 0
    # - Unknown must be <= 2
    # - Completion must be >= 90%
    pct = completion_pct(state)
    if c["fail"] == 0 and c["unknown"] <= 2 and pct >= 90:
        return "PASS"
    if c["fail"] > 0:
        return "AT RISK"
    if c["unknown"] > 2:
        return "AT RISK"
    return "AT RISK"

def kpi_chip_class_for_gate(g: str) -> str:
    if g == "PASS":
        return "green"
    if g == "AT RISK":
        return "yellow"
    return "gray"

def chip_class_for_unknown(unk: int) -> str:
    if unk == 0:
        return "green"
    if unk <= 2:
        return "yellow"
    return "red"

def chip_class_for_fail(f: int) -> str:
    if f == 0:
        return "green"
    return "red"

# -----------------------------
# Missing Critical Fields Engine (v1)
# -----------------------------
CRITICAL_FIELDS = [
    ("Due date", lambda s: bool(s["intake"]["due_date"].strip())),
    ("Submission method", lambda s: bool(s["intake"]["submission_method"].strip())),
    ("Submission destination (email/portal)", lambda s: bool(s["intake"]["submission_destination"].strip())),
    ("Company name", lambda s: bool(s["company"]["name"].strip())),
    ("POC email", lambda s: bool(s["company"]["poc_email"].strip())),
]

def ensure_critical_field_tasks(state: Dict[str, Any]):
    """
    Creates top-priority actionable tasks if critical intake/company fields missing.
    De-dupes by stable IDs.
    """
    existing_ids = set(x["id"] for x in state["items"])
    idx = 900  # critical tasks use R900+
    for label, ok_fn in CRITICAL_FIELDS:
        if not ok_fn(state):
            tid = f"R{idx}"
            if tid not in existing_ids:
                state["items"].insert(0, {
                    "id": tid,
                    "text": f"Add missing critical field: {label}",
                    "bucket": "Submission & Format" if "Submission" in label or "Due" in label else "Required Forms",
                    "gating_label": "ACTIONABLE",
                    "confidence": 0.95,
                    "status": "Unknown",
                    "done": False,
                    "notes": "",
                })
            idx += 1

# -----------------------------
# Export
# -----------------------------
def export_checklist_pdf(state: Dict[str, Any]) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, f"{APP_NAME} — Submission Checklist")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 70, f"Run ID: {state['run_id']}   Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    y = height - 100
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Actionable Tasks")
    y -= 18
    c.setFont("Helvetica", 10)

    for item in actionable_items(state):
        line = f"[{'X' if item.get('done') or item['status'] != 'Unknown' else ' '}] {item['id']} ({item['bucket']}) — {item['text']}"
        if len(line) > 120:
            line = line[:117] + "..."
        c.drawString(50, y, line)
        y -= 14
        if y < 60:
            c.showPage()
            y = height - 60
            c.setFont("Helvetica", 10)

    c.showPage()
    c.save()
    return buf.getvalue()

def export_compliance_matrix_df(state: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for x in state["items"]:
        rows.append({
            "id": x["id"],
            "bucket": x["bucket"],
            "gating_label": x["gating_label"],
            "confidence": x["confidence"],
            "status": x["status"],
            "done": x.get("done", False),
            "text": x["text"],
            "notes": x.get("notes", ""),
        })
    return pd.DataFrame(rows)

# -----------------------------
# UX Helpers
# -----------------------------
def hero(state: Dict[str, Any]):
    c = counts(state)
    pct = completion_pct(state)
    gate = state["gate"]["status"]

    st.markdown(
        f"""
        <div class="path-hero">
          <div class="path-brand">
            <div>
              <div class="path-title">{APP_NAME}</div>
              <div class="path-sub">A calm, guided path to a compliant proposal — only what matters, when it matters.</div>
            </div>
            <div class="path-meta">{APP_VERSION} • {APP_DATE}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # progress bar
    st.progress(pct / 100.0)

    # chips
    fail_ct = c["fail"]
    unk_ct = c["unknown"]
    total = c["total"]
    pass_ct = c["pass"]

    gate_class = kpi_chip_class_for_gate(gate)
    fail_class = chip_class_for_fail(fail_ct)
    unk_class = chip_class_for_unknown(unk_ct)

    st.markdown(
        f"""
        <div class="chips">
          <div class="chip blue">Completion: {pct}%</div>
          <div class="chip green">Pass: {pass_ct}</div>
          <div class="chip {fail_class}">Fail: {fail_ct}</div>
          <div class="chip {unk_class}">Unknown: {unk_ct}</div>
          <div class="chip {gate_class}">Gate: {gate}</div>
          <div class="chip gray">Actionable: {total}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def locked_message(need: str):
    st.info(f"🔒 Not yet. Complete **{need}** first — then this step unlocks automatically.")

def intake_complete(state: Dict[str, Any]) -> bool:
    return bool(state["intake"]["raw_text"].strip())

def company_complete(state: Dict[str, Any]) -> bool:
    # minimal: company name + POC email
    return bool(state["company"]["name"].strip()) and bool(state["company"]["poc_email"].strip())

def compliance_ready(state: Dict[str, Any]) -> bool:
    return len(state["items"]) > 0

def draft_ready(state: Dict[str, Any]) -> bool:
    # gate pass OR at least 70% completion
    return completion_pct(state) >= 70

def export_ready(state: Dict[str, Any]) -> bool:
    return state["gate"]["status"] in ["PASS", "AT RISK"] and completion_pct(state) >= 70

# -----------------------------
# Pages
# -----------------------------
def page_task_list(state: Dict[str, Any]):
    st.markdown('<div class="h2">Task List</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">Only tasks that matter show here. Everything else is quietly handled in the background.</div>', unsafe_allow_html=True)

    if not intake_complete(state):
        st.warning("No tasks yet. Start in **Intake** and paste your solicitation text to generate tasks.")
        return

    ensure_critical_field_tasks(state)

    tasks = actionable_items(state)
    if not tasks:
        st.success("Nice — nothing actionable right now.")
        return

    # Smart grouping
    grouped = {b: [] for b in BUCKETS}
    for t in tasks:
        grouped.get(t["bucket"], grouped["Other"]).append(t)

    for b in BUCKETS:
        if not grouped[b]:
            continue
        with st.expander(f"{b} ({len(grouped[b])})", expanded=(b in ["Submission & Format", "Required Forms"])):
            for item in grouped[b]:
                render_actionable_item(item, state)

    # Reference Drawer
    render_reference_drawer(state)

def render_actionable_item(item: Dict[str, Any], state: Dict[str, Any]):
    tid = item["id"]

    st.markdown('<div class="task">', unsafe_allow_html=True)
    top = st.columns([0.15, 0.65, 0.20], vertical_alignment="top")
    with top[0]:
        done_key = f"done_{tid}"
        if done_key not in st.session_state:
            st.session_state[done_key] = bool(item.get("done", False))
        st.session_state[done_key] = st.checkbox("Done", value=st.session_state[done_key], key=done_key, label_visibility="collapsed")
        item["done"] = st.session_state[done_key]

    with top[1]:
        st.markdown(f"**{tid}**  <span class='badge'>{item['bucket']}</span>", unsafe_allow_html=True)
        st.write(item["text"])
        st.caption(f"Confidence: {item['confidence']} • Label: {item['gating_label']}")

    with top[2]:
        status_key = f"status_{tid}"
        if status_key not in st.session_state:
            st.session_state[status_key] = item.get("status", "Unknown")
        st.session_state[status_key] = st.selectbox("Status", STATUS, index=STATUS.index(st.session_state[status_key]), key=status_key)
        item["status"] = st.session_state[status_key]

    notes_key = f"notes_{tid}"
    if notes_key not in st.session_state:
        st.session_state[notes_key] = item.get("notes", "")
    st.session_state[notes_key] = st.text_input("Notes (optional)", value=st.session_state[notes_key], key=notes_key, placeholder="Add a quick note if needed…")
    item["notes"] = st.session_state[notes_key]
    st.markdown("</div>", unsafe_allow_html=True)

def render_reference_drawer(state: Dict[str, Any]):
    info_items = [x for x in state["items"] if x["gating_label"] == "INFORMATIONAL"]
    if not info_items:
        return

    with st.expander(f"Reference (optional) • {len(info_items)} items", expanded=False):
        st.markdown('<div class="subtle">This is supporting information. It’s here if you need it — otherwise ignore it.</div>', unsafe_allow_html=True)
        q = st.text_input("Search reference", value="", placeholder="Search by keyword…")
        filt_bucket = st.selectbox("Filter by section", ["All"] + BUCKETS, index=0)

        shown = info_items
        if q.strip():
            shown = [x for x in shown if q.lower() in x["text"].lower()]
        if filt_bucket != "All":
            shown = [x for x in shown if x["bucket"] == filt_bucket]

        for x in shown[:120]:
            st.write(f"• **{x['id']}** ({x['bucket']}) — {x['text']}")

def page_intake(state: Dict[str, Any]):
    st.markdown('<div class="h2">Intake</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">Paste the solicitation text. Path.ai will extract and organize the work for you.</div>', unsafe_allow_html=True)

    colA, colB = st.columns([0.55, 0.45], vertical_alignment="top")

    with colA:
        state["intake"]["title"] = st.text_input("Solicitation title (optional)", value=state["intake"]["title"])
        state["intake"]["agency"] = st.text_input("Agency (optional)", value=state["intake"]["agency"])
        state["intake"]["rfp_number"] = st.text_input("RFP/RFI number (optional)", value=state["intake"]["rfp_number"])

        state["intake"]["raw_text"] = st.text_area(
            "Paste solicitation text",
            value=state["intake"]["raw_text"],
            height=260,
            placeholder="Paste the RFP/RFI/SOW text here…",
        )

        st.markdown("<div class='big-btn'>", unsafe_allow_html=True)
        if st.button("Generate my tasks", use_container_width=True):
            raw = state["intake"]["raw_text"].strip()
            if not raw:
                st.error("Paste the solicitation text first.")
            else:
                reqs = split_requirements(raw)
                state["items"] = build_items(reqs)
                ensure_critical_field_tasks(state)
                state["gate"]["status"] = "GATE NOT RUN"
                state["gate"]["last_run_at"] = None
                save_state()
                st.success(f"Generated {len(state['items'])} items. Go to Task List to work through the important ones.")

        st.markdown("</div>", unsafe_allow_html=True)

    with colB:
        st.markdown("**Detected submission details (fill what you can):**")
        state["intake"]["due_date"] = st.text_input("Due date", value=state["intake"]["due_date"], placeholder="Example: 2026-02-14 14:00 ET")
        state["intake"]["submission_method"] = st.text_input("Submission method", value=state["intake"]["submission_method"], placeholder="Email / Portal / eOffer / etc.")
        state["intake"]["submission_destination"] = st.text_input("Submission destination", value=state["intake"]["submission_destination"], placeholder="Email address or portal URL")
        state["intake"]["format_rules"] = st.text_area("Format rules (optional)", value=state["intake"]["format_rules"], height=110, placeholder="Fonts, margins, file naming, page limits…")

        st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
        st.markdown("**Save / Load your run**")
        run_json = json.dumps(state, indent=2)

        st.download_button("Download run state (JSON)", data=run_json, file_name=f"pathai_run_{state['run_id']}.json", mime="application/json")

        up = st.file_uploader("Upload run state (JSON)", type=["json"])
        if up is not None:
            try:
                loaded = json.load(up)
                st.session_state.state = loaded
                st.success("Loaded. Your run is back.")
            except Exception:
                st.error("That JSON file couldn’t be loaded.")

    save_state()

def page_company(state: Dict[str, Any]):
    st.markdown('<div class="h2">Company</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">These details make exports and checklists cleaner. Add the basics — you can refine later.</div>', unsafe_allow_html=True)

    cols = st.columns(2, vertical_alignment="top")
    with cols[0]:
        state["company"]["name"] = st.text_input("Company name", value=state["company"]["name"])
        state["company"]["uei"] = st.text_input("UEI (optional)", value=state["company"]["uei"])
        state["company"]["cage"] = st.text_input("CAGE (optional)", value=state["company"]["cage"])
        state["company"]["naics"] = st.text_input("NAICS (optional)", value=state["company"]["naics"])
        state["company"]["address"] = st.text_area("Address (optional)", value=state["company"]["address"], height=90)

    with cols[1]:
        state["company"]["poc_name"] = st.text_input("Point of contact (name)", value=state["company"]["poc_name"])
        state["company"]["poc_email"] = st.text_input("Point of contact (email)", value=state["company"]["poc_email"])
        state["company"]["poc_phone"] = st.text_input("Point of contact (phone)", value=state["company"]["poc_phone"])

    if intake_complete(state):
        ensure_critical_field_tasks(state)

    save_state()

def page_compliance(state: Dict[str, Any]):
    st.markdown('<div class="h2">Compliance</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">Mark each actionable task Pass/Fail/Unknown. This powers Gate + Export.</div>', unsafe_allow_html=True)

    tasks = actionable_items(state)
    if not tasks:
        st.info("No actionable items yet. Go to Intake and generate tasks.")
        return

    # Quick filter
    col1, col2, col3 = st.columns([0.33, 0.33, 0.34])
    with col1:
        bucket = st.selectbox("Filter by section", ["All"] + BUCKETS, index=0)
    with col2:
        status = st.selectbox("Filter by status", ["All"] + STATUS, index=0)
    with col3:
        min_conf = st.slider("Min confidence", 0.0, 1.0, 0.0, 0.05)

    filtered = tasks
    if bucket != "All":
        filtered = [x for x in filtered if x["bucket"] == bucket]
    if status != "All":
        filtered = [x for x in filtered if x["status"] == status]
    filtered = [x for x in filtered if x["confidence"] >= min_conf]

    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    for x in filtered[:200]:
        render_actionable_item(x, state)

    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    st.markdown("<div class='big-btn'>", unsafe_allow_html=True)
    if st.button("Run Gate Check", use_container_width=True):
        state["gate"]["status"] = gate_status(state)
        state["gate"]["last_run_at"] = now_iso()
        save_state()
        if state["gate"]["status"] == "PASS":
            st.success("Gate: PASS — you’re in a strong position to submit.")
        else:
            st.warning("Gate: AT RISK — reduce Unknown items and eliminate any Fail.")
    st.markdown("</div>", unsafe_allow_html=True)

def page_draft(state: Dict[str, Any]):
    st.markdown('<div class="h2">Draft</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">This is where we generate a clean outline + proposal skeleton. (Next upgrade: AI drafting.)</div>', unsafe_allow_html=True)

    st.info("Draft generation is staged next. This version focuses on gating + tasks + compliance + export.")
    st.markdown("**What’s next here:**")
    st.write("• One-click proposal outline (by volumes)")
    st.write("• Auto-filled cover sheet basics")
    st.write("• Draft sections based on your inputs")

def page_export(state: Dict[str, Any]):
    st.markdown('<div class="h2">Export</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">Generate your submission checklist and compliance matrix. Only relevant items are included.</div>', unsafe_allow_html=True)

    df = export_compliance_matrix_df(state)

    colA, colB = st.columns(2, vertical_alignment="top")

    with colA:
        st.markdown("**Submission Checklist (PDF)**")
        pdf_bytes = export_checklist_pdf(state)
        st.download_button("Download Checklist PDF", data=pdf_bytes, file_name=f"pathai_checklist_{state['run_id']}.pdf", mime="application/pdf")

    with colB:
        st.markdown("**Compliance Matrix (CSV / XLSX)**")
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", data=csv, file_name=f"pathai_matrix_{state['run_id']}.csv", mime="text/csv")

        xlsx_buf = BytesIO()
        with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Matrix")
        st.download_button("Download XLSX", data=xlsx_buf.getvalue(), file_name=f"pathai_matrix_{state['run_id']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)

# -----------------------------
# App
# -----------------------------
state = get_state()

# Always keep critical tasks up-to-date once items exist
if intake_complete(state):
    ensure_critical_field_tasks(state)

hero(state)

tabs = st.tabs(["Task List", "Intake", "Company", "Compliance", "Draft", "Export"])

# Tab 0: Home tasks (always available)
with tabs[0]:
    page_task_list(state)

# Tab 1: Intake (always available)
with tabs[1]:
    page_intake(state)

# Tab 2: Company (locked until intake)
with tabs[2]:
    if not intake_complete(state):
        locked_message("Intake")
    else:
        page_company(state)

# Tab 3: Compliance (locked until intake + items)
with tabs[3]:
    if not intake_complete(state):
        locked_message("Intake")
    elif not compliance_ready(state):
        locked_message("Task generation (Intake → Generate my tasks)")
    else:
        page_compliance(state)

# Tab 4: Draft (locked until minimum progress)
with tabs[4]:
    if not intake_complete(state):
        locked_message("Intake")
    elif completion_pct(state) < 70:
        locked_message("more task completion (aim for 70%+)")
    else:
        page_draft(state)

# Tab 5: Export (locked until progress)
with tabs[5]:
    if not intake_complete(state):
        locked_message("Intake")
    elif completion_pct(state) < 70:
        locked_message("more task completion (aim for 70%+)")
    else:
        page_export(state)

save_state()