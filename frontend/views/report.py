# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
GIAS — Build Report  (Screen 4)
=================================
Phase 5: full redesign to match Screen-4 of the design mock.

Controls (left):
  - Topic checkboxes with per-topic fact counts and deep-research badges
  - Reference style radio (Numbered, APA 7th, Harvard, Vancouver superscript)

Preview (right):
  - On-demand "Build preview" → renders once via the real pipeline, stores
    result, embeds PDF via st.pdf; same bytes served for download (no second render).

Session keys:
  report_generating         bool — pipeline is currently running
  dashboard_report_result   dict — last successful result {pdf_bytes, …}
  _gias_view                str  — "report" (drives sidebar spine state)
"""

import urllib.parse

import streamlit as st

from core.cache_layer.categorized_data_helpers import (
    load_categorized_data_by_id,
    count_topic_stats,
)
from frontend.components import step_icon_svg
from frontend.ui_components.field_renderers import humanize_field_name as _ht
from frontend.utils.icons import glyph_svg

# Mark current view for spine state
st.session_state["_gias_view"] = "report"

# ── Guards ─────────────────────────────────────────────────────────────────────

if not st.session_state.get("selected_species"):
    st.info("No species loaded yet. Start by searching for a species.")
    if st.button("Go to Search", type="primary", icon=":material/search:"):
        st.switch_page("frontend/views/ingest.py")
    st.stop()

species = st.session_state.get("selected_species", "")
universal_id = st.session_state.get("universal_id")
loaded_categories = st.session_state.get("loaded_categories", [])
eu_concern = st.session_state.get("_eu_concern", False)

if not loaded_categories:
    st.warning(
        "No topics are loaded yet. Open the **Knowledge base** page, load the "
        "topics you want to include, then return here.",
        icon=":material/info:",
    )
    if st.button("Go to Knowledge base", icon=":material/database:"):
        st.switch_page("frontend/views/dashboard.py")
    st.stop()

# ── Header: disclaimer row ────────────────────────────────────────────────────

# CSS injected before columns to avoid style/render races.
_dash_uri = "data:image/svg+xml," + urllib.parse.quote(
    step_icon_svg("dashboard", stroke="#136BAE", size=20)
)
st.html(
    f"<style>"
    f".st-key-rpt_back_btn button{{"
    f"width:40px;height:40px;padding:0;"
    f"display:inline-flex;align-items:center;justify-content:center;}}"
    f".st-key-rpt_back_btn button::before{{"
    f"content:'';display:block;width:20px;height:20px;"
    f"background:url(\"{_dash_uri}\") no-repeat center/contain;}}"
    f"</style>"
)
col_back, col_text, col_badge = st.columns([0.4, 6, 2], vertical_alignment="center")

with col_back:
    if st.button("", key="rpt_back_btn", help="Back to Knowledge base"):
        st.switch_page("frontend/views/dashboard.py")

with col_text:
    st.html(
        "<p style='margin:0;font-size:16px;color:var(--slate);line-height:1.5'>"
        "To inspect data extracted during Deep Research, open the "
        "<b>Knowledge base</b>."
        "</p>"
    )

with col_badge:
    if eu_concern:
        st.html(
            f"<span class='badge-eu'>{glyph_svg('star', stroke='white', size=13)} EU IAS Union Concern</span>"
        )

# ── KB-updated banner (only when studies were merged this session) ─────────────

research_state = st.session_state.get("research_state") or {}
merge_deltas = research_state.get("report_merge_deltas", {})
delta_total = merge_deltas.get("total", 0)
delta_by_topic = merge_deltas.get("by_topic", {})
delta_sources = merge_deltas.get("sources", [])

if delta_total > 0:
    src_str = " · ".join(delta_sources) if delta_sources else "research"
    per_topic_str = "  ·  ".join(
        f"**{_ht(t)}** +{n}"
        for t, n in delta_by_topic.items()
        if n > 0
    )
    with st.container(key="rpt_kb_banner"):
        st.success(
            f"Knowledge base updated — **{delta_total} fact{'s' if delta_total != 1 else ''}** "
            f"merged from {src_str}."
            + (f"  \n{per_topic_str}" if per_topic_str else ""),
            icon=":material/merge:",
        )

st.divider()

# ── Page info ────────────────────────────────────────────────────────────────

with st.expander("What can you do on this page?", expanded=False, icon=":material/info:"):
    st.markdown(
        "**Build Report** assembles a citable PDF from the facts already in your knowledge base.\n\n"
        "**How it works:**\n"
        "1. Tick the topics you want to include in the report.\n"
        "2. Choose a citation style for the references.\n"
        "3. Click **Build preview** — GIAS renders the PDF and shows it inline.\n"
        "4. Download it directly, or change selections and click **Rebuild**.\n\n"
        ":material/arrow_back: To inspect the underlying facts, return to the **dashboard** — "
        "this page is only for assembling the final report."
    )

# ── Load categorized data once for topic counts ───────────────────────────────

_cat_data_all = {}
try:
    _raw = load_categorized_data_by_id(universal_id)
    _cat_data_all = (_raw or {}).get("categorized_fields", {}) or {}
    if not _cat_data_all and _raw:
        # Some versions store directly at top level
        _cat_data_all = {k: v for k, v in (_raw or {}).items()
                         if isinstance(v, dict) and k not in ("sources", "universal_id")}
except Exception:
    pass


def _topic_counts(cat: str) -> tuple[int, int, int]:
    """Return (n_facts, n_sources, n_research) for a category.

    n_research counts entries with is_research_data=True (deep-research facts,
    persistent on disk — not session-scoped like report_merge_deltas).
    """
    data = _cat_data_all.get(cat, {})
    pts, srcs = count_topic_stats(data)
    n_research = sum(
        1
        for vals in data.values() if isinstance(vals, list)
        for e in vals if isinstance(e, dict) and e.get("is_research_data")
    )
    return pts, srcs, n_research


# ── Two-column body: controls (left) + preview (right) ───────────────────────

col_ctrl, col_prev = st.columns([2, 3], gap="medium")

# ─────────────────────── LEFT — controls ────────────────────────────────────

with col_ctrl:

    # ── 1 · Topics in report ─────────────────────────────────────────────────
    with st.container(border=True, key="report_topics"):
        n_total = len(loaded_categories)
        st.markdown("#### 1 · Topics in report")

        selected_topics: list[str] = []
        for cat in loaded_categories:
            if cat in ("taxonomic_identity", "data_metadata"):
                continue  # always included; not shown as a user choice
            pts, srcs, n_research = _topic_counts(cat)
            delta_n = delta_by_topic.get(cat, 0)
            label = _ht(cat)
            badge = f"  ▴ +{delta_n}" if delta_n else ""
            checked = st.checkbox(
                f"**{label}**{badge}",
                value=st.session_state.get(f"rpt_topic_{cat}", True),
                key=f"rpt_topic_{cat}",
            )
            if pts:
                count_str = f"{pts} facts · {srcs} src"
                if n_research:
                    count_str += f" · :green[{n_research} deep research]"
            else:
                count_str = "*no data yet*"
            st.caption(count_str)
            if checked:
                selected_topics.append(cat)

        if not selected_topics:
            st.caption(
                ":orange[No topics selected — report will contain only taxonomy.]")

    # ── 2 · Reference style ───────────────────────────────────────────────────
    with st.container(border=True, key="report_reference"):
        st.markdown("#### 2 · Reference style")
        ref_style = st.radio(
            "Reference style",
            options=["numbered", "apa", "harvard", "vancouver_superscript"],
            format_func=lambda x: {
                "numbered":             "Numbered [1][2]  —  inline brackets",
                "apa":                  "APA 7th (Author, Year)  —  author-date with comma",
                "harvard":              "Harvard (Author Year)  —  author-date, no comma",
                "vancouver_superscript": "Vancouver superscript¹  —  raised number",
            }[x],
            key="rpt_ref_style",
            label_visibility="collapsed",
        )

# ─────────────────────── RIGHT — preview ────────────────────────────────────

with col_prev:
    with st.container(border=True, key="report_preview"):
        st.markdown("#### Preview & generate")

        from frontend.pages.species_dashboard_v2 import generate_report_content

        is_generating = st.session_state.get("report_generating", False)
        report_result = st.session_state.get("dashboard_report_result")

        # ── Generating branch ─────────────────────────────────────────────────
        if is_generating:
            st.button(
                "Building report…", type="primary", width="stretch",
                disabled=True, key="rpt_building_btn",
            )
            categories_for_report = selected_topics or []

            n_topics = len(categories_for_report)
            with st.status(
                f"Generating report — {n_topics} topic(s)", expanded=True
            ) as _status:
                _progress = st.progress(0.0)
                _stage = st.empty()

                def _on_progress(fraction: float, message: str) -> None:
                    _progress.progress(min(fraction, 1.0))
                    _stage.markdown(f"*{message}*")

                try:
                    result = generate_report_content(
                        species_name=species,
                        universal_id=universal_id,
                        loaded_categories=categories_for_report,
                        reference_style=st.session_state.get(
                            "rpt_ref_style", "numbered"),
                        progress_callback=_on_progress,
                    )
                except Exception as exc:
                    result = {"success": False, "error": str(exc)}

                if result["success"]:
                    _progress.progress(1.0)
                    _stage.markdown("*Report complete.*")
                    _status.update(label="Report ready",
                                   state="complete", expanded=False)
                else:
                    _status.update(
                        label="Report generation failed", state="error")

            st.session_state.report_generating = False
            if result["success"]:
                st.session_state.dashboard_report_result = result
                # Record the inputs that produced this build so staleness can be detected.
                st.session_state.dashboard_report_signature = (
                    tuple(categories_for_report),
                    st.session_state.get("rpt_ref_style", "numbered"),
                )
                st.rerun()
            else:
                st.error(f"Report generation failed: {result.get('error')}")

        # ── Result ready branch ───────────────────────────────────────────────
        elif report_result:
            # Detect staleness: compare current selections against the signature
            # captured at build time.  Streamlit reruns on every widget change so
            # this comparison is always fresh.
            _current_sig = (
                tuple(selected_topics),
                st.session_state.get("rpt_ref_style", "numbered"),
            )
            is_stale = _current_sig != st.session_state.get(
                "dashboard_report_signature")

            # Status line
            cats_in = report_result.get("categories_included", [])
            style_label = {
                "numbered": "numbered citations",
                "apa": "APA 7th",
                "harvard": "Harvard",
                "vancouver_superscript": "Vancouver superscript",
            }.get(st.session_state.get("rpt_ref_style", "numbered"), "numbered citations")
            st.caption(
                f"**Report ready** · {len(cats_in)} topic(s) · {style_label}"
            )

            # Inline PDF preview (st.pdf uses pdf.js / canvas — not blocked by browser)
            st.pdf(report_result["pdf_bytes"], height=560)

            if is_stale:
                st.warning(
                    "Selections changed since this report was built — rebuild to apply.",
                    icon=":material/sync_problem:",
                )

            # Download + rebuild row — rebuild is primary when stale
            dl_col, rb_col = st.columns([3, 1])
            with dl_col:
                st.download_button(
                    label="Download PDF",
                    data=report_result["pdf_bytes"],
                    file_name=report_result["report_filename"],
                    mime="application/pdf",
                    type="secondary" if is_stale else "primary",
                    disabled=is_stale,
                    width="stretch",
                    key="rpt_download_btn",
                    icon=":material/download:",
                )
            with rb_col:
                if st.button(
                    "Rebuild",
                    key="rpt_rebuild_btn",
                    icon=":material/refresh:",
                    type="primary" if is_stale else "secondary",
                    width="stretch",
                ):
                    del st.session_state["dashboard_report_result"]
                    st.session_state.pop("dashboard_report_signature", None)
                    st.session_state.report_generating = True
                    st.rerun()

        # ── Idle branch ───────────────────────────────────────────────────────
        else:
            # Low-content warning
            try:
                from core.utils.cache_manager import get_extracted_data_dir
                import json as _json
                _meta_path = (
                    get_extracted_data_dir() / universal_id / "sources_metadata.json"
                )
                _has_research = _meta_path.exists() and bool(
                    _json.loads(_meta_path.read_text())
                )
            except Exception:
                _has_research = False

            if len(loaded_categories) < 3 and not _has_research:
                st.warning(
                    "**Limited content:** fewer than 3 topics are loaded and no research "
                    "papers have been extracted. The report will have very little content.",
                    icon=":material/warning:",
                )

            if st.button(
                "Build preview",
                type="primary",
                width="stretch",
                icon=":material/preview:",
                key="rpt_build_btn",
            ):
                st.session_state.report_generating = True
                st.rerun()
