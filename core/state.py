import streamlit as st

def init_state():
    ss = st.session_state

    # RFP
    ss.setdefault("rfp_filename", None)
    ss.setdefault("rfp_pages", 0)
    ss.setdefault("rfp_text", "")
    ss.setdefault("rfp_meta", {
        "due_date": "",
        "submit_email": "",
        "submission_method": "",
        "agency": "",
        "solicitation": "",
        "title": "",
    })
    ss.setdefault("requirements", [])  # list[dict]

    # Company Info
    ss.setdefault("company", {
        "legal_name": "",
        "dba": "",
        "uei": "",
        "cage": "",
        "sam_status": "",
        "naics": "",
        "psc": "",
        "address": "",
        "city": "",
        "state": "",
        "zip": "",
        "website": "",
        "phone": "",
        "email": "",
        "poc_name": "",
        "poc_title": "",
        "poc_email": "",
        "poc_phone": "",
        "capability_summary": "",
        "past_performance": "",
        "certifications": [],
        "logo_bytes": None,
        "logo_filename": None,
    })

    # Draft
    ss.setdefault("draft", {
        "cover_title": "",
        "cover_subtitle": "",
        "cover_contract": "",
        "cover_solicitation": "",
        "cover_agency": "",
        "cover_due_date": "",
        "outline": "",
        "narrative": "",
        "ai_suggestions": [],
    })

    ss.setdefault("ai_enabled", False)
    ss.setdefault("ai_last_error", "")
