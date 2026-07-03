# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
GIAS — frontend/utils/icons.py
================================
Dependency-free inline-SVG helpers for raw-HTML render contexts.

Usage (in any file):
    from frontend.utils.icons import glyph_svg

All glyphs: line-art, 24×24 viewBox, Feather/Lucide style.
`stroke` defaults to 'currentColor' so parent CSS `color` is inherited.
`style='vertical-align:middle'` is baked in for inline-text alignment.

Note: This module MUST NOT import from other frontend.* modules —
it is imported by modules across the circular chain:
  components.py → field_renderers.py → research_renderers.py
"""

# ── glyph inner paths (no <svg> wrapper) ─────────────────────────────────────
# Keys map to inner SVG path/shape markup consumed by _svg_wrap.

GLYPH_ICONS: dict = {
    # warning / alert-triangle (Feather alert-triangle)
    "warning": (
        "<path d='M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3"
        "L13.71 3.86a2 2 0 0 0-3.42 0z'/>"
        "<line x1='12' y1='9' x2='12' y2='13'/>"
        "<line x1='12' y1='17' x2='12.01' y2='17'/>"
    ),
    # checkmark (Feather check)
    "check": "<polyline points='20 6 9 17 4 12'/>",
    # X / close (Feather x)
    "close": (
        "<line x1='18' y1='6' x2='6' y2='18'/>"
        "<line x1='6' y1='6' x2='18' y2='18'/>"
    ),
    # map pin / location (Feather map-pin)
    "location": (
        "<path d='M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z'/>"
        "<circle cx='12' cy='10' r='3'/>"
    ),
    # eye / horizon scanning (Feather eye)
    "telescope": (
        "<path d='M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'/>"
        "<circle cx='12' cy='12' r='3'/>"
    ),
    # image / photo placeholder (Feather image)
    "image": (
        "<rect x='3' y='3' width='18' height='18' rx='2' ry='2'/>"
        "<circle cx='8.5' cy='8.5' r='1.5'/>"
        "<polyline points='21 15 16 10 5 21'/>"
    ),
    # book / knowledge base (Feather book)
    "book": (
        "<path d='M4 19.5A2.5 2.5 0 0 1 6.5 17H20'/>"
        "<path d='M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'/>"
    ),
    # star — EU concern badge (Feather star)
    "star": (
        "<polygon points='12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 "
        "12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2'/>"
    ),
    # document / source file (Feather file-text)
    "document": (
        "<path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/>"
        "<polyline points='14 2 14 8 20 8'/>"
        "<line x1='16' y1='13' x2='8' y2='13'/>"
        "<line x1='16' y1='17' x2='8' y2='17'/>"
        "<polyline points='10 9 9 9 8 9'/>"
    ),
    # hourglass / loading (Feather hourglass)
    "hourglass": (
        "<path d='M5 22h14'/>"
        "<path d='M5 2h14'/>"
        "<path d='M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414"
        "A2 2 0 0 0 7 17.828V22'/>"
        "<path d='M7 2v4.172a2 2 0 0 1 .586 1.414L12 12l4.414-4.414"
        "A2 2 0 0 0 17 6.172V2'/>"
    ),
    # filled dot — stage "running" indicator (overrides fill at element level)
    "dot": "<circle cx='12' cy='12' r='5' fill='currentColor' stroke='none'/>",
    # circle outline — stage "queued" indicator
    "circle": "<circle cx='12' cy='12' r='7'/>",
}


def _svg_wrap(inner: str, stroke: str = "currentColor", size: int = 16) -> str:
    """Wrap inner SVG markup in a full <svg> element."""
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' "
        f"viewBox='0 0 24 24' fill='none' stroke='{stroke}' stroke-width='1.8' "
        f"stroke-linecap='round' stroke-linejoin='round' "
        f"style='vertical-align:middle'>{inner}</svg>"
    )


def glyph_svg(key: str, stroke: str = "currentColor", size: int = 16) -> str:
    """
    Return an inline SVG string for the given glyph key.

    Args:
        key:    Key into GLYPH_ICONS (e.g. 'warning', 'check', 'location').
        stroke: SVG stroke colour. 'currentColor' (default) inherits from
                the surrounding CSS `color`, enabling coloured parent spans
                to drive the icon colour without extra work.
        size:   Width and height in pixels (default 16 for inline-text use).

    Returns empty SVG on unknown key (fails silently).
    """
    return _svg_wrap(GLYPH_ICONS.get(key, ""), stroke, size)
