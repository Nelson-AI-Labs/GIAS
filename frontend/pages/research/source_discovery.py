# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Source Discovery — two-pane workbench for the Deep Research screen.

Left pane: compact filterable source list (topic + source-type pills, click-to-open).
Right pane: active study's full analyze → extract → merge panel (render_study_panel).

No page-switch to extract.py. All source selection and extraction happen on one page.
Background PDF prefetch and API pagination are bounded as before.
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from frontend.pages.research.source_extraction import study_state, render_study_panel, _render_pdf_preview, _auto_pdf_filename

logger = logging.getLogger(__name__)

# Executor for find-more background prefetch and bounded PDF prefetch.
_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# How many PDF fetches to submit per render pass.
_MAX_PREFETCH_PER_RENDER = 3

# Fixed height (px) for the left source-list scroller. The right pane flows
# naturally (so the PDF iframe paints), so this applies to the left list only.
PANE_H = 720

_API_LABELS = {
    'semantic_scholar': 'Semantic Scholar',
    'europe_pmc': 'Europe PMC',
    'openalex': 'OpenAlex',
    'doaj': 'DOAJ',
    'tavily': 'Web Search',
    'google_scholar': 'Google Scholar',
}


# ============================================================================
# MANUAL PDF UPLOAD (standalone section at list bottom)
# ============================================================================

def show_manual_pdf_upload():
    """Inline upload section at the bottom of the left list."""
    research_state = st.session_state.research_state

    st.markdown("Upload PDFs from trusted sources. Topics are detected automatically after upload.")

    uploaded_files = st.file_uploader(
        "Upload PDF files",
        type=['pdf'],
        accept_multiple_files=True,
        key="manual_pdf_upload",
        help="Upload one or more PDF files from trusted sources"
    )

    if uploaded_files:
        if st.button("Add Papers", type="primary", key="add_manual_pdfs"):
            for uploaded_file in uploaded_files:
                source_id = f"manual_{uuid.uuid4().hex[:8]}"

                if source_id not in research_state['all_sources']:
                    research_state['all_sources'][source_id] = {
                        'id': source_id,
                        'url': f"manual_upload://{uploaded_file.name}",
                        'title': uploaded_file.name,
                        'domain': 'Manual Upload',
                        'score': 1.0,
                        'topics': [],
                        'search_terms_used': ['Manual Upload'],
                        'approved': True,
                        'is_dcp_source': False,
                        'uploaded_pdf': uploaded_file.read(),
                        'pdf_filename': uploaded_file.name,
                        'is_manual_upload': True
                    }

            st.success(f"Added {len(uploaded_files)} paper(s). Click a source on the left to open it and detect topics.")
            st.rerun()


# ============================================================================
# PDF PREFETCH — bounded, list-level
# ============================================================================

def _maybe_prefetch_pdfs(visible_items: list) -> None:
    """
    Submit background PDF fetches for visible rows that don't yet have a PDF.
    Capped at _MAX_PREFETCH_PER_RENDER submissions per render to prevent
    executor saturation.
    """
    submitted = 0
    for _, source in visible_items:
        if submitted >= _MAX_PREFETCH_PER_RENDER:
            break
        if (
            source.get('uploaded_pdf')
            or source.get('_pdf_fetch_status')
            or source.get('is_dcp_source')
            or source.get('is_manual_upload')
            or (not source.get('pdf_url') and not source.get('url'))
        ):
            continue

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
        submitted += 1


# ============================================================================
# ROW HELPERS
# ============================================================================

def _relevance_badge(source: dict) -> str:
    score = source.get('score', 0.0)
    if score >= 0.7:
        return ":green-badge[● strong match]"
    if score > 0:
        return ":orange-badge[● possible]"
    return ""


def _source_status_badge(source: dict) -> str:
    """
    Compact status badge for the left-list row — reflects extraction progress.
    Matches the extraction workflow: idle → fetching → analyzed → ready → merged.
    """
    if source.get('merged'):
        return ':green-badge[:material/check: merged]'
    if source.get('_analysis_status') == 'running' or source.get('_extraction_status') == 'running':
        return ':blue-badge[:material/progress_activity: working…]'
    if source.get('extraction_results'):
        return ':orange-badge[● ready to merge]'
    if source.get('suggested_topics_analysis') is not None:
        return ':orange-badge[● analyzed]'
    if source.get('uploaded_pdf'):
        return ':blue-badge[▶ PDF ready]'
    status = source.get('_pdf_fetch_status')
    if status == 'running':
        return ':blue-badge[:material/progress_activity: fetching PDF…]'
    if status in ('blocked', 'error'):
        return ':red-badge[:material/warning: auto-fetch failed — upload PDF]'
    return ':gray-badge[▶ not started]'


