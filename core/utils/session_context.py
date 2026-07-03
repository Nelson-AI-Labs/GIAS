#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Session Context Management for Multi-User Cache Isolation

Provides session-aware cache path resolution for Streamlit applications.
Enables multiple users to access GIAS simultaneously without cache conflicts.

Design:
    - Each user session gets isolated cache directory: cache/{session_id}/
    - Session ID comes from Streamlit's runtime context
    - Falls back to 'default' session for CLI/non-Streamlit usage
    - All cache operations are scoped to current session

Usage:
    from core.utils.session_context import get_session_id, get_session_cache_base

    session_id = get_session_id()  # e.g., "abc123def456"
    cache_base = get_session_cache_base()  # e.g., Path("cache/abc123def456")
"""

from pathlib import Path
from typing import Optional
from core.utils.config_loader import get_project_root


def get_session_id() -> str:
    """
    Get current Streamlit session ID.

    Returns the unique session identifier for the current user's browser session.
    This allows each user to have isolated cache storage.

    Returns:
        str: Unique session ID (e.g., "abc123def456") if in Streamlit context,
             or 'default' if running outside Streamlit (CLI, tests, etc.)

    Examples:
        >>> # In Streamlit app
        >>> get_session_id()
        'abc123def456'

        >>> # In CLI script
        >>> get_session_id()
        'default'
    """
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx(suppress_warning=True)
        if ctx is None or not ctx.session_id:
            # No usable context (background thread, CLI, tests)
            return 'default'

        connection_id = ctx.session_id

        # Prefer a refresh-stable client token over the per-connection session
        # id. ctx.session_id is regenerated on every browser refresh / WebSocket
        # reconnect, so keying caches by it loses all progress on reload. The
        # token is stored in the URL query string, which survives a refresh, and
        # is unique per browser tab — safe as a multi-user cache key.
        #
        # If query params are unavailable for any reason, fall back to the
        # per-connection id: still fully user-isolated (never shared), just not
        # refresh-stable. This guarantees we never collapse users onto a shared
        # cache directory.
        try:
            token = st.session_state.get('_gias_client_token')
            if not token:
                token = st.query_params.get('gias_cid')
                if not token:
                    import uuid
                    token = uuid.uuid4().hex
                    st.query_params['gias_cid'] = token
                st.session_state['_gias_client_token'] = token
            return token
        except Exception:
            return connection_id

    except (ImportError, AttributeError) as e:
        # Streamlit not available or version doesn't support get_script_run_ctx
        return 'default'


def get_session_cache_base(base_cache_dir: Optional[str] = None, create: bool = True) -> Path:
    """
    Get session-specific cache base directory.

    Returns the isolated cache directory for the current session.
    Directory structure: {base_cache_dir}/{session_id}/

    Args:
        base_cache_dir: Optional base cache directory. If None, uses default
                       'cache' directory in project root.
        create: Whether to create the directory if it doesn't exist (default True).
                Pass False when only resolving the path for existence checks.

    Returns:
        Path: Session-specific cache base directory
    """
    # Determine base cache directory
    if base_cache_dir is None:
        # Default: cache/ directory in project root
        base_cache_dir = get_project_root() / 'cache'
    else:
        base_cache_dir = Path(base_cache_dir)

    # Get current session ID
    session_id = get_session_id()

    # Build session-specific cache path
    session_cache = base_cache_dir / session_id

    if create:
        session_cache.mkdir(parents=True, exist_ok=True)

    return session_cache


def get_session_cache_subdirectory(subdirectory: str, base_cache_dir: Optional[str] = None, create: bool = True) -> Path:
    """
    Get a specific subdirectory within the session cache.

    Convenience function for accessing common cache subdirectories like
    'raw_api_data', 'categorized_data', 'extracted_data', 'search_results'.

    Args:
        subdirectory: Name of subdirectory (e.g., 'raw_api_data')
        base_cache_dir: Optional base cache directory
        create: Whether to create the directory if it doesn't exist (default True).
                Pass False when only checking for file existence to avoid creating
                empty 'default' session folders.

    Returns:
        Path: Session-specific subdirectory path (created if doesn't exist and create=True)

    Examples:
        >>> raw_data_dir = get_session_cache_subdirectory('raw_api_data')
        >>> raw_data_dir
        Path('/path/to/project/cache/abc123/raw_api_data')

        >>> categorized_dir = get_session_cache_subdirectory('categorized_data')
        >>> categorized_dir
        Path('/path/to/project/cache/abc123/categorized_data')
    """
    session_cache = get_session_cache_base(base_cache_dir, create=create)
    subdir_path = session_cache / subdirectory
    if create:
        subdir_path.mkdir(parents=True, exist_ok=True)
    return subdir_path


# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    """Test the session context utilities."""

    print("=== Testing Session Context Utilities ===\n")

    # Test 1: Get session ID (should be 'default' outside Streamlit)
    print("Test 1: Getting session ID...")
    session_id = get_session_id()
    print(f"  Session ID: {session_id}")
    if session_id == 'default':
        print("  ✓ Correctly returned 'default' (not in Streamlit context)\n")
    else:
        print(f"  ✓ Running in Streamlit context with session: {session_id}\n")

    # Test 2: Get session cache base
    print("Test 2: Getting session cache base...")
    cache_base = get_session_cache_base()
    print(f"  Cache base: {cache_base}")
    if cache_base.exists():
        print("  ✓ Directory created successfully\n")
    else:
        print("  ✗ Directory not created\n")

    # Test 3: Get session cache subdirectories
    print("Test 3: Getting session cache subdirectories...")
    subdirs = ['raw_api_data', 'categorized_data', 'extracted_data', 'search_results']
    for subdir in subdirs:
        path = get_session_cache_subdirectory(subdir)
        exists = "✓" if path.exists() else "✗"
        print(f"  {exists} {subdir}: {path}")

    print("\n=== Tests Complete ===")
