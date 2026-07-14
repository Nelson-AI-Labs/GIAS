# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
GIAS — app.py  (workspace shell / router)
==========================================
Persistent picture-frame: runs on EVERY rerun.
  1. Session lifecycle (GC daemon, heartbeat, snapshot restore)
  2. CSS injection (the one stylesheet)
  3. Page registration (st.navigation, sidebar nav suppressed)
  4. Sidebar chrome: logo plate → custom journey spine → activity log → credit
  5. Species context bar (only when a species is loaded)
  6. Dispatch to the current page via pg.run()

Run with:  streamlit run app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

import streamlit as st
from core.utils.session_context import get_session_cache_base
from core.cache_layer.cache_cleanup import start_session_gc
from frontend.pages.research.research_state_store import restore_workspace_snapshot
import frontend.components as ui

# Streamlit's run_every fragments leave a browser-side auto-refresh timer that keeps
# pinging the server after the fragment is removed (e.g. when the study panel early-returns
# on deselect/merge). Each stale ping logs a benign INFO line that floods the terminal.
# Drop only that one message; this is a known unpreventable Streamlit limitation.
# Guard with a sentinel attribute so the filter is only installed once per process
# (app.py re-executes on every Streamlit rerun).
_app_session_logger = logging.getLogger("streamlit.runtime.app_session")
if not any(getattr(f, "_gias_fragment_filter", False) for f in _app_session_logger.filters):
    def _drop_stale_fragment(record: logging.LogRecord) -> bool:
        return "does not exist anymore" not in record.getMessage()
    _drop_stale_fragment._gias_fragment_filter = True
    _app_session_logger.addFilter(_drop_stale_fragment)

st.set_page_config(
    page_title="GIAS · GuardIAS Intelligence Analyst System",
    page_icon="frontend/images/GuardIAS_icon.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Native sidebar logo — auto-pins to top; white variant visible on the dark ocean rail.
# icon_image shown when sidebar is collapsed.
st.logo(
    "frontend/images/GuardIASleftlogowhite.png",
    icon_image="frontend/images/GuardIAS_icon.png",
    size="large",
)

# ── 1. Session lifecycle ──────────────────────────────────────────────────────
start_session_gc(ttl_minutes=300, interval_minutes=10)
(get_session_cache_base() / ".last_active").touch()

# Restore research workspace + routing state after a refresh or reconnect.
# No-op on fresh sessions.
restore_workspace_snapshot()

# ── 2. Stylesheet injection ───────────────────────────────────────────────────
ui.inject_css("assets/shell.css")

# ── 3. Page registration ──────────────────────────────────────────────────────
# showSidebarNavigation = false (config.toml) hides the built-in nav;
# the custom journey spine below takes its place.
pages = {
    "": [
        st.Page(
            "frontend/views/home.py",
            title="Home",
            icon=":material/home:",
            default=True,
        ),
    ],
    "Workspace": [
        st.Page("frontend/views/ingest.py",    title="Search",         icon=":material/search:"),
        st.Page("frontend/views/dashboard.py", title="Knowledge base", icon=":material/database:"),
        st.Page("frontend/views/research.py",  title="Deep research",  icon=":material/biotech:"),
        st.Page("frontend/views/report.py",    title="Report",         icon=":material/description:"),
    ],
}
pg = st.navigation(pages, position="sidebar")

# Push credit to the absolute bottom of the sidebar viewport (not content bottom).
# st.markdown injects global CSS; st.html is sandboxed so we use this instead.
# ── 4. Sidebar chrome (shared on every page) ──────────────────────────────────
with st.sidebar:
    # "Intelligence Analyst System" sublabel under the native logo
    ui.rail_sublabel()

    # Journey spine: Home + 4 workflow steps (Search → KB → Research → Report)
    ui.custom_spine()

    # Disclaimer — always visible, below nav
    st.markdown(
        "<div style='font-size:0.8rem;color:rgba(255,255,255,0.78);line-height:1.5;"
        "padding:0.9rem 0.5rem;margin-top:1.2rem;"
        "border-top:1px solid rgba(255,255,255,0.15);"
        "border-bottom:1px solid rgba(255,255,255,0.15)'>"
        "<div style='color:rgba(255,255,255,0.95);font-size:0.85rem;"
        f"font-weight:600;margin-bottom:0.55rem'>{ui.glyph_svg('warning', stroke='rgba(255,255,255,0.95)', size=13)} Disclaimer</div>"
        "<div style='font-style:italic;margin-bottom:0.55rem'>"
        "GIAS assists your research. It does not replace your judgment.</div>"
        "<div style='display:flex;gap:0.45rem;margin-bottom:0.4rem'>"
        "<span>•</span><span>Coverage is not guaranteed. Not every fact about "
        "a species will be found.</span></div>"
        "<div style='display:flex;gap:0.45rem;margin-bottom:0.4rem'>"
        "<span>•</span><span>AI can make mistakes. Always verify against the "
        "original sources.</span></div>"
        "<div style='display:flex;gap:0.45rem;margin-bottom:0.4rem'>"
        "<span>•</span><span>Your expertise stays essential for interpretation "
        "and decisions.</span></div>"
        "<div style='display:flex;gap:0.45rem'>"
        "<span>•</span><span>Inactive sessions are automatically cleared after "
        "5 hours.</span></div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # Author credit + EU funding, below the disclaimer
    with st.container(key="sidebar_credit"):
        st.divider()
        ui.rail_credit()

# ── 5. Species context bar ────────────────────────────────────────────────────
# Only shown once a species has been loaded (not on the home/landing page).
if st.session_state.get("selected_species"):
    ui.species_context_bar()

# ── 6. Run the selected page ──────────────────────────────────────────────────
pg.run()
