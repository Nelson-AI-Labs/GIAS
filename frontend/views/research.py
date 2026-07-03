# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
GIAS — Deep Research  (Screen 3)
==================================
Single-page two-pane workbench: source discovery (left list) + per-study
analyze → extract → merge panel (right pane). No separate extract page.
"""

import streamlit as st

# Mark current view for spine state
st.session_state["_gias_view"] = "research"

# Guard: redirect to search if no species loaded
if not st.session_state.get("selected_species"):
    st.info("No species loaded yet. Start by searching for a species.")
    if st.button("Go to Search", type="primary", icon=":material/search:"):
        st.switch_page("frontend/views/ingest.py")
    st.stop()

from frontend.pages.research_interface import show_research_interface
from frontend.pages.research.research_state_store import save_workspace_snapshot

st.markdown(f"## Deep Research: *{st.session_state.selected_species}*")

show_research_interface()

save_workspace_snapshot()
