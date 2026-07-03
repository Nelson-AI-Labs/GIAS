# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Source Extraction — per-study analyze → extract → merge machinery.

Public API consumed by source_discovery.py (two-pane workbench right panel):
  render_study_panel(source_key, source)   — full panel, polling, no expander wrapper
  study_state(source)                      — derives display state from source flags
  render_source_card(source_key, source)   — expander card (legacy, kept for compat)
"""

import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st

from frontend.pages.research.extraction_process import (
    ensure_custom_prompt_exists,
    extract_single_topic,
)
from frontend.pages.research.topic_suggestion import analyze_single_source
from functionalities.extraction.pipelines.standard_pipeline import run_context_extraction_for_source
from core.utils.session_context import get_session_id
from functionalities.extraction.merge_engine import merge_extracted_data_dict
from core.cache_layer.categorized_data_helpers import load_categorized_data_by_id, save_categorized_data_by_id
from core.cache_layer.cache_cleanup import delete_source_cache

# Executor for PDF fetch, analysis, and extraction workers.
_EXECUTOR = ThreadPoolExecutor(max_workers=4)


# ============================================================================
# STUDY STATE (used by source_discovery left list + right panel)
# ============================================================================

def study_state(source: dict) -> str:
    """Derive display state from source flags. Public — imported by source_discovery.py."""
    if source.get('merged'):
        return 'merged'
    if source.get('_analysis_status') == 'running' or source.get('_extraction_status') == 'running':
        return 'analyzing'
    if source.get('suggested_topics_analysis') is not None or source.get('extraction_results'):
        return 'ready'
    return 'idle'


def _study_state_label(source: dict, state: str) -> str:
    """
    Badge string for a study queue chip — includes fact counts for merged/ready states.
    Labels match the mock's status strings.
    """
    if state == 'idle':
        return ':gray-badge[▶ not started]'
    if state == 'analyzing':
        return ':blue-badge[:material/progress_activity: analyzing…]'
    if state == 'ready':
        n = sum(
            len(r.get('extracted_data', {}))
            for r in source.get('extraction_results', {}).values()
            if r.get('extraction_status') == 'success'
        )
        return f':orange-badge[● {n} facts ready]' if n else ':orange-badge[● analyzed]'
    if state == 'merged':
        n = 0
        for topic, r in source.get('extraction_results', {}).items():
            if r.get('extraction_status') == 'success':
                rejected = source.get('rejected_facts', {}).get(topic, set())
                n += len(r.get('extracted_data', {})) - \
                    len(rejected & set(r.get('extracted_data', {})))
        return f':green-badge[:material/check: merged · {n} facts]' if n else ':green-badge[:material/check: merged]'
    return ':gray-badge[▶ not started]'


def render_study_panel(source_key: str, source: dict):
    """
    Full study panel for the Extract screen's active study — no expander wrapper.
    Polling and PDF fetch are active only here, so only this study runs background work.
    """
    run_every = "3s" if _card_needs_polling(source) else None

    @st.fragment(run_every=run_every)
    def _panel_fragment():
        _maybe_submit_pdf_fetch(source)

        if source.get('_pdf_fetch_status') == 'done':
            source.pop('_pdf_fetch_status', None)
            source.pop('_pdf_fetch_error', None)
            st.rerun(scope="app")

        research_state = st.session_state.research_state
        _render_expanded_content(source_key, source, research_state)

    _panel_fragment()


# ============================================================================
# POLLING HELPERS
# ============================================================================

def _will_start_pdf_fetch(source: dict) -> bool:
    return (
        not source.get('uploaded_pdf')
        and not source.get('_pdf_fetch_status')
        and not source.get('is_dcp_source')
        and not source.get('is_manual_upload')
        and bool(source.get('pdf_url') or source.get('url'))
    )


def _card_needs_polling(source: dict) -> bool:
    if _will_start_pdf_fetch(source):
        return True
    return any(
        source.get(flag) in ('running', 'done')
        for flag in ('_pdf_fetch_status', '_analysis_status', '_extraction_status')
    )


# ============================================================================
# SOURCE CARD (expander version — kept for any future use)
# ============================================================================

def render_source_card(source_key: str, source: dict):
    """
    Unified source card renderer with expander.
    Polls every 3s only while a background operation is active.
    """
    run_every = "3s" if _card_needs_polling(source) else None

    @st.fragment(run_every=run_every)
    def _card_fragment():
        _maybe_submit_pdf_fetch(source)

        if source.get('_pdf_fetch_status') == 'done':
            source.pop('_pdf_fetch_status', None)
            source.pop('_pdf_fetch_error', None)
            st.rerun(scope="app")

        research_state = st.session_state.research_state
        source_id = source.get('id', 'unknown')

        expander_key = f"card_open_{source_id}"
        expander_label = _expander_label(source)
        is_open = st.session_state.get(expander_key, True)
        with st.expander(expander_label, expanded=is_open):
            st.session_state[expander_key] = True
            _render_expanded_content(source_key, source, research_state)

        st.divider()

    _card_fragment()


def _expander_label(source: dict) -> str:
    title = source.get('title', 'Untitled source')
    if len(title) > 100:
        title = title[:97] + '…'
    return f"**{title}**"


def _render_card_meta_line(source: dict):
    """year · journal · citations · state caption below the title."""
    parts = []

    year = source.get('publication_year')
    if year:
        parts.append(str(year))

    journal = source.get('journal_name')
    if journal:
        parts.append(journal[:40] + '…' if len(journal) > 40 else journal)

    citations = source.get('citation_count')
    if citations and citations > 0:
        parts.append(f"{citations:,} citations")

    has_pdf = bool(source.get('uploaded_pdf'))
    has_extractions = bool(source.get('extraction_results'))
    pdf_fetch_status = source.get('_pdf_fetch_status')
    if source.get('merged'):
        parts.append(':material/check: Merged')
    elif has_extractions:
        count = len(source.get('extraction_results', {}))
        parts.append(f"{count} topic{'s' if count != 1 else ''} extracted")
    elif source.get('suggested_topics_analysis') is not None:
        parts.append('Analyzed — ready to extract')
    elif has_pdf:
        parts.append('PDF ready')
    elif pdf_fetch_status == 'running':
        parts.append('Fetching PDF...')
    elif pdf_fetch_status in ('blocked', 'error'):
        parts.append('PDF blocked — upload manually')
    elif not source.get('is_dcp_source'):
        parts.append('No PDF')

    if source.get("is_low_confidence"):
        parts.append(":material/warning: Low relevance")

    if parts:
        st.caption('  ·  '.join(parts))


# ============================================================================
# EXPANDED CONTENT
# ============================================================================

def _render_extraction_progress(source: dict):
    steps = source.get('_progress_steps', [])
    total = max(source.get('_progress_total', 1), 1)
    pct = min(len(steps) / total, 1.0)
    st.progress(pct, text="Extracting… this may take a minute per topic.")


def _render_expanded_content(source_key: str, source: dict, research_state: dict):
    """
    Render card detail in three phases based on progress.
    Active phase is prominent; earlier phases collapse to a summary line.
    """
    needs_rerun = False
    if source.get('_analysis_status') == 'done':
        source.pop('_analysis_status', None)
        source.pop('_analysis_error', None)
        needs_rerun = True
    if source.get('_extraction_status') == 'done':
        source.pop('_extraction_status', None)
        source.pop('_extraction_error', None)
        source.pop('_extraction_total', None)
        source.pop('_progress_steps', None)
        source.pop('_progress_total', None)
        source.pop('_pdf_annotated_bytes', None)
        source.pop('_pdf_annotated_key', None)
        needs_rerun = True
    if needs_rerun:
        st.rerun(scope="app")

    is_dcp = source.get('is_dcp_source', False)
    is_manual = source.get('is_manual_upload', False)
    has_pdf = bool(source.get('uploaded_pdf'))
    has_extractions = bool(source.get('extraction_results'))
    is_merged = source.get('merged', False)
    # Meta line is owned by _render_active_study_pane (source_discovery.py) — no second line here.

    if is_dcp:
        _render_full_metadata(source_key, source)
        return

    if is_merged:
        _render_full_metadata(source_key, source)
        st.divider()
        topics = source.get('topics', [])
        topic_str = ', '.join(t.replace('_', ' ')
                              for t in topics) if topics else '—'
        st.caption(f"Topics merged: {topic_str}")
        return

    _render_full_metadata(source_key, source, show_uploader=True)

    if is_manual:
        _render_delete_button(source_key, source, research_state)

    st.markdown("")

    has_analysis = source.get('suggested_topics_analysis') is not None
    has_pdf = bool(source.get('uploaded_pdf'))

    # ── Controls: analyze / extract ──────────────────────────────────────────
    if not has_analysis:
        _render_analyze_button(
            source, source_key, research_state, disabled=not has_pdf)
    else:
        _render_analysis_results(source, source_key, research_state)
        if source.get('topics'):
            _render_topic_extraction_button(source, source_key)
        elif not has_extractions:
            st.caption("Add topics above, then extract data.")
        if source.get('_extraction_status') == 'running':
            _render_extraction_progress(source)

    # ── Unified results tabs: 📄 Paper Summary + per-topic facts ──────────────
    if has_analysis or has_extractions:
        _render_results_tabs(source)

    # ── AI-proposed banner + merge ────────────────────────────────────────────
    if has_extractions:
        n_total = sum(
            len(r.get('extracted_data', {}))
            for r in source.get('extraction_results', {}).values()
            if r.get('extraction_status') == 'success'
        )
        if n_total:
            st.info(
                f"**{n_total} fact{'s' if n_total != 1 else ''}** proposed by AI · "
                "nothing is added to the dashboard until you merge",
                icon=":material/smart_toy:",
            )
        st.markdown("")
        _render_source_merge_button(source, source_key)

    # NB: the Source PDF preview is rendered by _render_active_study_pane
    # (source_discovery.py) at the pane's top level — outside this fragment and
    # outside any fixed-height scroll container — so the data-URI iframe paints.


def _render_full_metadata(source_key: str, source: dict, show_uploader: bool = False):
    """Source links/DOI/provenance, then the PDF uploader — full-width stacked.

    Rendered flat (no inner columns) so the panel stays responsive and uncramped
    inside the narrow-ish right column, and column depth stays ≤2.
    """
    url = source.get('url', '')
    domain = source.get('domain', '')

    # Source + DOI on one compact line — both remain clickable links.
    doi = source.get('doi')
    source_parts = []
    if not source.get('is_manual_upload') and url:
        source_parts.append(f"**Source:** [{domain or url}]({url})")
    if doi:
        source_parts.append(f"**DOI:** [{doi}](https://doi.org/{doi})")
    if source_parts:
        st.markdown("  ·  ".join(source_parts))

    if not source.get('is_dcp_source') and not source.get('is_manual_upload'):
        source_api = source.get('source_api', '')
        apis = source_api if isinstance(source_api, list) else [
            source_api] if source_api else []
        api_labels = {
            'semantic_scholar': 'Semantic Scholar', 'europe_pmc': 'Europe PMC',
            'openalex': 'OpenAlex', 'doaj': 'DOAJ',
            'google_scholar': 'Google Scholar', 'tavily': 'Web Search',
        }
        label_parts = [api_labels.get(a, a) for a in apis if a]

        is_tavily = 'tavily' in apis
        if not is_tavily:
            search_terms = [t for t in source.get(
                'search_terms_used', []) if t]
            seen = set()
            unique_terms = [t for t in search_terms if not (
                t in seen or seen.add(t))]
            # Provenance caption — search terms tucked into tooltip to save vertical space.
            if label_parts:
                help_text = (f"Search terms: {' · '.join(unique_terms)}"
                             if unique_terms else None)
                st.caption(f"via {' · '.join(label_parts)}", help=help_text)
        elif label_parts:
            st.caption(f"via {' · '.join(label_parts)}")

        if is_tavily:
            st.markdown(
                '<span style="background:#dbeafe; color:#1e40af; padding:2px 8px; '
                'border-radius:4px; font-size:0.82em;">Web Search Result</span>',
                unsafe_allow_html=True,
            )
            if 'guardias.eu' in source.get('domain', ''):
                st.markdown(
                    '<span style="background:#fef3c7; color:#92400e; padding:2px 8px; '
                    'border-radius:4px; font-size:0.82em;">From GuardIAS</span>',
                    unsafe_allow_html=True,
                )
            score = source.get('score', 0.0)
            if score > 0:
                institution = source.get('journal_name') or source.get(
                    'domain', 'institutional source')
                tooltip = (
                    f"This document was found via AI-powered web search on institutional "
                    f"sources ({institution}). The score reflects how closely this document "
                    f"matched the web search query for this topic."
                )
                st.progress(
                    score, text=f"Search relevance: {int(score * 100)}%")
                st.caption("What is this?", help=tooltip)

    if show_uploader:
        _render_pdf_upload_section(source)


def _render_pdf_upload_section(source: dict):
    """
    PDF section in four states:
    1. PDF present — filename + Clear + inline preview
    2. Fetch in progress — spinner message
    3. Fetch blocked/err — warning + manual uploader fallback
    4. No pdf_url — standard manual uploader
    """
    source_id = source.get('id', 'unknown')
    has_pdf = bool(source.get('uploaded_pdf'))
    fetch_status = source.get('_pdf_fetch_status')

    if has_pdf:
        st.caption(":material/picture_as_pdf: PDF attached")
        if st.button("Clear PDF", key=f"clear_pdf_{source_id}", type="secondary"):
            source['uploaded_pdf'] = None
            source['pdf_filename'] = None
            source.pop('_pdf_fetch_status', None)
            source.pop('_pdf_fetch_error', None)
            source.pop('context_results', None)
            source.pop('suggested_topics_analysis', None)
            source.pop('pre_analysis_topics', None)
            source.pop('extraction_results', None)
            st.rerun(scope="app")
        return

    if fetch_status == 'running':
        st.info("Fetching PDF automatically...")
        return

    if fetch_status in ('blocked', 'error'):
        error_msg = source.get('_pdf_fetch_error', 'Could not auto-fetch PDF.')
        st.warning(f"Auto-fetch failed: {error_msg}")

    uploaded_file = st.file_uploader(
        "Upload PDF",
        type=['pdf'],
        key=f"pdf_{source_id}",
    )

    if uploaded_file is not None:
        source['uploaded_pdf'] = uploaded_file.read()
        source['pdf_filename'] = uploaded_file.name


def _build_pdf_highlights(source: dict, registry) -> list:
    highlights = []
    extraction_results = source.get('extraction_results', {})
    rejected_facts = source.get('rejected_facts', {})

    for topic, result in extraction_results.items():
        if result.get('extraction_status') != 'success':
            continue
        color = registry.get_topic_color_rgb(topic)
        extracted_data = result.get('extracted_data', {})
        topic_rejected = rejected_facts.get(topic, set())
        for field_name, field_data in extracted_data.items():
            if field_name in topic_rejected:
                continue
            if not isinstance(field_data, dict):
                continue
            quote = field_data.get('source_quote', '')
            if quote and quote.lower() != 'not found':
                highlights.append(
                    {"topic": topic, "quote": quote, "color": color})

    return highlights


def _page_sort_key(field_data: dict) -> int:
    """First page number from reasoning string, or 999 if absent."""
    if not isinstance(field_data, dict):
        return 999
    reasoning = field_data.get('reasoning', '')
    location = reasoning.split('|')[0] if '|' in reasoning else reasoning
    numbers = re.findall(r'\d+', location)
    return int(numbers[0]) if numbers else 999


def _render_highlight_legend(topics_present: list, registry) -> None:
    if not topics_present:
        return
    legend_items = []
    for topic in topics_present:
        display = topic.replace('_', ' ').title()
        hex_color = registry.get_topic_color_hex(topic)
        legend_items.append(
            f'<span style="display:inline-flex;align-items:center;margin-right:12px;">'
            f'<span style="width:12px;height:12px;background:{hex_color};border-radius:2px;'
            f'display:inline-block;margin-right:4px;border:1px solid #ccc;"></span>'
            f'<span style="font-size:0.75rem;">{display}</span></span>'
        )
    st.markdown(
        '<div style="margin-bottom:4px;">' + ''.join(legend_items) + '</div>',
        unsafe_allow_html=True
    )


def _render_pdf_preview(source: dict):
    """
    Inline PDF preview via the native st.pdf viewer (PDF.js — renders on canvas,
    so it works inside any container, unlike a data:-URI iframe which Chromium
    blocks). Fact highlights are baked into the bytes by PyMuPDF before display.
    """
    from core.registries.topic_registry import StandardTopicRegistry

    pdf_bytes = source['uploaded_pdf']
    highlights = _build_pdf_highlights(source, StandardTopicRegistry)
    topics_present = list(dict.fromkeys(h['topic'] for h in highlights))

    display_bytes = pdf_bytes
    if highlights:
        _HIGHLIGHT_CACHE_VERSION = 2
        cache_key = (_HIGHLIGHT_CACHE_VERSION,) + \
            tuple((h['topic'], h['quote']) for h in highlights)
        if source.get('_pdf_annotated_key') == cache_key and source.get('_pdf_annotated_bytes'):
            display_bytes = source['_pdf_annotated_bytes']
        else:
            # Wrap annotation in try/except — the PDF highlighter is not yet stable
            annotated = None
            try:
                from frontend.ui_components.pdf_highlighter import annotate_pdf_with_highlights
                annotated = annotate_pdf_with_highlights(pdf_bytes, highlights)
            except Exception:
                pass
            if annotated:
                display_bytes = annotated
                source['_pdf_annotated_bytes'] = annotated
                source['_pdf_annotated_key'] = cache_key

    if topics_present:
        _render_highlight_legend(topics_present, StandardTopicRegistry)

    # If a "locate to" button set a target page, slice the annotated PDF to
    # that single page so the viewer opens on it.  A "Show full PDF" button
    # clears the target and reverts to the full document.
    source_id = source.get('id')
    target_page = st.session_state.get(f"pdf_target_page_{source_id}")
    if target_page is not None:
        try:
            from frontend.ui_components.pdf_highlighter import slice_pdf_to_page
            sliced = slice_pdf_to_page(display_bytes, target_page)
        except Exception:
            sliced = None
        if sliced:
            display_bytes = sliced
            col_info, col_btn = st.columns([0.65, 0.35], vertical_alignment="center")
            with col_info:
                st.caption(f":material/my_location: Showing page {target_page}")
            with col_btn:
                if st.button(
                    "Show full PDF",
                    icon=":material/menu_book:",
                    key=f"pdf_full_{source_id}",
                ):
                    st.session_state.pop(f"pdf_target_page_{source_id}", None)
                    st.rerun(scope="app")

    st.pdf(display_bytes, height=600)


def _auto_pdf_filename(source: dict) -> str:
    """Derive a meaningful, filesystem-safe filename for an auto-fetched PDF.

    Priority: title (readable) → DOI (canonical) → short source id (fallback).
    Slugified via sanitize_for_id so special characters, spaces, and Unicode are
    all stripped to alphanumeric + underscores/hyphens.
    """
    from core.utils.universal_identifier import sanitize_for_id
    title = source.get('title') or ''
    doi = source.get('doi') or ''
    if title:
        base = sanitize_for_id(title)[:60]
    elif doi:
        base = sanitize_for_id(doi)
    else:
        base = f"source_{str(source.get('id', '')).replace('-', '')[:8]}"
    return f"{base}.pdf"


def _maybe_submit_pdf_fetch(source: dict) -> None:
    """Submit background PDF fetch if needed. No-op if already fetched, in-flight, DCP, or manual."""
    if (
        source.get('uploaded_pdf')
        or source.get('_pdf_fetch_status')
        or source.get('is_dcp_source')
        or source.get('is_manual_upload')
        or (not source.get('pdf_url') and not source.get('url'))
    ):
        return

    source['_pdf_fetch_status'] = 'running'

    def _do_fetch(src: dict) -> None:
        from functionalities.source_finding.pdf_fetcher import fetch_pdf_for_source
        pdf_bytes, status, error = fetch_pdf_for_source(
            pdf_url=src.get('pdf_url'),
            url=src.get('url'),
        )
        if status == 'done':
            src['uploaded_pdf'] = pdf_bytes
            src['pdf_filename'] = _auto_pdf_filename(src)
        src['_pdf_fetch_status'] = status
        src['_pdf_fetch_error'] = error

    _EXECUTOR.submit(_do_fetch, source)


def _render_delete_button(source_key: str, source: dict, research_state: dict):
    source_id = source.get('id', 'unknown')

    if st.button("Delete this source", key=f"delete_manual_{source_id}", type="secondary"):
        if source_key in research_state['all_sources']:
            del research_state['all_sources'][source_key]

        universal_id = st.session_state.get('universal_id')
        if universal_id:
            delete_source_cache(source_id=source_key,
                                universal_id=universal_id)

        for topic in source.get('topics', []):
            if topic in research_state['topic_sources']:
                topic_data = research_state['topic_sources'][topic]
                if source_key in topic_data.get('research_source_urls', []):
                    topic_data['research_source_urls'].remove(source_key)
                if topic_data.get('research_count', 0) > 0:
                    topic_data['research_count'] -= 1
                if topic_data.get('total_count', 0) > 0:
                    topic_data['total_count'] -= 1

        # Clear active_study so the right pane shows the empty-state message
        # immediately rather than pointing at a deleted source key.
        # Filter pill sanitization is handled per-render in _pills_facet(), so
        # no explicit pill-state cleanup is needed here.
        if st.session_state.get("active_study") == source_key:
            st.session_state.pop("active_study", None)

        st.rerun(scope="app")


# ============================================================================
# STUDY ANALYSIS
# ============================================================================

def _render_analyze_button(source: dict, source_key: str, research_state: dict, disabled: bool = False):
    source_id = source.get('id', 'unknown')
    analysis_status = source.get('_analysis_status')

    if analysis_status == 'running':
        st.info("Analyzing study... this may take a minute.")
        return

    if analysis_status == 'error':
        st.error(
            f"Analysis failed: {source.get('_analysis_error', 'Unknown error')}")
        if st.button("Retry analysis", key=f"retry_analyze_{source_id}", type="secondary"):
            source.pop('_analysis_status', None)
            source.pop('_analysis_error', None)
            st.rerun(scope="app")
        return

    if st.button(
        "Analyze study",
        key=f"analyze_study_{source_id}",
        type="primary",
        disabled=disabled,
        help="Upload a PDF first" if disabled else "Scans document for relevant topics and extracts study context"
    ):
        _submit_study_analysis(source, source_key, research_state)
        st.rerun(scope="app")


def _submit_study_analysis(source: dict, source_key: str, research_state: dict):
    if source.get('_analysis_status') == 'running':
        return

    species_name = st.session_state.get('selected_species', '')
    if 'standardized_species_name' in st.session_state:
        species_name = st.session_state.standardized_species_name

    universal_id = st.session_state.get('universal_id', 'unknown_id')
    session_id = get_session_id()

    from core.utils.cache_manager import get_extracted_data_dir
    extracted_data_dir = get_extracted_data_dir()

    source_metadata = {
        'id': source.get('id', 'unknown'),
        'url': source.get('url', ''),
        'title': source.get('title', ''),
        'domain': source.get('domain', ''),
        'doi': source.get('doi'),
        'publication_year': source.get('publication_year'),
        'journal_name': source.get('journal_name'),
        'authors': source.get('authors', []),
    }

    source['_analysis_status'] = 'running'

    _EXECUTOR.submit(
        _bg_analysis_worker,
        source, source_metadata, species_name, universal_id,
        extracted_data_dir, research_state, session_id
    )


def _bg_analysis_worker(source, source_metadata, species_name, universal_id,
                        extracted_data_dir, research_state, session_id):
    try:
        with ThreadPoolExecutor(max_workers=2) as inner:
            context_future = inner.submit(
                run_context_extraction_for_source,
                pdf_bytes=source['uploaded_pdf'],
                source_metadata=source_metadata,
                species_name=species_name,
                universal_id=universal_id,
                save_output=True,
                extracted_data_dir=extracted_data_dir,
                session_id=session_id
            )
            suggestion_future = inner.submit(
                analyze_single_source, source, research_state)

            try:
                context_result = context_future.result()
                source['context_results'] = context_result
                if context_result.get('translated_from') and 'translated_from' not in source:
                    source['translated_from'] = context_result['translated_from']
                    source['translation_failed'] = context_result.get(
                        'translation_failed', False)
                    source['translation_note'] = context_result.get(
                        'translation_note', '')
            except Exception as e:
                source['context_results'] = {
                    'context_status': 'failed',
                    'error_message': str(e),
                    'context_results': {},
                    'context_keys_extracted': [],
                    'total_context_fields': 0
                }

            source['suggested_topics_analysis'] = suggestion_future.result()
            source['pre_analysis_topics'] = list(source.get('topics', []))

        source['_analysis_status'] = 'done'
    except Exception as e:
        source['_analysis_error'] = str(e)
        source['_analysis_status'] = 'error'


def _render_analysis_results(source: dict, source_key: str, research_state: dict):
    if source.get('translated_from'):
        lang = source['translated_from']
        if source.get('translation_failed'):
            st.warning(
                f"Translation from **{lang}** failed — data extracted from original text. "
                f"Verify data quality carefully.",
                icon=":material/warning:"
            )
        else:
            st.info(
                f"This document was automatically translated from **{lang}** before extraction.",
                icon=":material/translate:"
            )

    _render_suggested_topics_section(source, source_key, research_state)


# ============================================================================
# TOPIC EXTRACTION
# ============================================================================

def _render_topic_extraction_button(source: dict, source_key: str):
    source_id = source.get('id', 'unknown')
    extraction_status = source.get('_extraction_status')

    if extraction_status == 'running':
        done_count = len(source.get('extraction_results', {}))
        total = source.get('_extraction_total', '?')
        st.info(f"Extracting topics... ({done_count}/{total} complete)")
        return

    if extraction_status == 'error':
        st.error(
            f"Extraction failed: {source.get('_extraction_error', 'Unknown error')}")
        if st.button("Retry extraction", key=f"retry_extract_{source_id}", type="secondary"):
            source.pop('_extraction_status', None)
            source.pop('_extraction_error', None)
            st.rerun(scope="app")
        return

    extraction_results = source.get('extraction_results', {})
    topics = source.get('topics', [])
    topics_without_results = [t for t in topics if t not in extraction_results]

    if topics_without_results:
        n = len(topics_without_results)
        label = f"Extract data for {n} topic{'s' if n != 1 else ''}"
        if st.button(label, key=f"extract_topics_{source_id}", type="primary",
                     help="Run AI extraction for the assigned topics using this source's PDF"):
            _submit_topic_extraction(
                source, source_key, topics_without_results)
            st.rerun(scope="app")


def _run_context_inline(source, source_metadata, species_name, universal_id, extracted_data_dir, session_id):
    try:
        context_result = run_context_extraction_for_source(
            pdf_bytes=source['uploaded_pdf'],
            source_metadata=source_metadata,
            species_name=species_name,
            universal_id=universal_id,
            save_output=True,
            extracted_data_dir=extracted_data_dir,
            session_id=session_id
        )
        source['context_results'] = context_result
        if context_result.get('translated_from') and 'translated_from' not in source:
            source['translated_from'] = context_result['translated_from']
            source['translation_failed'] = context_result.get(
                'translation_failed', False)
            source['translation_note'] = context_result.get(
                'translation_note', '')
    except Exception as e:
        source['context_results'] = {
            'context_status': 'failed',
            'error_message': str(e),
            'context_results': {},
            'context_keys_extracted': [],
            'total_context_fields': 0
        }


def _render_context_results(context_results: dict):
    status = context_results.get('context_status', 'failed')
    if status == 'failed':
        st.warning(
            f"Context extraction failed: {context_results.get('error_message', 'Unknown error')}")
        return
    results = context_results.get('context_results', {})
    if not results:
        st.caption("No context data extracted")
        return
    for context_key, ctx_data in results.items():
        ctx_status = ctx_data.get('extraction_status', 'failed')
        fields_count = ctx_data.get('fields_extracted', 0)
        display_name = context_key.replace('_', ' ').title()
        if ctx_status == 'success' and fields_count > 0:
            # Always expanded — no fold control (per user request).
            st.markdown(f"**{display_name}** ({fields_count} fields)")
            for field_name, field_data in ctx_data.get('extracted_data', {}).items():
                readable_name = field_name.replace('_', ' ').title()
                value = field_data.get(
                    'value', 'N/A') if isinstance(field_data, dict) else field_data
                st.markdown(f"**{readable_name}:** {value}")
        else:
            st.caption(f"{display_name}: No data extracted")


def _submit_topic_extraction(source: dict, source_key: str, topics: list):
    if source.get('_extraction_status') == 'running':
        return

    species_name = st.session_state.get('selected_species', '')
    if 'standardized_species_name' in st.session_state:
        species_name = st.session_state.standardized_species_name

    universal_id = st.session_state.get('universal_id', 'unknown_id')
    session_id = get_session_id()
    research_state = st.session_state.research_state
    custom_topics = research_state.get('custom_topics', [])

    from core.utils.cache_manager import get_extracted_data_dir
    extracted_data_dir = get_extracted_data_dir()

    ready_topics = [
        t for t in topics if ensure_custom_prompt_exists(t, species_name)]
    if not ready_topics:
        return

    source.setdefault('extraction_results', {})
    source['_extraction_status'] = 'running'
    source['_extraction_total'] = len(ready_topics)
    source['_progress_steps'] = []
    source['_progress_total'] = 2 + 2 * len(ready_topics)

    _EXECUTOR.submit(
        _bg_extraction_worker,
        source, ready_topics, species_name, universal_id,
        custom_topics, extracted_data_dir, session_id
    )


def _bg_extraction_worker(source, topics, species_name, universal_id,
                          custom_topics, extracted_data_dir, session_id):
    try:
        source_metadata = {
            'id': source.get('id', 'unknown'),
            'url': source.get('url', ''),
            'title': source.get('title', ''),
            'domain': source.get('domain', ''),
            'doi': source.get('doi'),
            'publication_year': source.get('publication_year'),
            'journal_name': source.get('journal_name'),
            'authors': source.get('authors', []),
        }

        def _step(label):
            source['_progress_steps'].append(label)

        if 'context_results' not in source:
            _run_context_inline(source, source_metadata, species_name,
                                universal_id, extracted_data_dir, session_id)

        with ThreadPoolExecutor(max_workers=min(len(topics), 4)) as inner:
            futures = {
                inner.submit(
                    extract_single_topic,
                    topic=topic,
                    pdf_bytes=source['uploaded_pdf'],
                    source_metadata=source_metadata,
                    species_name=species_name,
                    search_terms=source.get('search_terms_used', []),
                    universal_id=universal_id,
                    custom_topics=custom_topics,
                    extracted_data_dir=extracted_data_dir,
                    session_id=session_id,
                    progress_callback=_step
                ): topic
                for topic in topics
            }

            for future in as_completed(futures):
                topic = futures[future]
                topic_result = future.result()
                if topic_result.get('_result'):
                    source['extraction_results'][topic] = topic_result['_result']
                    if topic_result['_result'].get('translated_from') and 'translated_from' not in source:
                        source['translated_from'] = topic_result['_result']['translated_from']
                        source['translation_note'] = topic_result['_result'].get(
                            'translation_note', '')
                        source['translation_failed'] = topic_result['_result'].get(
                            'translation_failed', False)

        source['_extraction_status'] = 'done'
    except Exception as e:
        from functionalities.extraction.agents.data_extraction_agent import _classify_api_error
        error_type, user_message = _classify_api_error(e)
        source['_extraction_error'] = user_message
        source['_extraction_error_type'] = error_type
        source['_extraction_status'] = 'error'


def _tab_label_for(topic: str, result: dict) -> str:
    """Build the tab label string for a single topic result."""
    display_topic = topic.replace('_', ' ').title()
    status = result.get('extraction_status')
    if status == 'no_data':
        return f"{display_topic} (0)"
    if status != 'success':
        return f"{display_topic} :material/cancel:"
    n_facts = len(result.get('extracted_data', {}))
    return f"{display_topic} ({n_facts})"


def _render_results_tabs(source: dict):
    """
    Unified results strip: '📄 Paper Summary' (context) first, then one tab per
    extracted topic. Before extraction the strip is just Paper Summary; topic
    tabs join it after extraction. All tabs share a 280px scroll height.
    """
    context_results = source.get('context_results')
    extraction_results = source.get('extraction_results', {})

    has_context = bool(context_results)
    if not has_context and not extraction_results:
        return

    if 'rejected_facts' not in source:
        source['rejected_facts'] = {}

    source_id = source.get('id', 'unknown')

    # Build tab labels: Paper Summary first, then per-topic with static fact totals.
    # Labels are static (no live included-count) so st.tabs identity is stable across reruns.
    tab_labels = []
    if has_context:
        tab_labels.append(":material/description: Paper Summary")
    for topic, result in extraction_results.items():
        tab_labels.append(_tab_label_for(topic, result))

    # Restore the last-active topic tab from session_state (written by _on_fact_change).
    # st.tabs sends default_tab_index to the frontend on EVERY rerun, so we must pass
    # the correct default each time or it resets to tab[0] (Paper Summary).
    active_topic = st.session_state.get(f"active_tab_{source_id}")
    default_tab = None
    if active_topic and active_topic in extraction_results:
        default_tab = _tab_label_for(active_topic, extraction_results[active_topic])

    tabs = st.tabs(tab_labels, default=default_tab)

    idx = 0
    if has_context:
        with tabs[0]:
            with st.container(height=280, border=False):
                _render_context_results(context_results)
        idx = 1

    for topic, result in extraction_results.items():
        with tabs[idx]:
            with st.container(height=280, border=False):
                _render_topic_facts(source, topic, result)
        idx += 1


def _on_fact_change(source_id: str, topic: str) -> None:
    """Record which topic tab the user last interacted with so st.tabs can restore it."""
    st.session_state[f"active_tab_{source_id}"] = topic


def _render_topic_facts(source: dict, topic: str, result: dict):
    """Render one extracted topic's facts as a checkbox list (one results tab body)."""
    source_id = source.get('id', 'unknown')
    status = result.get('extraction_status', 'failed')

    if status == 'no_data':
        st.info("No relevant facts found for this topic in this document.", icon=":material/info:")
        return
    if status != 'success':
        error_msg = result.get('error_message', 'Unknown error')
        error_type = result.get('error_type', 'unknown')
        if error_type in ('rate_limit', 'service_unavailable', 'auth_error', 'token_limit'):
            st.error(error_msg, icon=":material/warning:")
        else:
            st.error(f"Extraction failed: {error_msg}")
        return

    extracted_data = result.get('extracted_data', {})
    if not extracted_data:
        st.caption("No relevant data found for this topic in this document.")
        return

    source.setdefault('rejected_facts', {})
    topic_rejected = source['rejected_facts'].setdefault(topic, set())

    # Show live included count in the body (safe to recompute on every rerun here).
    n_facts = len(extracted_data)
    n_included = n_facts - len(topic_rejected & set(extracted_data.keys()))
    st.caption(f"{n_included} of {n_facts} facts included")

    for field_name, field_data in sorted(
        extracted_data.items(), key=lambda kv: _page_sort_key(kv[1])
    ):
        value = field_data.get('value', '') if isinstance(
            field_data, dict) else field_data
        display_field = field_name.replace('_', ' ').title()

        if isinstance(value, list):
            display_value = ', '.join(str(v) for v in value) if value else '—'
        elif value is None or value == '':
            display_value = '—'
        else:
            display_value = str(value)

        checkbox_key = f"fact_{source_id}_{topic}_{field_name}"

        page_idx = field_data.get('pdf_page_index') if isinstance(field_data, dict) else None
        has_pdf_locate = bool(page_idx and source.get('uploaded_pdf'))

        if has_pdf_locate:
            col_cb, col_btn = st.columns([0.92, 0.08], vertical_alignment="center")
        else:
            col_cb = st

        with col_cb:
            included = st.checkbox(
                f"**{display_field}:** {display_value}",
                value=field_name not in topic_rejected,
                key=checkbox_key,
                on_change=_on_fact_change,
                args=(source_id, topic),
            )

        if has_pdf_locate:
            with col_btn:
                if st.button(
                    "",
                    icon=":material/my_location:",
                    key=f"locate_{source_id}_{topic}_{field_name}",
                    help=f"Show this fact in the PDF (page {page_idx})",
                ):
                    st.session_state[f"pdf_open_{source_id}"] = True
                    st.session_state[f"pdf_target_page_{source_id}"] = page_idx
                    st.session_state[f"active_tab_{source_id}"] = topic
                    st.rerun(scope="app")

        if included:
            topic_rejected.discard(field_name)
        else:
            topic_rejected.add(field_name)


