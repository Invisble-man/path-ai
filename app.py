import streamlit as st
import pandas as pd
import sqlite3
import json
import re
import io
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from openpyxl import Workbook


# -----------------------------
# CONFIG
# -----------------------------
APP_NAME = "Path"
APP_VERSION = "v1.2.0"
DB_PATH = "path_state.db"

# Guided path pages (locked flow)
PAGES = ["Task List", "Intake", "Company", "Compliance", "Draft", "Export"]

# Gating labels
GL_ACTIONABLE = "ACTIONABLE"
GL_INFORMATIONAL = "INFORMATIONAL"
GL_IRRELEVANT = "IRRELEVANT"
GL_AUTO = "AUTO_RESOLVED"

# Compliance status
S_PASS = "Pass"
S_FAIL = "Fail"
S_UNKNOWN = "Unknown"

# Buckets (smart grouping)
BUCKETS = [
    "Submission & Format",
    "Required Forms",
    "Volume I – Technical",
    "Volume III – Price/Cost",
    "Attachments/Exhibits",
    "Other",
]

# Keywords/rules (Wave 1 gating – rule-based; AI can replace later)
ACTIONABLE_STRONG = [
    "must", "shall", "required", "offeror shall", "submit", "provide", "complete",
    "include", "fill", "deliver", "due", "deadline", "format", "font", "margin",
    "page limit", "pages", "electronic", "pdf", "excel", "spreadsheet", "sf1449",
    "block", "volume", "technical", "price", "cost", "pricing", "attachment", "exhibit",
    "forms", "representations", "certifications"
]

INFORMATIONAL_HINTS = [
    "background", "purpose", "overview", "the government", "will", "may", "should",
    "intended", "general", "note:", "reference"
]

IRRELEVANT_POST_AWARD = [
    # Common “noise” items you don’t want users touching during proposal prep
    "invoice", "invoicing", "payment", "paid", "warranty", "claims", "disputes",
    "contractor shall bill", "final invoice", "prompt payment", "modification",
    "change request", "deobligate"
]

AUTO_RESOLVE_HINTS = [
    "not applicable", "n/a", "none required", "no action required"
]

# Critical field patterns (missing critical fields engine)
CRITICAL_PATTERNS = {
    "Submission deadline": [
        r"offer due date",
        r"proposal(?:s)?\s+due",
        r"due\s+date",
        r"deadline"
    ],
    "Submission method": [
        r"submit\s+electronically",
        r"email\s+to",
        r"via\s+.*portal",
        r"upload"
    ],
    "File format rules": [
        r"pdf",
        r"editable\s+spreadsheet",
        r"excel",
        r"file\s+format",
        r"font",
        r"margin",
        r"page\s+limit"
    ],
    "SF1449 required blocks": [
        r"sf\s*1449",
        r"block\s+\d+"
    ],
    "Required attachments": [
        r"attachment\s+[a-z0-9]+",
        r"exhibit\s+[a-z0-9]+",
        r"include\s+the\s+following"
    ],
}


# -----------------------------
# DATA MODEL
# -----------------------------
@dataclass
class Item:
    item_id: str
    text: str
    source: str  # e.g., "RFP", "User", "Detected"
    section: str  # e.g., "Submission Instructions"
    bucket: str  # one of BUCKETS
    gating_label: str  # ACTIONABLE / INFORMATIONAL / IRRELEVANT / AUTO_RESOLVED
    confidence: float  # 0..1
    status: str  # Pass / Fail / Unknown
    done: bool  # checkbox only for ACTIONABLE
    is_critical: bool
    notes: str
    created_at: str


