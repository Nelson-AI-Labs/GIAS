# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Species Dashboard V2
====================

A simplified, dynamic dashboard that uses the field_renderers module to display
categorized species data. This version auto-discovers all categories in the JSON
and renders them using a clean card-based layout.

Usage:
    from frontend.pages.species_dashboard_v2 import create_species_dashboard_v2
    create_species_dashboard_v2("Procambarus clarkii", "2227300_procambarus_clarkii")
"""

import streamlit as st
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

# Import our field renderers (single source of truth for all field rendering)
from frontend.ui_components.field_renderers import humanize_field_name

# Import dashboard tools for images and taxonomic data
from core.dashboard.dashboard_tools import get_species_image_url, get_taxonomic_data
from core.cache_layer.categorized_data_helpers import load_categorized_data_by_id, get_available_categories, count_topic_stats
from functionalities.data_aggregation.api.cabi_sparql import fetch_cabi_compendium_datasheet_urls

# Import language utilities for flag emojis
from frontend.utils.language_utils import get_language_flag, normalize_language_name

# Import conflict detection utilities
from frontend.utils.conflict_detection import merge_related_fields, collect_rank_values_from_sources, collect_name_variants
from frontend.utils.icons import glyph_svg

# Import centralized topic registry (single source of truth)
from core.registries.topic_registry import StandardTopicRegistry

# Import overview panel
from core.dashboard.overview_metrics import compute_overview_metrics
from frontend.ui_components.search_overview import render_search_overview

# Import topic card (summary card + inspect modal — facts stay off the main flow)
from frontend.components import topic_card

# Category display order - generated from registry (single source of truth)
# System categories (data_metadata, needs_review) are appended at the end
CATEGORY_ORDER = StandardTopicRegistry.get_all_topic_keys() + ["data_metadata", "needs_review"]

# Category descriptions - loaded from centralized registry
CATEGORY_DESCRIPTIONS = StandardTopicRegistry.get_full_schema()


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_cabi_compendium_urls(scientific_name: str) -> tuple[tuple[str, ...], Optional[str]]:
    """Fetch CABI Compendium datasheet URLs; returns (urls, error_message)."""
    trimmed = (scientific_name or "").strip()
    if not trimmed:
        return ((), None)
    try:
        urls = fetch_cabi_compendium_datasheet_urls(trimmed)
        return (tuple(urls), None)
    except Exception as e:
        return ((), str(e))


def get_project_root() -> Path:
    """Get the project root directory."""
    current_file = Path(__file__).resolve()
    # Go up from frontend/pages/ to project root
    return current_file.parent.parent.parent


def load_categorized_data(universal_id: str) -> Optional[Dict[str, Any]]:
    """
    Load categorized data from folder structure for a given universal ID.

    Uses session-aware cache directory for multi-user isolation.

    Args:
        universal_id: Universal ID for the species (e.g., "2227300_procambarus_clarkii")

    Returns:
        Dictionary containing categorized_fields, or None if folder not found

    Raises:
        json.JSONDecodeError: If JSON files are malformed
    """
    try:
        # Load from session-aware folder structure (no explicit cache_dir - uses default)
        data = load_categorized_data_by_id(universal_id)

        if data is None:
            st.error(f"Categorized data not found for: {universal_id}")
            return None

        return data.get("categorized_fields", {})

    except json.JSONDecodeError as e:
        st.error(f"Error parsing JSON data: {e}")
        return None
    except Exception as e:
        st.error(f"Error loading categorized data: {e}")
        return None


def sort_categories(categories: List[str]) -> List[str]:
    """
    Sort categories in a sensible display order.

    Args:
        categories: List of category names

    Returns:
        Sorted list with important categories first, unknown last
    """
    def get_sort_key(category: str) -> tuple:
        """Rank a category by its index in CATEGORY_ORDER; unknown categories sort last."""
        # If in CATEGORY_ORDER, use its index; otherwise use 999
        try:
            order_index = CATEGORY_ORDER.index(category)
        except ValueError:
            order_index = 999

        # Unknown/uncategorized should always be last
        if "unknown" in category.lower() or "uncategorized" in category.lower():
            order_index = 1000

        return (order_index, category)

    return sorted(categories, key=get_sort_key)




def _render_common_names_panel(tax_data: dict, tax_identity_raw: dict) -> None:
    """
    Render the common-names panel: all vernacular names grouped by language, always visible.
    Shared between the taxonomy column and any future callers.
    """
    UNCLASSIFIED = "Unclassified language"

    raw_buckets = tax_data.get('vernacular_names', {}).copy()

    # EASIN common_names carry no language code → unclassified bucket
    for entry in tax_identity_raw.get('common_names', []):
        value = entry.get('value')
        if isinstance(value, list):
            for name_dict in value:
                if isinstance(name_dict, dict) and 'Name' in name_dict:
                    raw_buckets.setdefault('', []).append(name_dict['Name'])

    # Collapse equivalent language keys, dedup names case-insensitively
    display_buckets: dict = {}
    seen: dict = {}
    for language, names in raw_buckets.items():
        canonical = normalize_language_name(language) or UNCLASSIFIED
        bucket = display_buckets.setdefault(canonical, [])
        bucket_seen = seen.setdefault(canonical, set())
        for name in names:
            if name and name.strip().lower() not in bucket_seen:
                bucket_seen.add(name.strip().lower())
                bucket.append(name)

    if not any(display_buckets.values()):
        st.markdown(
            "<div style='border:1px solid rgba(0,107,166,0.25);border-radius:6px;"
            "padding:10px 12px;background:rgba(242,247,248,0.6);'>"
            "<div style='font-size:var(--fs-body);color:#6A828F;font-weight:600;"
            "margin-bottom:8px;padding-bottom:6px;"
            "border-bottom:1px solid rgba(0,107,166,0.15);'>COMMON NAMES</div>"
            "<span style='color:#9aacb5;font-size:var(--fs-body);'>No common names found</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    # Collect all rows into one HTML block inside a scrollable container so the
    # panel never pushes the rest of the page down as names accumulate.
    rows_html = ""
    for language in sorted(display_buckets, key=lambda l: (l == UNCLASSIFIED, l)):
        names = display_buckets[language]
        if not names:
            continue
        flag = "🌐" if language == UNCLASSIFIED else get_language_flag(language)
        names_str = " · ".join(names)
        rows_html += (
            f"<div style='margin-bottom:5px;'>{flag} "
            f"<span style='font-weight:600;font-size:var(--fs-body);'>{language}</span> "
            f"<span style='color:#4A5568;font-size:var(--fs-body);'>{names_str}</span></div>"
        )

    header_html = (
        "<div style='position:sticky;top:0;z-index:1;"
        "background:rgba(242,247,248,0.97);"
        "font-size:var(--fs-body);color:#6A828F;font-weight:600;"
        "padding-bottom:6px;margin-bottom:6px;"
        "border-bottom:1px solid rgba(0,107,166,0.15);'>"
        "COMMON NAMES</div>"
    )
    scroll_hint_html = (
        "<div style='font-size:0.78rem;color:#b0c4ce;text-align:center;"
        "padding:2px 0 10px;letter-spacing:0.04em;'>"
        "↕ scroll to explore</div>"
    )
    # max-height matches _MAX_H in render_taxonomic_identity_with_conflicts
    st.markdown(
        f"<div style='max-height:400px;overflow-y:auto;"
        f"border:1px solid rgba(0,107,166,0.25);border-radius:6px;"
        f"padding:10px 12px;background:rgba(242,247,248,0.6);"
        f"scrollbar-width:thin;scrollbar-color:rgba(0,107,166,0.35) rgba(0,0,0,0.04);"
        f"box-shadow:inset 0 -10px 8px -8px rgba(0,107,166,0.12);'>"
        f"{header_html}{scroll_hint_html}{rows_html}</div>",
        unsafe_allow_html=True,
    )


def render_taxonomic_identity_with_conflicts(species_name: str, universal_id: str) -> None:
    """
    Render taxonomic identity card with conflict highlighting, nomenclature block,
    always-visible common names panel, and full-width distribution map below.

    Layout: [ image | classification + nomenclature | common names ]
            [ ─── Distribution & Status (full width) ─── ]

    Args:
        species_name: Display name of the species
        universal_id: Universal ID for loading data
    """
    tax_data = get_taxonomic_data(species_name, universal_id)

    # Load raw categorized data (used for conflict detection and name variants)
    categorized_fields = load_categorized_data(universal_id)
    tax_identity_raw = categorized_fields.get('taxonomic_identity', {}) if categorized_fields else {}

    st.subheader("Taxonomic Identity")

    # Three columns: image | classification (wider) | common names
    col_image, col_classification, col_names = st.columns([2, 3, 2])

    # Shared max-height applied consistently across image, classification, and common names
    _MAX_H = "400px"
    _SCROLL_STYLE = (
        f"max-height:{_MAX_H};overflow-y:auto;"
        "border:1px solid rgba(0,107,166,0.25);border-radius:6px;"
        "padding:10px 12px;background:rgba(242,247,248,0.6);"
        "scrollbar-width:thin;scrollbar-color:rgba(0,107,166,0.35) rgba(0,0,0,0.04);"
        "box-shadow:inset 0 -10px 8px -8px rgba(0,107,166,0.12);"
    )

    # ── Left: species photo ───────────────────────────────────────────────────
    with col_image:
        image_url = get_species_image_url(species_name, universal_id)
        if image_url:
            st.markdown(
                f'<div style="max-height:{_MAX_H};overflow:hidden;border-radius:8px;">'
                f'<img src="{image_url}" style="width:100%;height:auto;display:block;" />'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="max-height:{_MAX_H};display:flex;align-items:center;justify-content:center;'
                f'border-radius:12px;'
                f'background:linear-gradient(135deg,rgba(200,200,200,0.1),rgba(150,150,150,0.05));'
                f'border:2px dashed rgba(150,150,150,0.3);text-align:center;color:#888;padding:40px 20px;">'
                f'<div><h3>No Image Available</h3><p>{glyph_svg("image", stroke="#888", size=32)}</p></div></div>',
                unsafe_allow_html=True,
            )

    # ── Middle: name variants + classification ranks in one container ─────────
    with col_classification:
        # Build name variants + classification into a single scrollable block
        accepted_binomial, name_result = collect_name_variants(
            tax_identity_raw,
            accepted_name=st.session_state.get("selected_species", species_name),
        )

        variant_list = [
            v for v in name_result.get('conflict_list', [])
            if isinstance(v.get('value'), str)
            and v['value'].strip().lower() != (accepted_binomial or "").strip().lower()
        ]

        _scroll_hint = (
            "<div style='font-size:0.78rem;color:#b0c4ce;text-align:center;"
            "padding:2px 0 10px;letter-spacing:0.04em;'>"
            "↕ scroll to explore</div>"
        )
        combined_html = _scroll_hint

        # Name variants section (omit if none)
        if variant_list:
            combined_html += (
                f"<div style='font-size:var(--fs-body);color:#6A828F;font-weight:600;margin-bottom:6px;'>"
                f"NAME VARIANTS &nbsp;·&nbsp; {len(variant_list)}</div>"
            )
            for entry in variant_list:
                name_val = entry['value']
                sources = entry['sources']
                source_badges = "".join(
                    f'<span style="background:rgba(0,107,166,0.1);color:#006BA6;'
                    f'border-radius:3px;padding:2px 6px;font-size:var(--fs-body);margin-left:4px;">{s}</span>'
                    for s in sources
                )
                combined_html += (
                    f'<div style="padding:4px 8px 4px 12px;margin:2px 0;'
                    f'border-left:2px solid rgba(0,107,166,0.25);font-size:var(--fs-body);">'
                    f'<span style="font-style:italic;color:#2C3E50;">{name_val}</span>'
                    f'{source_badges}</div>'
                )
            combined_html += "<div style='margin:10px 0;border-top:1px solid rgba(44,62,80,0.12);'></div>"

        # Classification section header
        combined_html += (
            "<div style='font-size:var(--fs-body);color:#6A828F;font-weight:600;margin-bottom:6px;'>"
            "CLASSIFICATION</div>"
        )

        # ── Classification ranks appended into the same combined_html block ─────
        ranks = ['genus', 'family', 'order', 'class', 'phylum', 'kingdom']

        for rank in ranks:
            rank_result = collect_rank_values_from_sources(tax_identity_raw, rank)

            if rank_result['has_conflict']:
                combined_html += (
                    f'<div style="margin-bottom:4px;">'
                    f'<span style="color:#2C3E50;font-weight:bold;font-size:var(--fs-body);">{rank.capitalize()}:</span> '
                    f'<span style="color:#f39c12;">{glyph_svg("warning", stroke="#f39c12", size=14)} Conflicting values</span></div>'
                )
                for idx, conflict_entry in enumerate(rank_result['conflict_list']):
                    value = conflict_entry['value']
                    sources = conflict_entry['sources']
                    bg_color = "rgba(255,193,7,0.1)" if idx % 2 == 0 else "rgba(255,152,0,0.1)"
                    combined_html += (
                        f'<div style="padding:6px 10px;margin:2px 0 6px 0;border-radius:4px;'
                        f'background:{bg_color};border-left:3px solid rgba(243,156,18,0.5);'
                        f'font-size:var(--fs-body);">'
                        f'<span style="font-style:italic;color:#2C3E50;font-weight:500;">{value}</span>'
                        f'<span style="color:#7f8c8d;font-size:var(--fs-body);"> • {", ".join(sources)}</span>'
                        f'</div>'
                    )
            else:
                value = rank_result['primary_value'] or 'Unknown'
                combined_html += (
                    f'<div style="margin-bottom:6px;">'
                    f'<span style="color:#2C3E50;font-weight:bold;font-size:var(--fs-body);">{rank.capitalize()}:</span> '
                    f'<span style="color:#2C3E50;font-style:italic;font-size:var(--fs-body);"> {value}</span>'
                    f'</div>'
                )

        # Authority / authorship appended inside the same container
        authority_result = merge_related_fields(tax_identity_raw, ['authority', 'authorship'])
        if authority_result['primary_value']:
            combined_html += (
                '<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(44,62,80,0.12);">'
            )
            if authority_result['has_conflict']:
                combined_html += (
                    '<span style="color:#2C3E50;font-weight:bold;font-size:var(--fs-body);">Authority:</span> '
                    f'<span style="color:#f39c12;">{glyph_svg("warning", stroke="#f39c12", size=14)} Conflicting values</span>'
                )
                for idx, conflict_entry in enumerate(authority_result['conflict_list']):
                    value = conflict_entry['value']
                    sources = conflict_entry['sources']
                    bg_color = "rgba(255,193,7,0.1)" if idx % 2 == 0 else "rgba(255,152,0,0.1)"
                    combined_html += (
                        f'<div style="padding:4px 8px;margin:4px 0 2px 0;border-radius:4px;'
                        f'background:{bg_color};border-left:3px solid rgba(243,156,18,0.5);'
                        f'font-size:var(--fs-body);">'
                        f'<span style="color:#2C3E50;font-weight:500;">{value}</span>'
                        f'<span style="color:#7f8c8d;font-size:var(--fs-body);"> • {", ".join(sources)}</span>'
                        f'</div>'
                    )
            else:
                combined_html += (
                    f'<span style="color:#2C3E50;font-weight:bold;font-size:var(--fs-body);">Authority:</span> '
                    f'<span style="color:#2C3E50;font-size:var(--fs-body);"> {authority_result["primary_value"]}</span>'
                )
            combined_html += '</div>'

        st.markdown(
            f"<div style='{_SCROLL_STYLE}'>{combined_html}</div>",
            unsafe_allow_html=True,
        )

    # ── Right: common names (always visible, no expander) ─────────────────────
    with col_names:
        _render_common_names_panel(tax_data, tax_identity_raw)

    # ── Distribution & Status — full width below the taxonomy row ─────────────
    st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
    st.subheader("Distribution & Status")
    from frontend.ui_components.distribution_map import render_distribution_map
    render_distribution_map(categorized_fields, universal_id)




def generate_report_content(
    species_name: str,
    universal_id: str,
    loaded_categories: List[str],
    reference_style: str = "numbered",
    include: Optional[Dict[str, Any]] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """Run the report-generation pipeline for a species and return its result dict.

    Ensures taxonomic_identity is always included so the AI receives taxonomic context,
    even though it is rendered separately in the UI rather than as a topic pill.
    """
    from functionalities.report_generation.pipeline import run_report_generation_pipeline

    # taxonomic_identity is stripped from UI pills (rendered separately as a card)
    # but must always enter the pipeline so the AI receives taxonomic data.
    if 'taxonomic_identity' not in loaded_categories:
        loaded_categories = ['taxonomic_identity'] + loaded_categories

    return run_report_generation_pipeline(
        species_name=species_name,
        universal_id=universal_id,
        selected_categories=loaded_categories,
        reference_style=reference_style,
        include=include,
        progress_callback=progress_callback,
    )


def create_species_dashboard_v2(species_name: str, universal_id: str) -> None:
    """
    Create the main species dashboard v2.

    This is the main entry point that loads categorized data and creates
    a dynamic grid layout with category cards.

    Args:
        species_name: Display name of the species (e.g., "Procambarus clarkii")
        universal_id: Universal ID for loading data (e.g., "2227300_procambarus_clarkii")
    """
    # Reset dashboard state when viewing a new species
    if 'current_dashboard_species' not in st.session_state or st.session_state.current_dashboard_species != universal_id:
        st.session_state.current_dashboard_species = universal_id
        st.session_state.selected_categories = []
        st.session_state.show_category_cards = False
        st.session_state.loaded_categories = []
        if 'dashboard_report_result' in st.session_state:
            del st.session_state.dashboard_report_result

    # Load categorized data
    with st.spinner("Loading categorized data..."):
        categorized_fields = load_categorized_data(universal_id)

    if categorized_fields is None:
        st.error("Could not load categorized data for this species.", icon=":material/error:")
        st.info("Make sure the categorization process has been run for this species.", icon=":material/lightbulb:")
        return

    # Get all categories and sort them
    categories = list(categorized_fields.keys())
    if not categories:
        st.warning("No categories found in categorized data.", icon=":material/warning:")
        return

    sorted_categories = sort_categories(categories)

    # Always show all standard registry topics (minus taxonomic_identity, rendered separately).
    # System categories (data_metadata, needs_review) are excluded — not useful in the grid.
    _registry_cats = [k for k in StandardTopicRegistry.get_all_topic_keys() if k != 'taxonomic_identity']
    # Preserve registry order; append any data categories not in the registry (edge cases)
    _extra_cats = [c for c in sorted_categories if c not in _registry_cats and c not in ('taxonomic_identity', 'data_metadata', 'needs_review')]
    other_categories = _registry_cats + _extra_cats

    # Add custom topics from research mode if they exist
    custom_topics = []
    custom_category_names = []
    if hasattr(st.session_state, 'research_state') and 'custom_topics' in st.session_state.research_state:
        custom_topics = st.session_state.research_state['custom_topics']
        # Convert custom topics to underscore format for consistency
        custom_category_names = [topic.lower().replace(' ', '_').replace('&', '').replace('__', '_') for topic in custom_topics]
        other_categories.extend(custom_category_names)

    # ALWAYS SHOW: Taxonomic Identity + Distribution map (full-width below)
    render_taxonomic_identity_with_conflicts(species_name, universal_id)

    # Warn when a taxonomic source failed during synonym lookup — the synonym list
    # (and therefore the data below) may be missing name variants. Distinguishes a
    # genuine "no synonyms" species from a transient database outage.
    synonym_sources_failed = st.session_state.get("synonym_sources_failed", [])
    if synonym_sources_failed:
        failed_sources = ", ".join(s.split(":")[0] for s in synonym_sources_failed)
        st.warning(
            f"Synonym lookup was incomplete — {failed_sources} could not be reached. "
            f"Results may be missing name variants. Re-run the search to retry.",
            icon=":material/warning:",
        )

    st.markdown("---")

    # Auto-load all topics. Keep loaded_categories in session state so Phase 4
    # merge tracking and the Report page can read the current topic set.
    st.session_state.loaded_categories = other_categories

    # Topic cards — all topics shown immediately; facts are off the main flow.
    # Click ↗ inspect on any card to open the facts in a centred modal.
    if other_categories:
        st.subheader("Topic Details")
        with st.expander("What is this page?", expanded=False, icon=":material/info:"):
            st.markdown(
                "This is your **knowledge base** — everything GIAS has collected about this species, "
                "organised by topic.\n\n"
                "**Where the data comes from:**\n"
                "- Six biodiversity databases searched automatically during ingest.\n"
                "- Additional sources found and extracted during **Deep Research**.\n"
                "- Facts you approved and merged from scientific papers.\n\n"
                "**How the Report page uses this:**\n"
                "The Report page reads these categorised topics directly. "
                "The AI structures, deduplicates, and cites the data into a clean dossier — "
                "the richer this knowledge base, the more comprehensive the report.\n\n"
                ":material/visibility: This page is read-only — it shows what's in the tool. "
                "Use **Deep Research** to add more facts, or inspect any card to see the raw sources."
            )
        if custom_topics:
            st.caption(f"Including {len(custom_topics)} custom research topic(s)")

        with st.container(key="topic_grid"):
            _grid_cols = st.columns(2, gap="medium")
            for _idx, _cat in enumerate(other_categories):
                _cat_data = categorized_fields.get(_cat, {})
                _pts, _n_srcs = count_topic_stats(_cat_data)
                with _grid_cols[_idx % 2]:
                    topic_card(
                        name=humanize_field_name(_cat),
                        points=_pts,
                        n_sources=_n_srcs,
                        topic_data=_cat_data,
                    )

    # ── Sources panel — below Topic Details ───────────────────────────────────
    st.markdown("---")
    synonyms_searched = st.session_state.get("synonyms_searched", [])
    _full_data = load_categorized_data_by_id(universal_id)
    _sources_with_data = _full_data.get("sources", []) if _full_data else []
    overview_metrics = compute_overview_metrics(categorized_fields, synonyms_searched, _sources_with_data)
    from core.dashboard.dashboard_tools import get_all_database_links_with_species
    _database_links = get_all_database_links_with_species(universal_id)
    render_search_overview(overview_metrics, _database_links)

    # ── CABI Compendium — grouped with sources at the bottom ──────────────────
    cabi_urls, cabi_err = _cached_cabi_compendium_urls(species_name)
    st.markdown(
        f"""
        <div style="
            margin-top: 20px;
            padding: 16px 20px;
            border-radius: 10px;
            background: linear-gradient(135deg, rgba(0, 107, 166, 0.06), rgba(74, 144, 164, 0.03));
            border: 1px solid rgba(0, 107, 166, 0.18);
            display: flex;
            align-items: center;
            gap: 14px;
        ">
            <div style="line-height: 1;">{glyph_svg('book', stroke='#136BAE', size=26)}</div>
            <div style="flex: 1;">
                <span style="font-weight: 600; color: #2C3E50; font-size: 1.1rem;">
                    CABI Invasive Species Compendium
                </span>
                <span style="color: #7f8c8d; font-size: 1.1rem; margin-left: 8px;">
                    Peer-reviewed datasheet
                </span>
            </div>
        """,
        unsafe_allow_html=True,
    )
    if cabi_err:
        st.warning("Could not load CABI Compendium link.", icon=":material/warning:")
    elif cabi_urls:
        for url in cabi_urls:
            st.markdown(
                f'<a href="{url}" target="_blank" rel="noopener noreferrer" style="'
                "display: inline-block; margin-top: 4px; padding: 6px 18px;"
                "background: #006BA6; color: white; border-radius: 6px;"
                "font-size: 1.1rem; font-weight: 600; text-decoration: none;"
                '">Open Datasheet ↗</a>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("No CABI Compendium datasheet found for this scientific name.")
    st.markdown("</div>", unsafe_allow_html=True)


# Standalone testing/demo
if __name__ == "__main__":
    st.set_page_config(
        page_title="Species Dashboard V2",
        page_icon="🦞",
        layout="wide"
    )

    # Test with a sample species
    st.sidebar.title("Test Dashboard")
    st.sidebar.markdown("Enter a species to test:")

    test_species = st.sidebar.text_input("Species Name", "Procambarus clarkii")
    test_id = st.sidebar.text_input("Universal ID", "2227300_procambarus_clarkii")

    if st.sidebar.button("Load Dashboard"):
        create_species_dashboard_v2(test_species, test_id)
