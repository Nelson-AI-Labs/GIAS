# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Search Filters Component
Compact filter bar rendered between topic selection and the Run Research button.
Two-card layout: Academic Sources (year range) | Constraints (citations, open-access).
"""

import streamlit as st

_CURRENT_YEAR = 2026
_DEFAULT_YEAR_MIN = 2000
_DEFAULT_YEAR_MAX = _CURRENT_YEAR

_DEFAULTS = {
    "year_range": (_DEFAULT_YEAR_MIN, _DEFAULT_YEAR_MAX),
    "min_citations": 0,
    "open_access_only": False,
}


def show_search_filters() -> None:
    """
    Render search filter controls in a single bordered card and persist values
    in session state under 'search_filters'.

    Year slider sits full-width; min-citations and open-access are in a sub-row.
    All widget keys and wiring are unchanged from before (layout-only redesign).
    """
    if "search_filters" not in st.session_state:
        st.session_state["search_filters"] = _DEFAULTS.copy()

    filters = st.session_state["search_filters"]

    st.markdown("#### 2 · Filters")
    with st.container(border=True, key="filter_card"):
        year_range = st.slider(
            "Publication year",
            min_value=1990,
            max_value=_CURRENT_YEAR,
            value=filters.get("year_range", (_DEFAULT_YEAR_MIN, _DEFAULT_YEAR_MAX)),
            key="sf_year_range",
        )
        filters["year_range"] = year_range
        filters["year_min"] = year_range[0]
        filters["year_max"] = year_range[1]

        col_cit, col_oa = st.columns([1, 1])
        with col_cit:
            min_cit = st.number_input(
                "Min citations",
                min_value=0,
                max_value=500,
                value=filters.get("min_citations", 0),
                step=5,
                key="sf_min_citations",
                help="Only show papers with at least this many citations. Papers with no citation data always pass through.",
            )
            filters["min_citations"] = int(min_cit)

        with col_oa:
            open_access = st.toggle(
                "Open access only",
                value=filters.get("open_access_only", False),
                key="sf_open_access",
                help="Only return papers with a freely available PDF (Semantic Scholar) or marked Open Access (Europe PMC).",
            )
            filters["open_access_only"] = open_access

        # Emergency reset — hidden in expander so it's out of the way
        research_state = st.session_state.get('research_state', {})
        researched_topics = research_state.get('researched_topics', [])
        if researched_topics:
            with st.expander("Source-finding ran into errors? Reset here", icon=":material/warning:"):
                st.caption(
                    "Only use this if source-finding hit errors (e.g. ran out of API credits). "
                    "Re-searches your already-searched topics from scratch and adds any new results."
                )
                if st.button("Reset & retry search", key="reset_retry_btn", type="secondary", icon=":material/restart_alt:"):
                    from frontend.pages.research.extraction_process import run_research_round
                    for t in researched_topics:
                        research_state.get('pagination', {}).pop(t, None)
                    with st.spinner("Retrying search (cache bypassed)…"):
                        run_research_round(
                            list(researched_topics),
                            search_filters=filters.copy(),
                            enable_caching=False,
                        )
                    st.rerun()


def get_search_filters() -> dict:
    """Return current filter values, falling back to defaults if not set."""
    return st.session_state.get("search_filters", _DEFAULTS.copy())
