import streamlit as st
import textwrap

PAGES = ["Dashboard", "Company Info", "Draft Proposal", "Export"]

CERTIFICATIONS = [
    "None / Not sure",
    "SDVOSB (Service-Disabled Veteran-Owned Small Business)",
    "VOSB (Veteran-Owned Small Business)",
    "8(a)",
    "HUBZone",
    "WOSB (Women-Owned Small Business)",
    "EDWOSB (Economically Disadvantaged WOSB)",
    "SDB (Small Disadvantaged Business)",
    "MBE (Minority Business Enterprise)",
    "DBE (Disadvantaged Business Enterprise)",
    "Small Business",
    "Large Business",
    "ISO 9001",
    "ISO 27001",
    "CMMI",
]

def ensure_state():
    ss = st.session_state
    ss.setdefault("analyzed", False)

    ss.setdefault("rfp_text", "")
    ss.setdefault("rfp_name", "")
    ss.setdefault("rfp_pages", 0)

    ss.setdefault("rfp_meta", {
        "solicitation_number": "",
        "contract_title": "",
        "agency": "",
        "due_date": "",
        "submission_email": "",
        "submission_method": "",
        "place_of_performance": "",
        "naics": "",
        "set_aside": "",
        "required_certs": [],  # detected from RFP
    })

    ss.setdefault("company", {
        "legal_name": "",
        "doing_business_as": "",
        "uei": "",
        "cage": "",
        "duns": "",
        "ein": "",
        "naics_codes": "",
        "address_line1": "",
        "address_line2": "",
        "city": "",
        "state": "",
        "zip": "",
        "country": "USA",
        "website": "",
        "phone": "",
        "capability_statement": "",
        "certifications": ["None / Not sure"],
        "primary_poc_name": "",
        "primary_poc_title": "",
        "primary_poc_email": "",
        "primary_poc_phone": "",
        "banking_duns_note": "",
        "logo_bytes": None,
        "logo_name": None,
    })

    ss.setdefault("matrix", [])  # [{id, requirement, status, evidence, notes, eligibility_tag}]
    ss.setdefault("eligibility", {"eligible": True, "warnings": []})

    ss.setdefault("draft", {
        "cover_page": {
            "contract_title": "",
            "solicitation_number": "",
            "agency": "",
            "due_date": "",
            "offeror_name": "",
            "poc_name": "",
            "poc_email": "",
            "poc_phone": "",
        },
        "cover_letter": "",
        "outline": "",
        "narrative": "",
        "notes": "",
    })

    ss.setdefault("last_ai_error", "")


