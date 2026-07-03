#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Species Context Service

Generates contextually related "wrong species" examples used across the tool
wherever extraction prompts need to illustrate what NOT to extract.

Runs once per research session (keyed by universal_id) and caches the result.
All subsequent calls within the same session load from cache — no LLM call made.

Cache location:
    cache/{session_id}/species_context/{universal_id}_wrong_species.json

Usage:
    from core.services.species_context_service import get_wrong_species

    context = get_wrong_species("Procambarus clarkii", "12345_procambarus_clarkii")
    # {"other_species_1": "Procambarus virginalis", "other_species_2": "Orconectes limosus"}
"""

import json
from typing import Dict, Optional
from pathlib import Path
from core.utils.generator_factory import create_generator
from haystack.dataclasses import ChatMessage
from core.utils.cache_manager import get_cache_manager
from functionalities.extraction.utils.json_parser import recover_json_from_response

_PROMPT_FILE = Path(__file__).parent / "prompts" / "species_context_prompt.md"
_PROMPT_TEMPLATE = _PROMPT_FILE.read_text(encoding="utf-8")


def get_wrong_species(species_name: str, universal_id: str, session_id: Optional[str] = None) -> Dict[str, str]:
    """
    Get two related-but-distinct species names for use as ❌ wrong-species
    examples in extraction prompts.

    Loads from session cache if already generated. Otherwise calls the LLM
    once and caches the result.

    Args:
        species_name: The target species being researched (e.g. "Procambarus clarkii")
        universal_id: Universal species ID used for cache file naming
        session_id: Explicit session ID to use for cache path. Pass this when calling
                    from Haystack component threads where Streamlit context is unavailable.

    Returns:
        Dict with:
            - "other_species_1": First wrong-example species (italicised in prompts)
            - "other_species_2": Second wrong-example species (italicised in prompts)
    """
    cache_manager = get_cache_manager(session_id=session_id)
    cache_dir = cache_manager.species_context_dir()
    cache_file = cache_dir / f"{universal_id}_wrong_species.json"

    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    result = _generate_wrong_species(species_name)

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result


def _generate_wrong_species(species_name: str) -> Dict[str, str]:
    """
    Call the LLM to generate two related-but-distinct species names.

    Uses mistral-small (cheap) since the task is simple name generation.
    """
    generator = create_generator("species_context")

    prompt = _PROMPT_TEMPLATE.replace("[SPECIES_NAME]", species_name)

    messages = [ChatMessage.from_user(prompt)]
    result = generator.run(messages=messages)
    raw = result["replies"][0].text
    parsed, _ = recover_json_from_response(raw)

    if "other_species_1" not in parsed or "other_species_2" not in parsed:
        raise ValueError(f"Unexpected response format from species context LLM: {parsed}")

    return {
        "other_species_1": str(parsed["other_species_1"]),
        "other_species_2": str(parsed["other_species_2"]),
    }
