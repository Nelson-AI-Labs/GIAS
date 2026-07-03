#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Centralized configuration loader for GIAS project.

Resolves secrets.toml from the PROJECT ROOT, not from __file__.
This makes all modules resilient to directory moves and refactoring.

Usage:
    from core.utils.config_loader import get_api_key, get_project_root

    MISTRAL_API_KEY = get_api_key('MISTRAL_API_KEY')
    project_root = get_project_root()
"""

from pathlib import Path
from typing import Optional
from functools import lru_cache


@lru_cache(maxsize=1)
def get_project_root() -> Path:
    """
    Find the GIAS project root directory.

    Strategy 1: Walk up from CWD (works when running via `streamlit run app.py`)
    Strategy 2: Walk up from this file's location (works for direct imports)

    Returns:
        Path to the project root directory

    Raises:
        FileNotFoundError: If project root cannot be determined
    """
    # Strategy 1: Walk up from CWD
    current = Path.cwd()
    for _ in range(10):
        if (current / '.streamlit' / 'secrets.toml').exists():
            return current
        if (current / 'app.py').exists() and (current / 'core').is_dir():
            return current
        current = current.parent

    # Strategy 2: Walk up from this file's location
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / '.streamlit' / 'secrets.toml').exists():
            return current
        if (current / 'app.py').exists() and (current / 'core').is_dir():
            return current
        current = current.parent

    raise FileNotFoundError(
        "Cannot find GIAS project root. "
        "Expected to find .streamlit/secrets.toml or app.py + core/ directory."
    )


@lru_cache(maxsize=1)
def _load_secrets() -> dict:
    """Load secrets, trying Streamlit first, then file fallback."""
    # Tier 1: Try Streamlit secrets (production / running app)
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and len(st.secrets) > 0:
            return dict(st.secrets)
    except (ImportError, Exception):
        pass

    # Tier 2: Load from file (development / CLI / testing)
    import toml
    secrets_path = get_project_root() / '.streamlit' / 'secrets.toml'
    return toml.load(str(secrets_path))


def get_secret(key: str) -> Optional[str]:
    """Get a secret value by key. Returns None if not found."""
    return _load_secrets().get(key)


def get_contact_email() -> str:
    """Return the project contact email used in HTTP User-Agent strings.

    Reads CONTACT_EMAIL from secrets.toml (optional). Falls back to the
    project alias so deployments without the key still send a valid address.
    """
    return get_secret("CONTACT_EMAIL") or "contact@guardias.eu"


def get_api_key(key: str) -> str:
    """
    Get an API key by name, raising if not found.

    Args:
        key: The secret key name (e.g., 'MISTRAL_API_KEY')

    Returns:
        The API key string

    Raises:
        ValueError: If the key is not found in secrets
    """
    value = get_secret(key)
    if not value:
        raise ValueError(f"API key '{key}' not found in .streamlit/secrets.toml")
    return value
