import streamlit as st
from core.ai import ai_build_draft_package, ai_recommend_fixes


def page_draft():
    st.title("Draft Proposal")
    ss = st.session_state

    if not ss.get("analyzed"):
        st.warning("Analyze an RFP first.")
        return

    rfp_text = ss.get("rfp_text", "")
    rfp_meta = ss.get("rfp_meta", {})
    company = ss.get("company", {})
    draft = ss.get("draft", {})

    st.markdown("### AI Sync (RFP + Company → Draft)")
    st.caption("This generates your cover page fields, cover letter, and a clean outline. You can edit everything after.")

    if st.button("AI: Build Draft Package", use_container_width=True):
        try:
            ss["last_ai_error"] = ""
            out = ai_build_draft_package(rfp_text, rfp_meta, company)

            # cover page
            cp = draft.get("cover_page", {})
            cp.update(out.get("cover_page", {}))
            # ensure company data is set
            cp["offeror_name"] = company.get("legal_name", "") or cp.get("offeror_name", "")
            cp["poc_name"] = company.get("primary_poc_name", "") or cp.get("poc_name", "")
            cp["poc_email"] = company.get("primary_poc_email", "") or cp.get("poc_email", "")
            cp["poc_phone"] = company.get("primary_poc_phone", "") or cp.get("poc_phone", "")
            draft["cover_page"] = cp

            draft["cover_letter"] = out.get("cover_letter", "") or draft.get("cover_letter", "")
            draft["outline"] = out.get("outline", "") or draft.get("outline", "")

            ss["draft"] = draft
            st.success("Draft package generated.")
        except Exception as e:
            ss["last_ai_error"] = str(e)
            st.error(f"AI failed: {e}")

    st.divider()
    st.markdown("## Cover Page")
    cp = draft.get("cover_page", {})
    col1, col2 = st.columns(2)
    with col1:
        cp["contract_title"] = st.text_input("Contract Title", cp.get("contract_title", "") or rfp_meta.get("contract_title", ""))
        cp["solicitation_number"] = st.text_input("Solicitation Number", cp.get("solicitation_number", "") or rfp_meta.get("solicitation_number", ""))
        cp["agency"] = st.text_input("Agency", cp.get("agency", "") or rfp_meta.get("agency", ""))
        cp["due_date"] = st.text_input("Due Date", cp.get("due_date", "") or rfp_meta.get("due_date", ""))
    with col2:
        cp["offeror_name"] = st.text_input("Offeror (Company)", cp.get("offeror_name", "") or company.get("legal_name", ""))
        cp["poc_name"] = st.text_input("POC Name", cp.get("poc_name", "") or company.get("primary_poc_name", ""))
        cp["poc_email"] = st.text_input("POC Email", cp.get("poc_email", "") or company.get("primary_poc_email", ""))
        cp["poc_phone"] = st.text_input("POC Phone", cp.get("poc_phone", "") or company.get("primary_poc_phone", ""))

    draft["cover_page"] = cp

    st.divider()
    st.markdown("## Cover Letter")
    draft["cover_letter"] = st.text_area("Edit cover letter", draft.get("cover_letter", ""), height=260)

    st.divider()
    st.markdown("## Outline")
    draft["outline"] = st.text_area("Edit outline", draft.get("outline", ""), height=220)

    st.divider()
    st.markdown("## Narrative")
    draft["narrative"] = st.text_area("Edit narrative", draft.get("narrative", ""), height=280)

    st.divider()
    st.markdown("## AI Fix Recommendations (inline, not a separate page)")
    if st.button("AI: Recommend Fixes", use_container_width=True):
        try:
            ss["last_ai_error"] = ""
            combined = "\n\n".join([
                draft.get("cover_letter", ""),
                draft.get("outline", ""),
                draft.get("narrative", ""),
            ]).strip()
            draft["notes"] = ai_recommend_fixes(ss.get("rfp_text",""), ss.get("matrix", []), combined)
        except Exception as e:
            ss["last_ai_error"] = str(e)
            st.error(f"AI failed: {e}")

    draft["notes"] = st.text_area("Recommendations / Fix list", draft.get("notes", ""), height=200)

    ss["draft"] = draft