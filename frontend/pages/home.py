# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""GIAS home page: the landing screen with the G.I.A.S branding and species search
entry point that resolves a species name and launches the data-aggregation pipeline."""

import streamlit as st
import os

# Configure sidebar to be collapsed by default
st.set_page_config(initial_sidebar_state="collapsed")
from frontend.ui_components.setup_research import create_research_topics_section

from frontend.pages.species_dashboard_v2 import create_species_dashboard_v2 as create_species_dashboard

from frontend.pages.research_interface import show_research_interface
from frontend.pages.research.research_state_store import save_workspace_snapshot
from frontend.pages.about_gias import show_about_gias
from functionalities.data_aggregation.pipeline import run_species_database_pipeline
from core.utils.species_name_utils import update_streamlit_input_with_standardized_name
from core.dashboard.dashboard_tools import check_data_categories

# Sidebar with explanation (collapsed by default)
with st.sidebar:
    show_about_gias()

# Three-column layout: Logos left, Title center, Empty right
col1, col2, col3 = st.columns([1, 4, 1])

with col1:
    # GuardIAS icon below
    st.image("frontend/images/GuardIAS_icon.png", width=150)

    # EU logo at top
    st.image("frontend/images/EN_fundedbyEU_VERTICAL_RGB_Monochrome.png", width=150)

    
with col2:
    # G.I.A.S title (centered in middle column)
    st.markdown('<h1 style="text-align: center; color: #006BA6; font-weight: 600; font-size: 10rem; margin-top: 1rem; margin-bottom: 0; letter-spacing: 1rem;">G.I.A.S</h1>', unsafe_allow_html=True)

    # Subtitle below title
    st.markdown('<h4 style="text-align: center; color: #b0b0b0; font-weight: 300; margin: 0.1rem 0 0 0; font-style: italic;">GuardIAS Intelligence Analyst System</h4>', unsafe_allow_html=True)

# col3 is intentionally left empty for spacing

# Tutorial hint pointing to sidebar
st.markdown('<p style="text-align: center; color: #888; font-size: 0.85rem; margin-bottom: 0;">New to GIAS? Press <strong>&gt;&gt;</strong> in the top left for a tutorial.</p>', unsafe_allow_html=True)

# Divider between logos and input
st.markdown("---")

# Input bar with larger text using markdown
st.markdown('<h3 style="text-align: center;">Which Aquatic Species do you want to research?</h3>', unsafe_allow_html=True)
# Style the input text to be centered
st.markdown('<style>div[data-testid="stTextInput"] input { text-align: center; }</style>', unsafe_allow_html=True)
# Use separate input value that can be cleared after successful fetch
default_value = st.session_state.get('current_input_value', '')
user_input = st.text_input("Species name input", value=default_value, placeholder="Enter species name here...", label_visibility="hidden", key="species_input")

# Full width fetch button
is_fetching = st.session_state.get('fetching', False)
fetch_button = st.button(
    "Fetching..." if is_fetching else "Fetch Species Data",
    disabled=is_fetching or not user_input.strip(),
    type="primary" if user_input.strip() and not is_fetching else "secondary",
    width="stretch",
    icon=":material/hourglass_empty:" if is_fetching else ":material/search:",
)

if fetch_button and user_input.strip() and not is_fetching:
    st.session_state.fetching = True
    st.session_state.pending_species_input = user_input.strip()
    st.rerun()

# Handle Fetch Data button click
if st.session_state.get('fetching') and st.session_state.get('pending_species_input'):
    species_to_fetch = st.session_state.pending_species_input
    from functionalities.data_aggregation.pipeline import run_species_database_pipeline_with_synonyms
    from core.cache_layer.cache_cleanup import clear_session_cache
    from core.utils.session_context import get_session_id

    # --- Progress UI ---
    status_box = st.status("Fetching species data...", expanded=True)
    progress_bar = st.progress(0, text="Resolving species name...")
    current_label = st.empty()

    try:
        # Only clear cache when switching to a different species — preserve extracted
        # data if the user accidentally re-fetches the same species.
        last_species = st.session_state.get('selected_species', '')
        session_id = get_session_id()
        if species_to_fetch.lower().strip() != last_species.lower().strip():
            print(f"Species changed '{last_species}' → '{species_to_fetch}': clearing cache for session {session_id}")
            clear_session_cache()
        else:
            print(f"Same species re-fetch ('{species_to_fetch}'): skipping cache clear")

        def on_synonym_progress(current, total, current_name):
            """Progress callback fired by SynonymCoordinator at the start of each synonym
            iteration; updates the progress bar and current-synonym label."""
            progress_bar.progress(current / total, text=f"Querying synonym {current} of {total}")
            current_label.markdown(
                f"*{current_name}*  \n"
                f"<span style='color:#888; font-size:0.85em;'>via GBIF · WRiMS · IUCN · EASIN · AquaNIS</span>",
                unsafe_allow_html=True
            )
            with status_box:
                st.write(f"[{current}/{total}] {current_name}")

        with status_box:
            st.markdown(f"**Your original input:** {species_to_fetch}")

        result = run_species_database_pipeline_with_synonyms(
            species_to_fetch,
            progress_callback=on_synonym_progress
        )

        pipeline_status = result.get('status')

        if pipeline_status == 'success':
            # Collapse status box, clear ephemeral progress widgets
            total_synonyms = len(result.get('all_synonyms_searched', []))
            status_box.update(
                label=f"Searched {total_synonyms} name variant(s) for *{result.get('corrected_name', species_to_fetch)}*",
                state="complete",
                expanded=False
            )
            progress_bar.empty()
            current_label.empty()

            # Extract results
            universal_id = result.get('universal_id')
            gbif_key = result.get('gbif_key')
            corrected_name = result.get('corrected_name')
            original_query = result.get('original_query')
            synonyms_searched = result.get('all_synonyms_searched', [])
            categorized_path = result.get('categorized_path')

            # Store in session state
            st.session_state.categorized_data_ready = True
            st.session_state.categorized_data_path = categorized_path
            st.session_state.universal_id = universal_id
            st.session_state.gbif_key = gbif_key
            st.session_state.selected_species = corrected_name
            st.session_state.original_query = original_query
            st.session_state.synonyms_searched = synonyms_searched
            st.session_state.synonym_sources_failed = result.get('synonym_sources_failed', [])
            st.session_state.current_input_value = ''
            st.session_state.show_dashboard = True
            st.session_state.fetching = False
            st.session_state.pending_species_input = None

            # Clear research mode state for new species
            if 'research_state' in st.session_state:
                del st.session_state.research_state
            if 'source_segment_radio' in st.session_state:
                del st.session_state.source_segment_radio
            if 'last_extraction_results' in st.session_state:
                del st.session_state.last_extraction_results

        else:
            status_box.update(label="Failed to fetch species data", state="error", expanded=True)
            progress_bar.empty()
            current_label.empty()
            error_message = result.get('error_message', 'Unknown error')
            st.session_state.fetching = False
            st.session_state.pending_species_input = None
            st.error(f"Failed to fetch species data: {error_message}", icon=":material/error:")

    except Exception as e:
        status_box.update(label="Error during fetch", state="error", expanded=True)
        progress_bar.empty()
        current_label.empty()
        st.session_state.fetching = False
        st.session_state.pending_species_input = None
        st.error(f"Error processing species data: {str(e)}", icon=":material/error:")


# Initialize selected cards state - all topics auto-selected
if 'selected_cards' not in st.session_state:
    st.session_state.selected_cards = {
        'taxonomic_identity': True,
        'morphological_traits': True,
        'physiological_traits': True,
        'distribution': True,
        'environmental_tolerances': True,
        'conservation': True,
        'risk_assessment': False,  # Under construction
        'management': False,  # Under construction
        'ecological_impact': False  # Under construction
    }

# Show dashboard if data has been fetched
if hasattr(st.session_state, 'show_dashboard') and st.session_state.show_dashboard:
    st.markdown("---")
    
    # Mode toggle buttons
    col1, col2 = st.columns([1, 1])

    # Determine current mode
    current_mode = st.session_state.get('current_mode', 'database')  # database, research

    with col1:
        if st.button("Dashboard", icon=":material/insights:", type="primary" if current_mode == 'database' else "secondary", width="stretch"):
            st.session_state.current_mode = 'database'
            st.rerun()

    with col2:
        if st.button("Research Mode", icon=":material/science:", type="primary" if current_mode == 'research' else "secondary", width="stretch"):
            st.session_state.current_mode = 'research'
            st.rerun()

    st.markdown("---")

    # Show appropriate view based on mode
    if current_mode == 'research':
        st.markdown(f'<h3 style="text-align: center;">Research Mode: {st.session_state.selected_species}</h3>', unsafe_allow_html=True)
        show_research_interface()
    else:
        # Create interactive dashboard
        universal_id = st.session_state.get('universal_id', None)

        create_species_dashboard(st.session_state.selected_species, universal_id)

    # Persist workspace (routing + research_state) so a refresh or reconnect
    # restores the user here instead of dropping them back to search.
    save_workspace_snapshot()