# ============================================================================
# PER-SOURCE MERGE
# ============================================================================

def _render_source_merge_button(source: dict, source_key: str):
    source_id = source.get('id', 'unknown')
    universal_id = st.session_state.get('universal_id')
    if not universal_id:
        st.caption("No species selected — cannot merge.")
        return

    if source.get('merged', False):
        st.caption(":material/check_circle: Facts merged into dashboard")
        return

    if st.button("Merge into dashboard", key=f"merge_source_{source_id}", type="primary", icon=":material/check:",
                 help="Add approved facts from this source to the species dashboard"):
        with st.spinner("Merging..."):
            _run_source_merge(source, universal_id)


def _run_source_merge(source: dict, universal_id: str):
    extraction_results = source.get('extraction_results', {})
    rejected_facts = source.get('rejected_facts', {})
    source_title = source.get('title', 'Research Source')
    research_state = st.session_state.research_state
    custom_topics = research_state.get('custom_topics', [])

    categorized_data = load_categorized_data_by_id(universal_id)
    if not categorized_data:
        st.error("Could not load species data for merging.")
        return

    total_added = 0
    total_skipped = 0
    errors = []
    topic_added: dict = {}  # per-topic fact counts for report-page merge deltas

    for topic, result in extraction_results.items():
        if result.get('extraction_status') != 'success':
            continue
        extracted_data = result.get('extracted_data', {})
        if not extracted_data:
            continue

        topic_rejected = rejected_facts.get(topic, set())
        topic_type = 'custom' if topic in custom_topics else 'standard'
        metadata = {
            'research_topic': topic,
            'topic_type': topic_type,
            'source_title': source_title,
            'extraction_timestamp': result.get('extraction_timestamp'),
        }

        try:
            added, skipped = merge_extracted_data_dict(
                extracted_data=extracted_data,
                metadata=metadata,
                categorized_data=categorized_data,
                rejected_fields=topic_rejected
            )
            total_added += added
            total_skipped += skipped
            if added:
                topic_added[topic] = topic_added.get(topic, 0) + added
        except Exception as e:
            errors.append(f"{topic}: {e}")

    if errors:
        for err in errors:
            st.error(f"Merge error — {err}")
        return

    save_categorized_data_by_id(universal_id, categorized_data)

    # Accumulate per-topic deltas so the Report page can show ▴ +N badges
    # and the KB-updated banner.
    if topic_added:
        deltas = research_state.setdefault(
            'report_merge_deltas', {'total': 0, 'by_topic': {}, 'sources': []}
        )
        for t, n in topic_added.items():
            deltas['by_topic'][t] = deltas['by_topic'].get(t, 0) + n
        deltas['total'] = deltas.get('total', 0) + total_added
        if source_title and source_title not in deltas['sources']:
            deltas['sources'].append(source_title)

    source['merged'] = True
    source['merged_fact_count'] = total_added
    source['approved'] = True

    source_id = source.get('id', 'unknown')
    expander_key = f"card_open_{source_id}"
    st.session_state[expander_key] = False

    msg = f"Merged {total_added} fact{'s' if total_added != 1 else ''} into dashboard"
    if total_skipped:
        msg += f" ({total_skipped} already present)"
    st.success(msg)
    st.toast(f"{msg} — you can keep going.")
    st.rerun(scope="app")


