#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
OutputSaver Component

Wraps save_extraction_output as a Haystack component so persisting verified
extraction data becomes the terminal node of the extraction graph. No-ops
(returns output_filepath=None) when there is nothing to save, matching the
former `if save_output and verified_data:` guard.
"""

from pathlib import Path
from typing import Dict, Any, Optional

from haystack import component

from functionalities.extraction.utils.output_saver import save_extraction_output


@component
class OutputSaver:
    """Persist verified extraction data to a per-source JSON file."""

    def __init__(self):
        pass

    @component.output_types(output_filepath=Optional[str])
    def run(
        self,
        verified_data: Dict[str, Any],
        universal_id: str,
        source_id: str,
        research_topic: str,
        source_metadata: Dict[str, Any],
        species_name: str,
        extraction_type: str = "topic",
        extracted_data_dir: Optional[Path] = None,
        save_output: bool = True,
    ) -> Dict[str, Any]:
        if not (save_output and verified_data):
            return {"output_filepath": None}

        save_result = save_extraction_output(
            extracted_data=verified_data,
            universal_id=universal_id,
            source_id=source_id,
            research_topic=research_topic,
            source_metadata=source_metadata,
            species_name=species_name,
            extraction_type=extraction_type,
            extracted_data_dir=extracted_data_dir,
        )
        return {"output_filepath": save_result["output_filepath"]}
