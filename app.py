import os
import re
import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

import streamlit as st

# ---------------------------
# Postgres persistence (Render)
# ---------------------------
from sqlalchemy import create_engine, Column, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

APP_VERSION = "v1.3.0 • Jan 09, 2026"

Base = declarative_base()

class ProposalRun(Base):
    __tablename__ = "proposal_runs"

    run_id = Column(String, primary_key=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    data_json = Column(Text, nullable=False)


def _normalize_database_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


@st.cache_resource
def get_db():
    db_url = _normalize_database_url(os.getenv("DATABASE_URL", "").strip())
    if not db_url:
        return None, None

    engine = create_engine(db_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal


def db_load_run(run_id: str) -> Dict[str, Any] | None:
    _, SessionLocal = get_db()
    if SessionLocal is None:
        return None
    with SessionLocal() as s:
        row = s.get(ProposalRun, run_id)
        if not row:
            return None
        try:
            return json.loads(row.data_json)
        except Exception:
            return None


def db_save_run(run_id: str, state: Dict[str, Any], name: str | None = None):
    _, SessionLocal = get_db()
    if SessionLocal is None:
        return

    now = datetime.now(timezone.utc)
    payload = json.dumps(state, ensure_ascii=False)

    with SessionLocal() as s:
        row = s.get(ProposalRun, run_id)
        if not row:
            row = ProposalRun(
                run_id=run_id,
                name=name or "",
                created_at=now,
                updated_at=now,
                data_json=payload,
            )
            s.add(row)
        else:
            row.updated_at = now
            if name is not None:
                row.name = name
            row.data_json = payload
        s.commit()


def db_list_runs(limit: int = 25) -> List[Tuple[str, str, str]]:
    _, SessionLocal = get_db()
    if SessionLocal is None:
        return []
    with SessionLocal() as s:
        rows = (
            s.query(ProposalRun)
            .order_by(ProposalRun.updated_at.desc())
            .limit(limit)
            .all()
        )
        out = []
        for r in rows:
            updated = r.updated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            out.append((r.run_id, (r.name or "").strip() or "Untitled Run", updated))
        return out


# ---------------------------
# Data model (items + gating)
# ---------------------------
GATING_ACTIONABLE = "ACTIONABLE"
GATING_INFORMATIONAL = "INFORMATIONAL"
GATING_IRRELEVANT = "IRRELEVANT"
GATING_AUTO = "AUTO_RESOLVED"

STATUS_UNKNOWN = "Unknown"
STATUS_PASS = "Pass"
STATUS_FAIL = "Fail"

BUCKETS = [
    "Missing Critical Fields",
    "Submission & Format",
    "Required Forms",
    "Volume I – Technical",
    "Volume III – Price/Cost",
    "Attachments / Exhibits",
    "Other",
]

PAGES = ["Task List", "Intake", "Company", "Compliance", "Draft", "Export"]

REQ_ID_RE = re.compile(r"\bR\d{3}\b", re.IGNORECASE)


def new_empty_state() -> Dict[str, Any]:
    return {
        "app_version": APP_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_name": "",
        "intake": {
            "source_text": "",
            "notes": "",
        },
        "company": {
            "company_name": "",
            "uei": "",
            "cage": "",
            "address": "",
            "email": "",
            "phone": "",
        },
        "items": [],
        "gate": {
            "last_run_at": None,
            "status": "GATE NOT RUN",
            "rules": {"max_unknown": 0, "max_fail": 0},
        },
        "draft": {
            "outline": "",
            "notes": "",
        },
        "export": {
            "last_export_at": None,
        },
    }


def ensure_item_shape(item: Dict[str, Any]) -> Dict[str, Any]:
    item.setdefault("id", f"I{uuid.uuid4().hex[:10]}")
    item.setdefault("req_id", "")
    item.setdefault("text", "")
    item.setdefault("bucket", "Other")
    item.setdefault("mapped_section", "")
    item.setdefault("gating_label", GATING_ACTIONABLE)
    item.setdefault("confidence", 0.50)
    item.setdefault("status", STATUS_UNKNOWN)
    item.setdefault("done", False)
    item.setdefault("notes", "")
    item.setdefault("source", "intake")
    item.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    return item


# ---------------------------
# Relevance gating (rule engine)
# ---------------------------
def infer_bucket(text: str) -> str:
    t = (text or "").lower()

    if any(k in t for k in ["offer due", "due date", "deadline", "submit", "submission", "electronic", "format", "pdf", "font", "margin", "page limit", "file format"]):
        return "Submission & Format"
    if any(k in t for k in ["sf1449", "sf 1449", "uei", "cage", "representations", "certifications", "sam.gov"]):
        return "Required Forms"
    if any(k in t for k in ["price", "pricing", "cost", "rates", "excel", "spreadsheet", "price sheet", "pricing data", "clins"]):
        return "Volume III – Price/Cost"
    if any(k in t for k in ["technical", "approach", "methodology", "sow", "statement of work", "deliverable", "performance"]):
        return "Volume I – Technical"
    if any(k in t for k in ["attachment", "exhibit", "appendix", "addendum"]):
        return "Attachments / Exhibits"
    return "Other"


def classify_gating(text: str) -> Tuple[str, float]:
    t = (text or "").strip().lower()
    if not t or len(t) < 8:
        return (GATING_IRRELEVANT, 0.95)

    # Noise
    if "page intentionally left blank" in t or "table of contents" in t:
        return (GATING_IRRELEVANT, 0.95)

    # AUTO (contract admin / invoicing terms usually not proposal-fixable)
    auto_terms = [
        "invoice", "invoices", "payment", "remit",
        "the government shall not be liable", "rejected if", "rejected",
        "contract administration",
    ]
    if any(k in t for k in auto_terms):
        return (GATING_AUTO, 0.80)

    actionable_terms = [
        "shall", "must", "required", "offeror shall", "contractor shall",
        "submit", "provide", "include", "complete", "fill",
        "no later than", "due date", "deadline", "format", "font", "margin",
    ]
    info_terms = ["for information", "reference", "see", "as described in", "may be", "reserved"]

    actionable_hits = sum(1 for k in actionable_terms if k in t)
    info_hits = sum(1 for k in info_terms if k in t)

    if actionable_hits >= 2:
        return (GATING_ACTIONABLE, min(0.95, 0.55 + 0.10 * actionable_hits))
    if actionable_hits == 1 and info_hits == 0:
        return (GATING_ACTIONABLE, 0.70)
    if info_hits >= 1 and actionable_hits == 0:
        return (GATING_INFORMATIONAL, min(0.90, 0.55 + 0.10 * info_hits))

    return (GATING_INFORMATIONAL, 0.55)


# ---------------------------
# Extraction (starter)
# ---------------------------
def extract_items_from_text(text: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]

    for ln in lines:
        keep = False
        if REQ_ID_RE.search(ln):
            keep = True
        if any(k in ln.lower() for k in ["shall", "must", "required", "offeror", "contractor", "submit", "deadline", "due date", "format", "pdf", "font", "margin"]):
            keep = True

        if not keep:
            continue

        req_match = REQ_ID_RE.search(ln)
        req_id = req_match.group(0).upper() if req_match else ""

        label, conf = classify_gating(ln)
        bucket = infer_bucket(ln)

        item = ensure_item_shape({
            "req_id": req_id,
            "text": ln,
            "bucket": bucket,
            "gating_label": label,
            "confidence": conf,
            "status": STATUS_UNKNOWN,
            "notes": "",
            "source": "intake",
        })

        if label == GATING_AUTO:
            item["status"] = STATUS_PASS
            item["done"] = True

        items.append(item)

    return items


# ---------------------------
# Missing critical fields engine (starter)
# ---------------------------
def detect_critical_missing(source_text: str) -> List[Dict[str, Any]]:
    t = (source_text or "").lower()
    missing = []

    has_deadline = any(k in t for k in ["offer due", "due date", "deadline", "no later than"])
    if not has_deadline:
        missing.append({
            "req_id": "CRIT-001",
            "text": "Submission deadline not detected. Enter/confirm the Offer Due Date (from solicitation).",
            "bucket": "Missing Critical Fields",
            "gating_label": GATING_ACTIONABLE,
            "confidence": 0.95,
        })

    has_method = any(k in t for k in ["submit electronically", "email", "portal", "upload", "sam.gov", "piee"])
    if not has_method:
        missing.append({
            "req_id": "CRIT-002",
            "text": "Submission method not detected. Confirm how proposals must be submitted (email/portal/upload).",
            "bucket": "Missing Critical Fields",
            "gating_label": GATING_ACTIONABLE,
            "confidence": 0.95,
        })

    has_format = any(k in t for k in ["pdf", "font", "margin", "page limit", "file format"])
    if not has_format:
        missing.append({
            "req_id": "CRIT-003",
            "text": "Formatting rules not detected. Confirm file format, font, margin, and page limit requirements.",
            "bucket": "Missing Critical Fields",
            "gating_label": GATING_ACTIONABLE,
            "confidence": 0.95,
        })

    has_price_sheet = any(k in t for k in ["excel", "spreadsheet", "price sheet", "pricing data"])
    if has_price_sheet:
        missing.append({
            "req_id": "CRIT-004",
            "text": "Pricing appears to require an editable spreadsheet (Excel). Prepare the required price sheet format.",
            "bucket": "Volume III – Price/Cost",
            "gating_label": GATING_ACTIONABLE,
            "confidence": 0.85,
        })

    return [ensure_item_shape(m) for m in missing]


# ---------------------------
# KPI + Gate logic
# ---------------------------
def compute_kpis(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    actionable = [i for i in items if i.get("gating_label") == GATING_ACTIONABLE]
    total = len(actionable)
    pass_ct = sum(1 for i in actionable if i.get("status") == STATUS_PASS)
    fail_ct = sum(1 for i in actionable if i.get("status") == STATUS_FAIL)
    unk_ct = sum(1 for i in actionable if i.get("status") == STATUS_UNKNOWN)
    done_ct = sum(1 for i in actionable if i.get("status") in (STATUS_PASS, STATUS_FAIL))
    completion = (done_ct / total) if total else 0.0
    return {
        "total_actionable": total,
        "pass": pass_ct,
        "fail": fail_ct,
        "unknown": unk_ct,
        "done": done_ct,
        "completion": completion,
    }


def gate_status(kpis: Dict[str, Any], max_unknown: int, max_fail: int) -> str:
    if kpis["fail"] > max_fail:
        return "FAIL"
    if kpis["unknown"] > max_unknown:
        return "AT RISK"
    return "PASS"


def chip_style(color: str) -> str:
    styles = {
        "green": "background:#e8f7ee;color:#136f3a;border:1px solid #bde5c9;",
        "yellow": "background:#fff7e6;color:#8a5a00;border:1px solid #ffe0a3;",
        "red": "background:#fdeaea;color:#9b1c1c;border:1px solid #f7b7b7;",
        "blue": "background:#e8f0fe;color:#1a3d8f;border:1px solid #bcd0ff;",
        "gray": "background:#f3f4f6;color:#374151;border:1px solid #e5e7eb;",
    }
    return styles.get(color, styles["gray"])


def render_chip(text: str, color: str):
    st.markdown(
        f"""
        <div style="
            display:inline-block;
            padding:10px 14px;
            border-radius:999px;
            font-weight:700;
            margin:6px 0;
            {chip_style(color)}
        ">{text}</div>
        """,
        unsafe_allow_html=True
    )


def clean_ui_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^\s*attachment mention:\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


# ---------------------------
# Helpers
# ---------------------------
def get_or_create_run_id() -> str:
    qp = st.query_params
    run_id = qp.get("run", "")
    if run_id:
        return run_id
    new_id = str(uuid.uuid4())
    st.query_params["run"] = new_id
    return new_id


def load_state(run_id: str) -> Dict[str, Any]:
    loaded = db_load_run(run_id)
    if loaded:
        return loaded
    return new_empty_state()


def save_state(run_id: str, state: Dict[str, Any]):
    db_save_run(run_id, state, name=state.get("run_name") or "")


def upsert_items(state: Dict[str, Any], new_items: List[Dict[str, Any]]) -> None:
    existing = state.get("items", [])
    seen = set((i.get("req_id",""), i.get("text","")) for i in existing)

    for ni in new_items:
        key = (ni.get("req_id",""), ni.get("text",""))
        if key in seen:
            continue
        existing.append(ensure_item_shape(ni))
        seen.add(key)

    state["items"] = existing


def apply_relevance_gating(state: Dict[str, Any]) -> None:
    items = []
    for it in state.get("items", []):
        it = ensure_item_shape(it)
        if not it.get("gating_label"):
            label, conf = classify_gating(it.get("text",""))
            it["gating_label"] = label
            it["confidence"] = conf
        if not it.get("bucket"):
            it["bucket"] = infer_bucket(it.get("text",""))

        if it["gating_label"] == GATING_AUTO:
            it["status"] = STATUS_PASS
            it["done"] = True
        if it["gating_label"] == GATING_ACTIONABLE:
            it["done"] = it["status"] in (STATUS_PASS, STATUS_FAIL)

        items.append(it)
    state["items"] = items


def page_ready(state: Dict[str, Any], page: str) -> bool:
    """
    "Lock the new flow" rule:
    You can still click tabs, but we show a clear block if prerequisites aren't done.
    """
    kpis = compute_kpis(state.get("items", []))
    if page == "Task List":
        return True
    if page == "Intake":
        return True
    if page == "Company":
        return bool(state.get("intake", {}).get("source_text", "").strip())
    if page == "Compliance":
        return bool(state.get("intake", {}).get("source_text", "").strip())
    if page == "Draft":
        return kpis["total_actionable"] > 0
    if page == "Export":
        return state.get("gate", {}).get("status") in ("PASS", "AT RISK")
    return True


# ---------------------------
# App UI
# ---------------------------
st.set_page_config(page_title="Path", layout="centered")

run_id = get_or_create_run_id()
state = load_state(run_id)

apply_relevance_gating(state)
kpis = compute_kpis(state.get("items", []))

# Header
col1, col2 = st.columns([3, 2])
with col1:
    st.markdown("## Path")
with col2:
    st.markdown(f"<div style='text-align:right;color:#6b7280;font-weight:700'>{APP_VERSION}</div>", unsafe_allow_html=True)

# Progress bar based on actionable completion
st.progress(kpis["completion"])

comp_pct = int(round(kpis["completion"] * 100))
comp_color = "red" if comp_pct < 40 else ("yellow" if comp_pct < 90 else "green")
render_chip(f"Completion: {comp_pct}%", comp_color)

render_chip(f"Pass: {kpis['pass']}", "green")
render_chip(f"Fail: {kpis['fail']}", "red" if kpis["fail"] > 0 else "gray")
render_chip(f"Unknown: {kpis['unknown']}", "yellow" if kpis["unknown"] > 0 else "green")

gate_txt = state.get("gate", {}).get("status", "GATE NOT RUN")
gate_color = "gray"
if gate_txt == "PASS":
    gate_color = "green"
elif gate_txt == "AT RISK":
    gate_color = "yellow"
elif gate_txt == "FAIL":
    gate_color = "red"
render_chip(f"Gate: {gate_txt}", gate_color)

st.divider()

# Horizontal navigation
tabs = st.tabs(PAGES)

# ---------------------------
# TAB 0: Task List (Home Screen)
# ---------------------------
with tabs[0]:
    st.markdown("### Task List (Home Screen)")
    st.caption("Only ACTIONABLE tasks show here. Everything else lives in Reference (collapsed) or is hidden.")

    # Run name
    state["run_name"] = st.text_input("Run name (optional)", value=state.get("run_name",""), placeholder="Example: DEA BPA – Jan 2026")

    items = state.get("items", [])
    actionable = [i for i in items if i.get("gating_label") == GATING_ACTIONABLE]

    if not actionable:
        st.info("No actionable tasks yet. Go to Intake and paste solicitation text to generate items.")
    else:
        grouped: Dict[str, List[Dict[str, Any]]] = {b: [] for b in BUCKETS}
        for a in actionable:
            b = a.get("bucket") or "Other"
            grouped.setdefault(b, [])
            grouped[b].append(a)

        for bucket in BUCKETS:
            bucket_items = grouped.get(bucket, [])
            if not bucket_items:
                continue

            # Show Missing Critical Fields expanded by default
            default_open = True if bucket == "Missing Critical Fields" else False
            with st.expander(bucket, expanded=default_open):
                for it in bucket_items:
                    it_id = it["id"]
                    rid = it.get("req_id","") or it_id
                    text = clean_ui_text(it.get("text",""))

                    st.markdown(f"**{rid}** — {text}")
                    c1, c2 = st.columns([2, 1])

                    with c1:
                        new_status = st.selectbox(
                            "Status",
                            [STATUS_UNKNOWN, STATUS_PASS, STATUS_FAIL],
                            index=[STATUS_UNKNOWN, STATUS_PASS, STATUS_FAIL].index(it.get("status", STATUS_UNKNOWN)),
                            key=f"status_{it_id}",
                            label_visibility="collapsed",
                        )
                        new_notes = st.text_input(
                            "Notes",
                            value=it.get("notes",""),
                            key=f"notes_{it_id}",
                            label_visibility="collapsed",
                            placeholder="Optional note (where it’s addressed, page ref, etc.)",
                        )

                    with c2:
                        st.markdown(f"<div style='color:#6b7280;font-size:12px;'>Confidence: {int(it.get('confidence',0.5)*100)}%</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='color:#6b7280;font-size:12px;'>Bucket: {it.get('bucket','Other')}</div>", unsafe_allow_html=True)

                    # Apply updates
                    if new_status != it.get("status") or new_notes != it.get("notes"):
                        it["status"] = new_status
                        it["notes"] = new_notes
                        it["done"] = (new_status in (STATUS_PASS, STATUS_FAIL))

                    st.divider()

        # Reference Drawer
        with st.expander("Reference (Informational content — collapsed by default)", expanded=False):
            info_items = [i for i in items if i.get("gating_label") == GATING_INFORMATIONAL]
            q = st.text_input("Search reference", value="", placeholder="Search by keyword…")
            if q:
                info_items = [i for i in info_items if q.lower() in (i.get("text","").lower())]

            st.caption(f"{len(info_items)} informational items.")
            for it in info_items[:300]:
                rid = it.get("req_id","") or it["id"]
                st.markdown(f"**{rid}** — {clean_ui_text(it.get('text',''))}")

    save_state(run_id, state)

# ---------------------------
# TAB 1: Intake
# ---------------------------
with tabs[1]:
    st.markdown("### Intake")
    st.caption("Paste solicitation text. Items are generated and relevance-gated automatically.")

    runs = db_list_runs(limit=25)
    if runs:
        with st.expander("Load an existing run", expanded=False):
            opts = [f"{name} — {updated} — {rid}" for rid, name, updated in runs]
            chosen = st.selectbox("Recent runs", opts, index=0)
            if st.button("Load selected run"):
                rid = chosen.split(" — ")[-1].strip()
                st.query_params["run"] = rid
                st.rerun()

    state["intake"]["source_text"] = st.text_area(
        "Solicitation Text",
        value=state["intake"].get("source_text",""),
        height=240,
        placeholder="Paste the solicitation/RFP text here…"
    )
    state["intake"]["notes"] = st.text_area(
        "Notes (optional)",
        value=state["intake"].get("notes",""),
        height=90,
        placeholder="Optional notes (scope, NAICS, special constraints)…"
    )

    cA, cB, cC = st.columns([1, 1, 1])
    with cA:
        if st.button("Generate / Refresh Items", use_container_width=True):
            src = state["intake"].get("source_text","")
            extracted = extract_items_from_text(src)
            crit = detect_critical_missing(src)

            upsert_items(state, extracted)
            upsert_items(state, crit)

            apply_relevance_gating(state)
            save_state(run_id, state)
            st.success("Items updated. Go to Task List to complete actionable tasks.")
            st.rerun()

    with cB:
        if st.button("Re-run Relevance Gating", use_container_width=True):
            apply_relevance_gating(state)
            save_state(run_id, state)
            st.success("Gating refreshed.")
            st.rerun()

    with cC:
        if st.button("Reset Items (danger)", use_container_width=True):
            state["items"] = []
            state["gate"]["status"] = "GATE NOT RUN"
            state["gate"]["last_run_at"] = None
            save_state(run_id, state)
            st.warning("Items cleared. Paste text and regenerate.")
            st.rerun()

# ---------------------------
# TAB 2: Company
# ---------------------------
with tabs[2]:
    st.markdown("### Company")
    if not page_ready(state, "Company"):
        st.warning("Complete Intake first (paste solicitation text) so the app can determine what’s relevant.")
    else:
        st.caption("Basic company info (used later for draft + export).")
        c1, c2 = st.columns(2)
        with c1:
            state["company"]["company_name"] = st.text_input("Company Name", value=state["company"].get("company_name",""))
            state["company"]["uei"] = st.text_input("UEI", value=state["company"].get("uei",""))
            state["company"]["cage"] = st.text_input("CAGE", value=state["company"].get("cage",""))
        with c2:
            state["company"]["email"] = st.text_input("Email", value=state["company"].get("email",""))
            state["company"]["phone"] = st.text_input("Phone", value=state["company"].get("phone",""))
            state["company"]["address"] = st.text_area("Address", value=state["company"].get("address",""), height=100)

        st.info("Next: go to Task List and start completing ACTIONABLE items.")
        save_state(run_id, state)

# ---------------------------
# TAB 3: Compliance
# ---------------------------
with tabs[3]:
    st.markdown("### Compliance")
    if not page_ready(state, "Compliance"):
        st.warning("Complete Intake first (paste solicitation text) to generate actionable compliance tasks.")
    else:
        st.caption("Compliance is driven ONLY by ACTIONABLE items (Pass/Fail/Unknown).")

        # Gate rules
        st.subheader("Gate Rules")
        r1, r2 = st.columns(2)
        with r1:
            state["gate"]["rules"]["max_unknown"] = st.number_input(
                "Max Unknown allowed",
                min_value=0,
                max_value=9999,
                value=int(state["gate"]["rules"].get("max_unknown", 0)),
            )
        with r2:
            state["gate"]["rules"]["max_fail"] = st.number_input(
                "Max Fail allowed",
                min_value=0,
                max_value=9999,
                value=int(state["gate"]["rules"].get("max_fail", 0)),
            )

        st.subheader("Run Gate Check")
        if st.button("Run Gate Check", use_container_width=True):
            apply_relevance_gating(state)
            kpis_now = compute_kpis(state.get("items", []))
            status = gate_status(
                kpis_now,
                max_unknown=int(state["gate"]["rules"]["max_unknown"]),
                max_fail=int(state["gate"]["rules"]["max_fail"]),
            )
            state["gate"]["status"] = status
            state["gate"]["last_run_at"] = datetime.now(timezone.utc).isoformat()
            save_state(run_id, state)
            st.success(f"Gate result: {status}")
            st.rerun()

        st.divider()
        st.subheader("Actionable Summary")
        k = compute_kpis(state.get("items", []))
        st.write(f"- Actionable total: **{k['total_actionable']}**")
        st.write(f"- Pass: **{k['pass']}**")
        st.write(f"- Fail: **{k['fail']}**")
        st.write(f"- Unknown: **{k['unknown']}**")
        st.write(f"- Completion: **{int(round(k['completion']*100))}%**")

        save_state(run_id, state)

# ---------------------------
# TAB 4: Draft
# ---------------------------
with tabs[4]:
    st.markdown("### Draft")
    if not page_ready(state, "Draft"):
        st.warning("Generate actionable tasks first (Intake → Generate).")
    else:
        st.caption("This is a starter draft area. Later we’ll add AI to generate a proposal draft from tasks + company info.")

        # Simple draft outline generator (non-AI placeholder)
        if st.button("Generate Draft Outline (starter)", use_container_width=True):
            actionable = [i for i in state.get("items", []) if i.get("gating_label") == GATING_ACTIONABLE]
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for a in actionable:
                grouped.setdefault(a.get("bucket","Other"), [])
                grouped[a.get("bucket","Other")].append(a)

            outline_lines = []
            outline_lines.append(f"Proposal Draft Outline — {state.get('company',{}).get('company_name','[Company]')}")
            outline_lines.append("")
            for bucket in BUCKETS:
                if bucket not in grouped:
                    continue
                outline_lines.append(f"## {bucket}")
                for it in grouped[bucket]:
                    rid = it.get("req_id","") or it["id"]
                    outline_lines.append(f"- {rid}: {clean_ui_text(it.get('text',''))}")
                outline_lines.append("")
            state["draft"]["outline"] = "\n".join(outline_lines)
            save_state(run_id, state)
            st.success("Draft outline created.")
            st.rerun()

        state["draft"]["outline"] = st.text_area(
            "Draft Outline",
            value=state["draft"].get("outline",""),
            height=260,
        )
        state["draft"]["notes"] = st.text_area(
            "Draft Notes",
            value=state["draft"].get("notes",""),
            height=120,
            placeholder="Add notes for later AI generation (tone, win themes, past performance, etc.)",
        )

        save_state(run_id, state)

# ---------------------------
# TAB 5: Export
# ---------------------------
with tabs[5]:
    st.markdown("### Export")
    if not page_ready(state, "Export"):
        st.warning("Run Gate Check first (Compliance tab). Export is locked until Gate is PASS or AT RISK.")
    else:
        st.caption("Export should only include what’s relevant. (PDF/CSV package generator will be expanded next.)")

        k = compute_kpis(state.get("items", []))
        st.info(f"Gate: {state.get('gate',{}).get('status','GATE NOT RUN')} • Completion: {int(round(k['completion']*100))}%")

        # Minimal CSV export of actionable items
        import pandas as pd

        actionable = [i for i in state.get("items", []) if i.get("gating_label") == GATING_ACTIONABLE]
        df = pd.DataFrame([{
            "Req ID": (i.get("req_id") or i.get("id")),
            "Bucket": i.get("bucket",""),
            "Requirement": clean_ui_text(i.get("text","")),
            "Status": i.get("status",""),
            "Notes": i.get("notes",""),
            "Confidence": i.get("confidence",0.0),
        } for i in actionable])

        st.subheader("Compliance Matrix (Actionable only)")
        st.dataframe(df, use_container_width=True, hide_index=True)

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download Compliance Matrix (CSV)",
            data=csv_bytes,
            file_name="compliance_matrix_actionable.csv",
            mime="text/csv",
            use_container_width=True
        )

        # Save export timestamp
        if st.button("Mark Export Generated", use_container_width=True):
            state["export"]["last_export_at"] = datetime.now(timezone.utc).isoformat()
            save_state(run_id, state)
            st.success("Export marked.")
            st.rerun()

        save_state(run_id, state)

# Final save
save_state(run_id, state)