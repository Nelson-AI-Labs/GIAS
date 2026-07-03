# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Unified Extraction System

This module consolidates the Source Extraction Pipeline (SEP) and Custom Topic System (CTS)
into a unified architecture with shared utilities and clear separation of concerns.

Architecture:
- agents/: All extraction agents (shared and specialized)
- converters/: PDF to markdown conversion
- formatters/: JSON formatting utilities
- registries/: Topic and context registries
- prompts/: All extraction prompts (topics, contexts, templates)
- pipelines/: Standard and custom extraction pipelines
- utils/: Shared utilities (prompt loading, validation, file I/O)
- merge_engine.py: Merges extractions into categorized data

Usage:
    # Standard topic extraction
    from functionalities.extraction.pipelines.standard_pipeline import run_standard_extraction_pipeline

    # Custom topic extraction
    from functionalities.extraction.pipelines.custom_pipeline import run_custom_topic_extraction

    # Shared utilities
    from functionalities.extraction.utils.output_saver import save_extraction_output
    from functionalities.extraction.utils.prompt_loader import load_prompt_with_fallback
    from functionalities.extraction.utils.json_parser import parse_and_validate_extraction
"""

__version__ = "1.0.0"

# Version history:
# 1.0.0 - Initial unified extraction system (consolidated from SEP + CTS)