# ============================================================================
# COMPACT SOURCE ROW — click-to-open, left pane
# ============================================================================

def _render_compact_source_row(source_key: str, source: dict) -> None:
    """
    Compact click-to-open row for the left discovery list.
    Title + status badge + relevance. 'Open' button sets active_study and reruns.
    Active row uses primary button type for visual distinction.
    """
    source_id = source.get('id', source_key)
    is_active = (st.session_state.get("active_study") == source_key)

    title = source.get('title', 'Untitled source')
    short_title = (title[:68] + '…') if len(title) > 68 else title

    status_badge = _source_status_badge(source)
    relevance = _relevance_badge(source)
    badge_line = status_badge + (f"  {relevance}" if relevance else "")
    if source.get('is_manual_upload'):
        badge_line += "  :violet-badge[manual]"

    chip_key = f"src_chip_active_{source_id}" if is_active else f"src_chip_{source_id}"
    with st.container(border=True, key=chip_key):
        st.markdown(f"**{short_title}**")
        st.markdown(badge_line)
        btn_label = "● Open" if is_active else "Open"
        btn_type = "primary" if is_active else "secondary"
        if st.button(btn_label, key=f"open_src_{source_id}", type=btn_type, width="stretch"):
            st.session_state["active_study"] = source_key
            st.rerun()


# ============================================================================
# ACTIVE STUDY PANE — right panel
# ============================================================================

def _render_active_study_pane(research_state: dict) -> None:
    """
    Right pane of the two-pane workbench.
    Renders the active study's full analyze → extract → merge panel.

    Auto-advances to the next un-merged study after a merge completes.
    Empty state is shown when no source is active yet.
    """
    all_sources = research_state.get('all_sources', {})
    non_dcp_keys = {k for k, v in all_sources.items() if not v.get('is_dcp_source')}

    active_key = st.session_state.get("active_study")
    if active_key not in non_dcp_keys:
        active_key = None

    if active_key is None:
        st.info(
            "Select a source from the list to open it here and start analyzing.",
            icon=":material/arrow_back:",
        )
        return

    active_source = all_sources[active_key]

    title = active_source.get('title', 'Untitled')

    # Merged — show a confirmation screen instead of the full study panel.
    # Never auto-advance: the user chose to open this source; respect that.
    if active_source.get('merged'):
        fact_count = active_source.get('merged_fact_count')
        if fact_count is not None:
            merged_msg = f"**{fact_count} fact{'s' if fact_count != 1 else ''}** merged into the dashboard."
        else:
            merged_msg = "Facts merged into the dashboard."
        st.markdown(f"### {title}")
        st.success(merged_msg, icon=":material/check_circle:")
        st.caption("Select another source from the list to continue.")
        return

    # Study header — title + meta line
    year = active_source.get('publication_year')
    citations = active_source.get('citation_count')
    score = active_source.get('score', 0.0)

    meta_parts = [str(year)] if year else []
    if citations and citations > 0:
        meta_parts.append(f"{citations:,} citations")
    if active_source.get('extraction_results'):
        meta_parts.append(":material/check: extracted")
    elif active_source.get('suggested_topics_analysis') is not None:
        meta_parts.append(":material/check: analyzed")
    if score >= 0.7:
        meta_parts.append(":green-badge[● strong match]")
    elif score > 0:
        meta_parts.append(":orange-badge[● possible]")

    st.markdown(f"### {title}")
    if meta_parts:
        st.caption('  ·  '.join(meta_parts))

    # Analyze → extract → merge controls (fragment-driven, polls in background).
    render_study_panel(active_key, active_source)

    # Source PDF — rendered HERE at the pane's top level, outside render_study_panel's
    # @st.fragment and outside any fixed-height container, so the data-URI iframe paints
    # (same context the report page renders in). Inside the fragment/scroller it stays blank.
    # Collapsed by default: frees ~600px above the fold. Expander is not a scroll container
    # so the iframe still paints when opened (verified manually).
    if active_source.get('uploaded_pdf') and not active_source.get('is_dcp_source'):
        _pdf_expanded = st.session_state.get(f"pdf_open_{active_source.get('id')}", False)
        with st.expander("View source PDF", expanded=_pdf_expanded, icon=":material/picture_as_pdf:"):
            _render_pdf_preview(active_source)


