# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
GIAS — frontend/components.py
==============================
Reusable render helpers for the v2 workspace shell.
Imports: import frontend.components as ui
         ui.inject_css("assets/shell.css")

Most functions read only from st.session_state. The context bar and journey
spine also call load_categorized_data_by_id (session-cached file read, not a
pipeline call) to derive field/source counts.
"""

import streamlit as st
from pathlib import Path
import base64
from typing import Optional

from frontend.ui_components.field_renderers import render_field
from frontend.utils.icons import glyph_svg, GLYPH_ICONS, _svg_wrap


# ── stylesheet injection ──────────────────────────────────────────────────────

def inject_css(path: str) -> None:
    """Inject the shell stylesheet once per page (in app.py).

    Must use st.markdown, NOT st.html: in Streamlit 1.50 st.html sandboxes its
    <style> so the rules never reach the app DOM (the whole stylesheet stays
    dormant). st.markdown injects CSS globally. Verified: with st.html, zero
    shell.css rules were present in document.styleSheets.
    """
    css = Path(path).read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


# ── canonical step-icon set ───────────────────────────────────────────────────
# Single source of truth — used by sidebar spine AND home page.
# Values are inner SVG path/shape markup (no <svg> wrapper).
# All icons: line-art, 24×24 viewBox, no fill.

STEP_ICONS: dict = {
    "home": (
        "<path d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/>"
        "<polyline points='9 22 9 12 15 12 15 22'/>"
    ),
    # search = Live ingestion — magnifier glyph
    "search": (
        "<circle cx='11' cy='11' r='7'/>"
        "<line x1='21' y1='21' x2='16.65' y2='16.65'/>"
    ),
    # dashboard = Knowledge base — stacked layers
    "dashboard": (
        "<polygon points='12 2 2 7 12 12 22 7 12 2'/>"
        "<polyline points='2 17 12 22 22 17'/>"
        "<polyline points='2 12 12 17 22 12'/>"
    ),
    # research = Deep research — flask
    "research": (
        "<path d='M10 2v8L6.5 17A2.5 2.5 0 0 0 9 20h6a2.5 2.5 0 0 0 2.5-3L14 10V2'/>"
        "<line x1='8.5' y1='2' x2='15.5' y2='2'/>"
        "<line x1='7' y1='13' x2='17' y2='13'/>"
    ),
    # extract = Analyze & extract — document with tick
    "extract": (
        "<path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/>"
        "<polyline points='14 2 14 8 20 8'/>"
        "<polyline points='9 15 11 17 15 13'/>"
    ),
    # report = Build report — page with ruled lines
    "report": (
        "<path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/>"
        "<polyline points='14 2 14 8 20 8'/>"
        "<line x1='8' y1='13' x2='16' y2='13'/>"
        "<line x1='8' y1='17' x2='12' y2='17'/>"
    ),
}


def step_icon_svg(key: str, stroke: str = "#136BAE", size: int = 22) -> str:
    """
    Inline line-art SVG for a workflow step.
    Sidebar state colours: done=#2E9E8B, active=#ffffff, todo=rgba(255,255,255,.35)
    Home page: stroke="#136BAE" (ocean) or "#2E9DB5" (cyan-600)
    """
    inner = STEP_ICONS.get(key, "")
    return _svg_wrap(inner, stroke=stroke, size=size)


# glyph_svg() is imported from frontend.utils.icons and re-exported here
# so callers can do `from frontend.components import glyph_svg`.
# It renders any key from GLYPH_ICONS (warning, check, close, location, etc.)


# ── sidebar rail ──────────────────────────────────────────────────────────────

def rail_sublabel() -> None:
    """'Intelligence Analyst System' sublabel shown below the native st.logo."""
    st.markdown(
        "<div style='font-size:13px;color:rgba(255,255,255,.60);letter-spacing:.06em;"
        "text-transform:uppercase;text-align:center;margin-top:2px;margin-bottom:10px'>"
        "Intelligence Analyst System</div>",
        unsafe_allow_html=True,
    )


# ── journey spine ─────────────────────────────────────────────────────────────

def _get_step_states() -> dict:
    """
    Compute done / active / todo for each journey step.
    Returns: {step_key: "done"|"active"|"todo"}
    """
    view = st.session_state.get("_gias_view", "home")
    has_species = bool(st.session_state.get("selected_species"))

    # Check if any source has been merged into the dashboard.
    # Sources live in research_state['all_sources'] (a dict keyed by source_id);
    # report_merge_deltas['total'] is set when facts are actually added on merge.
    _research_state = st.session_state.get("research_state") or {}
    _all_sources = _research_state.get("all_sources", {})
    has_merged = (
        any(s.get("merged") for s in _all_sources.values())
        or _research_state.get("report_merge_deltas", {}).get("total", 0) > 0
    )

    steps: dict = {}

    # ── Home step ──
    steps["home"] = "active" if view == "home" else "done"

    # ── Search step ──
    if has_species:
        steps["search"] = "done"
    else:
        steps["search"] = "active" if view == "ingest" else "todo"

    # ── Knowledge base step ──
    if has_species and view in ("research", "report"):
        steps["dashboard"] = "done"
    elif has_species:
        steps["dashboard"] = "active"
    else:
        steps["dashboard"] = "todo"

    # ── Deep research step ──
    if view == "research":
        steps["research"] = "active"
    elif has_merged:
        steps["research"] = "done"
    else:
        steps["research"] = "todo"

    # ── Report step ──
    if view == "report":
        steps["report"] = "active"
    elif st.session_state.get("dashboard_report_result"):
        steps["report"] = "done"
    else:
        steps["report"] = "todo"

    return steps


def custom_spine() -> None:
    """
    Renders the journey spine in the sidebar.
    Spine steps: Home → Search → Knowledge base → Deep research → Report.
    Icon stroke colour signals step state: kelp=done, white=active, muted=todo/locked.
    No separate ✓/●/○ glyph — state is embedded in the icon colour.
    Uses st.page_link (without icon=) for navigation; plain text for unreachable steps.
    """
    steps = _get_step_states()
    has_species = bool(st.session_state.get("selected_species"))

    spine_items = [
        ("Home",           "frontend/views/home.py",      "home"),
        ("Search",         "frontend/views/ingest.py",    "search"),
        ("Knowledge base", "frontend/views/dashboard.py", "dashboard"),
        ("Deep research",  "frontend/views/research.py",  "research"),
        ("Report",         "frontend/views/report.py",    "report"),
    ]

    # Faint connector line between steps
    connector_html = (
        "<div style='width:1px;height:14px;background:rgba(255,255,255,.18);"
        "margin:0 auto 2px 8px'></div>"
    )

    for i, (label, path, key) in enumerate(spine_items):
        state = steps.get(key, "todo")
        can_navigate = key in ("home", "search") or has_species

        # Icon stroke colour communicates state (no separate glyph)
        if state == "done":
            stroke = "#DDA033"                # gold — completed
        elif state == "active":
            stroke = "#ffffff"                # white — current page
        else:
            stroke = "rgba(255,255,255,.35)"  # muted — todo / locked

        icon_html = step_icon_svg(key, stroke=stroke, size=22)

        # Row: SVG icon + page link (or muted text) side by side
        c_icon, c_link = st.columns([1, 6], gap="small", vertical_alignment="center")
        with c_icon:
            st.markdown(icon_html, unsafe_allow_html=True)
        with c_link:
            if can_navigate:
                # No icon= on page_link — SVG in the left column is the icon
                st.page_link(path, label=label, width="stretch")
            else:
                st.markdown(
                    f"<div style='color:rgba(255,255,255,.30);font-size:17px;"
                    f"padding:6px 0;'>{label}</div>",
                    unsafe_allow_html=True,
                )

        if i < len(spine_items) - 1:
            st.markdown(connector_html, unsafe_allow_html=True)


# ── credit (bottom of sidebar) ───────────────────────────────────────────────

def rail_credit() -> None:
    """Author credit at the bottom of the ocean rail — centered, larger."""
    li_svg = linkedin_svg("#ffffff", 26)
    li_html = (
        f"<a href='https://linkedin.com/in/samuel-vander-velpen-910b31138' "
        f"target='_blank' style='display:inline-block'>{li_svg}</a>"
    )

    st.markdown(
        f"<div style='font-size:14px;color:rgba(255,255,255,.65);line-height:1.6;"
        f"text-align:center;'>"
        f"Built by <strong style='color:rgba(255,255,255,.90)'>Samuel Vander Velpen</strong>"
        f"<div style='height:10px'></div>"
        f"{li_html}"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    try:
        # White-outline variant — visible on dark ocean rail; centered via spacer columns
        _, eu_col, _ = st.columns([1, 2, 1])
        with eu_col:
            st.image(
                "frontend/images/EN_fundedbyEU_VERTICAL_RGB_WHITE Outline.png",
                width="stretch",
            )
    except Exception:
        pass


# ── species context bar ───────────────────────────────────────────────────────

def _render_species_name(species: str, original: str, synonym_count: int) -> None:
    """Render species name + optional redirect note + name-variant count."""
    # Explicit inline 3rem — the .gias-species var(--fs-hero-xl) does not resolve in this
    # nested-column st.html context, so size it directly (plain rem is sanitizer-proof).
    display = (
        f'<span style="font-family:\'Hanken Grotesk\',sans-serif;font-weight:500;'
        f'font-style:italic;color:#2E9DB5;font-size:3rem;line-height:1.12">{species}</span>'
    )
    if original and original.lower() != species.lower():
        display += (
            f'<p style="font-family:\'Hanken Grotesk\',sans-serif;font-size:1rem;'
            f'color:#6A828F;margin:0.2rem 0 0 0">Your original input: {original}</p>'
        )
    st.html(display)
    if synonym_count > 1:
        st.markdown(
            f"<span style='font-size:1.1rem;color:#6A828F;font-family:\"Hanken Grotesk\",sans-serif'>"
            f"{synonym_count} name variants searched</span>",
            unsafe_allow_html=True,
        )


@st.cache_data(show_spinner=False)
def _fetch_phylopic_silhouette(species_name: str) -> Optional[str]:
    """
    Return the local PNG path for the species' PhyloPic silhouette, or None.
    Disk-cached by the phylopic module; result is also Streamlit-cached per species
    so repeated renders don't hit the filesystem or network again.
    """
    try:
        from functionalities.report_generation.report_renderer.phylopic import fetch_silhouette
        result = fetch_silhouette(species_name)
        return result["path"] if result else None
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _fetch_eu_status_flags(species_name: str, universal_id: Optional[str]) -> dict:
    """
    Return the three EU regulatory flags from management_biosecurity.
    Keys: is_eu_concern, is_ms_concern, is_horizon_scanning (bool or None each).
    Cached per (species, id) so re-renders don't repeat file reads.
    """
    try:
        from core.dashboard.species_data import get_management_data
        mgmt = get_management_data(species_name, universal_id)
        return {
            "is_eu_concern":      mgmt.get("is_eu_concern"),
            "is_ms_concern":      mgmt.get("is_ms_concern"),
            "is_horizon_scanning": mgmt.get("is_horizon_scanning"),
        }
    except Exception:
        return {}


def species_context_bar() -> None:
    """
    Pinned species anchor at the top of the main pane — shown on every
    page once a species has been loaded. Reads from session_state.
    """
    species = st.session_state.get("selected_species", "")
    original = st.session_state.get("original_query", "")
    universal_id = st.session_state.get("universal_id")

    synonym_count = len(st.session_state.get("synonyms_searched", []))

    # Wider left column gives the italic species name room to breathe
    left, right = st.columns([6, 5], vertical_alignment="center")

    with left:
        # PhyloPic silhouette as a small icon beside the species name (fetched once, disk-cached)
        silhouette_path = _fetch_phylopic_silhouette(species) if species else None

        if silhouette_path:
            icon_col, name_col = st.columns([1, 11], vertical_alignment="center")
            with icon_col:
                st.image(silhouette_path, width=48)
            with name_col:
                _render_species_name(species, original, synonym_count)
        else:
            _render_species_name(species, original, synonym_count)

    with right:
        # EU badges and stats sit side-by-side in the right column
        badge_col, stats_col = st.columns([2, 3], vertical_alignment="center")

        with badge_col:
            # EU regulatory status badges
            if species and universal_id:
                flags = _fetch_eu_status_flags(species, universal_id)
                badges_html = ""
                if flags.get("is_eu_concern"):
                    badges_html += (
                        "<span style='background:#c0392b;color:white;padding:4px 10px;"
                        "border-radius:20px;font-size:0.8rem;font-weight:600;"
                        "display:inline-block;margin-bottom:4px;'>🇪🇺 EU IAS Union Concern</span>"
                    )
                if flags.get("is_ms_concern"):
                    badges_html += (
                        "<span style='background:#e67e22;color:white;padding:4px 10px;"
                        "border-radius:20px;font-size:0.8rem;font-weight:600;"
                        "display:inline-block;margin-bottom:4px;'>"
                        f"{glyph_svg('warning', stroke='white', size=13)}"
                        " Member State Concern</span>"
                    )
                if flags.get("is_horizon_scanning"):
                    badges_html += (
                        "<span style='background:#2980b9;color:white;padding:4px 10px;"
                        "border-radius:20px;font-size:0.8rem;font-weight:600;"
                        "display:inline-block;margin-bottom:4px;'>"
                        f"{glyph_svg('telescope', stroke='white', size=13)}"
                        " EU Horizon Scanning</span>"
                    )
                if badges_html:
                    st.markdown(
                        f"<div style='display:flex;flex-direction:column;gap:2px;'>"
                        f"{badges_html}</div>",
                        unsafe_allow_html=True,
                    )

        with stats_col:
            # Boxed metric strip — fields + sources only (conflicts untracked)
            # Derive counts from the cached categorized data (cheap re-read).
            n_fields: int = 0
            n_sources: int = 0
            if universal_id:
                try:
                    from core.cache_layer.categorized_data_helpers import load_categorized_data_by_id
                    from core.dashboard.overview_metrics import compute_overview_metrics
                    _data = load_categorized_data_by_id(universal_id)
                    if _data:
                        _metrics = compute_overview_metrics(
                            categorized_fields=_data.get("categorized_fields", {}),
                            synonyms_searched=st.session_state.get("synonyms_searched", []),
                            sources_with_data=_data.get("sources", []),
                        )
                        n_fields = _metrics.get("total_fields", 0)
                        n_sources = len(_data.get("sources", []))
                except Exception:
                    pass  # fail gracefully — metrics show "—" if data unavailable

            with st.container(key="kbstats"):
                m1, m2 = st.columns(2)
                m1.metric("fields", n_fields or "—")
                m2.metric("sources", n_sources or "—")

    st.divider()


# ── topic card ────────────────────────────────────────────────────────────────

def topic_card(
    name: str,
    points: int,
    n_sources: int,
    topic_data: dict,
    fresh: bool = False,
    new: int = 0,
) -> None:
    """
    A single knowledge-base topic card — summary only (count + source count).
    Click ↗ inspect to open the facts in a centred modal; page does not grow.
    topic_data = {field_name: [SourceEntry, ...]} for the modal.
    """
    slug = name.lower().replace(" ", "_").replace("/", "_")
    key = f"topic_{slug}" + ("_fresh" if fresh else "")

    with st.container(border=True, key=key):
        header_col, badge_col = st.columns([4, 1], vertical_alignment="center")
        with header_col:
            st.markdown(f"**{name}**")
        with badge_col:
            if fresh and new:
                st.markdown(
                    f"<span class='tag-new'>▴ +{new}</span>", unsafe_allow_html=True
                )

        if points:
            st.caption(f"**{points}** data point{'s' if points != 1 else ''} · {n_sources} source{'s' if n_sources != 1 else ''}")
        else:
            st.caption("no data yet — run deep research to fill this topic")

        if st.button("↗ inspect", key=f"insp_{key}", width="stretch"):
            _inspect_topic_dialog(name, topic_data)


@st.dialog("Inspect topic", width="large")
def _inspect_topic_dialog(name: str, topic_data: dict) -> None:
    """
    Modal showing all collected facts for a topic.
    Only this modal body scrolls — the KB page behind it stays put.
    topic_data = {field_name: [SourceEntry, ...]}
    """
    st.subheader(name)
    st.info(
        "Raw collected records — quick overview only. "
        "The **Report** page will structure, deduplicate, and cite this data for you."
    )

    if not topic_data or all(not v for v in topic_data.values()):
        st.caption("No data collected for this topic yet. Run deep research to fill it.")
        return

    for _field, _vals in topic_data.items():
        if _vals:
            render_field(_field, _vals)
            st.divider()


# ── conflict box ──────────────────────────────────────────────────────────────

def conflict_box(field: str, values: list) -> None:
    """
    Render a conflict box showing all reported values side-by-side.
    values: list of (value_str, [source_code_str, ...]) tuples.
    Never auto-resolves — shows ALL values + sources.
    """
    rows = "".join(
        f"<div class='confval'>"
        f"<span class='v'>{v}</span>"
        f"<span class='srcs'>"
        + "".join(f"<span class='src is-{s.lower()}'>{s}</span>" for s in srcs)
        + "</span></div>"
        for v, srcs in values
    )
    st.html(
        f"<div class='confbox'>"
        f"<div class='confbox__hd'>{glyph_svg('warning', size=14)} reported as {len(values)} different values</div>"
        f"{rows}"
        f"<div class='confnote'>"
        f"All values kept — GIAS never overrides source disagreements."
        f"</div></div>"
    )


# ── proposal card (AI-proposed, awaiting approval) ────────────────────────────

def proposal_card(
    field: str, value: str, source: str, quote: str, page_ref: str, key: str
) -> bool:
    """
    AI-proposed fact awaiting user review.
    Returns True when the user clicks 'Add to dashboard'.
    Nothing writes to the KB until this button fires (human-in-the-loop gate).
    """
    with st.container(border=True, key=f"prop_{key}"):
        col_tag, col_pin = st.columns([3, 1], vertical_alignment="center")
        with col_tag:
            st.markdown(
                "<span class='tag-ai'>AI-proposed · awaiting review</span>",
                unsafe_allow_html=True,
            )
        with col_pin:
            if page_ref:
                st.markdown(
                    f"<span style='font-family:\"Hanken Grotesk\",sans-serif;"
                    f"font-size:10px;color:#6A828F'>"
                    f"{glyph_svg('location', size=11)} {page_ref}</span>",
                    unsafe_allow_html=True,
                )

        st.caption(field)
        st.markdown(f"**{value}**")
        st.markdown(f"<span class='src is-paper'>{source}</span>", unsafe_allow_html=True)
        if quote:
            st.markdown(f"> {quote}")

        c_add, c_edit, c_rej = st.columns([2, 1, 1])
        added = c_add.button("Add to dashboard", key=f"add_{key}",
                             type="primary", width="stretch",
                             icon=":material/check:")
        c_edit.button("Edit", key=f"edit_{key}", width="stretch")
        c_rej.button("Reject", key=f"rej_{key}", width="stretch")
        return added


# ── internal helpers ──────────────────────────────────────────────────────────

def _read_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def linkedin_svg(fill: str = "#ffffff", size: int = 24) -> str:
    """
    Inline LinkedIn glyph SVG string.
    fill='#ffffff' for dark (sidebar rail); fill='#136BAE' for light backgrounds.
    Wrap in <a href=…> before injecting via st.markdown/st.html.
    """
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' "
        f"viewBox='0 0 24 24' fill='{fill}' style='vertical-align:middle;display:inline-block'>"
        f"<path d='M20.45 20.45h-3.55v-5.57c0-1.33-.02-3.04-1.85-3.04"
        f"-1.85 0-2.13 1.45-2.13 2.94v5.67H9.36V9h3.41v1.56h.05"
        f"c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.45v6.29z"
        f"M5.34 7.43a2.06 2.06 0 1 1 0-4.12 2.06 2.06 0 0 1 0 4.12z"
        f"M7.12 20.45H3.56V9h3.56v11.45z"
        f"M22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24"
        f"h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z'/>"
        f"</svg>"
    )
