# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Prompt Loading Utilities

Hierarchical prompt loading for extraction system with fallback support.
Consolidates prompt loading from session cache, topic registry, and context registry.
"""

import os
from pathlib import Path
from typing import Optional, Tuple, Dict

from core.utils.session_context import get_session_cache_subdirectory


def normalize_topic_name(topic: str) -> str:
    """
    Normalize topic name for consistent lookups.

    Args:
        topic: Raw topic name

    Returns:
        Normalized topic name (lowercase, sanitized)
    """
    return topic.lower().replace(' ', '_').replace('&', 'and')


def load_prompt_with_fallback(
    topic_key: str,
    topic_registry: Optional[object] = None,
    context_registry: Optional[object] = None,
    prompts_directory: Optional[str] = None,
    context_prompts_directory: Optional[str] = None,
    cache: Optional[Dict[str, str]] = None
) -> Tuple[str, str]:
    """
    Hierarchical prompt loading with fallback support.

    Loading order:
    1. Memory cache (if provided)
    2. Session cache (for custom topic prompts)
    3. Topic registry + prompts directory (for standard topics)
    4. Context registry + context prompts directory (for context prompts)

    Args:
        topic_key: Research topic string or context key (e.g., "habitat ecology" or "geographic_context")
        topic_registry: Optional StandardTopicRegistry class (for accessing topic mappings)
        context_registry: Optional ContextPromptRegistry class (for accessing context mappings)
        prompts_directory: Optional path to topic prompts directory
        context_prompts_directory: Optional path to context prompts directory
        cache: Optional memory cache dictionary for previously loaded prompts

    Returns:
        Tuple of (prompt_content, source_type)
        where source_type = "memory" | "session_cache" | "topic_registry" | "context_registry"

    Raises:
        ValueError: If no prompt found in any registry
        FileNotFoundError: If prompt file is defined in registry but missing
        IOError: If prompt file cannot be read
    """
    # Normalize topic key
    normalized_key = normalize_topic_name(topic_key)

    # STEP 1: Check memory cache
    if cache is not None and normalized_key in cache:
        return cache[normalized_key], "memory"

    # STEP 2: Check session cache for custom topic prompts
    try:
        custom_prompts_dir = get_session_cache_subdirectory('custom_extraction_prompts', create=False)
        custom_prompt_path = custom_prompts_dir / f"{normalized_key}_prompt.md"

        if custom_prompt_path.exists():
            with open(custom_prompt_path, 'r', encoding='utf-8') as f:
                prompt_content = f.read()

            # Cache it if cache provided
            if cache is not None:
                cache[normalized_key] = prompt_content

            print(f"Loaded custom prompt for '{topic_key}' from session cache")
            return prompt_content, "session_cache"

    except Exception as e:
        # Session cache not available or error reading - continue to predefined prompts
        print(f"Note: Could not load custom prompt from session cache: {e}")

    # STEP 3: Check topic registry (standard topics)
    if topic_registry is not None:
        topic_prompt_mapping = topic_registry.get_prompt_file_mapping()
        prompt_filename = topic_prompt_mapping.get(normalized_key)

        if prompt_filename:
            if prompts_directory is None:
                raise ValueError(
                    f"Topic '{topic_key}' found in registry but no prompts_directory provided"
                )

            prompt_filepath = os.path.join(prompts_directory, prompt_filename)

            if not os.path.exists(prompt_filepath):
                raise FileNotFoundError(
                    f"Extraction prompt file missing: {prompt_filepath}\n"
                    f"Topic '{topic_key}' is defined in StandardTopicRegistry but has no extraction prompt.\n"
                    f"Create the prompt file at: {prompt_filepath}"
                )

            try:
                with open(prompt_filepath, 'r', encoding='utf-8') as f:
                    prompt_content = f.read()

                # Cache it if cache provided
                if cache is not None:
                    cache[normalized_key] = prompt_content

                return prompt_content, "topic_registry"

            except Exception as e:
                raise IOError(f"Failed to read prompt file {prompt_filepath}: {e}")

    # STEP 4: Check context registry
    if context_registry is not None:
        context_prompt_mapping = context_registry.get_prompt_file_mapping()
        context_filename = context_prompt_mapping.get(normalized_key)

        if context_filename:
            if context_prompts_directory is None:
                raise ValueError(
                    f"Context '{topic_key}' found in registry but no context_prompts_directory provided"
                )

            context_filepath = os.path.join(context_prompts_directory, context_filename)

            if not os.path.exists(context_filepath):
                raise FileNotFoundError(
                    f"Context prompt file missing: {context_filepath}\n"
                    f"Context key '{topic_key}' is defined in ContextPromptRegistry but has no prompt.\n"
                    f"Create the prompt file at: {context_filepath}"
                )

            try:
                with open(context_filepath, 'r', encoding='utf-8') as f:
                    prompt_content = f.read()

                # Cache it if cache provided
                if cache is not None:
                    cache[normalized_key] = prompt_content

                print(f"Loaded context prompt for '{topic_key}'")
                return prompt_content, "context_registry"

            except Exception as e:
                raise IOError(f"Failed to read context prompt file {context_filepath}: {e}")

    # No prompt found in any registry
    raise ValueError(
        f"No prompt file defined for '{topic_key}' in any registry. "
        f"This topic needs to be added to StandardTopicRegistry, ContextPromptRegistry, "
        f"or generated as a custom topic via the Custom Topic System."
    )


def load_custom_prompt(topic: str) -> Optional[str]:
    """
    Load custom extraction prompt from session cache.

    This is a convenience function for loading only from session cache.
    For hierarchical loading with fallbacks, use load_prompt_with_fallback().

    Args:
        topic: Topic name (e.g., "invasive potential")

    Returns:
        Prompt content if exists, None otherwise
    """
    try:
        custom_prompts_dir = get_session_cache_subdirectory('custom_extraction_prompts', create=False)
        safe_topic_name = normalize_topic_name(topic)
        prompt_path = custom_prompts_dir / f"{safe_topic_name}_prompt.md"

        if prompt_path.exists():
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    except Exception as e:
        print(f"Error loading custom prompt for '{topic}': {e}")
        return None


def save_custom_prompt(topic: str, prompt_content: str) -> bool:
    """
    Save custom extraction prompt to session cache.

    Args:
        topic: Topic name
        prompt_content: Generated prompt markdown

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        custom_prompts_dir = get_session_cache_subdirectory('custom_extraction_prompts')
        safe_topic_name = normalize_topic_name(topic)
        prompt_path = custom_prompts_dir / f"{safe_topic_name}_prompt.md"

        with open(prompt_path, 'w', encoding='utf-8') as f:
            f.write(prompt_content)

        print(f"✓ Custom prompt saved: {prompt_path}")
        return True

    except Exception as e:
        print(f"Error saving custom prompt for '{topic}': {e}")
        return False


def prompt_exists(topic: str) -> bool:
    """
    Check if custom prompt exists in session cache.

    Args:
        topic: Topic name

    Returns:
        True if prompt file exists, False otherwise
    """
    try:
        custom_prompts_dir = get_session_cache_subdirectory('custom_extraction_prompts', create=False)
        safe_topic_name = normalize_topic_name(topic)
        prompt_path = custom_prompts_dir / f"{safe_topic_name}_prompt.md"
        return prompt_path.exists()
    except Exception:
        return False
