import io
import re
import streamlit as st
from pypdf import PdfReader
import docx

st.set_page_config(page_title="Path – Federal Proposal Generator", layout="wide")

st.title("Path – Federal Proposal Generator")

# ---------- Helpers ----------
def extract_text_from_pdf(file_bytes):
    reader = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def extract_text_from_docx(file_bytes):
    document = docx.Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in document.paragraphs)

def find_attachments(text):
    keywords = [
        "attachment", "appendix", "exhibit",
        "sf-1449", "pricing", "price schedule",
        "reps and certs", "signature", "fill out"
    ]
    results = []
    for line in text.splitlines():
        if any(k in line.lower() for k in keywords):
            results.append(line.strip())
    return list(set(results))

# ---------- UI ----------
uploaded_file = st.file_uploader(
    "Upload RFP (PDF, DOCX, or TXT)",
    type=["pdf", "docx", "txt"]
)

rfp_text = ""

if uploaded_file:
    if uploaded_file.name.endswith(".pdf"):
        rfp_text = extract_text_from_pdf(uploaded_file.read())
    elif uploaded_file.name.endswith(".docx"):
        rfp_text = extract_text_from_docx(uploaded_file.read())
    else:
        rfp_text = uploaded_file.read().decode("utf-8")

rfp_text = st.text_area(
    "Or paste RFP / RFI text",
    value=rfp_text,
    height=300
)

if st.button("Analyze"):
    if not rfp_text.strip():
        st.warning("Please upload or paste an RFP first.")
    else:
        st.success("Analysis complete")

        st.subheader("RFP Stats")
        st.write("Characters:", len(rfp_text))

        st.subheader("Attachments / Forms You Must Complete")
        attachments = find_attachments(rfp_text)

        if attachments:
            for a in attachments:
                st.write("-", a)
        else:
            st.write("No obvious attachments detected.")

        st.subheader("Preview")
        st.write(rfp_text[:1000])