def top_brand_bar():
    # Clean “Google-like” header on landing + everywhere
    st.markdown(
        """
        <div style="padding: 8px 0 4px 0;">
          <div style="font-size: 34px; font-weight: 800; letter-spacing: -0.5px;">Path.ai</div>
          <div style="margin-top:-6px; font-size: 16px; opacity: 0.85;">You’re on the right path to success.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def inject_global_css():
    # Slightly rugged + futuristic + clean
    css = """
    <style>
      .block-container { padding-top: 1.2rem; }
      [data-testid="stSidebar"] { border-right: 1px solid rgba(0,0,0,0.08); }
      .path-card {
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 14px;
        padding: 16px;
        background: rgba(255,255,255,0.75);
      }
      .path-muted { opacity: 0.8; }
      .path-warning { border-left: 6px solid #f5a623; padding-left: 10px; }
      .path-danger { border-left: 6px solid #e74c3c; padding-left: 10px; }
      .path-ok { border-left: 6px solid #2ecc71; padding-left: 10px; }
      .step-dot { display:inline-block; width:10px; height:10px; border-radius: 999px; margin-right:8px; }
      .step-red { background:#e74c3c; }
      .step-orange { background:#f5a623; }
      .step-green { background:#2ecc71; }
      .walker-wrap { margin-top: 6px; }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def compute_scores():
    ss = st.session_state

    # Compliance = % Pass in matrix
    matrix = ss.get("matrix", [])
    if not matrix:
        compliance = 0
    else:
        passed = sum(1 for r in matrix if r.get("status") == "Pass")
        compliance = int((passed / len(matrix)) * 100)

    # Company completeness
    c = ss.get("company", {})
    required_fields = ["legal_name", "uei", "cage", "address_line1", "city", "state", "zip", "primary_poc_name", "primary_poc_email"]
    company_ok = sum(1 for f in required_fields if str(c.get(f, "")).strip())
    company_pct = int((company_ok / len(required_fields)) * 100)

    # Progress
    rfp_ok = 1 if ss.get("rfp_text", "").strip() else 0
    analyzed_ok = 1 if ss.get("analyzed") else 0
    draft = ss.get("draft", {})
    draft_ok = 1 if (draft.get("outline", "").strip() or draft.get("narrative", "").strip()) else 0

    overall = int((rfp_ok * 20) + (analyzed_ok * 20) + (company_pct * 0.3) + (compliance * 0.3))
    overall = max(0, min(100, overall))

    # “Win Ability” (simple heuristic; you can refine later)
    eligibility = ss.get("eligibility", {})
    penalties = 25 if not eligibility.get("eligible", True) else 0
    win = max(0, min(100, int((overall * 0.65) + (compliance * 0.35) - penalties)))

    return compliance, company_pct, overall, win


def walker_bar(label: str, pct: int, meta: str = ""):
    pct = max(0, min(100, int(pct)))
    left = max(2, min(98, pct))

    # Simple inline walker (SVG circle “head” + body). No heavy images.
    walker_svg = """
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="6" r="3" fill="currentColor"></circle>
      <path d="M8 22l2-7 2 2 2-3 3 8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    """

    html = f"""
    <div class="walker-wrap">
      <div style="display:flex; justify-content:space-between; font-weight:700;">
        <div>{label}</div>
        <div class="path-muted">{pct}% {("• " + meta) if meta else ""}</div>
      </div>
      <div style="position:relative; height:14px; border-radius:999px; border:1px solid rgba(0,0,0,0.15); overflow:hidden;">
        <div style="height:100%; width:{pct}%; background:rgba(245,166,35,0.85);"></div>
        <div style="position:absolute; top:-6px; left:{left}%; transform:translateX(-50%); color:rgba(0,0,0,0.65);">
          {walker_svg}
        </div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def nav_sidebar(app_name: str, build_version: str):
    st.sidebar.title(app_name)
    st.sidebar.caption(build_version)

    compliance, company_pct, overall, win = compute_scores()

    st.sidebar.markdown("### Readiness Console")
    walker_bar("Compliance", compliance, "")
    walker_bar("Company Profile", company_pct, "")
    walker_bar("Overall Progress", overall, "")
    walker_bar("Win Ability", win, "")

    # step status colors
    ss = st.session_state
    step_company = company_pct >= 70
    step_draft = bool(ss.get("draft", {}).get("outline", "").strip() or ss.get("draft", {}).get("narrative", "").strip())
    step_export = True

    st.sidebar.divider()
    st.sidebar.markdown("### Navigate")

    def dot(ok, started):
        if ok:
            return "step-dot step-green"
        if started:
            return "step-dot step-orange"
        return "step-dot step-red"

    started_company = company_pct > 0
    started_draft = step_draft
    started_dashboard = True

    st.sidebar.markdown(f'<div><span class="{dot(True, started_dashboard)}"></span>Dashboard</div>', unsafe_allow_html=True)
    st.sidebar.markdown(f'<div><span class="{dot(step_company, started_company)}"></span>Company Info</div>', unsafe_allow_html=True)
    st.sidebar.markdown(f'<div><span class="{dot(step_draft, started_draft)}"></span>Draft Proposal</div>', unsafe_allow_html=True)
    st.sidebar.markdown(f'<div><span class="{dot(step_export, True)}"></span>Export</div>', unsafe_allow_html=True)

    st.sidebar.divider()
    page = st.sidebar.radio("Go to", PAGES, index=0)

    # Eligibility warnings
    elig = ss.get("eligibility", {})
    if elig and elig.get("warnings"):
        st.sidebar.warning("\n".join(elig["warnings"]), icon="⚠️")

    # AI errors
    if ss.get("last_ai_error"):
        st.sidebar.warning(f"AI issue: {ss['last_ai_error']}", icon="⚠️")

    return page


def get_certifications_list():
    return CERTIFICATIONS