# -----------------------------
# DB LAYER
# -----------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            name TEXT,
            created_at TEXT,
            updated_at TEXT,
            intake_json TEXT,
            company_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            run_id TEXT,
            item_id TEXT,
            json TEXT,
            PRIMARY KEY (run_id, item_id)
        )
    """)
    conn.commit()
    return conn


def create_run(run_name: str) -> str:
    run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    now = datetime.utcnow().isoformat()
    conn = db()
    conn.execute(
        "INSERT INTO runs (run_id, name, created_at, updated_at, intake_json, company_json) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, run_name, now, now, json.dumps({}), json.dumps({}))
    )
    conn.commit()
    return run_id


def list_runs() -> List[Tuple[str, str, str]]:
    conn = db()
    rows = conn.execute("SELECT run_id, name, updated_at FROM runs ORDER BY updated_at DESC").fetchall()
    return rows


def load_run_meta(run_id: str) -> Dict:
    conn = db()
    row = conn.execute("SELECT intake_json, company_json, name, created_at, updated_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        return {"intake": {}, "company": {}, "name": "", "created_at": "", "updated_at": ""}
    intake_json, company_json, name, created_at, updated_at = row
    return {
        "intake": json.loads(intake_json or "{}"),
        "company": json.loads(company_json or "{}"),
        "name": name,
        "created_at": created_at,
        "updated_at": updated_at
    }


def save_run_meta(run_id: str, intake: Dict, company: Dict):
    conn = db()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE runs SET intake_json=?, company_json=?, updated_at=? WHERE run_id=?",
        (json.dumps(intake), json.dumps(company), now, run_id)
    )
    conn.commit()


def load_items(run_id: str) -> Dict[str, Item]:
    conn = db()
    rows = conn.execute("SELECT item_id, json FROM items WHERE run_id=?", (run_id,)).fetchall()
    out = {}
    for item_id, j in rows:
        d = json.loads(j)
        out[item_id] = Item(**d)
    return out


def upsert_item(run_id: str, item: Item):
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO items (run_id, item_id, json) VALUES (?, ?, ?)",
        (run_id, item.item_id, json.dumps(asdict(item)))
    )
    conn.commit()


def delete_all_items(run_id: str):
    conn = db()
    conn.execute("DELETE FROM items WHERE run_id=?", (run_id,))
    conn.commit()


# -----------------------------
# UTILS / CLASSIFIER
# -----------------------------
def clean_text(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"\s+", " ", t)
    # remove developer-ish prefixes
    t = re.sub(r"(?i)\battachment mention:\s*", "", t)
    t = re.sub(r"(?i)\bmapped section:\s*", "", t)
    return t


def bucketize(text: str, section: str) -> str:
    s = (section or "").lower()
    t = (text or "").lower()
    if any(k in t for k in ["deadline", "due date", "submit", "format", "font", "margin", "page limit", "electronic", "pdf", "excel", "spreadsheet"]):
        return "Submission & Format"
    if any(k in t for k in ["sf1449", "representations", "certifications", "sam", "cage", "uei", "duns", "blocks"]):
        return "Required Forms"
    if "technical" in t or "volume i" in t:
        return "Volume I – Technical"
    if any(k in t for k in ["price", "cost", "pricing", "volume iii"]):
        return "Volume III – Price/Cost"
    if any(k in t for k in ["attachment", "exhibit", "sow", "addendum"]):
        return "Attachments/Exhibits"
    if "submission" in s:
        return "Submission & Format"
    return "Other"


def classify_gating(text: str) -> Tuple[str, float]:
    """
    Rule-based gating classifier (Wave 1).
    AI will replace this later, but the data model stays the same.
    """
    t = (text or "").lower()

    # Auto-resolve: explicit no-action phrases
    if any(h in t for h in AUTO_RESOLVE_HINTS):
        return (GL_AUTO, 0.85)

    # Irrelevant: post-award admin terms (usually noise during proposal build)
    if any(h in t for h in IRRELEVANT_POST_AWARD):
        # BUT: keep "submit invoice with proposal" style (rare) as actionable
        if "proposal" in t or "offer" in t:
            return (GL_ACTIONABLE, 0.65)
        return (GL_IRRELEVANT, 0.80)

    # Actionable: strong directive language tied to submission
    actionable_hits = sum(1 for k in ACTIONABLE_STRONG if k in t)
    if actionable_hits >= 2:
        # High confidence when directive + submit/format/forms present
        conf = min(0.95, 0.55 + actionable_hits * 0.07)
        return (GL_ACTIONABLE, conf)

    # Informational: generic language, or low directive signal
    info_hits = sum(1 for k in INFORMATIONAL_HINTS if k in t)
    if info_hits >= 1:
        conf = min(0.80, 0.50 + info_hits * 0.10)
        return (GL_INFORMATIONAL, conf)

    # Default: informational but low confidence (we hide it safely in Reference)
    return (GL_INFORMATIONAL, 0.45)


def detect_critical(text: str) -> bool:
    t = (text or "").lower()
    # Critical if it touches deadline/method/format/forms/attachments
    critical_keywords = ["deadline", "due", "offer due", "submit", "file format", "pdf", "excel", "font", "margin", "page limit", "sf1449", "block", "attachment", "exhibit"]
    return any(k in t for k in critical_keywords)


def dedupe_items(items: List[Item]) -> List[Item]:
    """
    Simple dedupe: merge near-exact duplicates by normalized text.
    Later AI can do semantic merge.
    """
    seen = {}
    for it in items:
        key = re.sub(r"[^a-z0-9 ]", "", it.text.lower())
        key = re.sub(r"\s+", " ", key).strip()
        if key in seen:
            # keep the more "actionable" version if conflict
            existing = seen[key]
            priority = {GL_ACTIONABLE: 3, GL_INFORMATIONAL: 2, GL_AUTO: 1, GL_IRRELEVANT: 0}
            if priority[it.gating_label] > priority[existing.gating_label]:
                seen[key] = it
            continue
        seen[key] = it
    return list(seen.values())


# -----------------------------
# EXTRACTION / MISSING CRITICAL FIELDS ENGINE
# -----------------------------
def extract_items_from_text(raw: str) -> List[Tuple[str, str]]:
    """
    Returns list of (section, requirement_text).
    Heuristic: lines with "R###" or bullet-like directives become items.
    """
    raw = raw or ""
    lines = [clean_text(x) for x in raw.splitlines() if clean_text(x)]
    out = []

    current_section = "General"
    for line in lines:
        # Section header heuristic
        if len(line) <= 60 and (line.isupper() or line.endswith(":")):
            current_section = line.replace(":", "").title()
            continue

        # Requirement line heuristic
        if re.match(r"^(R\d{3}|\d+\)|\(\w\)|•|-)\s*", line) or any(w in line.lower() for w in ["shall", "must", "required", "submit", "due"]):
            out.append((current_section, line))

    return out


def build_missing_critical_tasks(sol_text: str) -> List[Item]:
    """
    If we can't detect key fields in the solicitation text, create actionable critical tasks.
    """
    t = (sol_text or "").lower()
    tasks = []
    now = datetime.utcnow().isoformat()

    for name, patterns in CRITICAL_PATTERNS.items():
        found = False
        for p in patterns:
            if re.search(p, t, re.IGNORECASE):
                found = True
                break
        if not found:
            item_id = f"CRIT_{re.sub(r'[^A-Z0-9]+', '_', name.upper())}"
            tasks.append(Item(
                item_id=item_id,
                text=f"Confirm/enter: {name}",
                source="Detected",
                section="Critical Fields",
                bucket="Submission & Format" if "Submission" in name or "File format" in name else "Required Forms",
                gating_label=GL_ACTIONABLE,
                confidence=0.90,
                status=S_UNKNOWN,
                done=False,
                is_critical=True,
                notes="This field was not detected in the solicitation text. Add it manually or verify from the RFP.",
                created_at=now
            ))
    return tasks


# -----------------------------
# KPI / PROGRESS
# -----------------------------
def compute_kpis(items: Dict[str, Item]) -> Dict:
    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        return {
            "completion": 0.0,
            "pass": 0, "fail": 0, "unknown": 0,
            "gate": "GATE NOT RUN",
            "missing_critical": 0
        }

    # Completion: actionable tasks marked done OR status not unknown (either is acceptable)
    completed = [i for i in actionable if (i.done or i.status in [S_PASS, S_FAIL])]
    completion = len(completed) / max(1, len(actionable))

    pass_ct = sum(1 for i in actionable if i.status == S_PASS)
    fail_ct = sum(1 for i in actionable if i.status == S_FAIL)
    unk_ct = sum(1 for i in actionable if i.status == S_UNKNOWN)

    missing_critical = sum(1 for i in actionable if i.is_critical and i.status == S_UNKNOWN and not i.done)

    # Gate rules (strict + simple)
    # You can tune these later.
    if fail_ct > 0:
        gate = "FAIL"
    elif unk_ct > max(2, int(0.10 * len(actionable))):
        gate = "AT RISK"
    else:
        gate = "PASS"

    return {
        "completion": completion,
        "pass": pass_ct,
        "fail": fail_ct,
        "unknown": unk_ct,
        "gate": gate,
        "missing_critical": missing_critical
    }


def chip_color(label: str) -> str:
    # green/yellow/red
    if label in ["PASS", S_PASS]:
        return "#1f7a1f"
    if label in ["AT RISK", S_UNKNOWN, "GATE NOT RUN"]:
        return "#b7791f"
    if label in ["FAIL", S_FAIL]:
        return "#b91c1c"
    return "#374151"


def render_chip(text: str, color: str):
    st.markdown(
        f"""
        <span style="
            display:inline-block;
            padding:6px 10px;
            border-radius:999px;
            background:{color}1A;
            border:1px solid {color}55;
            color:{color};
            font-weight:600;
            font-size:0.9rem;
            margin-right:8px;">
            {text}
        </span>
        """,
        unsafe_allow_html=True
    )


# -----------------------------
# EXPORTS
# -----------------------------
def export_checklist_pdf(items: List[Item]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    y = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, f"{APP_NAME} – Submission Checklist")
    y -= 22
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    y -= 18

    grouped = {}
    for it in items:
        grouped.setdefault(it.bucket, []).append(it)

    for bucket in BUCKETS:
        if bucket not in grouped:
            continue
        c.setFont("Helvetica-Bold", 12)
        y -= 16
        if y < 80:
            c.showPage()
            y = height - 50
        c.drawString(50, y, bucket)

        c.setFont("Helvetica", 10)
        for it in grouped[bucket]:
            y -= 14
            if y < 80:
                c.showPage()
                y = height - 50
            status = it.status
            if it.done and status == S_UNKNOWN:
                status = "Done"
            prefix = "[CRITICAL] " if it.is_critical else ""
            line = f"- {prefix}{it.text}  ({status})"
            c.drawString(60, y, line[:120])

    c.showPage()
    c.save()
    return buf.getvalue()


def export_matrix_csv(items: List[Item]) -> bytes:
    df = pd.DataFrame([{
        "Item ID": it.item_id,
        "Bucket": it.bucket,
        "Section": it.section,
        "Requirement": it.text,
        "Gating": it.gating_label,
        "Confidence": it.confidence,
        "Status": it.status,
        "Done": it.done,
        "Critical": it.is_critical,
        "Notes": it.notes
    } for it in items])
    return df.to_csv(index=False).encode("utf-8")


def export_matrix_xlsx(items: List[Item]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Compliance Matrix"

    headers = ["Item ID", "Bucket", "Section", "Requirement", "Gating", "Confidence", "Status", "Done", "Critical", "Notes"]
    ws.append(headers)

    for it in items:
        ws.append([
            it.item_id, it.bucket, it.section, it.text, it.gating_label,
            float(it.confidence), it.status, bool(it.done), bool(it.is_critical), it.notes
        ])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_zip(pdf_bytes: bytes, csv_bytes: bytes, xlsx_bytes: bytes) -> bytes:
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("01_Submission_Checklist.pdf", pdf_bytes)
        z.writestr("02_Compliance_Matrix.csv", csv_bytes)
        z.writestr("03_Compliance_Matrix.xlsx", xlsx_bytes)
        z.writestr("README.txt", "Export includes only actionable + relevant items.\n")
    return zbuf.getvalue()


# -----------------------------
# UI BUILDING BLOCKS
# -----------------------------
def header(run_meta: Dict, kpis: Dict):
    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0 10px 0;">
          <div style="font-size:1.8rem; font-weight:800;">{APP_NAME}</div>
          <div style="color:#6b7280; font-weight:600;">{APP_VERSION} • {datetime.utcnow().strftime('%b %d, %Y')}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Progress bar (real progress)
    st.progress(float(kpis["completion"]))

    # KPI chips (color-coded)
    col1, col2, col3, col4, col5 = st.columns([1.3, 1, 1, 1.2, 1.4])
    with col1:
        render_chip(f"Completion: {int(kpis['completion']*100)}%", "#2563eb")
    with col2:
        render_chip(f"Pass: {kpis['pass']}", chip_color(S_PASS))
    with col3:
        render_chip(f"Fail: {kpis['fail']}", chip_color(S_FAIL))
    with col4:
        render_chip(f"Unknown: {kpis['unknown']}", chip_color(S_UNKNOWN))
    with col5:
        render_chip(f"Gate: {kpis['gate']}", chip_color(kpis["gate"]))

    if kpis["missing_critical"] > 0:
        st.warning(f"Missing critical fields: {kpis['missing_critical']} (these are top priority).")


def reference_drawer(items: Dict[str, Item]):
    info_items = [i for i in items.values() if i.gating_label == GL_INFORMATIONAL]
    if not info_items:
        return

    with st.expander("Reference (Informational) — collapsed by default", expanded=False):
        st.caption("This area is intentionally hidden by default. It’s reference-only (no checkboxes).")
        q = st.text_input("Search reference", "")
        src_filter = st.selectbox("Filter by source", ["All"] + sorted(list(set(i.source for i in info_items))))
        sec_filter = st.selectbox("Filter by section", ["All"] + sorted(list(set(i.section for i in info_items))))

        filtered = info_items
        if q.strip():
            filtered = [i for i in filtered if q.lower() in i.text.lower()]
        if src_filter != "All":
            filtered = [i for i in filtered if i.source == src_filter]
        if sec_filter != "All":
            filtered = [i for i in filtered if i.section == sec_filter]

        for it in filtered:
            st.markdown(f"**{it.section}** — {it.text}")
            if it.notes:
                st.caption(it.notes)


def render_task_list(items: Dict[str, Item], run_id: str):
    st.subheader("Task List (Home Screen)")
    st.caption("Only ACTIONABLE tasks show here. Everything else is hidden or moved to Reference.")

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        st.info("No actionable tasks yet. Go to Intake and paste/upload solicitation text to generate items.")
        return

    # Smart grouping buckets
    grouped = {}
    for it in actionable:
        grouped.setdefault(it.bucket, []).append(it)

    for bucket in BUCKETS:
        if bucket not in grouped:
            continue
        with st.expander(f"{bucket} ({len(grouped[bucket])})", expanded=(bucket == "Submission & Format")):
            for it in grouped[bucket]:
                left, mid, right = st.columns([0.10, 0.70, 0.20])
                with left:
                    checked = st.checkbox("", value=it.done, key=f"done_{it.item_id}")
                with mid:
                    prefix = "🚩 " if it.is_critical else ""
                    st.markdown(f"{prefix}**{it.text}**")
                    if it.notes:
                        st.caption(it.notes)
                with right:
                    status = st.selectbox(
                        "Status",
                        [S_UNKNOWN, S_PASS, S_FAIL],
                        index=[S_UNKNOWN, S_PASS, S_FAIL].index(it.status),
                        key=f"status_{it.item_id}"
                    )

                # persist changes
                it.done = bool(checked)
                it.status = status
                upsert_item(run_id, it)


def render_compliance(items: Dict[str, Item], run_id: str):
    st.subheader("Compliance")
    st.caption("Mark each actionable requirement Pass/Fail/Unknown. This powers gate and export.")

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        st.info("No actionable compliance items yet. Add items from Intake first.")
        return

    df = pd.DataFrame([{
        "Req ID": it.item_id,
        "Requirement": it.text,
        "Bucket": it.bucket,
        "Critical": "Yes" if it.is_critical else "",
        "Status": it.status
    } for it in actionable])

    st.dataframe(df, use_container_width=True, hide_index=True)

    # Gate check confirmation (kept minimal)
    st.markdown("---")
    st.subheader("Gate Check")
    st.caption("Gate is strict and reads only actionable items.")
    ack = st.checkbox("I acknowledge the detected submission information is correct (verify in the solicitation).", value=False)
    if st.button("Run Gate Check", disabled=(not ack)):
        k = compute_kpis(items)
        if k["gate"] == "PASS":
            st.success("Gate: PASS — ready to proceed.")
        elif k["gate"] == "AT RISK":
            st.warning("Gate: AT RISK — unknown items still exist.")
        else:
            st.error("Gate: FAIL — fix fail items before proceeding.")


def render_intake(run_id: str, run_meta: Dict, items: Dict[str, Item]):
    st.subheader("Intake")
    st.caption("Paste solicitation text (or extracted requirements). We will extract items, clean them, classify relevance, and generate your task list.")

    intake = run_meta.get("intake", {})
    sol_text = st.text_area("Solicitation / RFP text (paste here)", value=intake.get("sol_text", ""), height=220)

    colA, colB, colC = st.columns([1, 1, 1])
    with colA:
        run_name = st.text_input("Proposal run name", value=run_meta.get("name", "My Proposal Run"))
    with colB:
        auto_build = st.checkbox("Auto-build tasks now", value=True)
    with colC:
        reset = st.button("Reset items (danger)")

    if reset:
        st.error("Reset removes all items for this run.")
        confirm = st.checkbox("Yes, delete all items for this run.")
        if confirm:
            delete_all_items(run_id)
            st.success("Items deleted. Refresh the page.")
            return

    if st.button("Save Intake"):
        intake["sol_text"] = sol_text
        save_run_meta(run_id, intake=intake, company=run_meta.get("company", {}))
        st.success("Saved.")

    if auto_build and st.button("Build / Rebuild Task Items"):
        if not sol_text.strip():
            st.warning("Paste solicitation text first.")
            return

        # Extract raw items
        extracted = extract_items_from_text(sol_text)

        # Convert to Item objects + classify
        built: List[Item] = []
        now = datetime.utcnow().isoformat()

        # Include critical missing-field tasks first
        crit_tasks = build_missing_critical_tasks(sol_text)
        built.extend(crit_tasks)

        for idx, (section, raw_req) in enumerate(extracted, start=1):
            txt = clean_text(raw_req)
            gating, conf = classify_gating(txt)

            # Always hide irrelevant; auto-resolve silent
            status = S_UNKNOWN
            done = False
            if gating == GL_AUTO:
                done = True
                status = S_PASS  # silently resolved
            if gating == GL_IRRELEVANT:
                # do not store at all (completely hidden)
                continue

            item_id = f"R{idx:03d}"
            bucket = bucketize(txt, section)

            built.append(Item(
                item_id=item_id,
                text=txt,
                source="RFP",
                section=section,
                bucket=bucket,
                gating_label=gating,
                confidence=float(conf),
                status=status,
                done=done,
                is_critical=detect_critical(txt) or item_id.startswith("CRIT_"),
                notes="",
                created_at=now
            ))

        # Dedupe (reduce noise)
        built = dedupe_items(built)

        # Save (replace all)
        delete_all_items(run_id)
        for it in built:
            upsert_item(run_id, it)

        st.success(f"Built {len(built)} relevant items. ACTIONABLE tasks are now your only checkboxes.")


def render_company(run_id: str, run_meta: Dict):
    st.subheader("Company")
    st.caption("Store company info once. Drafting and exports will use this later (AI will plug in here).")

    company = run_meta.get("company", {})

    company["legal_name"] = st.text_input("Legal company name", value=company.get("legal_name", ""))
    company["uei"] = st.text_input("UEI", value=company.get("uei", ""))
    company["cage"] = st.text_input("CAGE", value=company.get("cage", ""))
    company["naics"] = st.text_input("Primary NAICS", value=company.get("naics", ""))
    company["address"] = st.text_area("Company address", value=company.get("address", ""), height=80)
    company["point_of_contact"] = st.text_input("Point of Contact", value=company.get("point_of_contact", ""))
    company["email"] = st.text_input("Email", value=company.get("email", ""))
    company["phone"] = st.text_input("Phone", value=company.get("phone", ""))

    if st.button("Save Company"):
        save_run_meta(run_id, intake=run_meta.get("intake", {}), company=company)
        st.success("Company info saved.")


def render_draft(run_id: str, run_meta: Dict, items: Dict[str, Item]):
    st.subheader("Draft")
    st.caption("This is where AI drafting will plug in. For now, we provide a clean outline from actionable buckets.")

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        st.info("No actionable items yet. Build items in Intake first.")
        return

    grouped = {}
    for it in actionable:
        grouped.setdefault(it.bucket, []).append(it)

    st.markdown("### Draft Outline (based on actionable tasks)")
    for bucket in BUCKETS:
        if bucket not in grouped:
            continue
        with st.expander(bucket, expanded=(bucket == "Volume I – Technical")):
            for it in grouped[bucket]:
                st.markdown(f"- {it.text}")

    st.markdown("---")
    st.info("AI Drafting comes next: button-per-section to generate technical approach, compliance narratives, and matrices.")


def render_export(run_id: str, run_meta: Dict, items: Dict[str, Item]):
    st.subheader("Export")
    st.caption("Exports include only what’s relevant. We export actionable tasks and statuses.")

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        st.info("No actionable items to export yet.")
        return

    # Only export relevant/actionable content
    pdf_bytes = export_checklist_pdf(actionable)
    csv_bytes = export_matrix_csv(actionable)
    xlsx_bytes = export_matrix_xlsx(actionable)
    zip_bytes = export_zip(pdf_bytes, csv_bytes, xlsx_bytes)

    st.download_button(
        "Download Submission Checklist PDF",
        data=pdf_bytes,
        file_name="Submission_Checklist.pdf",
        mime="application/pdf"
    )

    st.download_button(
        "Download Compliance Matrix CSV",
        data=csv_bytes,
        file_name="Compliance_Matrix.csv",
        mime="text/csv"
    )

    st.download_button(
        "Download Compliance Matrix XLSX",
        data=xlsx_bytes,
        file_name="Compliance_Matrix.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.download_button(
        "Download FULL Export Package (ZIP)",
        data=zip_bytes,
        file_name="Export_Package.zip",
        mime="application/zip"
    )


# -----------------------------
# MAIN APP
# -----------------------------
st.set_page_config(page_title="Path", layout="wide")

# Minimal CSS polish
st.markdown("""
<style>
/* Cleaner typography */
html, body, [class*="css"]  {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
</style>
""", unsafe_allow_html=True)

# Run selector (persistence)
with st.sidebar:
    st.markdown("## Proposal Runs")
    runs = list_runs()

    if "active_run_id" not in st.session_state:
        st.session_state.active_run_id = None

    if st.button("➕ New run"):
        new_name = f"My Proposal Run ({datetime.utcnow().strftime('%Y-%m-%d')})"
        rid = create_run(new_name)
        st.session_state.active_run_id = rid
        st.success("Created new run.")

    run_options = ["(Select a run)"] + [f"{name} — {rid}" for rid, name, _ in runs]
    sel = st.selectbox("Select run", run_options, index=0)

    if sel != "(Select a run)":
        rid = sel.split("—")[-1].strip()
        st.session_state.active_run_id = rid

    st.markdown("---")
    st.caption("Only actionable tasks are interactive. Informational content is hidden in Reference by default.")

run_id = st.session_state.active_run_id
if not run_id:
    st.title("Path")
    st.info("Create or select a proposal run from the left sidebar to begin.")
    st.stop()

run_meta = load_run_meta(run_id)
items = load_items(run_id)

# Compute KPIs always
kpis = compute_kpis(items)

# Header + KPIs + progress
header(run_meta, kpis)

# Horizontal nav (tabs)
tabs = st.tabs(PAGES)

with tabs[0]:
    render_task_list(items, run_id)
    reference_drawer(items)

with tabs[1]:
    render_intake(run_id, run_meta, items)

with tabs[2]:
    render_company(run_id, run_meta)

with tabs[3]:
    # refresh items after potential intake rebuild
    items = load_items(run_id)
    render_compliance(items, run_id)
    reference_drawer(items)

with tabs[4]:
    items = load_items(run_id)
    render_draft(run_id, run_meta, items)

with tabs[5]:
    items = load_items(run_id)
    render_export(run_id, run_meta, items)