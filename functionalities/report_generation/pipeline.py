#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Report Generation Pipeline (RGP)
=================================

Haystack pipeline that generates the species report PDF from categorized data.

Pipeline flow:
    JSONLoaderComponent
      -> CategoryFilterComponent
      -> DataCleanerComponent
      -> DistributionTableExtractor
      -> RegulatoryStatusExtractor
      -> NarrativeGeneratorComponent

The components emit structured data; build_report_context() shapes it into the
report object and render_report_pdf() renders it (Jinja2 -> HTML -> WeasyPrint).
"""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from haystack import Pipeline

from functionalities.report_generation.json_loader import JSONLoaderComponent
from functionalities.report_generation.category_filter import CategoryFilterComponent
from functionalities.report_generation.data_cleaner import DataCleanerComponent
from functionalities.report_generation.narrative_generator import NarrativeGeneratorComponent
from functionalities.report_generation.distribution_extractor import DistributionTableExtractor
from functionalities.report_generation.regulatory_status_extractor import RegulatoryStatusExtractor
from functionalities.report_generation.report_renderer.context_builder import build_report_context
from functionalities.report_generation.report_renderer.render_pdf import render_report_pdf


def _build_citation_map(universal_id: str) -> Dict[str, str]:
    """
    Build {source_name: "Author, Year"} map from sources_metadata.json.

    Used by the narrative generator in APA mode so the AI can write
    correct author-date inline citations.

    Database sources get a fixed year (current year) since they are
    continuously updated. Research papers use metadata from extraction.
    """
    from datetime import datetime as _dt
    year_now = _dt.now().year

    db_keys = {
        'GBIF': f'GBIF, {year_now}',
        'WRiMS': f'WRiMS, {year_now}',
        'WoRMS': f'WoRMS, {year_now}',
        'IUCN': f'IUCN, {year_now}',
        'EASIN': f'EASIN, {year_now}',
        'AquaNIS': f'AquaNIS, {year_now}',
    }

    try:
        from core.utils.cache_manager import get_extracted_data_dir
        import json as _json
        extracted_dir = get_extracted_data_dir()
        meta_path = extracted_dir / universal_id / "sources_metadata.json"
        if not meta_path.exists():
            return db_keys

        with open(meta_path, encoding='utf-8') as f:
            store = _json.load(f)

        for entry in store.values():
            title = (entry.get('title') or '').strip()
            if not title:
                continue
            authors = entry.get('authors') or []
            year = entry.get('publication_year')
            year_str = str(year) if year else 'n.d.'
            if authors:
                first = authors[0].split(',')[0].strip()
                key = f'{first} et al., {year_str}' if len(authors) > 1 else f'{first}, {year_str}'
            else:
                key = f'{title[:30]}..., {year_str}' if len(title) > 30 else f'{title}, {year_str}'
            db_keys[title] = key

    except Exception as e:
        print(f"WARNING pipeline: Could not build citation map: {e}")

    return db_keys


_VALID_REFERENCE_STYLES = ("numbered", "apa", "harvard", "vancouver_superscript")

_DEFAULT_INCLUDE = {
    "provenance": True,
    "conflicts": True,
    "map": True,
    "phylopic": True,
}


def run_report_generation_pipeline(
    species_name: str,
    universal_id: str,
    selected_categories: List[str],
    reference_style: str = "numbered",
    include: Optional[Dict[str, Any]] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Run the Report Generation Pipeline (RGP).

    Args:
        species_name: Scientific name of the species
        universal_id: Universal species identifier
        selected_categories: List of category names to include in report
        reference_style: "numbered", "apa", "harvard", or "vancouver_superscript"
        include: Optional dict controlling which report sections render.
            Keys: "provenance", "conflicts", "map", "phylopic" — all default True.

    Returns:
        Dict with:
            - success: bool
            - pdf_bytes: bytes (if successful)
            - report_filename: str (if successful)
            - categories_included: List[str] (if successful)
            - error: str (if failed)
    """
    # Merge caller's include flags over the defaults (None → all on).
    effective_include = {**_DEFAULT_INCLUDE, **(include or {})}

    print("\n" + "=" * 80)
    print("REPORT GENERATION PIPELINE (RGP)")
    print("=" * 80)
    print(f"Species: {species_name}")
    print(f"Universal ID: {universal_id}")
    print(f"Selected categories: {len(selected_categories)}")
    print(f"Reference style: {reference_style}")
    print(f"Include: {effective_include}")
    print("=" * 80 + "\n")

    try:
        # ====================================================================
        # VALIDATE INPUTS
        # ====================================================================
        if not selected_categories:
            return {
                'success': False,
                'error': 'No categories selected for report. Please load categories in the dashboard first.'
            }

        if not species_name or not universal_id:
            return {
                'success': False,
                'error': 'Species name and universal ID are required'
            }

        if reference_style not in _VALID_REFERENCE_STYLES:
            return {
                'success': False,
                'error': (
                    f'Invalid reference_style: {reference_style!r}. '
                    f'Must be one of: {", ".join(_VALID_REFERENCE_STYLES)}.'
                )
            }

        # Build citation map for author-date styles (APA + Harvard).
        # Both use the same {source_name: "Author, Year"} map; the marker
        # format (comma vs no comma) is handled downstream in context_builder.
        citation_map = (
            _build_citation_map(universal_id)
            if reference_style in ("apa", "harvard")
            else {}
        )

        # ====================================================================
        # BUILD PIPELINE
        # ====================================================================
        # json_loader -> category_filter -> data_cleaner -> distribution_extractor
        #   -> regulatory_extractor -> narrative_generator
        # The components emit STRUCTURED data; build_report_context() shapes it
        # into the report object and render_report_pdf() renders the PDF.
        pipeline = Pipeline()

        pipeline.add_component("json_loader", JSONLoaderComponent())
        pipeline.add_component("category_filter", CategoryFilterComponent())
        pipeline.add_component("data_cleaner", DataCleanerComponent())
        pipeline.add_component("distribution_extractor", DistributionTableExtractor())
        pipeline.add_component("regulatory_extractor", RegulatoryStatusExtractor())

        narrative_component = NarrativeGeneratorComponent()
        if progress_callback:
            narrative_component.progress_callback = progress_callback
        pipeline.add_component("narrative_generator", narrative_component)

        pipeline.connect("json_loader.categorized_data", "category_filter.categorized_data")
        pipeline.connect("category_filter.filtered_data", "data_cleaner.filtered_data")
        pipeline.connect("data_cleaner.cleaned_data", "distribution_extractor.cleaned_data")
        pipeline.connect("distribution_extractor.remaining_data", "regulatory_extractor.cleaned_data")
        pipeline.connect("regulatory_extractor.remaining_data", "narrative_generator.cleaned_data")
        pipeline.connect("data_cleaner.all_sources", "narrative_generator.all_sources")

        # ====================================================================
        # RUN PIPELINE
        # ====================================================================
        if progress_callback:
            progress_callback(0.02, "Loading and cleaning species data...")

        result = pipeline.run(
            {
                "json_loader": {"species_name": species_name, "universal_id": universal_id},
                "category_filter": {"selected_categories": selected_categories},
                "narrative_generator": {
                    "species_name": species_name,
                    "reference_style": reference_style,
                    "citation_map": citation_map,
                },
            },
            include_outputs_from={
                "category_filter", "data_cleaner",
                "distribution_extractor", "regulatory_extractor", "narrative_generator",
            },
        )

        # ====================================================================
        # EXTRACT STRUCTURED RESULTS
        # ====================================================================
        categories_included = result.get('category_filter', {}).get(
            'categories_included', selected_categories)
        cleaned_data = result.get('data_cleaner', {}).get('cleaned_data', {})
        all_sources = result.get('data_cleaner', {}).get('all_sources', [])
        stats = result.get('data_cleaner', {}).get('stats', {})
        if stats:
            print(f"\nData cleaning stats: {stats}")

        distribution_records = result.get('distribution_extractor', {}).get('distribution_records', [])
        regulatory_status = result.get('regulatory_extractor', {}).get('regulatory_status', [])
        remaining_data = result.get('regulatory_extractor', {}).get('remaining_data', {})
        narratives = result.get('narrative_generator', {}).get('narratives', {})
        ai_narrative_categories = result.get('narrative_generator', {}).get('ai_narrative_categories', [])

        if not narratives and not cleaned_data:
            return {
                'success': False,
                'error': 'Pipeline produced no content for the selected categories.'
            }

        # ====================================================================
        # BUILD CONTEXT -> RENDER PDF (Jinja2 + WeasyPrint)
        # ====================================================================
        if progress_callback:
            progress_callback(0.85, "Generating PDF...")

        with tempfile.TemporaryDirectory() as assets_dir:
            context = build_report_context(
                species_name=species_name,
                universal_id=universal_id,
                cleaned_data=cleaned_data,
                remaining_data=remaining_data,
                regulatory_status=regulatory_status,
                narratives=narratives,
                ai_narrative_categories=ai_narrative_categories,
                distribution_records=distribution_records,
                all_sources=all_sources,
                selected_categories=selected_categories,
                reference_style=reference_style,
                citation_map=citation_map,
                include=effective_include,
                assets_dir=assets_dir,
            )
            pdf_bytes = render_report_pdf(context)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = species_name.replace(' ', '_').replace('/', '_')
        pdf_filename = f"{safe_name}_dashboard_report_{timestamp}.pdf"

        # ====================================================================
        # RETURN SUCCESS
        # ====================================================================
        return {
            'success': True,
            'pdf_bytes': pdf_bytes,
            'report_filename': pdf_filename,
            'categories_included': categories_included
        }

    except Exception as e:
        print(f"\nERROR RGP: Pipeline execution failed: {e}")
        import traceback
        traceback.print_exc()

        print("\n" + "=" * 80)
        print("RGP FAILED")
        print("=" * 80 + "\n")

        return {
            'success': False,
            'error': f'Unexpected error during report generation: {str(e)}'
        }


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Testing Report Generation Pipeline")
    print("=" * 80)

    test_result = run_report_generation_pipeline(
        species_name="Procambarus clarkii",
        universal_id="urn:lsid:marinespecies.org:taxname:606418",
        selected_categories=['taxonomic_identity', 'morphological_traits', 'distribution'],
    )

    if test_result['success']:
        print(f"\nPipeline test successful!")
        print(f"  Generated: {test_result['report_filename']}")
        print(f"  Categories: {test_result['categories_included']}")
        print(f"  PDF size: {len(test_result['pdf_bytes'])} bytes")
    else:
        print(f"\nPipeline test failed: {test_result['error']}")

    print("\nReport Generation Pipeline test completed!")
