# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Search Overview Panel
=====================

Renders a compact data-coverage summary between the species overview and the
topic selector. Shows per-database synonym links (matching the footer style),
how many name variants were searched, and per-topic field counts as muted chips.
"""

from collections import defaultdict
from html import escape as _he
from typing import Any, Dict, List

import streamlit as st

# Database brand colours
_DB_COLORS = {
    "GBIF": "#4A90A4",
    "WRiMS": "#006BA6",
    "IUCN": "#22c55e",
    "EASIN": "#9333ea",
    "AquaNIS": "#0891b2",
    "CABI": "#5c8a00",
}
_DB_COLOR_DEFAULT = "#6b7280"


def render_search_overview(
    metrics: Dict[str, Any],
    database_links: List[Dict[str, str]],
) -> None:
    """
    Render the compact search-summary panel.

    Args:
        metrics:        Output of core.dashboard.overview_metrics.compute_overview_metrics()
        database_links: Output of core.dashboard.dashboard_tools.get_all_database_links_with_species()
                        Each item: {'database': str, 'species_name': str, 'url': str}
    """
    synonyms_searched = metrics.get("synonyms_searched", 0)
    synonym_list = metrics.get("synonym_list", [])
    sources_with_data = metrics.get("sources_with_data", [])
    sources_no_data = metrics.get("sources_no_data", [])

    # ── Group links by database ───────────────────────────────────────────────
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for link in database_links:
        grouped[link["database"]].append(link)

    # ── Synonym count line ────────────────────────────────────────────────────
    variant_word = "variant" if synonyms_searched == 1 else "variants"
    synonym_title = _he(", ".join(synonym_list), quote=True) if synonym_list else ""
    synonym_line = (
        f"<span style='color:#555;font-size:1.1rem;' title='Searched: {synonym_title}'>"
        f"Searched <strong style='color:#333'>{synonyms_searched}</strong> name {variant_word}"
        f"</span>"
    )

    # ── Per-database link rows ────────────────────────────────────────────────
    db_rows_html = []

    for db in sources_with_data:
        color = _DB_COLORS.get(db, _DB_COLOR_DEFAULT)
        links_for_db = grouped.get(db, [])

        label = (
            f"<span style='font-weight:700;color:{color};"
            f"font-size:1.1rem;min-width:70px;display:inline-block;'>{db}:</span>"
        )

        if links_for_db:
            parts = []
            for lnk in links_for_db:
                # Primary badge: species variant -> taxonomy page (WoRMS for WRiMS)
                parts.append(
                    f"<a href='{_he(lnk['url'], quote=True)}' target='_blank' style='"
                    f"display:inline-block;"
                    f"font-size:0.8rem;"
                    f"padding:2px 9px;"
                    f"border:1px solid {color};"
                    f"border-radius:5px;"
                    f"color:{color};"
                    f"text-decoration:none;"
                    f"margin-right:5px;"
                    f"margin-bottom:3px;"
                    f"white-space:nowrap;"
                    f"font-style:italic;"
                    f"'>{_he(lnk['species_name'])}</a>"
                )
                # Secondary badge (WRiMS only): the introduced-register page.
                # Filled style so it reads as a companion to the variant above.
                if lnk.get('introduced_url'):
                    parts.append(
                        f"<a href='{_he(lnk['introduced_url'], quote=True)}' target='_blank' style='"
                        f"display:inline-block;"
                        f"font-size:0.72rem;"
                        f"padding:2px 7px;"
                        f"border:1px solid {color};"
                        f"border-radius:5px;"
                        f"background:{color};"
                        f"color:#fff;"
                        f"text-decoration:none;"
                        f"margin-right:8px;"
                        f"margin-bottom:3px;"
                        f"white-space:nowrap;"
                        f"' title='WRiMS introduced-register page'>introduced ↗</a>"
                    )
            buttons = "".join(parts)
        else:
            # Data found but no direct URL available
            buttons = (
                f"<span style='color:#aaa;font-size:1.1rem;font-style:italic;'>"
                f"data found · no direct link</span>"
            )

        db_rows_html.append(
            f"<div style='display:flex;align-items:center;flex-wrap:wrap;"
            f"gap:0;margin-bottom:5px;'>{label}{buttons}</div>"
        )

    for db in sources_no_data:
        color = _DB_COLORS.get(db, _DB_COLOR_DEFAULT)
        db_rows_html.append(
            f"<div style='margin-bottom:4px;'>"
            f"<span style='font-weight:700;color:#ccc;font-size:1.1rem;"
            f"min-width:70px;display:inline-block;'>{db}:</span>"
            f"<span style='color:#ccc;font-size:1.1rem;font-style:italic;'>no data</span>"
            f"</div>"
        )

    db_section_html = "".join(db_rows_html)

    # ── Render ────────────────────────────────────────────────────────────────
    # NOTE: No blank lines inside the HTML string — CommonMark ends an HTML
    # block at the first blank line, causing everything after it to render
    # as raw text instead of HTML.
    html = (
        '<div style="border:1px solid rgba(0,107,166,0.15);border-radius:8px;'
        'padding:12px 16px 10px 16px;background:rgba(0,107,166,0.025);margin-bottom:8px;">'
        '<div style="font-size:0.7rem;color:#aaa;text-transform:uppercase;'
        'letter-spacing:0.07em;margin-bottom:7px;">Sources</div>'
        f'<div style="margin-bottom:10px;">{synonym_line}</div>'
        f'<div>{db_section_html}</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)
