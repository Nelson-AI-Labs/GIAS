#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Cache Cleanup Utility
Provides functions to clear session-isolated cache data.
"""

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any

from core.utils.session_context import get_session_id
from core.utils.cache_manager import get_cache_manager

# Guard: GC thread is started at most once per process lifetime.
_GC_STARTED = False
_GC_LOCK = threading.Lock()


def clear_session_cache(session_id: Optional[str] = None) -> None:
    """
    Clear cache for current session only (multi-user safe).

    This is the recommended way to clear cache in multi-user environments.
    Only removes data for the specified session, leaving other users' data intact.

    The 'default' session (used by CLI scripts and test runners when no
    Streamlit context is present) is never cleared, matching the protection
    already in the GC worker.

    Args:
        session_id: Session ID to clear. If None, uses current session from Streamlit context.

    Example:
        >>> # Clear current user's cache
        >>> clear_session_cache()

        >>> # Clear specific session's cache
        >>> clear_session_cache("abc123def456")
    """
    if session_id is None:
        session_id = get_session_id()

    # Never clear the 'default' session — it is used by CLI scripts and test
    # runners that fall back to this ID when there is no Streamlit context.
    # Wiping it during a normal UI fetch (where Streamlit hasn't yet assigned
    # a real session ID) or during tool testing would destroy test data.
    if session_id == 'default':
        print(f"Skipping cache clear for 'default' session (CLI/test context)")
        return

    # Get session cache base directory using cache_manager
    cache = get_cache_manager(session_id)
    session_dir = cache.cache_base

    if session_dir.exists():
        try:
            shutil.rmtree(session_dir)
            print(f"✓ Cleared cache for session: {session_id}")
        except Exception as e:
            print(f"✗ Error clearing session cache for {session_id}: {e}")
    else:
        print(f"No cache found for session: {session_id}")


def get_session_cache_statistics(session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get statistics about current session's cache contents.

    Args:
        session_id: Session ID to get stats for. If None, uses current session.

    Returns:
        Dictionary with cache statistics
    """
    cache = get_cache_manager(session_id)
    cache_base = cache.cache_base

    stats = {
        'session_id': cache.session_id,
        'cache_base': str(cache_base),
        'raw_files_count': 0,
        'categorized_files_count': 0,
        'extracted_files_count': 0,
        'search_results_count': 0,
        'custom_prompts_count': 0,
        'total_size_bytes': 0,
        'species_cached': []
    }

    if not cache_base.exists():
        return stats

    # Count raw data files
    raw_data_dir = cache_base / 'raw_api_data'
    if raw_data_dir.exists():
        for filepath in raw_data_dir.rglob('*.json'):
            stats['raw_files_count'] += 1
            stats['total_size_bytes'] += filepath.stat().st_size
        # Get species from subdirectories
        for subdir in raw_data_dir.iterdir():
            if subdir.is_dir():
                stats['species_cached'].append(subdir.name)

    # Count categorized files
    categorized_dir = cache_base / 'categorized_data'
    if categorized_dir.exists():
        for filepath in categorized_dir.glob('*_categorized.json'):
            stats['categorized_files_count'] += 1
            stats['total_size_bytes'] += filepath.stat().st_size

    # Count extracted data files
    extracted_dir = cache_base / 'extracted_data'
    if extracted_dir.exists():
        for filepath in extracted_dir.rglob('*_extraction.json'):
            stats['extracted_files_count'] += 1
            stats['total_size_bytes'] += filepath.stat().st_size

    # Count search results
    search_dir = cache_base / 'search_results'
    if search_dir.exists():
        for filepath in search_dir.glob('search_results_*.json'):
            stats['search_results_count'] += 1
            stats['total_size_bytes'] += filepath.stat().st_size

    # Count custom prompts
    prompts_dir = cache_base / 'custom_extraction_prompts'
    if prompts_dir.exists():
        for filepath in prompts_dir.glob('*_prompt.md'):
            stats['custom_prompts_count'] += 1
            stats['total_size_bytes'] += filepath.stat().st_size

    return stats


