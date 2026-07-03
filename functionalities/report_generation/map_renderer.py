#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Distribution Map Renderer
==========================

Generates a static Europe-focused choropleth PNG for embedding in PDF reports.

Uses the same extraction logic as the Streamlit distribution map
(frontend/ui_components/distribution_map.py) but loads RAW categorized data
(not cleaned data) so the extractor functions can read entry['value'] as usual.

Requires kaleido for Plotly static image export:
    pip install kaleido
Gracefully degrades if kaleido is not installed.
"""

from pathlib import Path
from typing import Dict, List, Tuple

# Extent → filename suffix. Drives both the dual-PNG render and the choropleth scope.
_EXTENTS = ("world", "europe")


def render_distribution_map_png(
    universal_id: str, assets_dir: Path
) -> Tuple[Dict[str, Path], List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Build worldwide + Europe-focused distribution choropleths and export as PNGs.

    Loads raw categorized data for the species ONCE, runs all distribution extractors,
    resolves country statuses (surfacing native↔introduced conflicts), then renders one
    static PNG per extent (world, europe).

    Args:
        universal_id: Species universal ID (used to locate raw categorized data)
        assets_dir:   Directory to write the PNGs into (distribution_map_<extent>.png)

    Returns:
        (written, conflicts, unmapped) where written maps extent ("world"/"europe") →
        PNG Path, conflicts is a list of {"country", "sources"} dicts for countries whose
        sources disagree, and unmapped is a list of {"locality", "status", "source"} dicts
        for marine/open-ocean records with no resolvable country. All empty on skip/failure.
    """
    try:
        # --- Load raw categorized data (not cleaned — extractors expect entry['value']) ---
        from core.cache_layer.categorized_data_helpers import load_categorized_data_by_id
        raw_data = load_categorized_data_by_id(universal_id)
        if not raw_data:
            print(f"INFO map_renderer: No raw data for '{universal_id}' — skipping map")
            return {}, [], []

        # load_categorized_data_by_id returns {universal_id, sources, categorized_fields: {...}}
        categorized_fields = raw_data.get('categorized_fields', {})
        distribution_data = categorized_fields.get('distribution_and_status', {})
        if not distribution_data:
            print(f"INFO map_renderer: No distribution_and_status data — skipping map")
            return {}, [], []

        # --- Import shared extraction logic from Streamlit component ---
        from frontend.ui_components.distribution_map import (
            _labeled_status_dicts,
            collect_country_statuses,
            resolve_country_statuses,
            extract_unmapped_localities,
            extract_from_extracted_distribution,
            extract_points_from_occurrence_sample,
            build_distribution_dataframe,
            iso2_to_iso3,
            _iso2_to_name,
            SHORT_LABELS,
            COLOR_MAP,
            LEGEND_LABELS,
            _build_choropleth,
        )

        # --- Run all extractors (provenance-tagged) and resolve per-country status ---
        per_country = collect_country_statuses(_labeled_status_dicts(distribution_data))
        statuses, details = resolve_country_statuses(per_country)
        if not statuses:
            print(f"INFO map_renderer: No country data found for '{universal_id}' — skipping map")
            return {}, [], []

        # Per-source pairs (not a joined string) so the report can render each
        # source as a citation link beside its status. Built straight from
        # per_country to avoid re-parsing the human-readable detail string.
        conflicts = [
            {
                "country": _iso2_to_name(iso2),
                "pairs": [
                    {"source": label, "status": SHORT_LABELS.get(status, status)}
                    for label, status in sorted(per_country[iso2].items())
                ],
            }
            for iso2 in sorted(statuses, key=_iso2_to_name)
            if statuses[iso2] == "CONFLICT"
        ]

        # Marine / open-ocean localities that resolve to no country — surfaced, not dropped.
        unmapped = [
            {
                "locality": u["locality"],
                "status": SHORT_LABELS.get(u["status"], u["status"]),
                "source": u["source"],
            }
            for u in sorted(extract_unmapped_localities(distribution_data),
                            key=lambda u: u["locality"])
        ]

        df = build_distribution_dataframe(statuses, details)
        if df is None:
            print(f"INFO map_renderer: No valid ISO-3 codes — skipping map")
            return {}, [], []

        # Precise occurrence points (same Tier-1 data the dashboard map overlays)
        points = extract_points_from_occurrence_sample(distribution_data.get('occurrence_sample', []))

        # Literature-reported countries → ISO-3 list, for the dashed-border echo
        literature = extract_from_extracted_distribution(distribution_data.get('extracted_distribution', []))
        literature_iso3 = [iso for iso in (iso2_to_iso3(c) if len(c) == 2 else c for c in literature) if iso]

        # --- Render one PNG per extent (world, europe) from the same merged data ---
        written: Dict[str, Path] = {}
        for extent in _EXTENTS:
            fig = _build_choropleth(df, COLOR_MAP, LEGEND_LABELS, points, literature_iso3, extent)
            dest = assets_dir / f"distribution_map_{extent}.png"
            try:
                fig.write_image(str(dest), format='png', width=900, height=480, scale=2)
                print(f"INFO map_renderer: {extent} map exported to {dest}")
                written[extent] = dest
            except Exception as kaleido_err:
                if 'kaleido' in str(kaleido_err).lower() or 'No module' in str(kaleido_err):
                    print(
                        f"WARNING map_renderer: kaleido not installed — no distribution map in PDF. "
                        f"Install with: pip install kaleido"
                    )
                else:
                    print(f"WARNING map_renderer: write_image failed ({extent}): {kaleido_err}")
                break  # kaleido failure is global — no point retrying the next extent
        return written, conflicts, unmapped

    except Exception as e:
        print(f"WARNING map_renderer: Unexpected error — {e}")
        import traceback
        traceback.print_exc()
        return {}, [], []
