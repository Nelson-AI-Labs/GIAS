#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Species Report Service
Separate service for generating Mistral reports from cached SQL data.
"""

import os
from typing import Dict, Any, Optional
from functionalities.data_aggregation.pipeline import ReportGeneratorComponent
from functionalities.data_aggregation.agents.species_analysis_agent import SpeciesAnalysisAgent

# ============================================================================
# SPECIES REPORT SERVICE
# ============================================================================

class SpeciesReportService:
    """
    Service for generating species reports from cached database data.
    Uses existing DCP components but operates independently from the main pipeline.
    Session-aware for multi-user cache isolation.
    """

    def __init__(self, cache_dir: str = None, session_id: str = None):
        """
        Initialize the report service.

        Args:
            cache_dir: Directory where reports should be saved (defaults to session-aware cache folder)
            session_id: Session ID for cache isolation. If None, uses current session.
        """
        if cache_dir is None:
            from core.utils.session_context import get_session_cache_base
            cache_dir = str(get_session_cache_base())

        self.cache_dir = cache_dir
        self.session_id = session_id
        self.analysis_agent = SpeciesAnalysisAgent()
        self.report_generator = ReportGeneratorComponent(output_dir=cache_dir)
    
    def generate_species_report(self, species_name: str, database_path: str = None) -> Dict[str, Any]:
        """
        Generate a comprehensive species report from cached database data.
        
        Args:
            species_name: Scientific name of the species
            database_path: Path to the cached database file (optional, will find latest if not provided)
            
        Returns:
            Dictionary with report generation results
        """
        
        print(f"Starting report generation for: {species_name}")
        
        try:
            # Step 1: Run species analysis agent
            print("Running species analysis...")
            analysis_result = self.analysis_agent.run(
                species_name=species_name,
                database_path=database_path
            )
            
            if not analysis_result.get("summary"):
                return {
                    "success": False,
                    "error": "Failed to generate species analysis",
                    "report_path": None
                }
            
            # Step 2: Generate report file
            print("Generating report file...")
            report_result = self.report_generator.run(
                summary=analysis_result["summary"],
                sources=analysis_result.get("sources", ["GBIF", "WRiMS"]),
                species_name=species_name,
                query_metadata=analysis_result.get("analysis_metadata", {})
            )
            
            if report_result.get("success"):
                print(f"Report generated successfully: {report_result['report_path']}")
                return {
                    "success": True,
                    "report_path": report_result["report_path"],
                    "summary": analysis_result["summary"],
                    "sources": analysis_result["sources"],
                    "analysis_metadata": analysis_result.get("analysis_metadata", {})
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to generate report file",
                    "report_path": None
                }
                
        except Exception as e:
            print(f"Error generating species report: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "report_path": None
            }

# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def generate_species_report(species_name: str, database_path: str = None, cache_dir: str = None) -> Dict[str, Any]:
    """
    Convenience function to generate a species report.
    
    Args:
        species_name: Scientific name of the species
        database_path: Path to the cached database file (optional)
        cache_dir: Directory for saving reports (optional)
        
    Returns:
        Dictionary with report generation results
    """
    
    service = SpeciesReportService(cache_dir=cache_dir)
    return service.generate_species_report(species_name, database_path)

# ============================================================================
# MAIN EXECUTION (FOR TESTING)
# ============================================================================

if __name__ == "__main__":
    # Test report generation
    test_species = "Smaragdia viridis"
    print(f"Testing Species Report Service with: {test_species}")
    print("-" * 60)
    
    result = generate_species_report(test_species)
    
    print("\nReport generation completed!")
    print(f"Success: {result.get('success', False)}")
    if result.get('report_path'):
        print(f"Report saved to: {result['report_path']}")
    if result.get('error'):
        print(f"Error: {result['error']}")