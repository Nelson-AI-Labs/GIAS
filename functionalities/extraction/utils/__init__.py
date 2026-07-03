# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Extraction Utilities

Shared utilities for extraction pipelines:
- output_saver: Consolidated file I/O for extraction results
- json_parser: JSON recovery and validation
- prompt_loader: Hierarchical prompt loading with fallback
"""

from .output_saver import save_extraction_output
from .json_parser import (
    parse_and_validate_extraction,
    recover_json_from_response,
    validate_extraction_structure,
    is_flat_value
)
from .prompt_loader import (
    load_prompt_with_fallback,
    load_custom_prompt,
    save_custom_prompt,
    prompt_exists,
    normalize_topic_name
)

__all__ = [
    # Output saving
    'save_extraction_output',

    # JSON parsing and validation
    'parse_and_validate_extraction',
    'recover_json_from_response',
    'validate_extraction_structure',
    'is_flat_value',

    # Prompt loading
    'load_prompt_with_fallback',
    'load_custom_prompt',
    'save_custom_prompt',
    'prompt_exists',
    'normalize_topic_name',
]
