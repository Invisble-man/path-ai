import streamlit as st
import pandas as pd
import sqlite3
import json
import re
import io
import zipfile
import base64
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

import docx
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH


# -----------------------------
# Brand + Config
# -----------------------------
APP_NAME = "Path.ai"
APP_VERSION = "v1.6.0"
DB_PATH = "path_state.db"

PAGES = ["Task List", "Intake", "Company", "Compliance", "Draft", "Export"]

GL_ACTIONABLE = "ACTIONABLE"
GL_INFORMATIONAL = "INFORMATIONAL"
GL_IRRELEVANT = "IRRELEVANT"
GL_AUTO = "AUTO_RESOLVED"

S_PASS = "pass"
S_FAIL = "fail"
S_UNKNOWN = "unknown"

BUCKETS_ORDER = [
    "Submission & Format",
    "Required Forms & Registrations",
    "Attachments/Exhibits",
    "Technical Requirements",
    "Pricing & Cost",
    "Past Performance",
    "Other",
]

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

IRRELEVANT_POST_AWARD = [
    "invoice", "invoicing", "payment", "paid", "warranty", "claims", "disputes",
    "contractor shall bill", "final invoice", "prompt payment", "modification",
    "change request", "deobligate", "termination for convenience"
]

AUTO_RESOLVE_HINTS = [
    "not applicable", "n/a", "none required", "no action required"
]

CRITICAL_PATTERNS = {
    "Submission deadline": [r"offer due date", r"proposal(?:s)?\s+due", r"due\s+date", r"deadline", r"no later than"],
    "Submission method": [r"submit\s+electronically", r"email\s+to", r"via\s+.*portal", r"upload", r"submit(?:tal)?\s+through"],
    "File format rules": [r"\bpdf\b", r"editable\s+spreadsheet", r"\bexcel\b", r"file\s+format", r"\bfont\b", r"\bmargin\b", r"page\s+limit"],
    "Required forms (SF/attachments)": [
        r"sf\s*1449", r"sf-\s*1449", r"\bsf\s*\d{3,5}\b",
        r"representations?\s+and\s+certifications?", r"reps?\s*&\s*certs?"
    ],
    "Required attachments/exhibits": [r"attachment\s+[a-z0-9]+", r"exhibit\s+[a-z0-9]+", r"include\s+the\s+following", r"submit\s+the\s+following"],
}


# -----------------------------
# Data model
# -----------------------------
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

    source_file: str
    page_number: Optional[int]
    source_snippet: str

    is_critical: bool
    created_at: str


