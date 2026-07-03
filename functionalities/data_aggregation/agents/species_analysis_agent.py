#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Species Analysis Agent with SQL Tools
Replaces SQLBasedSummaryComponent with intelligent agent that uses SQL tools dynamically.
"""

import json
from typing import Dict, List, Any, Optional
from pathlib import Path
from haystack import component
from haystack.dataclasses import ChatMessage

from functionalities.data_aggregation.tools.DCP_tools import get_species_overview, get_species_taxonomy, get_species_distribution
from core.utils.generator_factory import create_generator

_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "species_analysis_prompt.md"
_FILTERED_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "species_analysis_filtered_prompt.md"

# ============================================================================
# SPECIES ANALYSIS AGENT COMPONENT
# ============================================================================

@component
class SpeciesAnalysisAgent:
    """
    Simple species analysis agent that executes SQL queries and provides a clear summary.
    """
    
    def __init__(self):
        """Initialize the species analysis agent."""
        self.generator = create_generator("species_analysis")
        self._prompt_template = _PROMPT_FILE.read_text(encoding="utf-8")
        self._filtered_prompt_template = _FILTERED_PROMPT_FILE.read_text(encoding="utf-8")
    
    @component.output_types(summary=str, sources=List[str], species_name=str, analysis_metadata=Dict[str, Any])
    def run(self,
            species_name: str,
            database_path: str = None,
            cached_data: Dict[str, Any] = None,
            data_sources: List[str] = None,
            query_metadata: Dict[str, Any] = None,
            filter_categories: List[str] = None,
            universal_id: str = None) -> Dict[str, Any]:
        """
        Summarize species data from SQL database.

        Args:
            species_name: Scientific name of the species to analyze
            database_path: Path to SQLite cache database
            cached_data: Cached species data (for compatibility)
            data_sources: Available data sources
            query_metadata: Query metadata with cache info
            filter_categories: Optional list of category names to filter analysis (for dashboard reports)
            universal_id: Optional universal species identifier (for dashboard reports)

        Returns:
            Dict with species summary, sources, and analysis metadata
        """


        # Check if this is a filtered dashboard report
        if filter_categories:
            return self._generate_filtered_summary(species_name, filter_categories, universal_id)

        # Use database_path directly from pipeline connection
        cache_path = database_path

        # Fallback: try to extract from metadata if database_path not provided
        if not cache_path and query_metadata and 'cache_filepath' in query_metadata:
            cache_path = query_metadata['cache_filepath']

        # Use JSON-based tools to gather data
        analysis_steps = []
        json_queries_used = []
        gathered_data = {}

        try:
            # Comprehensive Species Overview using JSON cache
            overview_result = get_species_overview(species_name)
            gathered_data["overview"] = overview_result
            analysis_steps.append("Retrieved comprehensive species overview from JSON cache")
            json_queries_used.append("species_overview")
            
        except Exception as e:
            return {
                "summary": f"Error executing analysis for {species_name}: {str(e)}",
                "sources": [],
                "species_name": species_name,
                "analysis_metadata": {"analysis_type": "json_cache_summary", "error": str(e)}
            }
        
        # Concatenate SQL results for Mistral summary
        data_summary = f"""Species Data for {species_name}:

{gathered_data.get('overview', 'No overview data available')}

{gathered_data.get('taxonomy', 'No taxonomy data available')}

