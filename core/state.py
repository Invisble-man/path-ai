def init_state(ss):
    ss.setdefault("current_page", "Upload RFP")

    # RFP
    ss.setdefault("rfp_text", "")
    ss.setdefault("rfp_pages", 0)
    ss.setdefault("rfp_filename", "")
    ss.setdefault("rfp_meta", {
        "title": "",
        "solicitation": "",
        "agency": "",
        "due_date": "",
        "submit_email": "",
        "submission_method": "",
    })

    # Company Info
    ss.setdefault("company", {
        "legal_name": "",
        "uei": "",
        "cage": "",
        "sam_status": "Active",
        "address": "",
        "city": "",
        "state": "",
        "zip": "",
        "website": "",
        "phone": "",
        "email": "",
        "naics": "",
        "certifications": [],
        "poc_name": "",
        "poc_title": "",
        "poc_email": "",
        "poc_phone": "",
        "capability_summary": "",
        "past_performance": "",
        "logo_bytes": None,
    })

    # Requirements / matrix
    ss.setdefault("requirements", [])

    # Draft
    ss.setdefault("draft", {
        "cover_title": "",
        "cover_contract": "",
        "cover_solicitation": "",
        "cover_agency": "",
        "cover_due_date": "",
        "outline": "",
        "narrative": "",
    })

    # AI
    ss.setdefault("ai_enabled", False)
    ss.setdefault("ai_last_error", "")