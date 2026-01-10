import streamlit as st
import pandas as pd
import sqlite3
import json
import re
import io
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Tuple, Optional

from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill


# =========================================================
# CONFIG
# =========================================================
APP_NAME = "Path.ai"
APP_VERSION = "v1.3.0"
DB_PATH = "path_state.db"

# Locked path (core flow)
PAGES = ["Task List", "Intake", "Company", "Compliance", "Draft", "Export"]

# Gating labels
GL_ACTIONABLE = "ACTIONABLE"
GL_INFORMATIONAL = "INFORMATIONAL"
GL_IRRELEVANT = "IRRELEVANT"
GL_AUTO = "AUTO_RESOLVED"

# Compliance status
S_PASS = "pass"
S_FAIL = "fail"
S_UNKNOWN = "unknown"

# Buckets (calm, human grouping)
BUCKETS = [
    "Submission & Format",
    "Required Forms & Registrations",
    "Technical Requirements",
    "Pricing & Cost",
    "Past Performance",
    "Attachments/Exhibits",
    "Other",
]

# Wave 1 gating — rule-based (AI will replace later)
ACTIONABLE_STRONG = [
    "must", "shall", "required", "offeror shall", "submit", "provide", "complete",
    "include", "fill", "deliver", "due", "deadline", "no later than",
    "format", "font", "margin", "page limit", "pages", "electronic", "pdf", "excel",
    "spreadsheet", "sf1449", "sf-1449", "block", "volume", "technical", "price", "cost",
    "pricing", "attachment", "exhibit", "forms", "representations", "certifications",
    "sam.gov", "uei", "cage"
]

INFORMATIONAL_HINTS = [
    "background", "purpose", "overview", "the government", "will", "may", "should",
    "intended", "general", "note:", "reference", "definitions", "acronyms"
]

# “Noise” that is often post-award administration (hide)
IRRELEVANT_POST_AWARD = [
    "invoice", "invoicing", "payment", "paid", "warranty", "claims", "disputes",
    "contractor shall bill", "final invoice", "prompt payment", "modification",
    "change request", "deobligate", "termination for convenience"
]

AUTO_RESOLVE_HINTS = [
    "not applicable", "n/a", "none required", "no action required"
]

# Missing critical fields engine (creates tasks if not detected)
CRITICAL_PATTERNS = {
    "Submission deadline": [
        r"offer due date",
        r"proposal(?:s)?\s+due",
        r"due\s+date",
        r"deadline",
        r"no later than"
    ],
    "Submission method": [
        r"submit\s+electronically",
        r"email\s+to",
        r"via\s+.*portal",
        r"upload",
        r"submit(?:tal)?\s+through"
    ],
    "File format rules": [
        r"\bpdf\b",
        r"editable\s+spreadsheet",
        r"\bexcel\b",
        r"file\s+format",
        r"\bfont\b",
        r"\bmargin\b",
        r"page\s+limit"
    ],
    "Required forms (SF/attachments)": [
        r"sf\s*1449",
        r"sf-\s*1449",
        r"\bsf\s*\d{3,5}\b",
        r"block\s+\d+",
        r"representations?\s+and\s+certifications?",
        r"reps?\s*&\s*certs?"
    ],
    "Required attachments/exhibits": [
        r"attachment\s+[a-z0-9]+",
        r"exhibit\s+[a-z0-9]+",
        r"include\s+the\s+following",
        r"submit\s+the\s+following"
    ],
}


# =========================================================
# DATA MODEL (matches your expected schema + product needs)
# =========================================================
@dataclass
class Item:
    id: str
    raw_text: str
    normalized_text: str
    source: str
    section: str
    bucket: str
    gating_label: str
    confidence: float
    status: str
    done: bool
    mapped_section: str
    notes: str
    is_critical: bool
    created_at: str


# =========================================================
# DB LAYER (SQLite — same “progress point” architecture)
# =========================================================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            name TEXT,
            created_at TEXT,
            updated_at TEXT,
            intake_json TEXT,
            company_json TEXT,
            workflow_json TEXT
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


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def create_run(run_name: str) -> str:
    run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    now = now_iso()
    conn = db()
    conn.execute(
        "INSERT INTO runs (run_id, name, created_at, updated_at, intake_json, company_json, workflow_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, run_name, now, now, json.dumps({}), json.dumps({}), json.dumps({
            "intake_complete": False,
            "company_complete": False,
            "compliance_complete": False,
            "draft_complete": False
        }))
    )
    conn.commit()
    return run_id


def list_runs() -> List[Tuple[str, str, str]]:
    conn = db()
    rows = conn.execute("SELECT run_id, name, updated_at FROM runs ORDER BY updated_at DESC").fetchall()
    return rows


def load_run_meta(run_id: str) -> Dict:
    conn = db()
    row = conn.execute(
        "SELECT intake_json, company_json, workflow_json, name, created_at, updated_at FROM runs WHERE run_id=?",
        (run_id,)
    ).fetchone()
    if not row:
        return {"intake": {}, "company": {}, "workflow": {}, "name": "", "created_at": "", "updated_at": ""}
    intake_json, company_json, workflow_json, name, created_at, updated_at = row
    return {
        "intake": json.loads(intake_json or "{}"),
        "company": json.loads(company_json or "{}"),
        "workflow": json.loads(workflow_json or "{}"),
        "name": name,
        "created_at": created_at,
        "updated_at": updated_at
    }