{gathered_data.get('sources', 'No source comparison data available')}
"""
        
        analysis_prompt = self._prompt_template.replace("[DATA_SUMMARY]", data_summary)
        
        # Get Mistral analysis/summary of the gathered data
        messages = [ChatMessage.from_user(analysis_prompt)]
        
        try:
            result = self.generator.run(messages=messages)
            analysis_summary = result["replies"][0].text
            analysis_steps.append("Generated species summary with Mistral")
            
        except Exception as e:
            analysis_summary = f"Species Data for {species_name}:\n\n{data_summary}"
            analysis_steps.append("Used raw data due to Mistral error")
        
        
        # Prepare sources list
        if not data_sources:
            data_sources = ["GBIF", "WRiMS", "Cache Analysis"]
        
        # Analysis metadata
        analysis_metadata = {
            "analysis_type": "json_cache_summary",
            "analysis_steps": analysis_steps,
            "json_queries_used": json_queries_used,
        }
        
        return {
            "summary": analysis_summary,
            "sources": data_sources,
            "species_name": species_name,
            "analysis_metadata": analysis_metadata
        }

    def _generate_filtered_summary(self, species_name: str, filter_categories: List[str], universal_id: str = None) -> Dict[str, Any]:
        """
        Generate summary for filtered categories (dashboard reports).

        Args:
            species_name: Scientific name
            filter_categories: List of category names to include
            universal_id: Optional universal species identifier

        Returns:
            Dict with summary, sources, species_name, analysis_metadata
        """
        from core.dashboard.dashboard_tools import load_categorized_species_json

        try:
            # Load categorized data
            categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)

            if not categorized_data:
                return {
                    "summary": f"No data found for {species_name}",
                    "sources": [],
                    "species_name": species_name,
                    "analysis_metadata": {"analysis_type": "filtered_dashboard_report", "error": "No data found"}
                }

            all_fields = categorized_data.get('categorized_fields', {})
            all_sources = categorized_data.get('sources', [])

            # Filter to specified categories
            filtered_fields = {cat: all_fields[cat] for cat in filter_categories if cat in all_fields}

            if not filtered_fields:
                return {
                    "summary": f"Selected categories contain no data for {species_name}",
                    "sources": all_sources,
                    "species_name": species_name,
                    "analysis_metadata": {"analysis_type": "filtered_dashboard_report", "categories": filter_categories}
                }

            # Build data summary for Mistral
            category_summaries = []
            for cat_name, cat_data in filtered_fields.items():
                humanized_cat = cat_name.replace('_', ' ').title()
                category_summaries.append(f"\n=== {humanized_cat} ===")

                for field_name, field_entries in cat_data.items():
                    humanized_field = field_name.replace('_', ' ').title()
                    category_summaries.append(f"\n{humanized_field}:")

                    for entry in field_entries[:5]:  # Limit to first 5 entries per field
                        if isinstance(entry, dict):
                            value = entry.get('value')
                            source = entry.get('source', 'Unknown')
                            category_summaries.append(f"  - {value} (Source: {source})")

            data_summary = f"""Species Data for {species_name}

Selected Categories: {', '.join(c.replace('_', ' ').title() for c in filter_categories)}

{"".join(category_summaries)}"""

            analysis_prompt = (
                self._filtered_prompt_template
                .replace("[CATEGORY_COUNT]", str(len(filter_categories)))
                .replace("[DATA_SUMMARY]", data_summary)
            )

            # Get Mistral analysis
            messages = [ChatMessage.from_user(analysis_prompt)]

            try:
                result = self.generator.run(messages=messages)
                analysis_summary = result["replies"][0].text
            except Exception as e:
                # Fallback to structured summary
                analysis_summary = f"Data summary for {species_name} covering {len(filter_categories)} categories:\n\n{data_summary}"

            return {
                "summary": analysis_summary,
                "sources": all_sources,
                "species_name": species_name,
                "analysis_metadata": {
                    "analysis_type": "filtered_dashboard_report",
                    "categories_included": filter_categories,
                    "categories_count": len(filter_categories)
                }
            }

        except Exception as e:
            print(f"ERROR: Filtered summary generation failed: {e}")
            import traceback
            traceback.print_exc()

            return {
                "summary": f"Error generating filtered summary for {species_name}: {str(e)}",
                "sources": [],
                "species_name": species_name,
                "analysis_metadata": {"analysis_type": "filtered_dashboard_report", "error": str(e)}
            }

# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Testing Species Analysis Agent")
    print("=" * 40)
    
    # Test agent
    agent = SpeciesAnalysisAgent()
    
    test_species = "Apalone spinifera"
    print(f"\nTesting species summary for {test_species}:")
    
    result = agent.run(
        species_name=test_species
    )
    
    print(f"\nSummary completed!")
    print(f"Steps taken: {len(result['analysis_metadata']['analysis_steps'])}")
    print(f"JSON queries used: {len(result['analysis_metadata'].get('json_queries_used', []))}")
    print(f"Summary length: {len(result['summary'])} characters")
    print(f"Sources: {result['sources']}")
    
    print("\nSpecies Analysis Agent initialized successfully!")