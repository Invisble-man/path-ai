import io
from typing import Dict

def extract_rfp_text(uploaded_file) -> Dict:
    """
    Extracts raw text and metadata from an uploaded RFP.
    """

    if uploaded_file is None:
        return {
            "text": "",
            "pages": 0,
            "filename": None
        }

    try:
        content = uploaded_file.read().decode("utf-8", errors="ignore")
        page_estimate = max(1, len(content) // 1800)

        return {
            "text": content,
            "pages": page_estimate,
            "filename": uploaded_file.name
        }

    except Exception as e:
        return {
            "text": "",
            "pages": 0,
            "filename": uploaded_file.name,
            "error": str(e)
        }
