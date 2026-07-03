# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Research Interface - Main Entry Point
Handles the research mode UI for finding and reviewing additional sources.

This module is the main entry point that imports from submodules:
- research_state.py: State initialization and migration
- topic_selection.py: Topic selection UI components
- source_discovery.py: Static discovery list and find-more pagination
- source_extraction.py: Per-study analyze/extract/merge machinery
- extraction_process.py: Research execution and extraction
"""

import streamlit as st

# Import state management
from frontend.pages.research.research_state import (
    initialize_research_state_with_dcp_sources,
)

# Import topic selection components
from frontend.pages.research.topic_selection import (
    show_topic_selection_with_counters,
)

# Import source discovery components
from frontend.pages.research.source_discovery import (
    show_sources_grid,
)

# Import extraction process components
from frontend.pages.research.extraction_process import (
    show_run_research_button,
)

# Import search filters
from frontend.pages.research.search_filters import show_search_filters


def show_research_interface():
    """Display the research mode interface for finding additional sources"""

    # Initialize research state with DCP sources if not exists
    if 'research_state' not in st.session_state:
        species_name = st.session_state.get('selected_species', '')
        universal_id = st.session_state.get('universal_id', None)
        st.session_state.research_state = initialize_research_state_with_dcp_sources(
            species_name, universal_id
        )

    # Migrate existing sessions: remove taxonomic_identity from anchor topics
    research_state = st.session_state.research_state
    if 'taxonomic_identity' in research_state.get('anchor_topics', []):
        research_state['anchor_topics'] = [
            t for t in research_state['anchor_topics'] if t != 'taxonomic_identity'
        ]

    # Migrate existing sessions: add pagination cursor store if absent
    if 'pagination' not in research_state:
        research_state['pagination'] = {}

    # Migrate existing sessions: add researched_topics tracker if absent
    if 'researched_topics' not in research_state:
        research_state['researched_topics'] = []

    # Always show workspace (no state machine)
    show_research_workspace()


def show_research_workspace():
    """Main workspace layout for research mode."""
    with st.expander("What does Deep Research do?", expanded=False, icon=":material/info:"):
        st.markdown(
            "Deep Research finds **additional scientific sources** for your species beyond the six "
            "biodiversity databases already searched.\n\n"
            "**How it works:**\n"
            "1. Pick the topics you want to find more evidence for.\n"
            "2. Set filters (year range, citation threshold, open access).\n"
            "3. Click **Run Research** — GIAS queries academic databases and the web in parallel.\n"
            "4. Click a source in the results list to open it, then analyze and extract facts.\n"
            "5. After review, merge the extracted facts into your knowledge base."
        )

    show_topic_selection_with_counters()
    show_search_filters()
    show_run_research_button()

    st.divider()
    st.markdown("#### 3 · Sources found")

    with st.expander("How does source extraction work?", expanded=False, icon=":material/help:"):
        st.markdown(
            "When you click a source, GIAS tries to **automatically fetch the PDF** from the publisher. "
            "If that fails — paywalled or bot-protected — you'll see a prompt to download and upload it manually.\n\n"
            "**Once a PDF is available:**\n"
            "1. **Analyze** — AI reads the paper and gives a brief overview of what it covers.\n"
            "2. **Topic suggestions** — AI proposes which topics (from your selection above) it can extract facts for.\n"
            "3. **Extract** — An AI pipeline pulls specific facts from the paper, one topic at a time.\n"
            "4. **Review** — Extracted facts are shown to you individually; uncheck any you want to discard.\n"
            "5. **Merge** — Accepted facts are added to this session's knowledge base, filed under the topic they were found in.\n\n"
            ":material/info: Extracted facts only persist for the current session and do not overwrite the original database data."
        )

    show_sources_grid()
