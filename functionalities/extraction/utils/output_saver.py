# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Consolidated output saving for extraction pipelines.

This module provides unified file I/O functionality for both standard (SEP)
and custom (CTS) topic extraction pipelines.

Directory structure:
    extracted_data/{universal_id}/{source_id}_{sanitized_title}/
        context_paper_summary_{timestamp}_extraction.json
        morphological_traits_{timestamp}_extraction.json
        removed_fields_morphological_traits_{timestamp}.json
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from core.utils.cache_manager import get_extracted_data_dir


def _sanitize_folder_name(title: str, max_length: int = 60) -> str:
    """
    Sanitize a source title for use as a folder name.

    Args:
        title: Source title string
        max_length: Maximum length for the sanitized portion

    Returns:
        Filesystem-safe folder name
    """
    # Lowercase, replace spaces/special chars with underscores
    sanitized = title.lower().strip()
    sanitized = re.sub(r'[^\w\s-]', '', sanitized)  # Remove non-alphanumeric (keep spaces, hyphens)
    sanitized = re.sub(r'[\s-]+', '_', sanitized)    # Replace spaces/hyphens with underscores
    sanitized = re.sub(r'_+', '_', sanitized)        # Collapse multiple underscores
    sanitized = sanitized.strip('_')                  # Remove leading/trailing underscores

    # Truncate to keep folder names reasonable
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip('_')

    return sanitized or 'untitled'


def get_source_folder(
    universal_id: str,
    source_id: str,
    source_title: str = '',
    extracted_data_dir: Optional[Path] = None
) -> Path:
    """
    Get the folder path for a specific source within the extracted_data directory.

    Creates the directory if it doesn't exist.

    Args:
        universal_id: Universal species ID
        source_id: Source UUID
        source_title: Human-readable source title
        extracted_data_dir: Pre-resolved extracted data directory. If None,
            resolves via get_extracted_data_dir() (requires Streamlit context).

    Returns:
        Path to the source folder
    """
    extracted_dir = extracted_data_dir if extracted_data_dir is not None else get_extracted_data_dir()
    sanitized_title = _sanitize_folder_name(source_title)
    source_folder = extracted_dir / universal_id / f"{source_id}_{sanitized_title}"
    source_folder.mkdir(parents=True, exist_ok=True)
    return source_folder


def save_extraction_output(
    extracted_data: Dict[str, Any],
    universal_id: str,
    source_id: str,
    research_topic: str,
    source_metadata: Dict[str, Any],
    species_name: str,
    extraction_type: str = "topic",
    topic_type: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    extracted_data_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Save extracted data to JSON file with consistent formatting.

    Files are organized in per-source subdirectories:
        extracted_data/{universal_id}/{source_id}_{sanitized_title}/

    Args:
        extracted_data: The extracted data dictionary (flat JSON structure)
        universal_id: Universal species ID
        source_id: Source identifier
        research_topic: Research topic or context key
        source_metadata: Source metadata dictionary
        species_name: Species name
        extraction_type: "topic" for standard extractions, "context" for contextual extractions
        topic_type: Optional topic type ("custom", "anchor", etc.) for additional metadata
        pipeline_name: Optional pipeline name for tracking which pipeline performed extraction

    Returns:
        Dictionary containing:
        - output_filepath: Path to saved file
        - extraction_timestamp: ISO format timestamp
        - fields_extracted: Number of fields extracted
    """
    # Create per-source directory
    source_title = source_metadata.get('title', '')
    output_dir = get_source_folder(universal_id, source_id, source_title, extracted_data_dir)

    # Build the filename; source_id lives in the folder name, not the filename
    topic_safe = research_topic.lower().replace(' ', '_')
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    if extraction_type == "context":
        filename = f"context_{topic_safe}_{timestamp}_extraction.json"
    else:
        filename = f"{topic_safe}_{timestamp}_extraction.json"

    filepath = output_dir / filename

    # Prepare metadata
    metadata = {
        "species_name": species_name,
        "universal_id": universal_id,
        "research_topic": research_topic,
        "extraction_type": extraction_type,
        "source_id": source_id,
        "source_url": source_metadata.get('url', ''),
        "source_title": source_metadata.get('title', ''),
        "source_domain": source_metadata.get('domain', ''),
        "doi": source_metadata.get('doi'),
        "publication_year": source_metadata.get('publication_year'),
        "journal_name": source_metadata.get('journal_name'),
        "authors": source_metadata.get('authors', []),
        "extraction_timestamp": datetime.now().isoformat(),
        "fields_extracted": len(extracted_data)
    }

    # Add optional metadata fields if provided
    if topic_type is not None:
        metadata["topic_type"] = topic_type
    if pipeline_name is not None:
        metadata["pipeline"] = pipeline_name

    # Add translation metadata if document was translated
    if source_metadata.get("translated_from"):
        metadata["translated_from"] = source_metadata["translated_from"]
        metadata["translation_note"] = source_metadata.get("translation_note", "")
        metadata["translation_failed"] = source_metadata.get("translation_failed", False)

    # Prepare output data
    output_data = {
        "metadata": metadata,
        "extracted_data": extracted_data
    }

    # Save to file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"Saved {extraction_type} extraction output to: {filepath}")

    # Upsert citation record into sources_metadata.json (once per source)
    update_sources_metadata(
        universal_id=universal_id,
        source_id=source_id,
        citation_data={
            "source_id": source_id,
            "title": source_metadata.get('title', ''),
            "url": source_metadata.get('url', ''),
            "domain": source_metadata.get('domain', ''),
            "doi": source_metadata.get('doi'),
            "publication_year": source_metadata.get('publication_year'),
            "journal_name": source_metadata.get('journal_name'),
            "authors": source_metadata.get('authors', []),
        },
        extracted_data_dir=extracted_data_dir
    )

    return {
        "output_filepath": str(filepath),
        "extraction_timestamp": metadata["extraction_timestamp"],
        "fields_extracted": metadata["fields_extracted"]
    }


def update_sources_metadata(
    universal_id: str,
    source_id: str,
    citation_data: Dict[str, Any],
    extracted_data_dir: Optional[Path] = None
) -> None:
    """
    Upsert a citation record into sources_metadata.json for a species.

    The file is keyed by source_id so repeated saves for the same source
    (multiple topic extractions) do not create duplicate entries.

    File location:
        extracted_data/{universal_id}/sources_metadata.json

    Args:
        universal_id: Universal species ID (used for directory lookup)
        source_id: Source UUID — used as the key in the store
        citation_data: Dict with citation fields (title, url, doi, authors, etc.)
        extracted_data_dir: Pre-resolved extracted data directory. If None,
            resolves via get_extracted_data_dir() (requires Streamlit context).
    """
    extracted_dir = extracted_data_dir if extracted_data_dir is not None else get_extracted_data_dir()
    species_dir = extracted_dir / universal_id
    species_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = species_dir / "sources_metadata.json"

    # Load existing store or start fresh
    store: Dict[str, Any] = {}
    if metadata_path.exists():
        try:
            with open(metadata_path, encoding='utf-8') as f:
                store = json.load(f)
        except Exception as e:
            print(f"WARNING output_saver: Could not read sources_metadata.json — starting fresh: {e}")

    # Only write if this source is not already present (idempotent per source)
    if source_id not in store:
        store[source_id] = citation_data
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(store, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"WARNING output_saver: Could not write sources_metadata.json: {e}")