# ============================================================================
# TOPIC SUGGESTIONS
# ============================================================================

def _on_topic_suggestion_change(topic_key: str, source_key: str, checkbox_key: str):
    research_state = st.session_state.research_state
    source = research_state.get('all_sources', {}).get(source_key)
    if source is None:
        return

    is_checked = st.session_state.get(checkbox_key, False)
    current_topics = source.get('topics', [])

    if is_checked and topic_key not in current_topics:
        source['topics'].append(topic_key)

        topic_sources = research_state.setdefault('topic_sources', {})
        if topic_key not in topic_sources:
            topic_sources[topic_key] = {
                'dcp_sources': [],
                'research_source_urls': [],
                'dcp_count': 0,
                'research_count': 0,
                'total_count': 0
            }
        topic_data = topic_sources[topic_key]
        if source_key not in topic_data['research_source_urls']:
            topic_data['research_source_urls'].append(source_key)
            topic_data['research_count'] += 1
            topic_data['total_count'] += 1

    elif not is_checked and topic_key in current_topics:
        source['topics'].remove(topic_key)

        topic_sources = research_state.get('topic_sources', {})
        if topic_key in topic_sources:
            topic_data = topic_sources[topic_key]
            if source_key in topic_data.get('research_source_urls', []):
                topic_data['research_source_urls'].remove(source_key)
                topic_data['research_count'] = max(
                    0, topic_data.get('research_count', 1) - 1)
                topic_data['total_count'] = max(
                    0, topic_data.get('total_count', 1) - 1)


