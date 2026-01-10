import streamlit as st

from core.rfp import extract_rfp_text


def page_home() -> None:
    st.markdown("## You’re on the right path to success.")
    st.caption("Upload an RFP/RFI PDF (or paste text), then click Analyze.")

    ss = st.session_state
    ss.setdefault("rfp_text", "")
    ss.setdefault("rfp_filename", "")
    ss.setdefault("rfp_pages", 0)
    ss.setdefault("analyzed", False)

    st.markdown("### Upload RFP")

    uploaded = st.file_uploader(
        "Upload RFP/RFI (PDF recommended)",
        type=["pdf", "txt"],
        accept_multiple_files=False,
        label_visibility="collapsed",
    )

    pasted = st.text_area(
        "Or paste RFP text",
        value="",
        height=180,
        placeholder="Paste the RFP/RFI text here if PDF extraction fails.",
    )

    col1, col2 = st.columns([1, 1])

    with col1:
        analyze_clicked = st.button("Analyze", use_container_width=True)

    with col2:
        clear_clicked = st.button("Clear", use_container_width=True)

    if clear_clicked:
        ss["rfp_text"] = ""
        ss["rfp_filename"] = ""
        ss["rfp_pages"] = 0
        ss["analyzed"] = False
        st.rerun()

    if analyze_clicked:
        # Priority: pasted text overrides file extraction
        if pasted and pasted.strip():
            ss["rfp_text"] = pasted.strip()
            ss["rfp_filename"] = "Pasted Text"
            # rough page estimate: ~2,000 chars per page
            ss["rfp_pages"] = max(1, len(ss["rfp_text"]) // 2000)
            ss["analyzed"] = True
            st.success("Analyzed pasted text.")
            st.rerun()

        if uploaded is None:
            st.error("Upload a file or paste text first.")
            st.stop()

        data = extract_rfp_text(uploaded)  # expects dict: {text, pages, filename}
        text = (data.get("text") or "").strip()

        if not text:
            st.error("Could not extract text from this file. Try pasting the text instead.")
            st.stop()

        ss["rfp_text"] = text
        ss["rfp_filename"] = data.get("filename") or getattr(uploaded, "name", "Uploaded File")
        ss["rfp_pages"] = int(data.get("pages") or 0)
        ss["analyzed"] = True
        st.success("RFP analyzed.")
        st.rerun()

    # Diagnostics / status (shows after analyze)
    if ss.get("analyzed") and ss.get("rfp_text"):
        st.markdown("---")
        st.markdown("### Diagnostics")
        c1, c2, c3 = st.columns(3)
        c1.metric("File", ss.get("rfp_filename") or "—")
        c2.metric("Pages (est.)", ss.get("rfp_pages") or 0)
        c3.metric("Characters", len(ss.get("rfp_text") or ""))

        st.info("Next: go to **Company Info** and then **Draft Proposal**.")