# ============================================================================
# TWO-PANE SOURCES WORKBENCH
# ============================================================================

def show_sources_grid() -> None:
    """
    Two-pane workbench: compact left source list + active-study right panel.
    Replaces the old tab-split + batch-bar + switch_page approach.
    """
    research_state = st.session_state.research_state

    # Drain any sources staged by background workers before iterating.
    # Threads write into _pending_sources; we move them here on the main thread
    # to avoid RuntimeError: dictionary changed size during iteration.
    pending = research_state.pop('_pending_sources', [])
    for src in pending:
        url = src.get('url', '')
        if url and url not in research_state['all_sources']:
            research_state['all_sources'][url] = src

    all_sources = research_state['all_sources']
    research_sources = {k: v for k, v in all_sources.items() if not v.get('is_dcp_source')}

    # Always render the two-pane layout — the Add PDF popover must be reachable
    # even before the user has run research (no sources yet).
    col_list, col_active = st.columns([1, 2.2], gap="medium")
    with col_list:
        with st.container(key="src_list_pane"):
            _render_left_list(research_sources, research_state)
    with col_active:
        with st.container(key="active_study_pane"):
            _render_active_study_pane(research_state)


# ============================================================================
# LEFT LIST — filterable, paginated, click-to-open
# ============================================================================

# Keys for the three filter facets.
_FILTER_PILL_KEYS = ("src_filter_topics", "src_filter_types", "src_filter_status")

# Status-filter predicates — ordered to match the workflow stages.
# Displayed only when at least one source satisfies the predicate.
_STATUS_OPTIONS_ORDERED = ["Has PDF", "Analyzed", "Ready to merge", "Merged"]
_STATUS_PREDICATES = {
    "Has PDF":        lambda v: bool(v.get('uploaded_pdf')),
    "Analyzed":       lambda v: v.get('suggested_topics_analysis') is not None,
    "Ready to merge": lambda v: bool(v.get('extraction_results')) and not v.get('merged'),
    "Merged":         lambda v: bool(v.get('merged')),
}


def _save_filter_pills() -> None:
    """Persist all three facet selections to stable keys independent of widget
    re-registration. Called on_change so the saved value is always the user's
    last explicit choice and isn't reset by Streamlit's proto.default=[].
    """
    for k in _FILTER_PILL_KEYS:
        st.session_state[f"_saved_{k}"] = list(st.session_state.get(k) or [])


def _pills_facet(label: str, options: list, key: str) -> list:
    """Render one labelled st.pills facet with stale-state sanitization.

    Sanitizes st.session_state[key] against current options BEFORE the widget
    renders — stale values (e.g. "Manual" after the last manual source is deleted)
    crash st.pills in Streamlit 1.50 with a white screen.
    Restores the last saved selection as the widget default.
    """
    saved = [v for v in (st.session_state.get(f"_saved_{key}") or []) if v in options]
    cur = st.session_state.get(key)
    if cur:
        valid = [v for v in cur if v in options]
        if len(valid) != len(list(cur)):
            st.session_state[key] = valid
    st.caption(f"**{label}**")
    return st.pills(
        label,
        options,
        selection_mode="multi",
        key=key,
        default=saved,
        label_visibility="collapsed",
        on_change=_save_filter_pills,
    ) or []