# -----------------------------
# Persistence (single workspace; no runs UI)
# -----------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_state (
            id INTEGER PRIMARY KEY,
            json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            json TEXT
        )
    """)
    conn.commit()
    return conn


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def default_state() -> Dict[str, Any]:
    return {
        "ui": {"active_page": "Task List"},
        "intake": {
            "sol_text": "",
            "sources": [],
            "diagnostics": {},
            "last_analyzed_at": ""
        },
        "company": {
            "legal_name": "",
            "uei": "",
            "cage": "",
            "naics": "",
            "address": "",
            "primary_contact": "",
            "email": "",
            "phone": "",
            "sam_registered": False,
            "certs": [],
            "contract_title": "",
            "logo_b64": ""
        },
        "drafts": {"proposal": "", "cover_letter": ""},
        "activity": {
            "draft_generated_at": "",
            "exported_at": ""
        }
    }


def load_state() -> Dict[str, Any]:
    conn = db()
    row = conn.execute("SELECT json FROM app_state WHERE id=1").fetchone()
    if not row:
        s = default_state()
        conn.execute("INSERT INTO app_state (id, json) VALUES (1, ?)", (json.dumps(s),))
        conn.commit()
        return s
    try:
        s = json.loads(row[0] or "{}")
    except Exception:
        s = default_state()
    # patch missing keys
    d = default_state()
    d.update(s)
    d["ui"].update(s.get("ui", {}))
    d["intake"].update(s.get("intake", {}))
    d["company"].update(s.get("company", {}))
    d["drafts"].update(s.get("drafts", {}))
    d["activity"].update(s.get("activity", {}))
    return d


def save_state(state: Dict[str, Any]):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO app_state (id, json) VALUES (1, ?)", (json.dumps(state),))
    conn.commit()


def load_items() -> Dict[str, Item]:
    conn = db()
    rows = conn.execute("SELECT item_id, json FROM items").fetchall()
    out: Dict[str, Item] = {}
    for item_id, j in rows:
        d = json.loads(j)
        # patch in case of older fields
        d.setdefault("id", item_id)
        d.setdefault("raw_text", d.get("normalized_text", ""))
        d.setdefault("normalized_text", d.get("raw_text", ""))
        d.setdefault("source", "RFP")
        d.setdefault("section", "General")
        d.setdefault("bucket", "Other")
        d.setdefault("gating_label", GL_INFORMATIONAL)
        d.setdefault("confidence", 0.55)
        d.setdefault("status", S_UNKNOWN)
        d.setdefault("done", False)
        d.setdefault("mapped_section", "General / Supporting")
        d.setdefault("notes", "")
        d.setdefault("source_file", "Unknown")
        d.setdefault("page_number", None)
        d.setdefault("source_snippet", (d.get("normalized_text", "") or "")[:220])
        d.setdefault("is_critical", False)
        d.setdefault("created_at", now_iso())
        out[item_id] = Item(**d)
    return out


def upsert_item(item: Item):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO items (item_id, json) VALUES (?, ?)", (item.id, json.dumps(asdict(item))))
    conn.commit()


def delete_all_items():
    conn = db()
    conn.execute("DELETE FROM items")
    conn.commit()


# -----------------------------
# Text + classification
# -----------------------------
def clean_text(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def normalize_text(t: str) -> str:
    t = clean_text(t)
    t = re.sub(r"(?i)\battachment mention:\s*", "", t)
    t = re.sub(r"(?i)\bmapped section:\s*", "", t)
    return t


def infer_section(line: str) -> str:
    l = (line or "").lower()
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


def classify_gating(text: str) -> str:
    t = (text or "").lower()

    if any(h in t for h in AUTO_RESOLVE_HINTS):
        return GL_AUTO

    if any(h in t for h in IRRELEVANT_POST_AWARD):
        if "proposal" in t or "offer" in t:
            return GL_ACTIONABLE
        return GL_IRRELEVANT

    hits = sum(1 for k in ACTIONABLE_STRONG if k in t)
    if hits >= 2:
        return GL_ACTIONABLE

    if any(h in t for h in INFORMATIONAL_HINTS):
        return GL_INFORMATIONAL

    return GL_INFORMATIONAL


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
                notes="Not detected in extracted text. Verify directly in the solicitation.",
                source_file="Detected",
                page_number=None,
                source_snippet="Not detected in extracted text. Verify in the solicitation.",
                is_critical=True,
                created_at=created
            ))
    return tasks


# -----------------------------
# PDF extraction + diagnostics
# -----------------------------
def extraction_quality_label(total_pages: int, pages_with_text: int, chars: int) -> str:
    if total_pages <= 0:
        return "Unknown"
    if pages_with_text == 0 or chars < 300:
        return "Poor"
    ratio = pages_with_text / max(1, total_pages)
    chars_per_page = chars / max(1, pages_with_text)
    if ratio >= 0.90 and chars_per_page >= 1500:
        return "Excellent"
    if ratio >= 0.75 and chars_per_page >= 800:
        return "Good"
    if ratio >= 0.50 and chars_per_page >= 400:
        return "Fair"
    return "Poor"


def likely_scanned(total_pages: int, pages_with_text: int, chars: int) -> bool:
    if total_pages <= 0:
        return False
    ratio = pages_with_text / max(1, total_pages)
    if ratio < 0.25:
        return True
    if chars < max(800, total_pages * 120):
        return True
    return False


def extract_pages_from_pdfs(files: List) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
    pages_data: List[Dict[str, Any]] = []
    sources: List[str] = []
    total_pages = 0
    pages_with_text = 0
    chars = 0

    for f in files:
        fname = getattr(f, "name", "uploaded.pdf")
        try:
            reader = PdfReader(f)
            pages = len(reader.pages)
            total_pages += pages
            sources.append(f"{fname} ({pages} pages)")
            for i in range(pages):
                txt = reader.pages[i].extract_text() or ""
                txt = txt.strip()
                if txt:
                    pages_with_text += 1
                    chars += len(txt)
                    pages_data.append({"file_name": fname, "page_number": i + 1, "text": txt})
        except Exception:
            sources.append(f"{fname} (0 pages — extraction failed)")

    diag = {
        "file_type": "pdf",
        "pages": total_pages,
        "pages_with_text": pages_with_text,
        "characters_extracted": chars,
        "likely_scanned": "Yes" if likely_scanned(total_pages, pages_with_text, chars) else "No",
        "extraction_quality": extraction_quality_label(total_pages, pages_with_text, chars)
    }
    return pages_data, sources, diag


def split_candidates_from_page(text: str) -> List[str]:
    raw_lines = [clean_text(x) for x in (text or "").splitlines()]
    raw_lines = [x for x in raw_lines if x and len(x) >= 10]

    candidates: List[str] = []
    for ln in raw_lines:
        lnl = ln.lower()
        if re.match(r"^\d+\s*/\s*\d+$", ln):
            continue
        if lnl.startswith("page ") and len(ln) < 20:
            continue

        parts = re.split(r"(?<=[.;:])\s+(?=[A-Z0-9])", ln)
        for p in parts:
            p = clean_text(p)
            if p and len(p) >= 12:
                candidates.append(p)

    seen = set()
    out = []
    for c in candidates:
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def build_items_from_sources(
    combined_text: str,
    pages_data: List[Dict[str, Any]],
    pasted_text: str,
    include_reference: bool
) -> List[Item]:
    built: List[Item] = []
    created = now_iso()

    built.extend(build_missing_critical_tasks(combined_text))

    idx = 1
    for page in pages_data:
        fname = page["file_name"]
        pno = page["page_number"]
        page_text = page["text"]
        candidates = split_candidates_from_page(page_text)

        for ln in candidates:
            raw = clean_text(ln)
            if len(raw) < 12:
                continue

            gating = classify_gating(raw)
            if gating == GL_IRRELEVANT:
                continue
            if gating == GL_INFORMATIONAL and not include_reference:
                continue

            section = infer_section(raw)
            mapped = mapped_section_from_section(section)
            bucket = bucketize(raw, section)
            conf = confidence_score(raw, gating)

            done = False
            status = S_UNKNOWN
            if gating == GL_AUTO:
                done = True
                status = S_PASS

            item_id = f"r{idx:05d}_{re.sub(r'[^a-z0-9]+','_', raw.lower())[:16].strip('_')}"
            idx += 1

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
                source_file=fname,
                page_number=pno,
                source_snippet=normalize_text(raw)[:220],
                is_critical=detect_critical(raw) or item_id.startswith("crit_"),
                created_at=created
            ))

    if pasted_text and pasted_text.strip():
        lines = [clean_text(x) for x in pasted_text.splitlines() if clean_text(x)]
        for ln in lines:
            raw = clean_text(ln)
            if len(raw) < 12:
                continue

            gating = classify_gating(raw)
            if gating == GL_IRRELEVANT:
                continue
            if gating == GL_INFORMATIONAL and not include_reference:
                continue

            section = infer_section(raw)
            mapped = mapped_section_from_section(section)
            bucket = bucketize(raw, section)
            conf = confidence_score(raw, gating)

            done = False
            status = S_UNKNOWN
            if gating == GL_AUTO:
                done = True
                status = S_PASS

            item_id = f"t{idx:05d}_{re.sub(r'[^a-z0-9]+','_', raw.lower())[:16].strip('_')}"
            idx += 1

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
                source_file="Pasted text",
                page_number=None,
                source_snippet=normalize_text(raw)[:220],
                is_critical=detect_critical(raw) or item_id.startswith("crit_"),
                created_at=created
            ))

    return built


# -----------------------------
# KPI / progress (no company gating required)
# -----------------------------
def compute_kpis(items: Dict[str, Item]) -> Dict[str, Any]:
    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        return {
            "completion": 0.0,
            "pass": 0, "fail": 0, "unknown": 0,
            "gate": "WAITING",
            "missing_critical": 0,
            "actionable_total": 0,
        }

    completed = [i for i in actionable if (i.done or i.status in [S_PASS, S_FAIL])]
    completion = len(completed) / max(1, len(actionable))

    pass_ct = sum(1 for i in actionable if i.status == S_PASS)
    fail_ct = sum(1 for i in actionable if i.status == S_FAIL)
    unk_ct = sum(1 for i in actionable if i.status == S_UNKNOWN)

    missing_critical = sum(1 for i in actionable if i.is_critical and i.status == S_UNKNOWN and not i.done)

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
    }


def priority_score(it: Item) -> int:
    t = (it.normalized_text or "").lower()
    score = 0

    if any(k in t for k in ["deadline", "due date", "no later than", "due", "submit by"]):
        score += 60
    if any(k in t for k in ["page limit", "font", "margin", "format", "pdf", "excel", "electronic submission"]):
        score += 45
    if any(k in t for k in ["sf1449", "sf-1449", "sam.gov", "uei", "cage", "representations", "certifications"]):
        score += 40
    if any(k in t for k in ["attachment", "exhibit", "appendix", "include the following"]):
        score += 35
    if any(k in t for k in ["price", "pricing", "cost", "rates", "clins"]):
        score += 28
    if "past performance" in t or "references" in t:
        score += 22
    if any(k in t for k in ["technical", "approach", "method", "pws", "sow"]):
        score += 18

    if it.is_critical:
        score += 35
    if it.status == S_FAIL:
        score += 100
    if it.done or it.status == S_PASS:
        score -= 20

    return score


def step_status(state: Dict[str, Any], items: Dict[str, Item]) -> Dict[str, str]:
    intake_done = bool(state["intake"].get("last_analyzed_at"))
    company_fields = state["company"]
    company_started = any(clean_text(str(company_fields.get(k, ""))) for k in ["legal_name", "contract_title", "uei", "cage", "naics", "primary_contact"])
    company_done = bool(clean_text(company_fields.get("legal_name", ""))) and bool(clean_text(company_fields.get("primary_contact", "")))

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    compliance_started = any(i.status != S_UNKNOWN or i.done for i in actionable)
    k = compute_kpis(items)
    compliance_done = k["completion"] >= 0.60

    draft_started = bool(state["drafts"].get("proposal")) or bool(state["drafts"].get("cover_letter"))
    draft_done = bool(state["activity"].get("draft_generated_at"))

    export_started = bool(state["activity"].get("exported_at"))
    export_done = export_started  # no extra gating

    def status3(started: bool, done: bool) -> str:
        if done:
            return "done"
        if started:
            return "in_progress"
        return "not_started"

    return {
        "Task List": "done" if intake_done else "in_progress" if (len(items) > 0) else "not_started",
        "Intake": status3(intake_done, intake_done),
        "Company": status3(company_started, company_done),
        "Compliance": status3(compliance_started, compliance_done),
        "Draft": status3(draft_started, draft_done),
        "Export": status3(export_started, export_done),
    }


# -----------------------------
# Calm UI helpers
# -----------------------------
def badge(text: str, tone: str):
    colors = {
        "green": ("#1f7a1f", "#E7F6EA"),
        "orange": ("#8a4b12", "#FFE8D6"),
        "red": ("#a11a1a", "#FDE2E2"),
        "blue": ("#1d4ed8", "#E8F0FF"),
        "gray": ("#374151", "#F3F4F6"),
        "yellow": ("#8a6a12", "#FBF3D0"),
    }
    fg, bg = colors.get(tone, colors["gray"])
    st.markdown(
        f"""
        <span style="
            display:inline-block;
            padding:10px 14px;
            border-radius:999px;
            background:{bg};
            border:1px solid rgba(0,0,0,0.08);
            color:{fg};
            font-weight:700;
            font-size:0.95rem;
            margin-right:10px;
            margin-bottom:8px;">
            {text}
        </span>
        """,
        unsafe_allow_html=True
    )


def tone_for_gate(gate: str) -> str:
    if gate == "PASS":
        return "green"
    if gate == "AT RISK":
        return "yellow"
    if gate == "FAIL":
        return "red"
    return "gray"


def diagnostics_panel(diag: Dict[str, Any]):
    with st.container(border=True):
        st.subheader("Diagnostics")
        st.caption("This helps you understand if the PDF text was actually readable.")

        q = (diag or {}).get("extraction_quality", "Unknown")
        tone = "green" if q == "Excellent" else ("yellow" if q in ["Good", "Fair"] else ("red" if q == "Poor" else "gray"))
        badge(f"Extraction quality: {q}", tone=tone)

        st.write(f"**File Type:** {diag.get('file_type', 'pdf')}")
        st.write(f"**Pages:** {diag.get('pages', 0)}    **Pages with Text:** {diag.get('pages_with_text', 0)}")
        st.write(f"**Characters Extracted:** {diag.get('characters_extracted', 0)}")
        st.write(f"**Likely Scanned:** {diag.get('likely_scanned', 'No')}")


def compliance_kpi_panel(kpis: Dict[str, Any]):
    with st.container(border=True):
        st.subheader("Compliance KPI")
        comp = int((kpis.get("completion", 0.0)) * 100)
        badge(f"Compliance: {comp}%", "green" if comp >= 80 else ("yellow" if comp >= 40 else "red"))
        badge(f"Pass: {kpis.get('pass', 0)}", "green")
        badge(f"Fail: {kpis.get('fail', 0)}", "red" if kpis.get("fail", 0) > 0 else "green")
        badge(f"Unknown: {kpis.get('unknown', 0)}", "yellow" if kpis.get("unknown", 0) > 0 else "green")
        badge(f"Gate: {kpis.get('gate', 'WAITING')}", tone_for_gate(kpis.get("gate", "WAITING")))
        badge(f"Missing critical fields: {kpis.get('missing_critical', 0)}", "yellow" if kpis.get("missing_critical", 0) > 0 else "green")


def stepper_sidebar(active_page: str, statuses: Dict[str, str]):
    with st.sidebar:
        st.markdown(f"## {APP_NAME}")
        st.caption("You’re now on the Path to success.")
        st.markdown("---")
        st.markdown("### Your path")

        tone_map = {"done": "green", "in_progress": "orange", "not_started": "red"}
        for page in PAGES:
            tone = tone_map.get(statuses.get(page, "not_started"), "red")
            label = f"{page}"
            if page == active_page:
                st.markdown(f"**{label}**")
            else:
                st.markdown(label)
            badge("Complete" if statuses.get(page) == "done" else ("In progress" if statuses.get(page) == "in_progress" else "Not started"), tone=tone)

        st.markdown("---")
        if st.button("Reset workspace (danger)", use_container_width=True):
            st.session_state["_confirm_reset"] = True
        if st.session_state.get("_confirm_reset", False):
            st.warning("This clears the entire workspace: items, intake, drafts.")
            if st.button("Yes — clear everything", type="primary", use_container_width=True):
                delete_all_items()
                s = default_state()
                save_state(s)
                st.session_state["_confirm_reset"] = False
                st.success("Cleared.")
                st.rerun()
            if st.button("Cancel", use_container_width=True):
                st.session_state["_confirm_reset"] = False
                st.rerun()


# -----------------------------
# Navigation (top horizontal buttons)
# -----------------------------
def top_nav(state: Dict[str, Any], items: Dict[str, Item]):
    k = compute_kpis(items)
    progress_ok = k["completion"] >= 0.60
    active = state["ui"].get("active_page", "Task List")

    st.markdown("""
    <style>
      .path-nav button { border-radius: 14px !important; padding: 0.55rem 0.9rem !important; }
    </style>
    """, unsafe_allow_html=True)

    cols = st.columns([1, 1, 1, 1, 1, 1], gap="small")
    for i, page in enumerate(PAGES):
        disabled = False
        if page in ["Draft", "Export"] and not progress_ok:
            disabled = True

        btn_label = page
        with cols[i]:
            if st.button(btn_label, use_container_width=True, disabled=disabled, key=f"nav_{page}"):
                state["ui"]["active_page"] = page
                save_state(state)
                st.rerun()

    st.markdown("")
    # Top progress bar always visible
    st.progress(float(k.get("completion", 0.0)))
    st.caption("Draft + Export unlock at **60%** progress.")


# -----------------------------
# AI (optional, modular)
# -----------------------------
def call_ai(prompt: str, system: str = "") -> Tuple[str, Optional[str]]:
    api_key = st.secrets.get("OPENAI_API_KEY", None) if hasattr(st, "secrets") else None
    if not api_key:
        api_key = st.session_state.get("_OPENAI_API_KEY_OVERRIDE") or None
    if not api_key:
        return ("", "AI is not connected (missing OPENAI_API_KEY).")

    model = st.secrets.get("PATHAI_MODEL", "gpt-4.1-mini") if hasattr(st, "secrets") else "gpt-4.1-mini"

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system or "You are a senior proposal writer and compliance expert."},
            {"role": "user", "content": prompt}
        ]
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=data,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            obj = json.loads(raw)

        text = ""
        out = obj.get("output", [])
        for item in out:
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") in ["output_text", "text"]:
                        text += c.get("text", "")

        if not text:
            text = obj.get("output_text", "") or ""
        text = (text or "").strip()
        return (text, None if text else "AI returned empty output.")
    except Exception as e:
        return ("", f"AI request failed: {e}")


# -----------------------------
# Exports
# -----------------------------
def style_xlsx_header(ws, row=1):
    fill = PatternFill("solid", fgColor="EEF2FF")
    for cell in ws[row]:
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)


def autosize_ws(ws, max_width=70):
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
        "source", "bucket", "critical", "source_file", "page_number", "notes"
    ])

    for it in items:
        ws.append([
            it.id, it.section, it.mapped_section, it.normalized_text,
            it.gating_label, float(it.confidence), it.status, bool(it.done),
            it.source, it.bucket, bool(it.is_critical),
            it.source_file, it.page_number if it.page_number is not None else "",
            it.notes
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
    actionable = sorted(actionable, key=lambda x: (-priority_score(x), -x.confidence))

    ws.append(["done", "bucket", "task", "mapped_section", "confidence", "status", "source_file", "page", "id", "critical"])
    for it in actionable:
        ws.append([
            "YES" if it.done else "NO",
            it.bucket,
            it.normalized_text,
            it.mapped_section,
            int(it.confidence * 100),
            it.status,
            it.source_file,
            it.page_number if it.page_number is not None else "",
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
    gaps = sorted(gaps, key=lambda x: (-priority_score(x), -x.confidence))

    ws.append(["gap", "bucket", "task", "mapped_section", "confidence", "status", "source_file", "page", "id", "critical"])
    for it in gaps:
        ws.append([
            "OPEN",
            it.bucket,
            it.normalized_text,
            it.mapped_section,
            int(it.confidence * 100),
            it.status,
            it.source_file,
            it.page_number if it.page_number is not None else "",
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


def export_pdf_submission_checklist(items: List[Item]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    y = height - 54
    c.setFont("Helvetica-Bold", 16)
    c.drawString(48, y, f"{APP_NAME} — Submission Checklist")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(48, y, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    y -= 22

    actionable = [i for i in items if i.gating_label == GL_ACTIONABLE]
    grouped: Dict[str, List[Item]] = {}
    for it in actionable:
        grouped.setdefault(it.bucket, []).append(it)

    for bucket in BUCKETS_ORDER:
        if bucket not in grouped:
            continue
        if y < 100:
            c.showPage()
            y = height - 54
        c.setFont("Helvetica-Bold", 12)
        c.drawString(48, y, bucket)
        y -= 18
        c.setFont("Helvetica", 10)
        for it in sorted(grouped[bucket], key=lambda x: (-priority_score(x), -x.confidence)):
            if y < 80:
                c.showPage()
                y = height - 54
                c.setFont("Helvetica", 10)
            box = "[x]" if (it.done or it.status == S_PASS) else "[ ]"
            prefix = "CRITICAL: " if it.is_critical else ""
            src = f" ({it.source_file}{'' if it.page_number is None else f' p.{it.page_number}'})"
            y = pdf_write_wrapped(c, 58, y, f"{box} {prefix}{it.normalized_text}{src}", max_chars=108)
            y -= 2

    c.showPage()
    c.save()
    return buf.getvalue()


def export_zip_package(pdf_bytes: bytes, xlsx_matrix: bytes, xlsx_tasks: bytes, xlsx_gaps: bytes) -> bytes:
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("01_Submission_Checklist.pdf", pdf_bytes)
        z.writestr("02_Compliance_Matrix.xlsx", xlsx_matrix)
        z.writestr("03_Task_List.xlsx", xlsx_tasks)
        z.writestr("04_Gap_Report.xlsx", xlsx_gaps)
        z.writestr("README.txt", f"{APP_NAME} export package.\nIncludes traceability (file + page) where available.\n")
    return zbuf.getvalue()


# -----------------------------
# Draft DOCX (cover page + cover letter + proposal)
# -----------------------------
def b64_from_uploaded_file(uploaded) -> str:
    if not uploaded:
        return ""
    try:
        content = uploaded.getvalue()
        return base64.b64encode(content).decode("utf-8")
    except Exception:
        return ""


def build_proposal_package_docx(
    company: Dict[str, Any],
    items: Dict[str, Item],
    cover_letter_text: str,
    proposal_text: str
) -> bytes:
    doc = docx.Document()

    contract_title = clean_text(company.get("contract_title", "")) or "Solicitation"
    company_name = clean_text(company.get("legal_name", "")) or "Company Name"

    logo_b64 = company.get("logo_b64", "")
    if logo_b64:
        try:
            img_bytes = base64.b64decode(logo_b64)
            img_stream = io.BytesIO(img_bytes)
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run()
            run.add_picture(img_stream, width=Inches(2.0))
        except Exception:
            pass

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(company_name)
    r.bold = True
    r.font.size = docx.shared.Pt(24)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(contract_title)
    r.bold = True
    r.font.size = docx.shared.Pt(16)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f"Generated by {APP_NAME} • {datetime.utcnow().strftime('%Y-%m-%d')}")

    doc.add_page_break()

    doc.add_heading("Cover Letter", level=1)
    for line in (cover_letter_text or "").splitlines():
        doc.add_paragraph(line)

    doc.add_paragraph("")
    sig = doc.add_paragraph()
    sig.add_run("Sincerely,").bold = True
    doc.add_paragraph("")
    doc.add_paragraph(company.get("primary_contact", "") or "Authorized Representative")
    doc.add_paragraph(company_name)
    if company.get("email"):
        doc.add_paragraph(company["email"])
    if company.get("phone"):
        doc.add_paragraph(company["phone"])

    doc.add_page_break()

    doc.add_heading("Proposal", level=1)
    for line in (proposal_text or "").splitlines():
        doc.add_paragraph(line)

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if actionable:
        doc.add_page_break()
        doc.add_heading("Appendix: Compliance Snapshot", level=1)
        for it in sorted(actionable, key=lambda x: (-priority_score(x), -x.confidence))[:80]:
            status = it.status.upper()
            doc.add_paragraph(f"- [{status}] {it.normalized_text} (Source: {it.source_file}{'' if it.page_number is None else f' p.{it.page_number}'})")

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# -----------------------------
# Pages
# -----------------------------
def page_task_list(state: Dict[str, Any], items: Dict[str, Item]):
    intake = state["intake"]
    company = state["company"]

    left, right = st.columns([0.62, 0.38], gap="large")

    with left:
        with st.container(border=True):
            st.subheader("Upload your RFP")
            pdfs = st.file_uploader("Upload PDF(s)", type=["pdf"], accept_multiple_files=True, key="home_pdfs")

            st.subheader("Or add RFP text")
            pasted = st.text_area("Paste text here (optional)", value=intake.get("sol_text", ""), height=160, key="home_text")

            include_reference = st.checkbox("Keep reference items (recommended)", value=True, key="home_keep_ref")

            analyze = st.button("Analyze", type="primary", use_container_width=True)
            if analyze:
                pages_data: List[Dict[str, Any]] = []
                sources: List[str] = []
                diag: Dict[str, Any] = {
                    "file_type": "pdf",
                    "pages": 0,
                    "pages_with_text": 0,
                    "characters_extracted": 0,
                    "likely_scanned": "No",
                    "extraction_quality": "Unknown"
                }

                if pdfs:
                    with st.spinner("Reading PDFs…"):
                        pages_data, sources, diag = extract_pages_from_pdfs(pdfs)

                combined_parts = [p.get("text", "") for p in pages_data]
                if pasted and pasted.strip():
                    combined_parts.append(pasted)

                combined_text = "\n".join(combined_parts)
                if not (combined_text or "").strip():
                    st.warning("Upload at least one PDF or paste RFP text.")
                    st.stop()

                with st.spinner("Building your task list…"):
                    built = build_items_from_sources(combined_text, pages_data, pasted, include_reference)
                    built = dedupe_items(built)

                    delete_all_items()
                    for it in built:
                        upsert_item(it)

                    intake["sol_text"] = pasted or ""
                    intake["sources"] = sources + (["Pasted text"] if pasted and pasted.strip() else [])
                    intake["diagnostics"] = diag
                    intake["last_analyzed_at"] = now_iso()
                    save_state(state)

                st.success(f"Done. Built {len(built)} relevant items.")
                st.rerun()

        st.markdown("")
        st.subheader("Task List")
        st.caption("Only ACTIONABLE tasks show here. Everything else is hidden or saved as reference.")

        actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
        if not actionable:
            st.info("Upload an RFP above and hit Analyze to generate your task list.")
            return

        grouped: Dict[str, List[Item]] = {}
        for it in actionable:
            grouped.setdefault(it.bucket, []).append(it)

        for bucket in BUCKETS_ORDER:
            if bucket not in grouped:
                continue
            bucket_items = sorted(grouped[bucket], key=lambda x: (-priority_score(x), -x.confidence))
            expanded = bucket in ["Submission & Format", "Required Forms & Registrations"]
            with st.expander(f"{bucket} ({len(bucket_items)})", expanded=expanded):
                for it in bucket_items:
                    cols = st.columns([0.08, 0.68, 0.24])
                    with cols[0]:
                        new_done = st.checkbox("", value=it.done, key=f"done_{it.id}")
                    with cols[1]:
                        prefix = "🚩 " if it.is_critical else ""
                        st.markdown(f"{prefix}**{it.normalized_text}**")
                        src = f"{it.source_file}{'' if it.page_number is None else f' p.{it.page_number}'}"
                        with st.expander("View source", expanded=False):
                            st.write(f"**Source:** {src}")
                            st.write(it.source_snippet or it.raw_text)
                    with cols[2]:
                        new_status = st.selectbox("Status", [S_UNKNOWN, S_PASS, S_FAIL],
                                                  index=[S_UNKNOWN, S_PASS, S_FAIL].index(it.status),
                                                  key=f"status_{it.id}")
                    it.done = bool(new_done)
                    it.status = new_status
                    upsert_item(it)

        with st.expander("Reference (Informational) — hidden by default", expanded=False):
            info_items = [i for i in items.values() if i.gating_label == GL_INFORMATIONAL]
            st.caption("These items are stored for context and traceability. They are not tasks.")
            q = st.text_input("Search reference", "")
            srcs = sorted(list(set(i.source_file for i in info_items)))
            src_filter = st.selectbox("Source file", ["All"] + srcs)
            filtered = info_items
            if q.strip():
                filtered = [i for i in filtered if q.lower() in i.normalized_text.lower()]
            if src_filter != "All":
                filtered = [i for i in filtered if i.source_file == src_filter]
            for it in filtered[:300]:
                src = f"{it.source_file}{'' if it.page_number is None else f' p.{it.page_number}'}"
                st.write(f"• **{it.section}** — {it.normalized_text}")
                st.caption(f"Source: {src}")

    with right:
        diag = intake.get("diagnostics", {}) or {}
        kpis = compute_kpis(items)

        diagnostics_panel(diag if diag else {
            "file_type": "pdf",
            "pages": 0,
            "pages_with_text": 0,
            "characters_extracted": 0,
            "likely_scanned": "No",
            "extraction_quality": "Unknown"
        })
        compliance_kpi_panel(kpis)

        st.markdown("")
        with st.container(border=True):
            st.subheader("Quick details (optional)")
            company["contract_title"] = st.text_input("Contract / solicitation title", value=company.get("contract_title", ""))
            company["legal_name"] = st.text_input("Company name", value=company.get("legal_name", ""))
            company["primary_contact"] = st.text_input("Primary contact", value=company.get("primary_contact", ""))
            if st.button("Save", use_container_width=True):
                save_state(state)
                st.success("Saved.")


def page_intake(state: Dict[str, Any], items: Dict[str, Item]):
    st.subheader("Intake")
    st.caption("This is your intake record. Use Task List to Analyze.")

    intake = state["intake"]
    if intake.get("last_analyzed_at"):
        st.success(f"Analyzed: {intake.get('last_analyzed_at')}")
    else:
        st.info("Not analyzed yet.")

    with st.container(border=True):
        st.subheader("Sources")
        sources = intake.get("sources", []) or []
        if not sources:
            st.write("No sources yet.")
        else:
            for s in sources:
                st.write(f"• {s}")

    diagnostics_panel(intake.get("diagnostics", {}) or {
        "file_type": "pdf",
        "pages": 0,
        "pages_with_text": 0,
        "characters_extracted": 0,
        "likely_scanned": "No",
        "extraction_quality": "Unknown"
    })

    with st.expander("RFP pasted text (optional)", expanded=False):
        intake["sol_text"] = st.text_area("RFP text", value=intake.get("sol_text", ""), height=240)
        if st.button("Save intake text", type="primary"):
            save_state(state)
            st.success("Saved.")


def page_company(state: Dict[str, Any], items: Dict[str, Item]):
    st.subheader("Company")
    st.caption("This improves drafting and exports, but it is not required to compute compliance.")

    company = state["company"]

    with st.container(border=True):
        st.subheader("Cover page")
        company["contract_title"] = st.text_input("Contract / Solicitation title", value=company.get("contract_title", ""))
        logo = st.file_uploader("Upload company logo (PNG/JPG)", type=["png", "jpg", "jpeg"], key="logo_uploader")
        if logo is not None:
            company["logo_b64"] = b64_from_uploaded_file(logo)
        if company.get("logo_b64"):
            try:
                st.image(base64.b64decode(company["logo_b64"]), width=180)
            except Exception:
                pass

    st.markdown("")
    with st.container(border=True):
        st.subheader("Company info")
        company["legal_name"] = st.text_input("Legal company name", value=company.get("legal_name", ""))
        company["uei"] = st.text_input("UEI", value=company.get("uei", ""))
        company["cage"] = st.text_input("CAGE", value=company.get("cage", ""))
        company["naics"] = st.text_input("Primary NAICS", value=company.get("naics", ""))
        company["address"] = st.text_area("Company address", value=company.get("address", ""), height=90)
        company["primary_contact"] = st.text_input("Primary contact", value=company.get("primary_contact", ""))
        company["email"] = st.text_input("Email", value=company.get("email", ""))
        company["phone"] = st.text_input("Phone", value=company.get("phone", ""))

    st.markdown("")
    with st.container(border=True):
        st.subheader("Registrations & certifications")
        company["sam_registered"] = st.checkbox("Registered in SAM.gov", value=bool(company.get("sam_registered", False)))
        cert_options = ["SDVOSB", "VetCert", "8(a)", "HUBZone", "WOSB"]
        company["certs"] = st.multiselect("Certifications (optional)", options=cert_options, default=company.get("certs", []))

    if st.button("Save Company", type="primary"):
        save_state(state)
        st.success("Saved.")


def page_compliance(state: Dict[str, Any], items: Dict[str, Item]):
    st.subheader("Compliance")
    st.caption("Mark actionable requirements Pass/Fail/Unknown. Your score updates live.")

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    if not actionable:
        st.info("Analyze an RFP first (Task List → Analyze).")
        return

    k = compute_kpis(items)
    compliance_kpi_panel(k)

    df = pd.DataFrame([{
        "Bucket": it.bucket,
        "Requirement": it.normalized_text,
        "Critical": "Yes" if it.is_critical else "",
        "Status": it.status,
        "Done": "Yes" if it.done else "",
        "Source": f"{it.source_file}{'' if it.page_number is None else f' p.{it.page_number}'}",
        "Confidence": int(it.confidence * 100)
    } for it in sorted(actionable, key=lambda x: (-priority_score(x), -x.confidence))])

    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Quick update")
    st.caption("Use the Task List to update status/done quickly, or use this bulk helper.")

    # Bulk helper
    col1, col2 = st.columns([1, 1])
    with col1:
        bucket = st.selectbox("Bucket", ["All"] + BUCKETS_ORDER)
    with col2:
        action = st.selectbox("Action", ["Mark all in bucket as Done", "Mark all in bucket as Pass", "Mark all in bucket as Unknown"])

    if st.button("Apply", type="primary"):
        for it in actionable:
            if bucket != "All" and it.bucket != bucket:
                continue
            if action == "Mark all in bucket as Done":
                it.done = True
            elif action == "Mark all in bucket as Pass":
                it.status = S_PASS
            else:
                it.status = S_UNKNOWN
            upsert_item(it)
        st.success("Applied.")
        st.rerun()


def page_draft(state: Dict[str, Any], items: Dict[str, Item]):
    st.subheader("Draft")
    st.caption("Draft unlocks at 60% progress. Your score is the only gate.")

    k = compute_kpis(items)
    if k["completion"] < 0.60:
        st.warning(f"Draft is locked until you reach 60% progress. Current: {int(k['completion']*100)}%.")
        return

    company = state["company"]
    intake = state["intake"]

    with st.expander("AI connection (optional)", expanded=False):
        st.caption("If secrets are not set, paste a key for testing.")
        st.session_state["_OPENAI_API_KEY_OVERRIDE"] = st.text_input("OPENAI_API_KEY", type="password", value=st.session_state.get("_OPENAI_API_KEY_OVERRIDE", ""))

    actionable = [i for i in items.values() if i.gating_label == GL_ACTIONABLE]
    top_reqs = sorted(actionable, key=lambda x: (-priority_score(x), -x.confidence))[:35]
    req_lines = []
    for it in top_reqs:
        src = f"{it.source_file}{'' if it.page_number is None else f' p.{it.page_number}'}"
        req_lines.append(f"- {it.normalized_text} (Status: {it.status}, Done: {it.done}, Source: {src})")
    req_block = "\n".join(req_lines)

    company_block = "\n".join([
        f"Company: {company.get('legal_name','')}",
        f"UEI: {company.get('uei','')}",
        f"CAGE: {company.get('cage','')}",
        f"NAICS: {company.get('naics','')}",
        f"Address: {company.get('address','')}",
        f"Primary Contact: {company.get('primary_contact','')}",
        f"Email: {company.get('email','')}",
        f"Phone: {company.get('phone','')}",
        f"SAM Registered: {company.get('sam_registered', False)}",
        f"Certifications: {', '.join(company.get('certs', []) or [])}"
    ])

    contract_title = company.get("contract_title", "") or "Solicitation"
    company_name = company.get("legal_name", "") or "Company"

    colA, colB = st.columns([0.55, 0.45], gap="large")

    with colA:
        with st.container(border=True):
            st.subheader("Proposal generator")
            proposal_style = st.selectbox("Style", ["Clear & compliant", "Executive & persuasive", "Technical & detailed"], index=0)
            length = st.select_slider("Length", options=["Short", "Medium", "Long"], value="Medium")
            focus = st.multiselect("Focus", options=["Compliance-first", "Differentiators", "Risk mitigation", "Past performance framing", "Pricing narrative (non-pricing)"],
                                   default=["Compliance-first", "Differentiators"])

            if st.button("Generate proposal draft", type="primary", use_container_width=True):
                system = (
                    "You are a senior federal proposal writer, compliance manager, and capture strategist. "
                    "Produce a maximally compliant and highly competitive draft. "
                    "If details are missing, use placeholders and list what must be confirmed."
                )
                prompt = f"""