def save_run_meta(run_id: str, intake: Dict, company: Dict, workflow: Dict):
    conn = db()
    conn.execute(
        "UPDATE runs SET intake_json=?, company_json=?, workflow_json=?, updated_at=? WHERE run_id=?",
        (json.dumps(intake), json.dumps(company), json.dumps(workflow), now_iso(), run_id)
    )
    conn.commit()


def load_items(run_id: str) -> Dict[str, Item]:
    conn = db()
    rows = conn.execute("SELECT item_id, json FROM items WHERE run_id=?", (run_id,)).fetchall()
    out: Dict[str, Item] = {}
    for item_id, j in rows:
        d = json.loads(j)
        out[item_id] = Item(**d)
    return out


def upsert_item(run_id: str, item: Item):
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO items (run_id, item_id, json) VALUES (?, ?, ?)",
        (run_id, item.id, json.dumps(asdict(item)))
    )
    conn.commit()


def delete_all_items(run_id: str):
    conn = db()
    conn.execute("DELETE FROM items WHERE run_id=?", (run_id,))
    conn.commit()


# =========================================================
# TEXT + PARSING UTILITIES
# =========================================================
def clean_text(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def normalize_text(t: str) -> str:
    t = clean_text(t)
    # strip some common boilerplate prefixes
    t = re.sub(r"(?i)\battachment mention:\s*", "", t)
    t = re.sub(r"(?i)\bmapped section:\s*", "", t)
    return t


def infer_section(line: str) -> str:
    l = line.lower()
    if any(k in l for k in ["deadline", "due date", "no later than", "submit", "submission", "format", "font", "margin", "page limit"]):
        return "Submission"
    if any(k in l for k in ["sf-", "sf1449", "representations", "certifications", "sam.gov", "uei", "cage"]):
        return "Forms & Registration"
    if any(k in l for k in ["past performance", "experience", "references"]):
        return "Past Performance"
    if any(k in l for k in ["price", "pricing", "cost", "rates", "clins", "labor categories"]):
        return "Pricing"
    if any(k in l for k in ["technical", "approach", "method", "pws", "sow", "performance work statement"]):
        return "Technical"
    if any(k in l for k in ["attachment", "exhibit", "appendix"]):
        return "Attachments"
    return "General"


def mapped_section_from_section(section: str) -> str:
    mapping = {
        "Submission": "Volume 1 – Submission / Admin",
        "Forms & Registration": "Forms / Reps & Certs",
        "Technical": "Volume 2 – Technical Approach",
        "Pricing": "Volume 3 – Pricing",
        "Past Performance": "Volume 4 – Past Performance",
        "Attachments": "Attachments / Exhibits",
        "General": "General / Supporting",
    }
    return mapping.get(section, "General / Supporting")


def bucketize(text: str, section: str) -> str:
    t = (text or "").lower()
    s = (section or "").lower()

    if "submission" in s or any(k in t for k in ["deadline", "due", "format", "font", "margin", "page limit", "pdf", "excel", "electronic"]):
        return "Submission & Format"
    if any(k in t for k in ["sf1449", "sf-1449", "representations", "certifications", "sam.gov", "uei", "cage"]):
        return "Required Forms & Registrations"
    if any(k in t for k in ["past performance", "references", "experience"]):
        return "Past Performance"
    if any(k in t for k in ["price", "pricing", "cost", "rates", "labor category", "clins"]):
        return "Pricing & Cost"
    if any(k in t for k in ["technical", "approach", "method", "pws", "sow"]):
        return "Technical Requirements"
    if any(k in t for k in ["attachment", "exhibit", "appendix"]):
        return "Attachments/Exhibits"
    return "Other"


def confidence_score(text: str, gating: str) -> float:
    base = 0.55
    t = (text or "").lower()
    actionable_hits = sum(1 for k in ACTIONABLE_STRONG if k in t)
    info_hits = sum(1 for k in INFORMATIONAL_HINTS if k in t)

    if gating == GL_ACTIONABLE:
        base = min(0.95, 0.55 + actionable_hits * 0.07)
    elif gating == GL_INFORMATIONAL:
        base = min(0.85, 0.45 + info_hits * 0.08)
    elif gating == GL_AUTO:
        base = 0.85
    elif gating == GL_IRRELEVANT:
        base = 0.80

    return float(max(0.30, min(0.99, base)))


def classify_gating(text: str) -> str:
    t = (text or "").lower()

    # auto-resolve
    if any(h in t for h in AUTO_RESOLVE_HINTS):
        return GL_AUTO

    # irrelevant (post-award noise)
    if any(h in t for h in IRRELEVANT_POST_AWARD):
        # keep rare cases that mention proposal/offer
        if "proposal" in t or "offer" in t:
            return GL_ACTIONABLE
        return GL_IRRELEVANT

    # actionable
    hits = sum(1 for k in ACTIONABLE_STRONG if k in t)
    if hits >= 2:
        return GL_ACTIONABLE

    # informational
    if any(h in t for h in INFORMATIONAL_HINTS):
        return GL_INFORMATIONAL

    # default safe: informational (goes into Reference)
    return GL_INFORMATIONAL


def detect_critical(text: str) -> bool:
    t = (text or "").lower()
    critical_keywords = [
        "deadline", "due", "no later than", "submit", "submission", "file format",
        "pdf", "excel", "font", "margin", "page limit", "sf1449", "sf-1449", "block",
        "attachment", "exhibit", "representations", "certifications"
    ]
    return any(k in t for k in critical_keywords)


def dedupe_items(items: List[Item]) -> List[Item]:
    seen: Dict[str, Item] = {}
    priority = {GL_ACTIONABLE: 3, GL_INFORMATIONAL: 2, GL_AUTO: 1, GL_IRRELEVANT: 0}
    for it in items:
        key = re.sub(r"[^a-z0-9 ]", "", it.normalized_text.lower())
        key = re.sub(r"\s+", " ", key).strip()
        if key in seen:
            if priority[it.gating_label] > priority[seen[key].gating_label]:
                seen[key] = it
            continue
        seen[key] = it
    return list(seen.values())


def extract_items_from_text(raw: str) -> List[Tuple[str, str]]:
    """
    Returns list of (section, requirement_text).
    Heuristic: bullet-ish lines or lines with directive language.
    """
    raw = raw or ""
    lines = [clean_text(x) for x in raw.splitlines() if clean_text(x)]
    out: List[Tuple[str, str]] = []

    current_section = "General"
    for line in lines:
        # section header heuristic
        if len(line) <= 70 and (line.isupper() or line.endswith(":")):
            current_section = line.replace(":", "").title()
            continue

        # requirement heuristic
        if re.match(r"^(R\d{2,4}|\d+\)|\(\w\)|•|-)\s*", line) or any(w in line.lower() for w in ["shall", "must", "required", "submit", "deadline", "due"]):
            out.append((current_section, line))

    return out


def build_missing_critical_tasks(sol_text: str) -> List[Item]:
    t = (sol_text or "").lower()
    tasks: List[Item] = []
    created = now_iso()

    for name, patterns in CRITICAL_PATTERNS.items():
        found = False
        for p in patterns:
            if re.search(p, t, re.IGNORECASE):
                found = True
                break
        if not found:
            item_id = f"crit_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}"
            section = "Critical Fields"
            bucket = "Submission & Format" if "submission" in name.lower() or "format" in name.lower() else "Required Forms & Registrations"
            tasks.append(Item(
                id=item_id,
                raw_text=f"Confirm/enter: {name}",
                normalized_text=f"Confirm/enter: {name}",
                source="Detected",
                section=section,
                bucket=bucket,
                gating_label=GL_ACTIONABLE,
                confidence=0.90,
                status=S_UNKNOWN,
                done=False,
                mapped_section=mapped_section_from_section("Submission"),
                notes="This field was not detected. Verify in the RFP and enter it manually.",
                is_critical=True,
                created_at=created
            ))
    return tasks


# =========================================================
# PDF EXTRACTION (new — restores the missing feature)
# =========================================================
def extract_text_from_pdfs(files: List) -> Tuple[str, List[Tuple[str, int]]]:
    combined_parts: List[str] = []
    sources: List[Tuple[str, int]] = []
    for f in files:
        try:
            reader = PdfReader(f)
            pages = len(reader.pages)
            sources.append((getattr(f, "name", "uploaded.pdf"), pages))
            for i in range(pages):
                txt = reader.pages[i].extract_text() or ""
                if txt.strip():
                    combined_parts.append(txt)
        except Exception:
            sources.append((getattr(f, "name", "uploaded.pdf"), 0))
    return "\n".join(combined_parts), sources


# =========================================================
# KPI / GATE / PROGRESS
# =========================================================
def compute_kpis(items: Dict[str, Item]) -> Dict:
    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        return {
            "completion": 0.0,
            "pass": 0, "fail": 0, "unknown": 0,
            "gate": "WAITING",
            "missing_critical": 0,
            "actionable_total": 0,
            "actionable_done": 0
        }

    completed = [i for i in actionable if (i.done or i.status in [S_PASS, S_FAIL])]
    completion = len(completed) / max(1, len(actionable))

    pass_ct = sum(1 for i in actionable if i.status == S_PASS)
    fail_ct = sum(1 for i in actionable if i.status == S_FAIL)
    unk_ct = sum(1 for i in actionable if i.status == S_UNKNOWN)

    missing_critical = sum(1 for i in actionable if i.is_critical and i.status == S_UNKNOWN and not i.done)

    # Gate rules: simple + strict
    if fail_ct > 0:
        gate = "FAIL"
    elif missing_critical > 0:
        gate = "AT RISK"
    elif unk_ct > max(2, int(0.10 * len(actionable))):
        gate = "AT RISK"
    else:
        gate = "PASS"

    return {
        "completion": float(completion),
        "pass": int(pass_ct),
        "fail": int(fail_ct),
        "unknown": int(unk_ct),
        "gate": gate,
        "missing_critical": int(missing_critical),
        "actionable_total": len(actionable),
        "actionable_done": len([i for i in actionable if i.done])
    }


def workflow_unlocks(run_meta: Dict, items: Dict[str, Item]) -> Dict[str, bool]:
    """
    Locked flow:
      - Intake unlocks after at least one build event (workflow.intake_complete)
      - Company unlocks after intake_complete
      - Compliance unlocks after company_complete
      - Draft unlocks after compliance_complete
      - Export unlocks after draft_complete
    We also auto-update compliance_complete when completion >= 60% and no FAIL items.
    """
    workflow = run_meta.get("workflow", {}) or {}
    intake_ok = bool(workflow.get("intake_complete", False))
    company_ok = bool(workflow.get("company_complete", False))
    compliance_ok = bool(workflow.get("compliance_complete", False))
    draft_ok = bool(workflow.get("draft_complete", False))

    kpis = compute_kpis(items)
    # auto-advance compliance when user is meaningfully done and not failing
    if intake_ok and company_ok and (kpis["actionable_total"] > 0):
        if (kpis["completion"] >= 0.60) and (kpis["gate"] != "FAIL"):
            compliance_ok = True
            workflow["compliance_complete"] = True

    # persist any auto update
    run_meta["workflow"] = workflow

    return {
        "Task List": True,
        "Intake": True,
        "Company": intake_ok,
        "Compliance": intake_ok and company_ok,
        "Draft": intake_ok and company_ok and compliance_ok,
        "Export": intake_ok and company_ok and compliance_ok and draft_ok,
    }


# =========================================================
# EXPORTS (restores + expands your export set)
# =========================================================
def style_xlsx_header(ws, row=1):
    fill = PatternFill("solid", fgColor="EEF2FF")
    for cell in ws[row]:
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)