def _render_left_list(research_sources: dict, research_state: dict) -> None:
    """
    Compact filterable left-pane source list.
    Three-facet filter popover: Topics / Source type / Status.
    Rows are click-to-open; no checkboxes or batch bar.
    """
    # Add PDF popover is always rendered — even when there are no sources yet —
    # so users can upload before running research.
    with st.popover(":material/add: Add PDF", use_container_width=True):
        show_manual_pdf_upload()

    if not research_sources:
        st.info(
            "No sources yet. Upload a PDF above, or select topics and "
            "click **Run Research** to find sources.",
            icon=":material/info:",
        )
        return

    # ── Build facet options ────────────────────────────────────────────────────
    # Topics facet — topics assigned to any source (via analysis)
    all_topic_keys = sorted({
        t for source in research_sources.values()
        for t in source.get('topics', [])
    })
    topic_labels = [t.replace('_', ' ').title() for t in all_topic_keys]
    label_to_topic_key = dict(zip(topic_labels, all_topic_keys))

    # Source-type facet — only show types that are actually present
    type_labels = []
    has_academic = any(
        not v.get('is_manual_upload')
        and v.get('content_category') != 'web_search'
        and v.get('source_api') != 'tavily'
        for v in research_sources.values()
    )
    has_web = any(
        v.get('content_category') == 'web_search' or v.get('source_api') == 'tavily'
        for v in research_sources.values()
    )
    has_manual = any(v.get('is_manual_upload') for v in research_sources.values())
    if has_academic:
        type_labels.append("Academic")
    if has_web:
        type_labels.append("Web")
    if has_manual:
        type_labels.append("Manual")

    # Status facet — only show statuses that at least one source satisfies
    status_labels = [
        s for s in _STATUS_OPTIONS_ORDERED
        if any(_STATUS_PREDICATES[s](v) for v in research_sources.values())
    ]

    # ── Filter popover — three clearly labelled sections ──────────────────────
    active_n = sum(len(st.session_state.get(k) or []) for k in _FILTER_PILL_KEYS)
    filter_label = f":material/filter_alt: Filter ({active_n})" if active_n else ":material/filter_alt: Filter"
    with st.popover(filter_label, use_container_width=True):
        selected_topic_labels = _pills_facet("Topics", topic_labels, "src_filter_topics")
        st.divider()
        selected_types = _pills_facet("Source type", type_labels, "src_filter_types")
        st.divider()
        selected_status = _pills_facet("Status", status_labels, "src_filter_status")

    selected_topics = [label_to_topic_key[l] for l in selected_topic_labels if l in label_to_topic_key]

    # ── Apply filters (OR within facet, AND across facets) ────────────────────
    filtered = dict(research_sources)
    if selected_topics:
        filtered = {
            k: v for k, v in filtered.items()
            if any(t in v.get('topics', []) for t in selected_topics)
        }
    if selected_types:
        def _matches_type(v: dict) -> bool:
            is_manual = bool(v.get('is_manual_upload'))
            is_web = v.get('content_category') == 'web_search' or v.get('source_api') == 'tavily'
            is_academic = not is_manual and not is_web
            for t in selected_types:
                if t == "Academic" and is_academic:
                    return True
                if t == "Web" and is_web:
                    return True
                if t == "Manual" and is_manual:
                    return True
            return False
        filtered = {k: v for k, v in filtered.items() if _matches_type(v)}
    if selected_status:
        filtered = {
            k: v for k, v in filtered.items()
            if any(_STATUS_PREDICATES[s](v) for s in selected_status)
        }

    _PAGE_SIZE = 10
    filter_key = ','.join(sorted(selected_topics + selected_types + selected_status))
    count_key = f"page_display_left__{filter_key}"
    displayed_count = st.session_state.get(count_key, _PAGE_SIZE)

    source_items = list(filtered.items())
    visible_items = source_items[:displayed_count]
    remaining = len(source_items) - displayed_count

    # Submit bounded PDF prefetch for visible rows
    _maybe_prefetch_pdfs(visible_items)

    # Only the source rows scroll — pills + count caption above and the Show-more
    # button below stay pinned outside the scroller.
    with st.container(height=PANE_H, border=False, key="src_scroll"):
        for source_key, source in visible_items:
            _render_compact_source_row(source_key, source)

    _render_load_more(remaining, displayed_count, count_key, filter_key, research_state)


# ============================================================================
# LOAD MORE — merged reveal + API fetch
# ============================================================================

def _render_load_more(
    remaining: int,
    displayed_count: int,
    count_key: str,
    filter_key: str,
    research_state: dict,
) -> None:
    """
    'Show more sources' button pinned below the list (outside the scroller).
    While the local buffer has hidden rows: reveals the next page locally and
    silently triggers an API top-up in the background.
    Once the buffer is exhausted: foreground API fetch with a spinner.
    """
    _PAGE_SIZE = 10
    if remaining > 0:
        if st.button(
            "Find more sources on the previously selected topics",
            key=f"load_more__{filter_key}",
            type="secondary",
            width="stretch",
        ):
            st.session_state[count_key] = displayed_count + _PAGE_SIZE
            _species = (
                st.session_state.get('standardized_species_name')
                or st.session_state.get('selected_species', '')
            )
            _filters = st.session_state.get('search_filters', {}).copy()
            _EXECUTOR.submit(_bg_prefetch_sources, "Academic Papers", research_state, _species, _filters)
            st.rerun()
    else:
        # Local buffer exhausted — offer synchronous API fetch (academic only)
        if st.button(
            "Find more sources on the previously selected topics",
            key=f"find_more_api__{filter_key}",
            type="secondary",
            width="stretch",
        ):
            with st.spinner("Searching for more sources…"):
                added = _fetch_more_sources_for_segment("Academic Papers")
            if added > 0:
                st.session_state[count_key] = displayed_count + added
                st.rerun()
            else:
                st.warning("No new sources found. All available sources for these topics may have been loaded.")


