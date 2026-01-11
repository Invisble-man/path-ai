from __future__ import annotations

import streamlit as st

from core.state import get_rfp, get_company, set_current_step, mark_complete
from core.ai import ai_enabled, polish_for_submission
from ui.components import section_header, warn_box, ok_box, badge


def _basic_generate(company: dict, rfp: dict) -> tuple[str, str]:
    name = (company.get("name") or "").strip() or "[Company Name]"
    uei = (company.get("uei") or "").strip() or "[UEI]"
    cage = (company.get("cage") or "").strip() or "[CAGE]"
    certs = ", ".join(company.get("certifications") or []) or "[Certifications]"
    due = (rfp.get("due_date") or "").strip() or "[Due Date]"
    sub = (rfp.get("submission_email") or "").strip() or "[Submission Email/Method]"
    rfp_name = (rfp.get("filename") or "").strip() or "Solicitation"

    cover = f"""Subject: Proposal Submission – {rfp_name}

Dear Contracting Officer,

{name} is pleased to submit this proposal in response to the solicitation. We understand submissions are due {due} and will submit per the stated instructions ({sub}).

Company Identifiers:
- UEI: {uei}
- CAGE: {cage}
- Certifications: {certs}

Respectfully,
{name}
"""

    body = f"""1. Executive Summary
{name} submits this proposal to support the Government’s requirement. Our approach emphasizes compliance, accountability, and measurable execution.

2. Company Overview
- Company: {name}
- UEI/CAGE: {uei} / {cage}
- Certifications: {certs}

3. Technical Approach
[Add your approach aligned to the PWS/SOW.]

4. Staffing & Management
[Add staffing plan, management approach, and quality control.]

5. Past Performance
{company.get("past_performance") or "[Add past performance]"}

6. Differentiators
{company.get("differentiators") or "[Add differentiators]"}
"""
    return cover, body


def render() -> None:
    rfp = get_rfp()
    company = get_company()

    st.title("Draft Proposal")
    st.markdown("<div class='path-muted'>Generate, refine, and optimize your proposal for submission.</div>", unsafe_allow_html=True)
    st.write("")

    badge("Drafting Console")
    section_header("Draft", "Step 4 of 5")

    if not (rfp.extracted and (rfp.text or "").strip()):
        warn_box("Upload and analyze an RFP first.")
        if st.button("Go to Upload", type="primary", use_container_width=True):
            set_current_step("home")
            st.rerun()
        return

    st.session_state.setdefault("draft_cover_letter", "")
    st.session_state.setdefault("draft_body", "")
    st.session_state.setdefault("final_cover_letter", "")
    st.session_state.setdefault("final_body", "")
    st.session_state.setdefault("qa_findings", "")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Generate Draft", type="primary", use_container_width=True):
            cover, body = _basic_generate(company.__dict__, rfp.__dict__)
            st.session_state.draft_cover_letter = cover
            st.session_state.draft_body = body
            ok_box("Draft generated. Review it, then optimize for submission.")
    with c2:
        st.markdown(
            f"<div class='path-muted'>{'AI enabled' if ai_enabled() else 'AI optional (no key detected) — still exportable'}</div>",
            unsafe_allow_html=True,
        )

    st.write("")
    section_header("Edit Draft")

    st.session_state.draft_cover_letter = st.text_area("Cover Letter", st.session_state.draft_cover_letter, height=260)
    st.session_state.draft_body = st.text_area("Proposal Body", st.session_state.draft_body, height=360)

    st.write("")
    section_header("Optimize for Submission")

    if st.button("Optimize for Submission", use_container_width=True):
        with st.spinner("Tailoring, fixing grammar, and formatting for federal submission..."):
            out = polish_for_submission(
                rfp_text=rfp.text or "",
                company=company.__dict__,
                cover_letter=st.session_state.draft_cover_letter,
                proposal_body=st.session_state.draft_body,
            )
            st.session_state.final_cover_letter = out["polished_cover_letter"]
            st.session_state.final_body = out["polished_proposal_body"]
            st.session_state.qa_findings = out["qa_findings"]

    if (st.session_state.final_cover_letter or "").strip() or (st.session_state.final_body or "").strip():
        with st.expander("Evaluator Notes (QA Findings)", expanded=True):
            st.markdown(st.session_state.qa_findings or "No findings.")

    st.write("")
    c3, c4 = st.columns(2)
    with c3:
        if st.button("Back to Company Info", use_container_width=True):
            set_current_step("company")
            st.rerun()
    with c4:
        if st.button("Continue to Export", type="primary", use_container_width=True):
            mark_complete("draft")
            set_current_step("export")
            st.rerun()