Create a proposal draft for this solicitation.

Solicitation title: {contract_title}

Company profile:
{company_block}

High-priority compliance requirements (actionable):
{req_block}

User preference:
- Style: {proposal_style}
- Length: {length}
- Focus: {", ".join(focus) if focus else "Compliance-first"}

Output requirements:
1) Use clear headings and sections.
2) Include a Compliance Mapping section that references how the draft addresses actionable requirements.
3) Include a “Missing Inputs” list if anything is unknown or ambiguous.
4) Do not invent contract facts like dates or portals. Use placeholders when needed.
Return only the proposal text.
"""
                with st.spinner("Generating proposal…"):
                    text, err = call_ai(prompt=prompt, system=system)
                if err:
                    st.error(err)
                    text = f"""PROPOSAL DRAFT (TEMPLATE FALLBACK)

Solicitation: {contract_title}
Offeror: {company_name}

1. Executive Summary
- [Understanding of requirement]
- [Differentiators]

2. Technical Approach
- [Approach aligned to PWS/SOW]
- [Staffing and management]
- [Quality control]

3. Compliance Mapping (Actionable)
{req_block if req_block else "- [No actionable requirements captured]"}

4. Past Performance
- [Insert relevant past performance references]

5. Risk Mitigation
- [Risks + mitigations]

