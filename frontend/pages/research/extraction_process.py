# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Extraction Process Components
Research execution and single-source extraction functionality for the research interface.
"""

import uuid
from pathlib import Path
import streamlit as st
from core.utils.species_name_utils import standardize_species_name
from functionalities.source_finding.pipeline import run_source_finding_pipeline
from functionalities.source_finding.paginated_fetch import find_existing_source
from functionalities.extraction.pipelines.standard_pipeline import run_source_extraction_pipeline, run_context_extraction_for_source
from functionalities.extraction.pipelines.custom_pipeline import run_prompt_generation, run_custom_topic_extraction, generate_custom_search_terms
from functionalities.extraction.utils.prompt_loader import prompt_exists
from core.registries.topic_registry import StandardTopicRegistry


def ensure_custom_prompt_exists(topic: str, species_name: str) -> bool:
    """
    Ensure extraction prompt exists for custom topic.
    Uses CTS Agent 2 to generate if needed.

    Args:
        topic: Topic name (custom or predefined)
        species_name: Species name for context

    Returns:
        bool: True if prompt exists/was created, False if generation failed
    """
    research_state = st.session_state.research_state

    # Only generate for custom topics
    if topic not in research_state.get('custom_topics', []):
        return True  # Predefined topics use static prompts

    # Check if prompt already exists using CTS utility
    if prompt_exists(topic):
        return True

    # Get interpretation data
    interpretations = research_state.get('custom_topic_interpretations', {})
    if topic not in interpretations:
        print(f"Error: No interpretation found for custom topic '{topic}'")
        return False

    interp_data = interpretations[topic]

    # Generate prompt using CTS Agent 2
    print(f"[CTS] Generating extraction prompt for custom topic: '{topic}'")
    result = run_prompt_generation(
        custom_topic=topic,
        interpretation_data=interp_data,
        species_name=species_name
    )

    if result['generation_status'] not in ['success', 'loaded_from_cache']:
        print(f"Error generating prompt: {result['generation_status']}")
        return False

    print(f"Custom prompt ready for '{topic}'")
    return True


def show_run_research_button():
    """Button to trigger research on selected topics, plus a Reset button for error recovery."""
    research_state = st.session_state.research_state
    selected_count = len(research_state['selected_for_next_run'])
    researched_topics = research_state.get('researched_topics', [])

    button_disabled = selected_count == 0
    button_text = f"Run Research on {selected_count} Topic{'s' if selected_count != 1 else ''}" if selected_count > 0 else "Run Research"

    if st.button(button_text, type="primary", width="stretch", disabled=button_disabled):
        with st.spinner("Searching for sources..."):
            search_filters = st.session_state.get("search_filters", {})
            run_research_round(research_state['selected_for_next_run'].copy(), search_filters=search_filters)
            # Uncheck all after completion
            research_state['selected_for_next_run'] = []
            # Clear checkbox widget states to reset them
            for topic in research_state['anchor_topics'] + research_state['custom_topics']:
                checkbox_key = f"topic_checkbox_{topic}"
                if checkbox_key in st.session_state:
                    del st.session_state[checkbox_key]
            st.rerun()

    st.caption(
        "Select topics above and click **Run Research** to find an initial set of sources. "
        "To keep digging on topics you've already researched, use **Find more sources** in the results list below."
    )


def run_research_round(selected_topics, search_filters: dict = None, enable_caching: bool = True):
    """Execute research for selected topics with source deduplication.

    Args:
        selected_topics:  List of topic keys to research.
        search_filters:   Year/access filters from the UI.
        enable_caching:   Pass False to bypass the source-finding cache (used by Reset).
    """
    research_state = st.session_state.research_state
    species_name = st.session_state.get('selected_species', '')
    filters = search_filters or {}

    # Use cached standardized species name if available
    if 'standardized_species_name' in st.session_state:
        species_name = st.session_state.standardized_species_name
    else:
        species_name = standardize_species_name(species_name)

    progress_bar = st.progress(0)

    for i, topic in enumerate(selected_topics):
        progress_bar.progress((i + 1) / len(selected_topics))
        st.write(f"Searching for: **{topic}** sources about *{species_name}*...")

        try:
            # Determine if this is an anchor topic or custom topic
            is_custom_topic = topic in research_state.get('custom_topics', [])

            # Get search terms based on topic type
            if is_custom_topic:
                # Custom topic: generate search terms using AI agent (will be implemented in CTS)
                search_terms = generate_custom_search_terms(topic, species_name)
            else:
                # Anchor topic: get predefined search terms from registry
                normalized_topic_key = StandardTopicRegistry.normalize_topic_name(topic)
                search_terms = StandardTopicRegistry.get_search_terms(normalized_topic_key)

                if not search_terms:
                    st.warning(f"No search terms found for topic '{topic}'. Skipping.")
                    continue

            # Mark topic as researched before the pipeline call so it's locked
            # even if the run errors out — Reset is the retry path.
            if topic not in research_state.get('researched_topics', []):
                research_state.setdefault('researched_topics', []).append(topic)

            # Run SFP pipeline with predefined search terms
            result = run_source_finding_pipeline(
                research_topic=topic,
                species_name=species_name,
                search_terms=search_terms,
                enable_caching=enable_caching,
                search_filters=filters,
            )

            # Process results
            if 'search_executor' in result and 'search_results' in result['search_executor']:
                search_results = result['search_executor']['search_results']

                for source in search_results:
                    url = source.get('url', '')
                    doi = source.get('doi')

                    # Deduplication: match by URL or DOI so the same paper from
                    # two different APIs (at different URLs) is never stored twice.
                    existing = find_existing_source(url, doi, research_state['all_sources'])
                    if existing is not None:
                        # Existing source — merge topic, search terms, and source API
                        if topic not in existing['topics']:
                            existing['topics'].append(topic)
                        if source.get('search_term_used'):
                            existing['search_terms_used'].append(source.get('search_term_used'))

                        # Merge source_api so we know all APIs that found this source
                        new_api = source.get('source_api')
                        if new_api:
                            existing_api = existing.get('source_api', '')
                            # Normalize existing to list
                            if isinstance(existing_api, str):
                                existing_api = [existing_api] if existing_api else []
                            new_apis = [new_api] if isinstance(new_api, str) else (new_api or [])
                            for api in new_apis:
                                if api and api not in existing_api:
                                    existing_api.append(api)
                            existing['source_api'] = existing_api
                    else:
                        # New source — spread all pipeline fields, then add frontend-managed fields
                        research_state['all_sources'][url] = {
                            **source,
                            'id': str(uuid.uuid4()),
                            'title': source.get('title', 'No title'),
                            'domain': source.get('domain', ''),
                            'topics': [topic],
                            'search_terms_used': [source.get('search_term_used', '')],
                            'approved': False,
                            'uploaded_pdf': None,
                            'pdf_filename': None
                        }

                        # Update research source count for this topic
                        # Defensive: ensure topic exists in topic_sources
                        if topic not in research_state['topic_sources']:
                            research_state['topic_sources'][topic] = {
                                'dcp_sources': [],
                                'research_source_urls': [],
                                'dcp_count': 0,
                                'research_count': 0,
                                'total_count': 0,
                                'dashboard_card': None
                            }

                        research_state['topic_sources'][topic]['research_source_urls'].append(url)
                        research_state['topic_sources'][topic]['research_count'] += 1

                        # Recalculate total instead of incrementing to preserve dcp_count
                        dcp_count = research_state['topic_sources'][topic].get('dcp_count', 0)
                        research_count = research_state['topic_sources'][topic]['research_count']
                        research_state['topic_sources'][topic]['total_count'] = dcp_count + research_count

        except Exception as e:
            st.error(f"Error searching for {topic}: {str(e)}")

    progress_bar.progress(1.0)
    st.success(f"Research complete! Found sources for {len(selected_topics)} topic(s)")

    # Reset display counters so new sources appear from the top (page 1).
    # Counters are keyed "page_display_<prefix>__<filter>"; clear every variant.
    for key in [k for k in list(st.session_state.keys()) if k.startswith("page_display_")]:
        st.session_state.pop(key, None)


def extract_single_topic(
    topic: str,
    pdf_bytes: bytes,
    source_metadata: dict,
    species_name: str,
    search_terms: list,
    universal_id: str,
    custom_topics: list,
    extracted_data_dir: Path = None,
    session_id: str = None,
    progress_callback=None
) -> dict:
    """
    Extract a single topic from a source. Runs in a thread pool worker.

    Each call creates its own pipeline/generator/agent instances — no shared state.

    Args:
        topic: Topic key to extract
        pdf_bytes: PDF content
        source_metadata: Source metadata dict
        species_name: Species name
        search_terms: Search terms used for this source
        universal_id: Universal species ID
        custom_topics: List of custom topic names (for routing to correct pipeline)
        extracted_data_dir: Pre-resolved session-specific extracted data directory

    Returns:
        Dict with source_title, topic, status, fields_extracted, error, output_file
    """
    source_title = source_metadata.get('title', 'Untitled')

    try:
        if topic in custom_topics:
            result = run_custom_topic_extraction(
                pdf_bytes=pdf_bytes,
                source_metadata=source_metadata,
                custom_topic=topic,
                species_name=species_name,
                search_terms=search_terms,
                universal_id=universal_id,
                save_output=True,
                extracted_data_dir=extracted_data_dir,
                session_id=session_id
            )
        else:
            result = run_source_extraction_pipeline(
                pdf_bytes=pdf_bytes,
                source_metadata=source_metadata,
                species_name=species_name,
                research_topic=topic,
                search_terms=search_terms,
                universal_id=universal_id,
                save_output=True,
                extracted_data_dir=extracted_data_dir,
                session_id=session_id,
                progress_callback=progress_callback
            )

        return {
            'source_title': source_title,
            'topic': topic,
            'status': result['extraction_status'],
            'fields_extracted': result['fields_extracted'],
            'error': result.get('error_message'),
            'output_file': result.get('output_filepath'),
            '_result': result
        }

    except Exception as e:
        return {
            'source_title': source_title,
            'topic': topic,
            'status': 'failed',
            'fields_extracted': 0,
            'error': str(e),
            'output_file': None
        }
