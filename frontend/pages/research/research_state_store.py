# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Disk persistence for the research workspace.

The research workspace (sources, analyses, extractions, custom topics) lives in
st.session_state.research_state, which is otherwise lost on a browser refresh,
a WebSocket reconnect after a transient crash, or a Streamlit server restart —
forcing users to start over. This module serializes that state, plus the few
routing keys needed to land the user back where they were, to the per-session
disk cache so the workspace can be restored on reload.

Design notes:
  - Framework-agnostic core: serialization/deserialization are plain dict + JSON
    + file I/O with no streamlit imports, so a future non-Streamlit UI can reuse
    them. Only the thin save_workspace_snapshot / restore_workspace_snapshot
    wrappers touch st.session_state.
  - Multi-user safe: everything is written under the per-session cache base
    (cache/{token}/), keyed by the refresh-stable client token resolved in
    session_context.get_session_id(). No global state, no cross-session locks.
  - PDF bytes are offloaded to a sidecar directory and referenced by filename,
    keeping the JSON small and serializable. In memory, source['uploaded_pdf']
    stays raw bytes (unchanged contract for every existing consumer); the
    bytes<->disk conversion happens only at the persistence boundary here.

Limitation: on Streamlit Community Cloud the container filesystem is ephemeral.
This restores across refresh / reconnect / in-container crash, but NOT if the
platform recycles or sleeps the container (the disk is wiped with it). Durable
cross-container recovery would require external storage (e.g. S3/GCS).
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from core.utils.session_context import get_session_cache_base

_STATE_FILENAME = "workspace_snapshot.json"
_PDF_SUBDIR = "research_pdfs"

# Session keys (besides research_state) needed to restore the user's location.
_ROUTING_KEYS = (
    "selected_species",
    "standardized_species_name",
    "raw_species_input",
    "universal_id",
    "synonyms_searched",
    "show_dashboard",
    "current_mode",
)

# Per-render / in-flight source keys that must NOT be persisted: regenerable
# byte caches, and background-op status flags whose worker thread does not
# survive a reload (restoring them as 'running' would strand the card).
_TRANSIENT_SOURCE_KEYS = (
    "_pdf_annotated_bytes",
    "_pdf_annotated_key",
    "_pdf_fetch_status",
    "_pdf_fetch_error",
    "_analysis_status",
    "_extraction_status",
)


# ---------------------------------------------------------------------------
# Framework-agnostic core
# ---------------------------------------------------------------------------

def serialize_research_state(research_state: Dict[str, Any], pdf_dir: Path) -> Dict[str, Any]:
    """Return a JSON-serializable copy of research_state, offloading PDF bytes.

    Each source's raw `uploaded_pdf` bytes are written to pdf_dir/<id>.pdf and
    replaced by an `_uploaded_pdf_file` reference; transient keys are dropped.
    The original research_state is not mutated.
    """
    out = dict(research_state)
    sources_out: Dict[str, Any] = {}

    for source_key, source in research_state.get("all_sources", {}).items():
        clean = {k: v for k, v in source.items() if k not in _TRANSIENT_SOURCE_KEYS}

        pdf = source.get("uploaded_pdf")
        if isinstance(pdf, (bytes, bytearray)):
            fname = f"{source.get('id', source_key)}.pdf"
            pdf_path = pdf_dir / fname
            # Content for a given source id is immutable once set — write once.
            if not pdf_path.exists():
                pdf_dir.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(pdf)
            clean["uploaded_pdf"] = None
            clean["_uploaded_pdf_file"] = fname

        sources_out[source_key] = clean

    out["all_sources"] = sources_out
    return out


def deserialize_research_state(data: Dict[str, Any], pdf_dir: Path) -> Dict[str, Any]:
    """Rehydrate a serialized research_state, loading offloaded PDF bytes back
    into memory as raw bytes so every existing consumer sees the same contract."""
    for source in data.get("all_sources", {}).values():
        fname = source.pop("_uploaded_pdf_file", None)
        if fname:
            pdf_path = pdf_dir / fname
            if pdf_path.exists():
                source["uploaded_pdf"] = pdf_path.read_bytes()
    return data


# ---------------------------------------------------------------------------
# Streamlit-facing wrappers
# ---------------------------------------------------------------------------

def save_workspace_snapshot() -> bool:
    """Persist research_state + routing keys for the current session.

    Safe to call on every main-thread rerun; never raises (a failed save must
    not crash the UI). Returns True on success. Must run on the main thread —
    background threads have no Streamlit context and would resolve a different
    session key.
    """
    try:
        import streamlit as st

        base = get_session_cache_base()
        snapshot: Dict[str, Any] = {
            "routing": {k: st.session_state[k] for k in _ROUTING_KEYS if k in st.session_state},
        }

        research_state = st.session_state.get("research_state")
        if research_state is not None:
            snapshot["research_state"] = serialize_research_state(
                research_state, base / _PDF_SUBDIR
            )

        path = base / _STATE_FILENAME
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)  # atomic swap, avoids half-written files on crash
        return True
    except Exception as e:  # noqa: BLE001 — persistence must never break the UI
        print(f"save_workspace_snapshot failed: {e}")
        return False


def restore_workspace_snapshot() -> bool:
    """Repopulate st.session_state from a saved snapshot if one exists and the
    session is fresh. Returns True if a snapshot was restored.

    Idempotent: only restores when research_state / routing keys are absent, so
    it is safe to call at the top of every rerun.
    """
    try:
        import streamlit as st

        # Already populated this session — nothing to restore.
        if st.session_state.get("_gias_snapshot_restored"):
            return False
        if "research_state" in st.session_state or "selected_species" in st.session_state:
            st.session_state["_gias_snapshot_restored"] = True
            return False

        base = get_session_cache_base(create=False)
        path = base / _STATE_FILENAME
        if not path.exists():
            return False

        snapshot = json.loads(path.read_text(encoding="utf-8"))

        for key, value in snapshot.get("routing", {}).items():
            st.session_state[key] = value

        research_state = snapshot.get("research_state")
        if research_state is not None:
            st.session_state["research_state"] = deserialize_research_state(
                research_state, base / _PDF_SUBDIR
            )

        st.session_state["_gias_snapshot_restored"] = True
        return True
    except Exception as e:  # noqa: BLE001
        print(f"restore_workspace_snapshot failed: {e}")
        return False
