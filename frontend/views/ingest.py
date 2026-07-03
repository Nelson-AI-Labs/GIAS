# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
GIAS — Search / Live Ingestion  (Screen 1)
===========================================
Species search input + pipeline run.
Extracted from the original frontend/pages/home.py fetch handler.

On a successful fetch, navigates to the Knowledge base (dashboard) page
via st.switch_page. On failure, stays here with the error shown.

v2: the 6 databases are queried IN PARALLEL (ParallelAPIComponent). The run drives
three live callbacks — all fired on the main thread, so they repaint Streamlit
widgets during the blocking run:
  • resolution_callback → left stage panel (resolved name, synonym variants)
  • progress_callback    → left stage panel ("Query databases", synonym X of N)
  • db_progress_callback → right panel, one bar per database, advancing gradually
                           by one step per synonym variant.
"""

import streamlit as st
from frontend.utils.icons import glyph_svg


# ── Mark current view (spine state) ──────────────────────────────────────────
st.session_state["_gias_view"] = "ingest"

# ── Design tokens (subset from the v2 redesign tokens.css) ────────────────────
_CYAN = "#46B6CB"      # running / in-progress
_CYAN_600 = "#2E9DB5"
_KELP = "#2E9E8B"      # done / found
_CORAL = "#D9544A"     # failed
_SLATE_2 = "#93A7B1"   # queued / no data
_INK = "#102A38"
_SLATE = "#6A828F"

# Database display order (matches the redesign reference)
_DB_ORDER = ["GBIF", "IUCN", "EASIN", "CABI", "WRiMS", "AquaNIS"]

# Stage-panel presentation — inline SVG glyphs; currentColor inherits from parent span
_STAGE_ICON = {
    "done":    glyph_svg("check",  size=15),
    "running": glyph_svg("dot",    size=15),
    "queued":  glyph_svg("circle", size=15),
}
_STAGE_COLOR = {"done": _KELP, "running": _CYAN, "queued": _SLATE_2}

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown("## Search")
st.markdown(
    "Enter a species name and GIAS will attempt to match it to an accepted Latin binomial. "
    "For the most reliable results, use the Latin name directly. "
    "If you enter a common or vernacular name, verify that the resolved name matches the species you intended "
    "before relying on the results. GIAS then searches all six biodiversity databases across every known synonym variant."
)
st.markdown("---")

# ── Search input ──────────────────────────────────────────────────────────────
# Restyle the input to match the v2 redesign: centered, mono placeholder,
# cyan focus accent, applied via inline CSS.
st.markdown(
    f"""<style>
    div[data-testid='stTextInput'] input {{
        text-align: center;
        font-family: 'Hanken Grotesk', sans-serif;
        color: {_INK};
    }}
    div[data-testid='stTextInput'] input::placeholder {{
        font-family: 'Hanken Grotesk', sans-serif;
        color: {_SLATE_2};
    }}
    div[data-testid='stTextInput'] input:focus {{
        border-color: {_CYAN} !important;
        box-shadow: 0 0 0 2px {_CYAN}33 !important;
    }}
    </style>""",
    unsafe_allow_html=True,
)

default_value = st.session_state.get("current_input_value", "")
user_input = st.text_input(
    "Species name",
    value=default_value,
    placeholder="e.g. red swamp crayfish, Procambarus clarkii, écrevisse rouge…",
    label_visibility="collapsed",
    key="species_input",
)

is_fetching = st.session_state.get("fetching", False)
fetch_button = st.button(
    "Fetching…" if is_fetching else "Fetch Species Data",
    disabled=is_fetching or not user_input.strip(),
    type="primary" if user_input.strip() and not is_fetching else "secondary",
    width="stretch",
    icon=":material/hourglass_empty:" if is_fetching else ":material/search:",
)

if fetch_button and user_input.strip() and not is_fetching:
    st.session_state.fetching = True
    st.session_state.pending_species_input = user_input.strip()
    st.rerun()


def _render_stages(placeholder, stages):
    """Render the persistent pipeline stage list into a single placeholder."""
    rows = []
    for s in stages:
        color = _STAGE_COLOR[s["state"]]
        icon = _STAGE_ICON[s["state"]]
        label_color = _INK if s["state"] != "queued" else _SLATE_2
        weight = "600" if s["state"] != "queued" else "400"
        detail = (
            f"<div style='font-size:1.1rem;color:{_SLATE};margin-top:2px'>{s['detail']}</div>"
            if s.get("detail") else ""
        )
        rows.append(
            "<div style='display:flex;gap:10px;margin:12px 0'>"
            f"<span style='color:{color};font-size:1.05em;line-height:1.4'>{icon}</span>"
            f"<div><span style='font-weight:{weight};color:{label_color}'>{s['label']}</span>"
            f"{detail}</div></div>"
        )
    placeholder.markdown("".join(rows), unsafe_allow_html=True)


def _render_db_row(container, db_name: str):
    """Create one database-source row; return (progress_handle, status_placeholder)."""
    c = container.container(border=True)
    cols = c.columns([1.4, 2, 1.4], vertical_alignment="center")
    cols[0].markdown(f"`{db_name}`")
    bar = cols[1].progress(0.0)
    status_ph = cols[2].empty()
    status_ph.markdown(
        f"<span style='color:{_SLATE_2};font-size:1.1rem'>· queued</span>",
        unsafe_allow_html=True,
    )
    return bar, status_ph


# ── Fetch handler ─────────────────────────────────────────────────────────────
if st.session_state.get("fetching") and st.session_state.get("pending_species_input"):
    species_to_fetch = st.session_state.pending_species_input

    from functionalities.data_aggregation.pipeline import (
        run_species_database_pipeline_with_synonyms,
    )
    from core.cache_layer.cache_cleanup import clear_session_cache
    from core.utils.session_context import get_session_id

    # Resolution header (query → resolved Latin name) — filled on resolution_callback
    resolve_header = st.empty()

    # ── Live-ingestion layout: Pipeline (left) + Database sources (right) ──────
    col_pipe, col_src = st.columns([1.15, 0.85])

    with col_pipe:
        st.markdown("**Pipeline**")
        stage_panel = st.container(border=True).empty()

    with col_src:
        st.markdown("**Database sources**")
        db_bars = {}
        db_status_ph = {}
        for _db in _DB_ORDER:
            db_bars[_db], db_status_ph[_db] = _render_db_row(col_src, _db)

    # ── Mutable run state (closed over by the callbacks) ──────────────────────
    stages = [
        {"key": "resolve",    "label": "Resolve species name", "state": "running", "detail": ""},
        {"key": "synonyms",   "label": "Expand synonyms",      "state": "queued",  "detail": ""},
        {"key": "query",      "label": "Query databases",      "state": "queued",  "detail": ""},
        {"key": "categorize", "label": "Categorize fields",    "state": "queued",  "detail": ""},
    ]
    run_state = {
        "total_synonyms": 0,            # set on resolution
        "current_synonym": 0,          # index, set on each synonym
        "current_synonym_name": "",    # name, set on each synonym
        "db_queried": {db: 0 for db in _DB_ORDER},      # increments per synonym
        "db_found": {db: False for db in _DB_ORDER},    # ever returned data
        "db_found_count": {db: 0 for db in _DB_ORDER},  # variants with data
        "db_last": {db: "" for db in _DB_ORDER},
    }

    def _stage(key):
        return next(s for s in stages if s["key"] == key)

    _render_stages(stage_panel, stages)

    try:
        # Clear cache only when switching to a different species — preserve
        # extracted data if the user re-fetches the same species.
        last_species = st.session_state.get("selected_species", "")
        session_id   = get_session_id()
        if species_to_fetch.lower().strip() != last_species.lower().strip():
            clear_session_cache()
        # else: same species re-fetch — skip cache clear

        def on_resolution(corrected_name, synonym_list):
            """Progress callback: species name resolved to its accepted name and synonym set."""
            run_state["total_synonyms"] = len(synonym_list)
            _stage("resolve")["state"] = "done"
            _stage("resolve")["detail"] = corrected_name
            _stage("synonyms")["state"] = "done"
            _stage("synonyms")["detail"] = (
                f"{len(synonym_list)} variant(s): " + " · ".join(synonym_list)
            )
            _stage("query")["state"] = "running"
            _render_stages(stage_panel, stages)
            resolve_header.markdown(
                f"<div style='text-align:center;margin:4px 0 18px'>"
                f"<span style='font-family:\"Hanken Grotesk\",sans-serif;font-size:1.1rem;"
                f"color:{_SLATE}'>“{species_to_fetch}”</span> "
                f"<span style='color:{_CYAN_600};font-size:18px'>→</span> "
                f"<span style='font-family:\"Hanken Grotesk\",sans-serif;font-style:italic;"
                f"font-size:30px;color:{_INK}'>{corrected_name}</span></div>",
                unsafe_allow_html=True,
            )

        def on_synonym_progress(current: int, total: int, current_name: str) -> None:
            """Progress callback: querying synonym `current` of `total`; refresh the stage panel."""
            run_state["total_synonyms"] = total
            run_state["current_synonym"] = current
            run_state["current_synonym_name"] = current_name
            _stage("query")["state"] = "running"
            _stage("query")["detail"] = f"synonym {current} of {total}: {current_name}"
            _render_stages(stage_panel, stages)
            # Mark every database row as actively querying this synonym, so it's
            # always clear which variant is in flight right now.
            for _db in _DB_ORDER:
                db_status_ph[_db].markdown(
                    f"<span style='color:{_CYAN_600};font-size:1.1rem'>"
                    f"{glyph_svg('hourglass', size=14)} querying <i>{current_name}</i>…</span>",
                    unsafe_allow_html=True,
                )

        def on_db_progress(db_name: str, status: str, done: int, total: int) -> None:
            """Progress callback: one database finished a synonym query; advance its bar and status."""
            total_syn = run_state["total_synonyms"] or 1
            run_state["db_queried"][db_name] = min(
                run_state["db_queried"][db_name] + 1, total_syn
            )
            run_state["db_last"][db_name] = status
            if status == "found":
                run_state["db_found"][db_name] = True
                run_state["db_found_count"][db_name] += 1

            bar = db_bars.get(db_name)
            ph = db_status_ph.get(db_name)
            if bar is None or ph is None:
                return  # unknown DB — ignore defensively

            queried = run_state["db_queried"][db_name]
            bar.progress(min(queried / total_syn, 1.0))
            syn_name = run_state["current_synonym_name"]
            is_final = queried >= total_syn  # this DB has now seen every synonym

            if is_final:
                # Settle to the cumulative outcome across all variants.
                if run_state["db_found"][db_name]:
                    ph.markdown(
                        f"<span style='color:{_KELP};font-size:1.1rem'>"
                        f"{glyph_svg('check', size=14)} found "
                        f"({run_state['db_found_count'][db_name]}/{total_syn})</span>",
                        unsafe_allow_html=True,
                    )
                elif run_state["db_last"][db_name] == "fail":
                    ph.markdown(
                        f"<span style='color:{_CORAL};font-size:1.1rem'>"
                        f"{glyph_svg('close', size=14)} failed</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    ph.markdown(
                        f"<span style='color:{_SLATE_2};font-size:1.1rem'>— no data</span>",
                        unsafe_allow_html=True,
                    )
            else:
                # Momentary result for the variant just queried.
                if status == "found":
                    ph.markdown(
                        f"<span style='color:{_KELP};font-size:1.1rem'>"
                        f"{glyph_svg('check', size=14)} found in "
                        f"<i>{syn_name}</i></span>",
                        unsafe_allow_html=True,
                    )
                elif status == "fail":
                    ph.markdown(
                        f"<span style='color:{_CORAL};font-size:1.1rem'>"
                        f"{glyph_svg('close', size=14)} failed on "
                        f"<i>{syn_name}</i></span>",
                        unsafe_allow_html=True,
                    )
                else:
                    ph.markdown(
                        f"<span style='color:{_SLATE_2};font-size:1.1rem'>— none in "
                        f"<i>{syn_name}</i></span>",
                        unsafe_allow_html=True,
                    )

            # Last database of the last synonym → querying done, categorizing starts
            if run_state["current_synonym"] >= total_syn and done >= total:
                _stage("query")["state"] = "done"
                _stage("query")["detail"] = (
                    f"queried {len(_DB_ORDER)} databases across {total_syn} variant(s)"
                )
                _stage("categorize")["state"] = "running"
                _render_stages(stage_panel, stages)

        result = run_species_database_pipeline_with_synonyms(
            species_to_fetch,
            progress_callback=on_synonym_progress,
            db_progress_callback=on_db_progress,
            resolution_callback=on_resolution,
        )

        pipeline_status = result.get("status")

        if pipeline_status == "success":
            _stage("categorize")["state"] = "done"
            _render_stages(stage_panel, stages)

            # Store results in session state (preserve the existing contract)
            st.session_state.categorized_data_ready  = True
            st.session_state.categorized_data_path   = result.get("categorized_path")
            st.session_state.universal_id             = result.get("universal_id")
            st.session_state.gbif_key                 = result.get("gbif_key")
            st.session_state.selected_species         = result.get("corrected_name")
            st.session_state.original_query           = result.get("original_query")
            st.session_state.synonyms_searched        = result.get("all_synonyms_searched", [])
            st.session_state.synonym_sources_failed   = result.get("synonym_sources_failed", [])
            st.session_state.current_input_value      = ""
            # Legacy routing keys (kept for snapshot compatibility)
            st.session_state.show_dashboard           = True
            st.session_state.current_mode             = "database"
            st.session_state.fetching                 = False
            st.session_state.pending_species_input    = None

            # Clear research state for new species
            for key in ("research_state", "source_segment_radio", "last_extraction_results"):
                st.session_state.pop(key, None)

            # Navigate to the Knowledge Base
            st.switch_page("frontend/views/dashboard.py")

        else:
            st.session_state.fetching              = False
            st.session_state.pending_species_input = None
            error_msg = result.get("error_message", "Unknown error")
            st.error(f"Failed to fetch species data: {error_msg}", icon=":material/error:")

    except Exception as exc:
        st.session_state.fetching              = False
        st.session_state.pending_species_input = None
        st.error(f"Error: {exc}", icon=":material/error:")

# ── No data yet — hint ────────────────────────────────────────────────────────
elif not st.session_state.get("selected_species"):
    st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)
    with st.container(border=False):
        st.markdown(
            "<div style='text-align:center;color:#6A828F;font-size:1.1rem'>"
            "Tip: Latin names give the most reliable results. Common names and misspellings are accepted "
            "but always verify that the resolved binomial matches the species you intended."
            "</div>",
            unsafe_allow_html=True,
        )