6. Missing Inputs
- [Submission deadline]
- [Submission portal/email]
- [Format/page limits]
- [Required forms/attachments]
"""
                state["drafts"]["proposal"] = text
                state["activity"]["draft_generated_at"] = now_iso()
                save_state(state)
                st.success("Proposal draft generated.")
                st.rerun()

            if state["drafts"].get("proposal"):
                st.text_area("Proposal draft", value=state["drafts"]["proposal"], height=420)

    with colB:
        with st.container(border=True):
            st.subheader("Cover letter")
            tone = st.selectbox("Tone", ["Professional & direct", "Warm & confident", "Bold & competitive"], index=0)

            if st.button("Generate cover letter", use_container_width=True):
                system = (
                    "You are a senior federal proposal writer. "
                    "Write a compliant, confident cover letter tailored to the solicitation. "
                    "Use placeholders for unknowns. End with a signature block."
                )
                prompt = f"""
Write a cover letter for this proposal submission.

Solicitation title: {contract_title}

Company profile:
{company_block}

Key submission/compliance items (high priority):
{req_block}

Tone: {tone}

Cover letter requirements:
- Mention the solicitation title.
- Confirm intent to submit a compliant proposal.
- Briefly highlight differentiators (do not invent).
- End with signature block:
  Sincerely,
  <Name>
  <Title or Authorized Representative>
  <Company>
  <Email>
  <Phone>

