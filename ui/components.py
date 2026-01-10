import streamlit as st

def inject_css():
    st.markdown(
        """
<style>
:root{
  --bg:#0b0f14;
  --card:#101826;
  --muted:#9aa4b2;
  --line:rgba(255,255,255,.10);
  --good:#18c964;
  --warn:#f5a524;
  --bad:#f31260;
}
.block-container { padding-top: 1.0rem; }
h1,h2,h3 { letter-spacing: .5px; }
.hero {
  background: linear-gradient(135deg, rgba(24,201,100,.12), rgba(245,165,36,.10));
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 20px 18px;
  margin-bottom: 16px;
}
.card {
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 14px 14px;
  background: white;
}
.smallmuted { color: #667085; font-size: 12px; }
.hr { height:1px; background: rgba(0,0,0,.08); margin: 10px 0; }

.barwrap{ border:1px solid rgba(0,0,0,.12); border-radius: 999px; padding: 3px; }
.barfill{ height: 14px; border-radius: 999px; background: rgba(0,0,0,.10); position: relative;}
.barprog{ height: 14px; border-radius: 999px; background: #0ea5e9; }
.walker{
  position:absolute; top:-26px; transform: translateX(-50%);
  font-size: 16px;
}
</style>
        """,
        unsafe_allow_html=True,
    )

def bar_html(label: str, pct: int, meta: str = "", emoji: str = "🚶"):
    pct = max(0, min(100, int(pct)))
    left = max(2, min(98, pct))
    return f"""
<div style="margin:10px 0 14px 0;">
  <div style="display:flex;justify-content:space-between;align-items:baseline;">
    <div style="font-weight:700;">{label}</div>
    <div class="smallmuted">{meta}</div>
  </div>
  <div class="barwrap">
    <div class="barfill">
      <div class="barprog" style="width:{pct}%;"></div>
      <div class="walker" style="left:{left}%;">{emoji}</div>
    </div>
  </div>
</div>
"""

def sidebar_nav(app_name: str, build_version: str):
    st.sidebar.title(app_name)
    st.sidebar.caption(f"{build_version}")

    items = ["Dashboard", "Company Info", "Draft Proposal", "Export"]
    current = st.session_state.route

    # TurboTax-like progress colors
    analysis_done = bool(st.session_state.get("rfp", {}).get("text"))
    company_done = bool(st.session_state.get("company", {}).get("legal_name"))
    draft_done = bool(st.session_state.get("draft", {}).get("narrative"))

    status = {
        "Dashboard": "✅" if analysis_done else "🟠",
        "Company Info": "✅" if company_done else "🟠",
        "Draft Proposal": "✅" if draft_done else "🟠",
        "Export": "✅",
    }

    for it in items:
        label = f"{status[it]}  {it}"
        if st.sidebar.button(label, use_container_width=True, disabled=(it == current)):
            st.session_state.route = it
            st.rerun()

    st.sidebar.markdown("---")
    # Optional debug quick view (safe)
    key = (st.secrets.get("OPENAI_API_KEY") if hasattr(st, "secrets") else None) or ""
    env_key = ""
    try:
        import os
        env_key = os.getenv("OPENAI_API_KEY", "")
    except Exception:
        pass
    has_key = bool(env_key or key)
    st.sidebar.caption(f"AI: {'enabled' if has_key else 'missing key'}")