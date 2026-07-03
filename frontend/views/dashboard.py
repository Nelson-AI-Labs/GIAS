# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
GIAS — Knowledge Base Dashboard  (Screen 2)
============================================
Phase 2: thin wrapper around the existing create_species_dashboard_v2().
Phase 3 will replace the streamlit-elements MUI grid with native
st.container(border=True) + st.columns cards, fully themed.
"""

import streamlit as st

# Mark current view for spine state
st.session_state["_gias_view"] = "dashboard"

# Guard: redirect to search if no species loaded
if not st.session_state.get("selected_species"):
    st.info("No species loaded yet. Start by searching for a species.")
    if st.button("Go to Search →", type="primary", icon=":material/search:"):
        st.switch_page("frontend/views/ingest.py")
    st.stop()

# Persist workspace after every interaction
from frontend.pages.research.research_state_store import save_workspace_snapshot

# Delegate to existing dashboard renderer
from frontend.pages.species_dashboard_v2 import create_species_dashboard_v2

universal_id = st.session_state.get("universal_id")
selected_species = st.session_state.get("selected_species")

create_species_dashboard_v2(selected_species, universal_id)

save_workspace_snapshot()
