import streamlit as st
from core.rfp import extract_rfp_text
from core.analyze import analyze_rfp
from ui.components import walker_bar, compute_scores


def _eligibility_check():
    ss = st.session_state
    company_certs = set((ss.get("company", {}).get("certifications") or []))
    required = set(ss.get("rfp_meta", {}).get("required_certs") or [])
    warnings = []

    # If RFP explicitly requires cert(s) and company doesn't have them → not eligible
    missing = [c for c in required if c not in company_certs and c != "None / Not sure"]
    eligible = len(missing) == 0

    if missing:
        warnings.append(f"Eligibility warning: RFP appears to require {', '.join(missing)}. Your Company Info does not include it yet.")

    # Also check matrix eligibility tags
    for row in ss.get("matrix", []):
        tag = row.get("eligibility_tag")
        if tag and tag not in company_certs:
            # warning but still allow
            warnings.append(f"Potential mismatch: requirement '{row['id']}' references {tag}, but Company Info doesn't show it.")

    # Deduplicate warnings
    dedup = []
    seen = set()
    for w in warnings:
        if w not in seen:
            dedup.append(w)
            seen.add(w)

    ss["eligibility"] = {"eligible": eligible, "warnings": dedup}


def page_home(show_results_only: bool = False):
    ss = st.session_state

    if not show_results_only:
        st.markdown('<div class="path-card">', unsafe_allow_html=True)
        st.markdown("### Upload RFP")
        st.caption("Upload a PDF or paste RFP text. Then click Analyze.")

        up = st.file_uploader("RFP PDF", type=["pdf"])
        pasted = st.text_area("Or paste RFP text", height=150)

        colA, colB = st.columns([1, 1])
        with colA:
            analyze = st.button("Analyze", use_container_width=True)
        with colB:
            st.button("Clear", use_container_width=True, on_click=lambda: _clear_all())

        st.markdown("</div>", unsafe_allow_html=True)

        # Load
        if up is not None:
            b = up.read()
text, name = extract_rfp_text(b)
            ss["rfp_text"] = text
            ss["rfp_name"] = name
            ss["rfp_file_bytes"] = b  # used for page count analysis

        if pasted.strip():
            ss["rfp_text"] = pasted.strip()
            ss["rfp_name"] = "Pasted RFP"
            ss["rfp_file_bytes"] = b""  # no pages

        # Analyze
        if analyze:
            if not ss.get("rfp_text", "").strip():
                st.error("Upload or paste an RFP first.")
                return

            file_bytes = ss.get("rfp_file_bytes", b"")
            pages, meta, matrix = analyze_rfp(file_bytes, ss.get("rfp_name", ""), ss["rfp_text"])
            ss["rfp_pages"] = pages
            ss["rfp_meta"] = meta
            ss["matrix"] = matrix
            ss["analyzed"] = True

            _eligibility_check()

            st.success("Analysis complete. Scroll down for diagnostics, then use the sidebar steps.")

    # Results / Dashboard
    st.divider()
    st.markdown("## Readiness Console")

    compliance, company_pct, overall, win = compute_scores()
    walker_bar("Compliance", compliance)
    walker_bar("Company Profile", company_pct)
    walker_bar("Overall Progress", overall)
    walker_bar("Win Ability", win)

    st.divider()
    st.markdown("## Diagnostics")

    meta = ss.get("rfp_meta", {})
    left, right = st.columns([1, 1])

    with left:
        st.markdown('<div class="path-card">', unsafe_allow_html=True)
        st.markdown("### RFP Snapshot")
        st.write(f"**File:** {ss.get('rfp_name','')}")
        st.write(f"**Pages:** {ss.get('rfp_pages', 0)}")
        st.write(f"**Solicitation #:** {meta.get('solicitation_number','')}")
        st.write(f"**Contract Title:** {meta.get('contract_title','')}")
        st.write(f"**Agency:** {meta.get('agency','')}")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="path-card">', unsafe_allow_html=True)
        st.markdown("### Submission Info")
        st.write(f"**Due Date:** {meta.get('due_date','')}")
        st.write(f"**Submit To:** {meta.get('submission_email','')}")
        st.write(f"**Submission Method:** {meta.get('submission_method','')}")
        st.write(f"**Set-Aside:** {meta.get('set_aside','')}")
        st.write(f"**NAICS:** {meta.get('naics','')}")
        st.markdown("</div>", unsafe_allow_html=True)

    elig = ss.get("eligibility", {})
    if elig and elig.get("warnings"):
        st.markdown('<div class="path-card path-warning">', unsafe_allow_html=True)
        st.markdown("### Eligibility / Warnings")
        for w in elig["warnings"][:6]:
            st.write(f"- {w}")
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    st.markdown("## Requirements (Compatibility Matrix Preview)")
    matrix = ss.get("matrix", [])
    st.caption("This will become your core “Compatibility Matrix” export + compliance scoring source of truth.")
    st.dataframe(matrix[:30], use_container_width=True)


def _clear_all():
    # reset only key states
    for k in ["analyzed", "rfp_text", "rfp_name", "rfp_pages", "rfp_meta", "matrix", "eligibility", "draft", "last_ai_error", "rfp_file_bytes"]:
        if k in st.session_state:
            del st.session_state[k]