def autosize_ws(ws, max_width=65):
    for col in ws.columns:
        max_len = 10
        col_letter = col[0].column_letter
        for cell in col:
            if cell.value:
                max_len = max(max_len, min(max_width, len(str(cell.value))))
        ws.column_dimensions[col_letter].width = max_len + 2


def export_xlsx_compliance_matrix(items: List[Item]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Compliance Matrix"

    ws.append([
        "id", "section", "mapped_section", "normalized_text",
        "gating_label", "confidence", "status", "done",
        "source", "bucket", "is_critical", "notes"
    ])

    for it in items:
        ws.append([
            it.id, it.section, it.mapped_section, it.normalized_text,
            it.gating_label, float(it.confidence), it.status, bool(it.done),
            it.source, it.bucket, bool(it.is_critical), it.notes
        ])

    style_xlsx_header(ws)
    autosize_ws(ws)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_xlsx_task_list(items: List[Item]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Task List"

    actionable = [i for i in items if i.gating_label == GL_ACTIONABLE]
    actionable = sorted(actionable, key=lambda x: (x.bucket, -x.confidence))

    ws.append(["done", "bucket", "task", "mapped_section", "confidence", "status", "source", "id", "critical"])
    for it in actionable:
        ws.append([
            "YES" if it.done else "NO",
            it.bucket,
            it.normalized_text,
            it.mapped_section,
            float(it.confidence),
            it.status,
            it.source,
            it.id,
            "YES" if it.is_critical else "NO"
        ])

    style_xlsx_header(ws)
    autosize_ws(ws)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_xlsx_gap_report(items: List[Item]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Gap Report"

    actionable = [i for i in items if i.gating_label == GL_ACTIONABLE]
    gaps = [i for i in actionable if not i.done and i.status != S_PASS]

    ws.append(["gap", "bucket", "task", "mapped_section", "confidence", "status", "source", "id", "critical"])
    for it in gaps:
        ws.append([
            "OPEN",
            it.bucket,
            it.normalized_text,
            it.mapped_section,
            float(it.confidence),
            it.status,
            it.source,
            it.id,
            "YES" if it.is_critical else "NO"
        ])

    style_xlsx_header(ws)
    autosize_ws(ws)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def pdf_write_wrapped(c: canvas.Canvas, x: int, y: int, text: str, max_chars: int = 100, line_height: int = 14) -> int:
    words = text.split()
    line = []
    cur = 0
    for w in words:
        if cur + len(w) + 1 > max_chars:
            c.drawString(x, y, " ".join(line))
            y -= line_height
            line = [w]
            cur = len(w)
        else:
            line.append(w)
            cur += len(w) + 1
    if line:
        c.drawString(x, y, " ".join(line))
        y -= line_height
    return y


def export_pdf_submission_checklist(items: List[Item], run_name: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    y = height - 54
    c.setFont("Helvetica-Bold", 16)
    c.drawString(48, y, f"{APP_NAME} — Submission Checklist")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(48, y, f"Run: {run_name}")
    y -= 14
    c.drawString(48, y, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    y -= 22

    actionable = [i for i in items if i.gating_label == GL_ACTIONABLE]
    grouped: Dict[str, List[Item]] = {}
    for it in actionable:
        grouped.setdefault(it.bucket, []).append(it)

    for bucket in BUCKETS:
        if bucket not in grouped:
            continue
        if y < 100:
            c.showPage()
            y = height - 54
        c.setFont("Helvetica-Bold", 12)
        c.drawString(48, y, bucket)
        y -= 18
        c.setFont("Helvetica", 10)
        for it in grouped[bucket]:
            if y < 80:
                c.showPage()
                y = height - 54
                c.setFont("Helvetica", 10)
            box = "[x]" if (it.done or it.status == S_PASS) else "[ ]"
            prefix = "CRITICAL: " if it.is_critical else ""
            line = f"{box} {prefix}{it.normalized_text}"
            y = pdf_write_wrapped(c, 58, y, line, max_chars=108)
            y -= 2

    c.showPage()
    c.save()
    return buf.getvalue()


def export_pdf_gate_report(items: List[Item], run_name: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    k = compute_kpis({i.id: i for i in items})
    y = height - 54
    c.setFont("Helvetica-Bold", 16)
    c.drawString(48, y, f"{APP_NAME} — Gate Report")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(48, y, f"Run: {run_name}")
    y -= 14
    c.drawString(48, y, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(48, y, "Summary")
    y -= 16
    c.setFont("Helvetica", 10)
    c.drawString(48, y, f"Gate: {k['gate']}")
    y -= 14
    c.drawString(48, y, f"Completion: {int(k['completion']*100)}%")
    y -= 14
    c.drawString(48, y, f"Pass/Fail/Unknown: {k['pass']}/{k['fail']}/{k['unknown']}")
    y -= 14
    c.drawString(48, y, f"Missing critical fields: {k['missing_critical']}")
    y -= 24

    c.setFont("Helvetica-Bold", 12)
    c.drawString(48, y, "Top open gaps (actionable not yet done)")
    y -= 18
    c.setFont("Helvetica", 10)

    actionable = [i for i in items if i.gating_label == GL_ACTIONABLE]
    gaps = [i for i in actionable if (not i.done and i.status != S_PASS)]
    gaps = sorted(gaps, key=lambda x: (0 if x.is_critical else 1, x.bucket, -x.confidence))

    if not gaps:
        c.drawString(48, y, "✅ No open gaps detected in actionable items.")
        y -= 14
    else:
        for it in gaps[:60]:
            if y < 80:
                c.showPage()
                y = height - 54
                c.setFont("Helvetica", 10)
            prefix = "CRITICAL: " if it.is_critical else ""
            y = pdf_write_wrapped(c, 52, y, f"• {prefix}{it.normalized_text}", max_chars=112)

    c.showPage()
    c.save()
    return buf.getvalue()


def export_pdf_compliance_summary(items: List[Item], run_name: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    k = compute_kpis({i.id: i for i in items})
    state = "ON TRACK" if k["completion"] >= 0.80 and k["gate"] != "FAIL" else ("IN PROGRESS" if k["completion"] >= 0.40 else "BLOCKED")

    y = height - 54
    c.setFont("Helvetica-Bold", 16)
    c.drawString(48, y, f"{APP_NAME} — Compliance Summary")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(48, y, f"Run: {run_name}")
    y -= 14
    c.drawString(48, y, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    y -= 24

    c.setFont("Helvetica-Bold", 12)
    c.drawString(48, y, "Overall readiness")
    y -= 16
    c.setFont("Helvetica", 10)
    c.drawString(48, y, f"Status: {state}")
    y -= 14
    c.drawString(48, y, f"Gate: {k['gate']}")
    y -= 14
    c.drawString(48, y, f"Completion: {int(k['completion']*100)}%")
    y -= 22

    c.setFont("Helvetica-Bold", 12)
    c.drawString(48, y, "Counts")
    y -= 16
    c.setFont("Helvetica", 10)
    c.drawString(48, y, f"Actionable total: {k['actionable_total']}")
    y -= 14
    c.drawString(48, y, f"Pass: {k['pass']}   Fail: {k['fail']}   Unknown: {k['unknown']}")
    y -= 14
    c.drawString(48, y, f"Missing critical: {k['missing_critical']}")
    y -= 22

    c.showPage()
    c.save()
    return buf.getvalue()


def export_zip_package(run_name: str, pdf1: bytes, pdf2: bytes, pdf3: bytes, xlsx1: bytes, xlsx2: bytes, xlsx3: bytes) -> bytes:
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("01_Submission_Checklist.pdf", pdf1)
        z.writestr("02_Gate_Report.pdf", pdf2)
        z.writestr("03_Compliance_Summary.pdf", pdf3)
        z.writestr("04_Compliance_Matrix.xlsx", xlsx1)
        z.writestr("05_Task_List.xlsx", xlsx2)
        z.writestr("06_Gap_Report.xlsx", xlsx3)
        z.writestr("README.txt", f"{APP_NAME} export package for run: {run_name}\nIncludes only relevant items (ACTIONABLE + REFERENCE).\n")
    return zbuf.getvalue()


# =========================================================
# UI BUILDING BLOCKS (no enterprise UI, calm + clear)
# =========================================================
def render_header(run_meta: Dict, kpis: Dict):
    st.title(APP_NAME)
    st.caption(f"{APP_VERSION} • Calm, guided proposal compliance")

    # Real progress bar
    st.progress(float(kpis["completion"]))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Completion", f"{int(kpis['completion']*100)}%")
    with c2:
        st.metric("Actionable", kpis["actionable_total"])
    with c3:
        st.metric("Open gaps", max(0, kpis["actionable_total"] - kpis["pass"] - kpis["actionable_done"]))
    with c4:
        st.metric("Missing critical", kpis["missing_critical"])

    # Gate status block
    if kpis["gate"] == "PASS":
        st.success("Gate: PASS — you’re in good shape.")
    elif kpis["gate"] == "AT RISK":
        st.warning("Gate: AT RISK — some key fields are missing or unknown.")
    elif kpis["gate"] == "FAIL":
        st.error("Gate: FAIL — resolve failed items before export.")
    else:
        st.info("Upload an RFP (or paste text) in Intake to generate your task list.")


def reference_drawer(items: Dict[str, Item]):
    info_items = [i for i in items.values() if i.gating_label == GL_INFORMATIONAL]
    if not info_items:
        return

    with st.expander("Reference (Informational) — hidden by default", expanded=False):
        st.caption("These items are not tasks. They’re stored for context and traceability.")
        q = st.text_input("Search reference", "")
        srcs = sorted(list(set(i.source for i in info_items)))
        secs = sorted(list(set(i.section for i in info_items)))
        src_filter = st.selectbox("Source", ["All"] + srcs)
        sec_filter = st.selectbox("Section", ["All"] + secs)

        filtered = info_items
        if q.strip():
            filtered = [i for i in filtered if q.lower() in i.normalized_text.lower()]
        if src_filter != "All":
            filtered = [i for i in filtered if i.source == src_filter]
        if sec_filter != "All":
            filtered = [i for i in filtered if i.section == sec_filter]

        for it in filtered[:300]:
            st.write(f"• **{it.section}** — {it.normalized_text}")


def render_locked(message: str):
    st.info(f"🔒 {message}")


# =========================================================
# CORE SCREENS
# =========================================================
def render_task_list(items: Dict[str, Item], run_id: str):
    st.subheader("Task List")
    st.caption("Only ACTIONABLE items show here. Everything else stays out of your way.")

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        st.info("No actionable tasks yet. Go to Intake and upload PDFs or paste solicitation text.")
        return

    # group by bucket
    grouped: Dict[str, List[Item]] = {}
    for it in actionable:
        grouped.setdefault(it.bucket, []).append(it)

    # show critical buckets expanded first
    for bucket in BUCKETS:
        if bucket not in grouped:
            continue
        bucket_items = grouped[bucket]
        bucket_items = sorted(bucket_items, key=lambda x: (0 if x.is_critical else 1, x.done, -x.confidence))

        expanded = bucket in ["Submission & Format", "Required Forms & Registrations"]
        with st.expander(f"{bucket} ({len(bucket_items)})", expanded=expanded):
            for it in bucket_items:
                cols = st.columns([0.08, 0.72, 0.20])
                with cols[0]:
                    new_done = st.checkbox("", value=it.done, key=f"done_{it.id}")
                with cols[1]:
                    if it.is_critical:
                        st.markdown(f"🚩 **{it.normalized_text}**")
                    else:
                        st.markdown(f"**{it.normalized_text}**")
                    st.caption(f"Maps to: {it.mapped_section} • Confidence: {int(it.confidence*100)}% • Source: {it.source}")
                with cols[2]:
                    new_status = st.selectbox(
                        "Status",
                        [S_UNKNOWN, S_PASS, S_FAIL],
                        index=[S_UNKNOWN, S_PASS, S_FAIL].index(it.status),
                        key=f"status_{it.id}"
                    )

                it.done = bool(new_done)
                it.status = new_status
                upsert_item(run_id, it)

    reference_drawer(items)


def render_intake(run_id: str, run_meta: Dict, items: Dict[str, Item]):
    st.subheader("Intake")
    st.caption("Upload PDFs or paste RFP text. Path.ai will extract and gate what matters.")

    intake = run_meta.get("intake", {}) or {}
    workflow = run_meta.get("workflow", {}) or {}

    c1, c2 = st.columns([0.60, 0.40])
    with c1:
        run_name = st.text_input("Proposal run name", value=run_meta.get("name", "My Proposal Run"))
        intake["notes"] = st.text_area("Notes for this run (optional)", value=intake.get("notes", ""), height=90)

        st.markdown("### Upload PDFs")
        pdfs = st.file_uploader("Upload one or more PDFs", type=["pdf"], accept_multiple_files=True)

        st.markdown("### Or paste solicitation text")
        sol_text = st.text_area("Paste text here (optional)", value=intake.get("sol_text", ""), height=180)

        cA, cB, cC = st.columns(3)
        with cA:
            auto_build = st.checkbox("Build tasks now", value=True)
        with cB:
            include_reference = st.checkbox("Keep reference items", value=True)
        with cC:
            reset = st.button("Reset items (danger)")

        if reset:
            st.error("This removes all items for this run.")
            confirm = st.checkbox("Yes, delete all items.")
            if confirm:
                delete_all_items(run_id)
                workflow["intake_complete"] = False
                workflow["company_complete"] = False
                workflow["compliance_complete"] = False
                workflow["draft_complete"] = False
                save_run_meta(run_id, intake=intake, company=run_meta.get("company", {}), workflow=workflow)
                st.success("Items deleted. You can rebuild from PDFs/text now.")
                return

        if st.button("Save Intake"):
            run_meta["name"] = run_name
            intake["sol_text"] = sol_text
            save_run_meta(run_id, intake=intake, company=run_meta.get("company", {}), workflow=workflow)
            st.success("Saved.")

        if auto_build and st.button("Build / Rebuild Task Items", type="primary"):
            # Gather combined text from PDFs + paste
            combined_text = ""
            sources: List[str] = []

            if pdfs:
                with st.spinner("Reading PDFs…"):
                    pdf_text, pdf_sources = extract_text_from_pdfs(pdfs)
                    combined_text += "\n" + pdf_text
                    for fn, pages in pdf_sources:
                        sources.append(f"{fn} ({pages} pages)")

            if sol_text.strip():
                combined_text += "\n" + sol_text
                sources.append("Pasted text")

            combined_text = clean_text(combined_text)
            if not combined_text.strip():
                st.warning("Upload at least one PDF or paste some text first.")
                return

            # Build items
            built: List[Item] = []
            created = now_iso()

            # Critical missing-field tasks (always actionable)
            built.extend(build_missing_critical_tasks(combined_text))

            # Extract requirement-like lines
            extracted = extract_items_from_text(combined_text)
            for idx, (sec_guess, raw_req) in enumerate(extracted, start=1):
                raw = clean_text(raw_req)
                if len(raw) < 12:
                    continue

                gating = classify_gating(raw)
                if gating == GL_IRRELEVANT:
                    continue  # hidden completely

                section = infer_section(raw)
                mapped = mapped_section_from_section(section)
                bucket = bucketize(raw, section)
                conf = confidence_score(raw, gating)

                # auto-resolve becomes silently done + pass
                done = False
                status = S_UNKNOWN
                if gating == GL_AUTO:
                    done = True
                    status = S_PASS

                # reference items optional (you can turn off storing them)
                if gating == GL_INFORMATIONAL and not include_reference:
                    continue

                item_id = f"r{idx:04d}_{re.sub(r'[^a-z0-9]+','_', raw.lower())[:18].strip('_')}"
                built.append(Item(
                    id=item_id,
                    raw_text=raw,
                    normalized_text=normalize_text(raw),
                    source="RFP",
                    section=section,
                    bucket=bucket,
                    gating_label=gating,
                    confidence=float(conf),
                    status=status,
                    done=done,
                    mapped_section=mapped,
                    notes="",
                    is_critical=detect_critical(raw) or item_id.startswith("crit_"),
                    created_at=created
                ))

            built = dedupe_items(built)

            # Save (replace)
            delete_all_items(run_id)
            for it in built:
                upsert_item(run_id, it)

            # Update run name + intake + workflow
            run_meta["name"] = run_name
            intake["sol_text"] = sol_text
            intake["sources"] = sources
            workflow["intake_complete"] = True
            save_run_meta(run_id, intake=intake, company=run_meta.get("company", {}), workflow=workflow)

            st.success(f"Built {len(built)} relevant items. Only ACTIONABLE items appear as tasks.")
            st.info("Go back to Task List — that’s the main screen.")

    with c2:
        st.markdown("### What you’ll get")
        st.write("• A clean Task List (ACTIONABLE only)")
        st.write("• A hidden Reference drawer (INFORMATIONAL)")
        st.write("• Irrelevant noise removed completely")
        st.write("• Auto-resolved items marked done quietly")

        if intake.get("sources"):
            st.markdown("### Sources")
            for s in intake["sources"]:
                st.write(f"• {s}")


def render_company(run_id: str, run_meta: Dict):
    st.subheader("Company")
    st.caption("Save your core company profile once. We’ll use it for drafting and exports next.")

    company = run_meta.get("company", {}) or {}
    workflow = run_meta.get("workflow", {}) or {}

    company["legal_name"] = st.text_input("Legal company name", value=company.get("legal_name", ""))
    company["uei"] = st.text_input("UEI", value=company.get("uei", ""))
    company["cage"] = st.text_input("CAGE", value=company.get("cage", ""))
    company["naics"] = st.text_input("Primary NAICS", value=company.get("naics", ""))
    company["address"] = st.text_area("Company address", value=company.get("address", ""), height=90)
    company["primary_contact"] = st.text_input("Primary contact", value=company.get("primary_contact", ""))
    company["email"] = st.text_input("Email", value=company.get("email", ""))
    company["phone"] = st.text_input("Phone", value=company.get("phone", ""))

    if st.button("Save Company", type="primary"):
        # minimal completion condition
        if company.get("legal_name", "").strip() and company.get("primary_contact", "").strip():
            workflow["company_complete"] = True
        save_run_meta(run_id, intake=run_meta.get("intake", {}), company=company, workflow=workflow)
        st.success("Company info saved.")


def render_compliance(run_id: str, run_meta: Dict, items: Dict[str, Item]):
    st.subheader("Compliance")
    st.caption("Mark each actionable requirement Pass/Fail/Unknown. This drives the gate and exports.")

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        st.info("No actionable compliance items yet. Build items in Intake first.")
        return

    df = pd.DataFrame([{
        "Bucket": it.bucket,
        "Requirement": it.normalized_text,
        "Critical": "Yes" if it.is_critical else "",
        "Status": it.status,
        "Done": "Yes" if it.done else "",
        "Confidence": int(it.confidence * 100)
    } for it in actionable])

    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Gate Check")
    st.caption("Gate is strict and reads only actionable items. Fix FAIL items before exporting.")
    if st.button("Run Gate Check"):
        k = compute_kpis(items)
        if k["gate"] == "PASS":
            st.success("Gate: PASS — ready to proceed.")
        elif k["gate"] == "AT RISK":
            st.warning("Gate: AT RISK — unknown or missing critical fields remain.")
        else:
            st.error("Gate: FAIL — resolve failed items before proceeding.")

    # Auto unlock compliance when user is far enough along
    workflow = run_meta.get("workflow", {}) or {}
    k = compute_kpis(items)
    if k["completion"] >= 0.60 and k["gate"] != "FAIL":
        if not workflow.get("compliance_complete", False):
            workflow["compliance_complete"] = True
            save_run_meta(run_id, intake=run_meta.get("intake", {}), company=run_meta.get("company", {}), workflow=workflow)
            st.success("Unlocked: Draft step (you’ve completed enough to move forward).")

    reference_drawer(items)


def render_draft(run_meta: Dict, items: Dict[str, Item]):
    st.subheader("Draft")
    st.caption("This is the clean outline that AI drafting will fill in next.")

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        st.info("No actionable items yet.")
        return

    grouped: Dict[str, List[Item]] = {}
    for it in actionable:
        grouped.setdefault(it.bucket, []).append(it)

    st.markdown("### Draft Outline (from actionable requirements)")
    for bucket in BUCKETS:
        if bucket not in grouped:
            continue
        with st.expander(bucket, expanded=(bucket == "Technical Requirements")):
            for it in sorted(grouped[bucket], key=lambda x: (0 if x.is_critical else 1, -x.confidence)):
                st.write(f"• {it.normalized_text}")

    st.markdown("---")
    st.info("Next: section-by-section AI drafting (technical approach, compliance narratives, matrices).")


def render_export(run_id: str, run_meta: Dict, items: Dict[str, Item]):
    st.subheader("Export")
    st.caption("Exports include your actionable task list and full compliance matrix.")

    all_items = list(items.values())
    if not all_items:
        st.info("Nothing to export yet. Build items in Intake first.")
        return

    run_name = run_meta.get("name", "My Proposal Run")

    # Build exports
    xlsx_matrix = export_xlsx_compliance_matrix(all_items)
    xlsx_tasks = export_xlsx_task_list(all_items)
    xlsx_gaps = export_xlsx_gap_report(all_items)

    pdf_checklist = export_pdf_submission_checklist(all_items, run_name)
    pdf_gate = export_pdf_gate_report(all_items, run_name)
    pdf_summary = export_pdf_compliance_summary(all_items, run_name)

    zip_bytes = export_zip_package(run_name, pdf_checklist, pdf_gate, pdf_summary, xlsx_matrix, xlsx_tasks, xlsx_gaps)

    st.download_button(
        "Download Submission Checklist (PDF)",
        data=pdf_checklist,
        file_name="Submission_Checklist.pdf",
        mime="application/pdf"
    )
    st.download_button(
        "Download Gate Report (PDF)",
        data=pdf_gate,
        file_name="Gate_Report.pdf",
        mime="application/pdf"
    )
    st.download_button(
        "Download Compliance Summary (PDF)",
        data=pdf_summary,
        file_name="Compliance_Summary.pdf",
        mime="application/pdf"
    )

    st.download_button(
        "Download Compliance Matrix (XLSX)",
        data=xlsx_matrix,
        file_name="Compliance_Matrix.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    st.download_button(
        "Download Task List (XLSX)",
        data=xlsx_tasks,
        file_name="Task_List.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    st.download_button(
        "Download Gap Report (XLSX)",
        data=xlsx_gaps,
        file_name="Gap_Report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.download_button(
        "Download FULL Export Package (ZIP)",
        data=zip_bytes,
        file_name="PathAI_Export_Package.zip",
        mime="application/zip"
    )


# =========================================================
# MAIN APP
# =========================================================
st.set_page_config(page_title=APP_NAME, layout="wide")

# Sidebar: runs (you said you're ok with it)
with st.sidebar:
    st.markdown("## Proposal Runs")
    runs = list_runs()

    if "active_run_id" not in st.session_state:
        st.session_state.active_run_id = None

    if st.button("➕ New run", use_container_width=True):
        new_name = f"My Proposal Run ({datetime.utcnow().strftime('%Y-%m-%d')})"
        rid = create_run(new_name)
        st.session_state.active_run_id = rid
        st.success("Created.")

    run_options = ["(Select a run)"] + [f"{name} — {rid}" for rid, name, _ in runs]
    sel = st.selectbox("Select run", run_options, index=0)

    if sel != "(Select a run)":
        rid = sel.split("—")[-1].strip()
        st.session_state.active_run_id = rid

    st.markdown("---")
    st.caption("Path.ai shows only ACTIONABLE tasks as checkboxes.\n\nReference items stay hidden by default.")


run_id = st.session_state.active_run_id
if not run_id:
    st.title(APP_NAME)
    st.info("Create or select a proposal run from the sidebar to begin.")
    st.stop()

run_meta = load_run_meta(run_id)
items = load_items(run_id)
kpis = compute_kpis(items)

# header + readiness
render_header(run_meta, kpis)

# Locked flow logic (tabs exist; content locked)
unlocks = workflow_unlocks(run_meta, items)
# persist any auto updates
save_run_meta(run_id, intake=run_meta.get("intake", {}), company=run_meta.get("company", {}), workflow=run_meta.get("workflow", {}))

tabs = st.tabs(PAGES)

with tabs[0]:
    render_task_list(items, run_id)

with tabs[1]:
    render_intake(run_id, run_meta, items)
    # refresh after potential rebuild
    items = load_items(run_id)

with tabs[2]:
    if not unlocks["Company"]:
        render_locked("Complete Intake first (upload PDFs / build your task list).")
    else:
        render_company(run_id, run_meta)

with tabs[3]:
    # refresh meta for workflow changes
    run_meta = load_run_meta(run_id)
    items = load_items(run_id)
    unlocks = workflow_unlocks(run_meta, items)
    if not unlocks["Compliance"]:
        render_locked("Complete Company first (save your company profile).")
    else:
        render_compliance(run_id, run_meta, items)

with tabs[4]:
    run_meta = load_run_meta(run_id)
    items = load_items(run_id)
    unlocks = workflow_unlocks(run_meta, items)
    if not unlocks["Draft"]:
        render_locked("Complete Compliance first (reach ~60% completion without FAIL).")
    else:
        render_draft(run_meta, items)

        workflow = run_meta.get("workflow", {}) or {}
        st.markdown("---")
        st.caption("When you’re ready, mark Draft as ready to unlock Export.")
        ready = st.checkbox("Draft is ready", value=bool(workflow.get("draft_complete", False)))
        if ready != bool(workflow.get("draft_complete", False)):
            workflow["draft_complete"] = bool(ready)
            save_run_meta(run_id, intake=run_meta.get("intake", {}), company=run_meta.get("company", {}), workflow=workflow)
            st.success("Updated.")

with tabs[5]:
    run_meta = load_run_meta(run_id)
    items = load_items(run_id)
    unlocks = workflow_unlocks(run_meta, items)
    if not unlocks["Export"]:
        render_locked("Mark Draft as ready to unlock Export.")
    else:
        render_export(run_id, run_meta, items)