# ============================================================================
# FIND MORE SOURCES (API pagination — background prefetch)
# ============================================================================

def _bg_prefetch_sources(
    segment: str,
    research_state: dict,
    species_name: str,
    search_filters: dict,
) -> None:
    """Background worker: fetch next batch from APIs into _pending_sources. No st.* calls."""
    category = 'academic' if segment == 'Academic Papers' else 'web_search'
    _fetch_more_sources_for_segment_silent(segment, category, research_state, species_name, search_filters)


def _fetch_more_sources_for_segment_silent(
    segment: str,
    category: str,
    research_state: dict,
    species_name: str,
    search_filters: dict,
    batch_size: int = 8,
    per_api_limit: int = 2,
    on_error=None,
) -> int:
    """
    Fetch next API batch for the segment and stage new sources for the main thread.

    Thread-safe — no st.* calls. Returns count of new sources staged.

    New sources are appended to research_state['_pending_sources'] (a list) rather
    than written directly into all_sources. The main thread drains _pending_sources
    into all_sources at the top of show_sources_grid(), before any iteration, to
    avoid RuntimeError: dictionary changed size during iteration.
    on_error: optional callable(topic, exception) for foreground callers.

    per_api_limit controls how many results each paginating API (SS / EPMC / OpenAlex
    / DOAJ) is asked for per call. GS and Tavily are single-shot and are never
    re-queried here; their credits are preserved after the initial run.
    """
    from functionalities.source_finding.paginated_fetch import fetch_next_batch
    topics = research_state.get('anchor_topics', []) + research_state.get('custom_topics', [])
    added = 0

    known_urls = set(research_state['all_sources'].keys())

    for topic in topics:
        try:
            result = fetch_next_batch(
                topic=topic,
                species_name=species_name,
                search_filters=search_filters,
                existing_sources=research_state['all_sources'],
                research_state=research_state,
                batch_size=batch_size,
                per_api_limit=per_api_limit,
            )
            for source in result.get('new_sources', []):
                if source.get('content_category') != category:
                    continue
                url = source.get('url', '')
                if not url or url in known_urls:
                    continue
                known_urls.add(url)
                staged = {
                    **source,
                    'id': str(uuid.uuid4()),
                    'topics': [topic],
                    'search_terms_used': [source.get('search_term_used', '')],
                    'approved': False,
                    'uploaded_pdf': None,
                    'pdf_filename': None,
                }
                research_state.setdefault('_pending_sources', []).append(staged)
                if topic in research_state.get('topic_sources', {}):
                    ts = research_state['topic_sources'][topic]
                    ts.setdefault('research_source_urls', []).append(url)
                    ts['research_count'] = ts.get('research_count', 0) + 1
                    ts['total_count'] = ts.get('dcp_count', 0) + ts['research_count']
                added += 1
        except Exception as e:
            if on_error:
                on_error(topic, e)
            else:
                logger.warning("Background prefetch failed for topic '%s': %s", topic, e)

    return added


def _fetch_more_sources_for_segment(segment: str) -> int:
    """Resolve session state and delegate to the thread-safe silent version."""
    research_state = st.session_state.research_state
    species_name = (
        st.session_state.get('standardized_species_name')
        or st.session_state.get('selected_species', '')
    )
    search_filters = st.session_state.get('search_filters', {}).copy()
    category = 'academic' if segment == 'Academic Papers' else 'web_search'
    return _fetch_more_sources_for_segment_silent(
        segment, category, research_state, species_name, search_filters,
        batch_size=8,
        per_api_limit=2,
        on_error=lambda topic, e: st.warning(
            f"Could not fetch more sources for topic '{topic}': {e}"
        ),
    )
