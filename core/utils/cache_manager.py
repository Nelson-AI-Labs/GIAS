#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Centralized Cache Manager for Session-Isolated Multi-User Access

This module provides a single point of control for all cache operations.
All cache paths are session-aware by default.

Usage:
    from core.utils.cache_manager import CacheManager

    cache = CacheManager()
    raw_data_dir = cache.raw_api_data_dir()
    categorized_dir = cache.categorized_data_dir()
"""

from pathlib import Path
from typing import Optional
from core.utils.session_context import get_session_id, get_session_cache_base


class CacheManager:
    """
    Centralized cache path manager with session isolation.

    All paths are session-aware by default. This ensures multiple users
    can access GIAS simultaneously without cache conflicts.
    """

    def __init__(self, session_id: Optional[str] = None):
        """
        Initialize cache manager.

        Args:
            session_id: Optional session ID. If None, uses current Streamlit session.
        """
        self._session_id = session_id
        self._cache_base = None

    @property
    def session_id(self) -> str:
        """Get current session ID."""
        if self._session_id is None:
            self._session_id = get_session_id()
        return self._session_id

    @property
    def cache_base(self) -> Path:
        """Get session-specific cache base directory."""
        if self._cache_base is None:
            if self._session_id is not None:
                # Session ID was explicitly provided (e.g. captured on main thread before
                # dispatching to a background worker). Build the path directly so we never
                # call get_session_cache_base() — which would lose the ID by calling
                # get_session_id() from a thread without Streamlit context.
                from core.utils.config_loader import get_project_root
                base = get_project_root() / 'cache'
                session_cache = base / self._session_id
                session_cache.mkdir(parents=True, exist_ok=True)
                self._cache_base = session_cache
            else:
                self._cache_base = get_session_cache_base()
        return self._cache_base

    def raw_api_data_dir(self) -> Path:
        """Get session-specific raw API data directory."""
        path = self.cache_base / 'raw_api_data'
        path.mkdir(parents=True, exist_ok=True)
        return path

    def categorized_data_dir(self) -> Path:
        """Get session-specific categorized data directory."""
        path = self.cache_base / 'categorized_data'
        path.mkdir(parents=True, exist_ok=True)
        return path

    def extracted_data_dir(self) -> Path:
        """Get session-specific extracted data directory."""
        path = self.cache_base / 'extracted_data'
        path.mkdir(parents=True, exist_ok=True)
        return path

    def search_results_dir(self) -> Path:
        """Get session-specific search results directory."""
        path = self.cache_base / 'search_results'
        path.mkdir(parents=True, exist_ok=True)
        return path

    def species_raw_data_dir(self, universal_id: str) -> Path:
        """Get session-specific directory for species raw data."""
        path = self.raw_api_data_dir() / universal_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def species_categorized_dir(self, universal_id: str) -> Path:
        """Get session-specific directory for species categorized data."""
        path = self.categorized_data_dir() / universal_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def species_extracted_dir(self, universal_id: str) -> Path:
        """Get session-specific directory for species extracted data."""
        path = self.extracted_data_dir() / universal_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def species_context_dir(self) -> Path:
        """Get session-specific directory for species context data (contextual species examples used in extraction prompts)."""
        path = self.cache_base / 'species_context'
        path.mkdir(parents=True, exist_ok=True)
        return path

    def clear_session_cache(self):
        """Clear all cache for current session."""
        import shutil
        if self.cache_base.exists():
            try:
                shutil.rmtree(self.cache_base)
                print(f"✓ Cleared cache for session: {self.session_id}")
            except Exception as e:
                print(f"✗ Error clearing cache: {e}")


# Global singleton instance
_cache_manager = None


def get_cache_manager(session_id: Optional[str] = None) -> CacheManager:
    """
    Get the global cache manager instance.

    Args:
        session_id: Optional session ID. If None, uses current session.

    Returns:
        CacheManager instance
    """
    global _cache_manager

    # Always create new instance to ensure fresh session ID
    # (session might change between calls in Streamlit)
    _cache_manager = CacheManager(session_id)
    return _cache_manager


# Convenience functions for direct access
def get_raw_api_data_dir() -> Path:
    """Get session-specific raw API data directory."""
    return get_cache_manager().raw_api_data_dir()


def get_categorized_data_dir() -> Path:
    """Get session-specific categorized data directory."""
    return get_cache_manager().categorized_data_dir()


def get_extracted_data_dir() -> Path:
    """Get session-specific extracted data directory."""
    return get_cache_manager().extracted_data_dir()


def get_search_results_dir() -> Path:
    """Get session-specific search results directory."""
    return get_cache_manager().search_results_dir()


# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    """Test the cache manager."""

    print("=== Testing Cache Manager ===\n")

    cache = get_cache_manager()

    print(f"Session ID: {cache.session_id}")
    print(f"Cache base: {cache.cache_base}")
    print(f"Raw API data: {cache.raw_api_data_dir()}")
    print(f"Categorized data: {cache.categorized_data_dir()}")
    print(f"Extracted data: {cache.extracted_data_dir()}")
    print(f"Search results: {cache.search_results_dir()}")

    print("\n=== Testing species-specific paths ===\n")
    test_id = "2227300_procambarus_clarkii"
    print(f"Species raw data: {cache.species_raw_data_dir(test_id)}")
    print(f"Species categorized: {cache.species_categorized_dir(test_id)}")
    print(f"Species extracted: {cache.species_extracted_dir(test_id)}")

    print("\n=== Tests Complete ===")
