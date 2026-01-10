from __future__ import annotations

import streamlit as st

from exporters.compat_matrix import (
    build_compatibility_matrix_xlsx,
    get_requirements_rows,
)


def page_compat_matrix() -> None:
    st.markdown("# Compatibility Matrix")
    st.caption("Track requirements, map to your draft, export Excel.")

    # Requirements live in session
    reqs = st.session_state.get("requirements") or []

    if not reqs:
        st.warning("No requirements found yet. Upload an RFP and click Analyze first.")
        return

    # Editable UI
    for i, r in enumerate(reqs[:200]):
        rid = r.get("requirement_id", f"R{i+1:03d}")
        req_text = r.get("requirement", "")
        with st.expander(f"{rid} — {req_text[:90]}"):
            r["status"] = st.selectbox(
                "Status",
                ["Open", "In Progress", "Done"],
                index=["Open", "In Progress", "Done"].index(r.get("status", "Open"))
                if r.get("status") in ["Open", "In Progress", "Done"]
                else 0,
                key=f"cm_status_{i}",
            )
            r["notes"] = st.text_area(
                "Notes / Where this is addressed",
                value=r.get("notes", ""),
                key=f"cm_notes_{i}",
            )

    # save back
    st.session_state["requirements"] = reqs

    st.markdown("---")

    rows = get_requirements_rows(reqs)
    xlsx = build_compatibility_matrix_xlsx(rows)

    st.download_button(
        "Download Compatibility Matrix (XLSX)",
        data=xlsx,
        file_name="compatibility_matrix.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
