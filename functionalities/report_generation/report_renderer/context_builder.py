# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
context_builder.py — pipeline output -> `report` object for the template.

build_report_context() reshapes the cleaned pipeline data into the dict the
Jinja template renders (the contract in templates/report.html.jinja). It is the
only porting work between the pipeline and the renderer: everything here already
exists upstream in structured form; this module maps and orders it.

Transient cover images (species photo, distribution map) are written into
`assets_dir` (a per-run temp dir owned by the caller); the PhyloPic silhouette
is cached persistently by phylopic.py.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from functionalities.report_generation.report_formatter import ReportDataBuilder
from functionalities.report_generation.report_renderer import phylopic

logger = logging.getLogger(__name__)

_PIPELINE_VERSION = "GuardIAS RGP v2.0"
_INTERNAL_LABELS = {'AI-normalization', 'Unknown', 'Research Source'}


# =====================================================================
# Public entry point
# =====================================================================
_DEFAULT_INCLUDE = {
    "provenance": True,
    "conflicts": True,
    "map": True,
    "phylopic": True,
}


def build_report_context(
    species_name: str,
    universal_id: str,
    cleaned_data: Dict[str, Any],
    remaining_data: Dict[str, Any],
    regulatory_status: List[Dict[str, Any]],
    narratives: Dict[str, str],
    distribution_records: List[Dict[str, Any]],
    all_sources: List[str],
    selected_categories: List[str],
    ai_narrative_categories: Optional[List[str]] = None,
    reference_style: str = "numbered",
    citation_map: Optional[Dict[str, str]] = None,
    include: Optional[Dict[str, bool]] = None,
    assets_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return the `report` dict the template renders.

    Args:
        cleaned_data: data_cleaner output (pre-extractor) — drives risk +
            management blocks, which read fields the extractors later pop.
        remaining_data: regulatory_extractor.remaining_data — drives section
            facts (status + distribution already removed).
        narratives: {category: section HTML} from narrative_generator.
        distribution_records: structured rows from distribution_extractor.
        selected_categories: Layer-1 selection, in display order.
        assets_dir: per-run dir for transient cover photo + map PNG.
    """
    builder = ReportDataBuilder()
    assets_dir = Path(assets_dir) if assets_dir else Path.cwd()
    effective_include = {**_DEFAULT_INCLUDE, **(include or {})}

    species = _species_meta(species_name, cleaned_data)

    # --- cover images (best-effort; each falls back to a placeholder) ----
    photo_url, photo_credit = _cover_photo(species_name, universal_id, assets_dir)
    silhouette_url, silhouette_attr, silhouette_page_url = _silhouette(species_name)
    map_world_url, map_europe_url, distribution_conflicts, distribution_unmapped = _distribution_map(universal_id, assets_dir)

    # External database identifiers (EASIN id, …) → mono code-chip cloud on the
    # taxonomy section; rendered as a standalone section if taxonomy isn't selected.
    external_ids = builder.build_external_ids(universal_id)

    # --- sections (Layer-1 order) ----------------------------------------
    ai_set = set(ai_narrative_categories or [])
    sections = []
    for cat in _ordered_categories(selected_categories, remaining_data, narratives):
        blocks = builder.build_section_blocks(cat, remaining_data.get(cat, {}))
        if cat == "taxonomic_identity" and external_ids:
            blocks["clouds"].append(external_ids)
            external_ids = None
        # Research extracts for this category (raw is_research_data entries).
        blocks["evidence"] = builder.build_evidence(universal_id, cat)
        narrative = _linkify_citations(narratives.get(cat, ""), reference_style)
        if not narrative and not any(blocks[k] for k in
                                     ("facts", "classification", "clouds",
                                      "tables", "notes", "evidence")):
            continue
        sections.append({
            "title": builder._humanize_category_name(cat),
            # flags the chapter the distribution maps + conflict/marine tables
            # render under (template injects them at this section's end).
            "is_distribution": cat == "distribution_and_status",
            # True when this section's prose came from the LLM (not the
            # deterministic fallback) → template shows an "AI-assisted" badge.
            "is_ai_generated": cat in ai_set,
            "narrative": narrative,
            **blocks,
        })

    # External IDs but no taxonomy section selected → emit a minimal section.
    if external_ids:
        sections.insert(0, {
            "title": "Taxonomic Identity", "narrative": "", "is_distribution": False,
            "is_ai_generated": False,
            "facts": [], "classification": None, "conflict": None,
            "clouds": [external_ids], "tables": [], "notes": [], "evidence": [],
        })

    visible_sources = [s for s in all_sources if s not in _INTERNAL_LABELS]
    kpis = builder.build_kpis(cleaned_data, len(visible_sources))

    # References + the per-source cross-reference handles fact chips link to.
    references = builder.build_references(
        species_name, universal_id, all_sources, reference_style
    )

    return {
        "species": species,
        "universal_id": universal_id,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "pipeline_version": _PIPELINE_VERSION,
        "source_count": len(visible_sources),
        "reference_style": reference_style,
        "include": effective_include,
        "regulatory_status": regulatory_status or [],
        "cover": {
            "photo_url": photo_url,
            "photo_credit": photo_credit,
            "silhouette_url": silhouette_url,
            "silhouette_credit": silhouette_attr,
            "silhouette_page_url": silhouette_page_url,
            "verdict": _verdict_tiles(builder.build_risk_indicators(cleaned_data)),
        },
        "kpis": kpis,
        "sections": sections,
        "distribution_map_world_url": map_world_url,
        "distribution_map_europe_url": map_europe_url,
        "distribution_conflicts": distribution_conflicts,
        "distribution_unmapped": distribution_unmapped,
        "management_priority": builder.build_management_matrix(cleaned_data),
        "appendix": {"records": distribution_records or []},
        "references": references,
        "source_citations": _source_citations(references, reference_style, citation_map),
    }


_CITATION_MARKER_RE = re.compile(r'\[(\d+(?:\s*,\s*\d+)*)\]')


def _linkify_citations(html: str, reference_style: str) -> str:
    """Make inline numbered citation markers in the AI narrative clickable.

    For "numbered": '[3]' → '[<a href="#ref-3">3</a>]'
    For "vancouver_superscript": '[3]' → '<sup><a href="#ref-3">3</a></sup>'
    APA and Harvard use author-date markers — no numeric linkification needed.
    """
    if not html or reference_style not in ("numbered", "vancouver_superscript"):
        return html

    def _link_num(d: "re.Match") -> str:
        n = d.group(0)
        return f'<a href="#ref-{n}">{n}</a>'

    if reference_style == "vancouver_superscript":
        def _repl(m: "re.Match") -> str:
            inner = re.sub(r"\d+", _link_num, m.group(1))
            return f'<sup>{inner}</sup>'
    else:
        def _repl(m: "re.Match") -> str:
            return f'[{re.sub(r"\d+", _link_num, m.group(1))}]'

    return _CITATION_MARKER_RE.sub(_repl, html)


# =====================================================================
# Source cross-references (fact chips → Sources page anchors)
# =====================================================================
def _source_citations(
    references: List[Dict[str, str]],
    reference_style: str,
    citation_map: Optional[Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    """Map each source key → {anchor, marker} so a fact's source chip can link
    to its Sources-page entry (#ref-N) and show the citation marker the
    narrative uses.

    Marker formats by style:
      numbered            → "[3]"
      apa                 → "(2026)"          (year only, APA short form)
      harvard             → "(Gherardi 2006)"  (no comma, full author-year)
      vancouver_superscript → "<sup>3</sup>"  (HTML; template renders |safe)

    Anchors are positional (ref-1, ref-2…), matching the template's
    `id="ref-{loop.index}"` on the references list — identical across styles.
    """
    citation_map = citation_map or {}
    out: Dict[str, Dict[str, str]] = {}
    for i, ref in enumerate(references, start=1):
        key = ref.get("key")
        if not key:
            continue

        if reference_style == "apa":
            full = citation_map.get(key, "")
            # "GBIF, 2026" → "(2026)"; drop the redundant source-name prefix.
            tail = full[len(key):].lstrip(", ").strip() if full.startswith(key) else full
            marker = f"({tail})" if tail else ""
        elif reference_style == "harvard":
            full = citation_map.get(key, "")
            # "Gherardi, 2006" → "(Gherardi 2006)" — drop comma between name and year.
            harvard_form = full.replace(", ", " ", 1) if ", " in full else full
            marker = f"({harvard_form})" if harvard_form else ""
        elif reference_style == "vancouver_superscript":
            # HTML superscript — rendered with |safe in the template.
            marker = f"<sup>{i}</sup>"
        else:
            # "numbered" (default)
            marker = f"[{i}]"

        entry = {"anchor": f"ref-{i}", "marker": marker}
        out[key] = entry
        if key == "WRiMS":            # facts may carry either spelling
            out.setdefault("WoRMS", entry)
    return out


# =====================================================================
# Section + fact shaping
# =====================================================================
def _ordered_categories(
    selected: List[str], remaining_data: Dict[str, Any], narratives: Dict[str, str]
) -> List[str]:
    """Selected categories first (display order), then any extra categories
    that carry data but weren't in the selection list, de-duplicated."""
    seen = set()
    ordered = []
    for cat in list(selected) + list(remaining_data.keys()) + list(narratives.keys()):
        if cat in seen:
            continue
        seen.add(cat)
        ordered.append(cat)
    return ordered


# =====================================================================
# Cover derivations
# =====================================================================
def _species_meta(species_name: str, cleaned_data: Dict[str, Any]) -> Dict[str, str]:
    """Pull cover taxonomy fields best-effort from taxonomic_identity."""
    def first(field: str) -> str:
        """Return the first fact string for a taxonomic_identity field, or '' if absent."""
        entries = cleaned_data.get("taxonomic_identity", {}).get(field, [])
        if entries and isinstance(entries, list):
            val = entries[0].get("fact")
            if isinstance(val, str):
                return val.strip()
        return ""

    return {
        "name": species_name,
        "common_name": first("vernacular_name") or first("common_name"),
        "authority": first("scientific_name_authorship") or first("authority") or first("authorship"),
        "family": first("family"),
    }


_TONE_OK = {"LC", "LEAST CONCERN", "NOT LISTED", "NO"}
_TONE_BAD_HINTS = ("union concern", "established")


def _verdict_tiles(indicators: List) -> List[Dict[str, str]]:
    """Map up to 4 non-empty risk indicators to cover verdict tiles with tones."""
    tiles = []
    for label, value in indicators:
        if not value or value == "—":
            continue
        tiles.append({"label": label, "value": value, "tone_class": _tone_for(label, value)})
        if len(tiles) == 4:
            break
    return tiles


def _tone_for(label: str, value: str) -> str:
    v = value.lower()
    if any(h in v for h in _TONE_BAD_HINTS):
        return "tone-bad"
    if value.upper() in _TONE_OK or v.startswith("not listed"):
        return "tone-ok"
    if v.startswith("spreading") or label in ("EICAT", "SEICAT") or v == "yes":
        return "tone-warn"
    return "tone-ink"


def _cover_photo(species_name: str, universal_id: str, assets_dir: Path) -> tuple[str, str]:
    """Download a CC species photo locally; return (file_uri, credit) or ('','')."""
    try:
        from core.dashboard.image_fetchers import get_species_image_url
        from core.utils.config_loader import get_contact_email
        import requests

        image_url = get_species_image_url(species_name, universal_id=universal_id or None)
        if not image_url:
            return "", ""
        dest = assets_dir / "species_photo.jpg"
        resp = requests.get(
            image_url,
            headers={"User-Agent": f"GuardIAS/1.0 (contact: {get_contact_email()})",
                     "Accept": "image/*"},
            timeout=15,
        )
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return dest.as_uri(), "Wikimedia Commons (CC)"
    except Exception as e:
        logger.warning("Cover photo fetch failed for %r: %s", species_name, e)
        return "", ""


def _silhouette(species_name: str) -> tuple[str, str, str]:
    """Resolve a PhyloPic silhouette; return (file_uri, attribution, page_url) or ('','','')."""
    sil = phylopic.fetch_silhouette(species_name)
    if not sil:
        return "", "", ""
    return Path(sil["path"]).as_uri(), sil.get("attribution", ""), sil.get("page_url", "")


def _distribution_map(universal_id: str, assets_dir: Path) -> tuple[str, str, list, list]:
    """Render world + Europe choropleth PNGs; return
    (world_uri, europe_uri, conflicts, unmapped). conflicts is a list of
    {"country", "sources"} dicts; unmapped is a list of {"locality", "status", "source"}
    dicts for marine/open-ocean localities; all empty when missing."""
    if not universal_id:
        return "", "", [], []
    try:
        from functionalities.report_generation.map_renderer import render_distribution_map_png
        written, conflicts, unmapped = render_distribution_map_png(universal_id, assets_dir)
        world = written["world"].as_uri() if "world" in written else ""
        europe = written["europe"].as_uri() if "europe" in written else ""
        return world, europe, conflicts, unmapped
    except Exception as e:
        logger.warning("Distribution map render failed for %s: %s", universal_id, e)
    return "", "", [], []
