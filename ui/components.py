import streamlit as st

def get_certifications_list():
    """
    Master list of business certifications for gov contracting.
    Used in Company Info dropdowns and eligibility checks.
    """
    return [
        "Small Business (SB)",
        "8(a)",
        "HUBZone",
        "Women-Owned Small Business (WOSB)",
        "Economically Disadvantaged WOSB (EDWOSB)",
        "Veteran-Owned Small Business (VOSB)",
        "Service-Disabled Veteran-Owned Small Business (SDVOSB)",
        "Minority-Owned Business (MBE)",
        "Disadvantaged Business Enterprise (DBE)",
        "ISO 9001",
        "ISO 27001",
        "CMMI Level 3+",
        "GSA MAS",
        "State / Local Certified Vendor",
        "Tribal-Owned Business",
        "LGBTQ+ Owned",
        "Non-Profit",
        "Public Benefit Corporation (B-Corp)"
    ]