Return only the cover letter text.
"""
                with st.spinner("Generating cover letter…"):
                    text, err = call_ai(prompt=prompt, system=system)
                if err:
                    st.error(err)
                    text = f"""COVER LETTER (TEMPLATE FALLBACK)

Date: {datetime.utcnow().strftime('%Y-%m-%d')}

Subject: Proposal Submission — {contract_title}

Dear Contracting Officer,

{company_name} is pleased to submit our proposal in response to the solicitation titled "{contract_title}."
We have reviewed the submission requirements and prepared our response to comply with the instructions and required forms.

Thank you for your consideration.

Sincerely,

{company.get("primary_contact","Authorized Representative")}
{company_name}
{company.get("email","")}
{company.get("phone","")}
"""
                state["drafts"]["cover_letter"] = text
                state["activity"]["draft_generated_at"] = now_iso()
                save_state(state)
                st.success("Cover letter generated.")
                st.rerun()

            if state["drafts"].get("cover_letter"):
                st.text_area("Cover letter", value=state["drafts"]["cover_letter"], height=320)

        st.markdown("")
        with st.container(border=True):
            st.subheader("Download proposal package (DOCX)")
            if not state["drafts"].get("proposal") or not state["drafts"].get("cover_letter"):
                st.info("Generate both proposal and cover letter first.")
            else:
                docx_bytes = build_proposal_package_docx(
                    company=company,
                    items=items,
                    cover_letter_text=state["drafts"]["cover_letter"],
                    proposal_text=state["drafts"]["proposal"]
                )
                st.download_button(
                    "Download DOCX package",
                    data=docx_bytes,
                    file_name="PathAI_Proposal_Package.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True
                )


def page_export(state: Dict[str, Any], items: Dict[str, Item]):
    st.subheader("Export")
    st.caption("Export unlocks at 60% progress. Your score is the only gate.")

    k = compute_kpis(items)
    if k["completion"] < 0.60:
        st.warning(f"Export is locked until you reach 60% progress. Current: {int(k['completion']*100)}%.")
        return

    all_items = list(items.values())
    if not all_items:
        st.info("Nothing to export yet.")
        return

    xlsx_matrix = export_xlsx_compliance_matrix(all_items)
    xlsx_tasks = export_xlsx_task_list(all_items)
    xlsx_gaps = export_xlsx_gap_report(all_items)
    pdf_checklist = export_pdf_submission_checklist(all_items)
    zip_bytes = export_zip_package(pdf_checklist, xlsx_matrix, xlsx_tasks, xlsx_gaps)

    st.download_button("Download Submission Checklist (PDF)", data=pdf_checklist, file_name="Submission_Checklist.pdf", mime="application/pdf")
    st.download_button("Download Compliance Matrix (XLSX)", data=xlsx_matrix, file_name="Compliance_Matrix.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.download_button("Download Task List (XLSX)", data=xlsx_tasks, file_name="Task_List.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.download_button("Download Gap Report (XLSX)", data=xlsx_gaps, file_name="Gap_Report.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.download_button("Download FULL Export Package (ZIP)", data=zip_bytes, file_name="PathAI_Export_Package.zip", mime="application/zip")

    state["activity"]["exported_at"] = now_iso()
    save_state(state)


# -----------------------------
# App
# -----------------------------
st.set_page_config(page_title=APP_NAME, layout="wide")

# Calm styling
st.markdown("""
<style>
html, body, [class*="css"]  {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
div[data-testid="stSidebar"] { background: #fbfbfd; }
</style>
""", unsafe_allow_html=True)

state = load_state()
items = load_items()
kpis = compute_kpis(items)

# Sidebar stepper (no runs)
statuses = step_status(state, items)
stepper_sidebar(state["ui"].get("active_page", "Task List"), statuses)

# Header
st.title(APP_NAME)
st.caption("You’re now on the Path to success.")
st.caption(f"{APP_VERSION}")

# Top nav + progress bar
top_nav(state, items)

active_page = state["ui"].get("active_page", "Task List")

# Render active page
if active_page == "Task List":
    page_task_list(state, load_items())
elif active_page == "Intake":
    page_intake(state, load_items())
elif active_page == "Company":
    page_company(state, load_items())
elif active_page == "Compliance":
    page_compliance(state, load_items())
elif active_page == "Draft":
    page_draft(state, load_items())
elif active_page == "Export":
    page_export(state, load_items())
else:
    state["ui"]["active_page"] = "Task List"
    save_state(state)
    st.rerun()