def _render_suggested_topics_section(source: dict, source_key: str, research_state: dict):
    from core.registries.topic_registry import StandardTopicRegistry

    source_id = source.get('id')
    analysis_results = source.get('suggested_topics_analysis')

    if analysis_results is None:
        return

    status = analysis_results.get('status')
    if status == 'failed' or not analysis_results.get('has_structure', False):
        error_msg = analysis_results.get('error_message', 'Analysis failed')
        st.caption(f"Analysis: {error_msg}")
        if st.button("Re-analyze", key=f"reanalyze_{source_id}"):
            source['suggested_topics_analysis'] = None
            source.pop('pre_analysis_topics', None)
            source.pop('context_results', None)
        return

    suggestions = analysis_results.get('suggestions', {})

    pre_analysis_topics = list(source.get(
        'pre_analysis_topics', source.get('topics', [])))
    pre_analysis_set = set(pre_analysis_topics)
    sorted_suggestions = sorted(
        [(k, v) for k, v in suggestions.items() if k not in pre_analysis_set],
        key=lambda x: x[1].get('score', 0),
        reverse=True
    )

    if not pre_analysis_topics and not sorted_suggestions:
        st.caption("No topics found")
        return

    st.caption(
        "Topics to extract — check to include:",
        help=(
            "Confidence is an AI estimate of how likely each topic is covered, "
            "based on the document's table of contents. "
            "Strong match: the section is named after or explicitly covers the topic. "
            "Likely: the section clearly relates to it. "
            "Possible: only a tangential mention is likely. "
            "Always review extracted facts before merging."
        ),
    )

    def _make_callback(tk, sk, ck):
        return lambda: _on_topic_suggestion_change(tk, sk, ck)

    def _render_locked_checkbox(topic_key):
        """Pre-configured research topic — always included, not togglable here."""
        topic_def = StandardTopicRegistry.get_topic(topic_key)
        display_name = topic_def.display_name if topic_def else topic_key.replace(
            '_', ' ').title()
        st.checkbox(
            display_name,
            value=True,
            disabled=True,
            key=f"locked_{source_id}_{topic_key}",
            help="Selected as a research topic in Step 1",
        )

    def _render_checkbox(topic_key, data):
        score = data.get('score', 0)
        reasoning = data.get('reasoning', '')
        topic_def = StandardTopicRegistry.get_topic(topic_key)
        display_name = topic_def.display_name if topic_def else topic_key.replace(
            '_', ' ').title()

        if score >= 0.9:
            confidence = "Strong match"
        elif score >= 0.7:
            confidence = "Likely"
        else:
            confidence = "Possible"

        checkbox_key = f"suggest_{source_id}_{topic_key}"
        tooltip = f"{confidence}. {reasoning}" if reasoning else confidence

        if checkbox_key not in st.session_state:
            auto_check = (score >= 0.9)
            st.session_state[checkbox_key] = auto_check
            if auto_check and topic_key not in source.get('topics', []):
                _on_topic_suggestion_change(
                    topic_key, source_key, checkbox_key)

        st.checkbox(
            f"{display_name} — *{confidence}*",
            key=checkbox_key,
            help=tooltip,
            on_change=_make_callback(topic_key, source_key, checkbox_key)
        )

    # Locked base topics first, then AI suggestions — one unified 2-col grid.
    all_items = [(tk, None) for tk in pre_analysis_topics] + sorted_suggestions
    mid = (len(all_items) + 1) // 2
    col_a, col_b = st.columns(2)
    with col_a:
        for topic_key, data in all_items[:mid]:
            if data is None:
                _render_locked_checkbox(topic_key)
            else:
                _render_checkbox(topic_key, data)
    with col_b:
        for topic_key, data in all_items[mid:]:
            if data is None:
                _render_locked_checkbox(topic_key)
            else:
                _render_checkbox(topic_key, data)
