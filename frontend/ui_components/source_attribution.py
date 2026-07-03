# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Source Attribution Module
=========================

Provides functions for rendering source badges and attribution information
in the dashboard UI.
"""

import streamlit as st
from typing import List, Optional
from frontend.utils.icons import glyph_svg


def render_source_badge(
    source: str,
    method: str = "unknown",
    is_research_data: bool = False,
    query_names: Optional[List[str]] = None
) -> None:
    """
    Render a small badge showing data source, categorization method, and
    optionally which synonym names were used to query this source.

    Args:
        source: Source name (e.g., "AquaNIS", "GBIF", "paper.pdf")
        method: Categorization method ("ai" or "direct_mapping")
        is_research_data: Whether this is research-extracted data
        query_names: List of synonym names that were queried for this source

    Examples:
        >>> render_source_badge("GBIF", "direct_mapping", query_names=["Cambarus clarkii"])
        # Displays: [GBIF • Direct] via Cambarus clarkii
        >>> render_source_badge("GBIF", "ai", query_names=["Procambarus clarkii", "Cambarus clarkii"])
        # Displays: [GBIF • AI] via Procambarus clarkii, Cambarus clarkii
    """
    if is_research_data:
        color = "#9C27B0"
        method_label = "Research"
        source_display = f"{glyph_svg('document', stroke='white', size=12)} {source}"
    else:
        method_label = "AI" if method == "ai" else "Direct"
        color = "#4CAF50" if method == "direct_mapping" else "#2196F3"
        source_display = source

    badge_html = (
        f'<span style="background-color: {color}; color: white; padding: 2px 8px; '
        f'border-radius: 4px; font-size: 0.75em; margin-left: 8px;">'
        f'{source_display} • {method_label}</span>'
    )

    if query_names:
        names_str = ", ".join(f"<i>{n}</i>" for n in query_names)
        badge_html += (
            f'<span style="font-size: 0.72em; color: #888; margin-left: 5px;">'
            f'via {names_str}</span>'
        )

    st.markdown(badge_html, unsafe_allow_html=True)
