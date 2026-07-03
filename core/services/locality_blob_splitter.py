#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Locality Blob Splitter
======================

Some database connectors hand us a distribution record whose ``locality`` field
is not a single place but a *blob* — the entire range of a species concatenated
into one string. GBIF does this when it surfaces Catalogue of Life / WCVP data,
e.g.::

    "England [I] (England [I], Wales [I], S-Scotland [I]); Ireland [I]; Germany [I]; ..."

Rendered as-is, that becomes one giant, unreadable table cell. This module turns
a blob into clean per-locality records so downstream consumers (the distribution
table, geo-normalisation, categorisation) all work with atomic data.

It is deliberately connector-agnostic: it parses the WGSRPD/TDWG-style grammar
``Region [status] (sub-region [status], ...); Region [status]; ...`` and knows
nothing about taxa. Any connector with a concatenated locality blob can call
:func:`split_locality_blob`.

Granularity choice: only the **top-level** regions become rows (England, Germany,
USA, ...). The parenthetical sub-regions are dropped — they are sub-national
detail that would bloat the table and rarely match the granularity of other
sources. The status tag on each top-level region (``[I]`` introduced,
``[N]`` native) is preserved, recovering establishment information that the blob
otherwise hides.
"""

import re
from typing import Any, Dict, List, Optional

# A bracketed status tag, e.g. "[I]", "[N]", "[?]". The WGSRPD/TDWG convention:
# I = introduced, N = native. Anything else is left unmapped (status stays None).
_TAG_RE = re.compile(r"\[([^\]]+)\]")

# Name + optional trailing status tag, with a possible leading "?" (doubtful
# occurrence marker) stripped. The parenthetical sub-region group is removed
# before this is applied.
_HEAD_RE = re.compile(r"^\??\s*(?P<name>.+?)\s*(?:\[(?P<tag>[^\]]+)\])?\s*$")

_TAG_TO_MEANS = {
    "I": "Introduced",
    "N": "Native",
}


def is_locality_blob(locality: str) -> bool:
    """Return True if ``locality`` looks like a concatenated multi-place blob.

    Heuristic, no taxon logic: a blob carries multi-place structure — either the
    top-level ``; `` separator or the bracketed status grammar. An atomic value
    like "Alabama" or "Argentina Northeast" has neither.
    """
    if not isinstance(locality, str):
        return False
    return "; " in locality or bool(_TAG_RE.search(locality))


def _split_top_level(blob: str) -> List[str]:
    """Split on ';' only at paren depth 0, so sub-region lists stay intact."""
    segments: List[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(blob):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            segments.append(blob[start:i])
            start = i + 1
    segments.append(blob[start:])
    return [s.strip() for s in segments if s.strip()]


def _parse_segment(segment: str) -> Optional[Dict[str, Any]]:
    """Parse one top-level entry into {'locality', 'means', 'status'}.

    The parenthetical sub-region group is discarded; only the head (region name
    plus its own status tag) is kept.
    """
    head = segment.split("(", 1)[0].strip()
    if not head:
        return None

    match = _HEAD_RE.match(head)
    if not match:
        return None

    name = (match.group("name") or "").strip()
    if not name:
        return None

    tag = (match.group("tag") or "").strip().upper()
    return {
        "locality": name,
        "means": _TAG_TO_MEANS.get(tag),
        "status": None,
    }


def parse_locality_blob(locality: str) -> List[Dict[str, Any]]:
    """Parse a blob into a list of atomic {'locality','means','status'} dicts.

    An atomic (non-blob) input echoes back as a single-element list, so callers
    can run every record through this unconditionally. ``means`` is None when no
    status tag was present, so the caller can fall back to the record's own
    establishment value.
    """
    if not is_locality_blob(locality):
        return [{"locality": locality.strip(), "means": None, "status": None}]

    parsed = [p for seg in _split_top_level(locality) if (p := _parse_segment(seg))]

    # Never lose data: if parsing yielded nothing usable, keep the original blob
    # as a single record rather than silently dropping the locality.
    if not parsed:
        return [{"locality": locality.strip(), "means": None, "status": None}]
    return parsed


def split_locality_blob(locality: str, base: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Expand one raw distribution record into atomic records.

    ``base`` is the record minus its ``locality`` (country, countryCode, source,
    establishment fields, ...). Each parsed locality is merged onto a copy of
    ``base``; a status tag recovered from the blob overrides the base
    establishment value, otherwise the base value is kept.

    Returns a list with one record per atomic locality (one element for atomic
    input).
    """
    records: List[Dict[str, Any]] = []
    for parsed in parse_locality_blob(locality or ""):
        record = dict(base)
        record["locality"] = parsed["locality"]
        if parsed.get("means"):
            record["establishment_means"] = parsed["means"]
        if parsed.get("status"):
            record["establishment_status"] = parsed["status"]
        records.append(record)
    return records