def _gc_worker(cache_base: Path, ttl_minutes: int, interval_minutes: int) -> None:
    """
    Background daemon that periodically removes stale session folders.

    A session folder is stale when its .last_active file has not been touched
    for longer than ttl_minutes. Folders named 'default' are never expired
    (CLI / test usage). Runs forever as a daemon thread.
    """
    while True:
        time.sleep(interval_minutes * 60)
        try:
            if not cache_base.exists():
                continue
            cutoff = time.time() - ttl_minutes * 60
            for session_dir in cache_base.iterdir():
                if not session_dir.is_dir():
                    continue
                if session_dir.name == 'default':
                    continue  # Never expire CLI/test sessions
                last_active_file = session_dir / '.last_active'
                mtime = (
                    last_active_file.stat().st_mtime
                    if last_active_file.exists()
                    else session_dir.stat().st_mtime
                )
                if mtime < cutoff:
                    try:
                        shutil.rmtree(session_dir)
                        print(f"GC: removed stale session cache {session_dir.name}")
                    except Exception as e:
                        print(f"GC: error removing {session_dir.name}: {e}")
        except Exception as e:
            print(f"GC: scan error: {e}")


def start_session_gc(
    cache_base: Optional[Path] = None,
    ttl_minutes: int = 30,
    interval_minutes: int = 5,
) -> None:
    """
    Start the background GC daemon thread (at most once per process).

    Safe to call on every Streamlit script run — the global guard ensures
    only one thread is ever started. Subsequent calls are no-ops.

    Args:
        cache_base: Root cache directory to scan. Defaults to project-root/cache.
        ttl_minutes: Minutes of inactivity before a session folder is deleted.
        interval_minutes: How often the GC wakes up to scan.
    """
    global _GC_STARTED
    with _GC_LOCK:
        if _GC_STARTED:
            return
        if cache_base is None:
            from core.utils.config_loader import get_project_root
            cache_base = get_project_root() / 'cache'
        t = threading.Thread(
            target=_gc_worker,
            args=(cache_base, ttl_minutes, interval_minutes),
            daemon=True,
            name="session-cache-gc",
        )
        t.start()
        _GC_STARTED = True


def delete_source_cache(
    source_id: str,
    universal_id: str,
    session_id: Optional[str] = None,
) -> None:
    """
    Delete all extracted cache files for a single source.

    Removes every folder under extracted_data/{universal_id}/ whose name
    starts with {source_id}_, and removes the source's entry from
    sources_metadata.json.

    Args:
        source_id: Source identifier, e.g. 'manual_a25230d6'
        universal_id: Universal species ID, e.g. '20260409_151337_procambarus_clarkii'
        session_id: Explicit session ID. If None, reads from current Streamlit context.
    """
    cache = get_cache_manager(session_id)
    extracted_dir = cache.cache_base / 'extracted_data' / universal_id

    if not extracted_dir.exists():
        return

    prefix = source_id + '_'
    for entry in extracted_dir.iterdir():
        if entry.is_dir() and entry.name.startswith(prefix):
            try:
                shutil.rmtree(entry)
                print(f"Deleted cache folder: {entry.name}")
            except Exception as e:
                print(f"Error deleting cache folder {entry.name}: {e}")

    # Remove source entry from sources_metadata.json
    metadata_path = extracted_dir / 'sources_metadata.json'
    if metadata_path.exists():
        try:
            with open(metadata_path, encoding='utf-8') as f:
                store = json.load(f)
            if source_id in store:
                del store[source_id]
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(store, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error updating sources_metadata.json: {e}")


# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    """Test the cache cleanup utilities."""

    print("=== Testing Cache Cleanup Utilities ===\n")

    # Get current session cache statistics
    print("Current session cache statistics:")
    stats = get_session_cache_statistics()
    print(f"  Session ID: {stats['session_id']}")
    print(f"  Cache base: {stats['cache_base']}")
    print(f"  Raw files: {stats['raw_files_count']}")
    print(f"  Categorized files: {stats['categorized_files_count']}")
    print(f"  Extracted files: {stats['extracted_files_count']}")
    print(f"  Search results: {stats['search_results_count']}")
    print(f"  Custom prompts: {stats['custom_prompts_count']}")
    print(f"  Total size: {stats['total_size_bytes']:,} bytes")
    print(f"  Species cached: {stats['species_cached']}")
    print()
