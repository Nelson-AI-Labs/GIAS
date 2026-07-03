# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
PhyloPic silhouette fetch
=========================

Resolves a scientific name to a public silhouette image from PhyloPic
(https://www.phylopic.org) for the report cover's field-guide plate.

Best-effort: any failure (no match, network error, API change) returns None so
the report template falls back to the plate placeholder. Results are cached on
disk by name — a PNG plus a small JSON sidecar holding attribution/license — so
repeated runs for the same species don't re-hit the API.

PNG rasters are preferred over the vector SVG because WeasyPrint renders raster
images more reliably than arbitrary SVG paths.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

_API = "https://api.phylopic.org"
_TIMEOUT = 15
_DEFAULT_CACHE = Path(__file__).resolve().parent / ".cache" / "phylopic"


def _area(sizes: str) -> int:
    """'288x536' -> 154368; 0 on anything unparseable."""
    try:
        w, h = sizes.lower().split("x")
        return int(w) * int(h)
    except (ValueError, AttributeError):
        return 0


def _query_images(name: str, build: int) -> Optional[dict]:
    """Return the first embedded image item for a name filter, or None."""
    resp = requests.get(
        f"{_API}/images",
        params={"build": build, "filter_name": name.lower(),
                "page": 0, "embed_items": "true"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    items = resp.json().get("_embedded", {}).get("items", [])
    return items[0] if items else None


def fetch_silhouette(
    scientific_name: str,
    cache_dir: Path | str | None = None,
) -> Optional[Dict[str, str]]:
    """Resolve `scientific_name` to a cached silhouette PNG.

    Returns {"path": <abs png path>, "attribution": str, "license": str} on
    success, or None if no silhouette could be obtained. Falls back to the
    genus (first word) when the full binomial has no match.
    """
    if not scientific_name or not scientific_name.strip():
        return None

    cache = Path(cache_dir) if cache_dir else _DEFAULT_CACHE
    cache.mkdir(parents=True, exist_ok=True)
    safe = scientific_name.strip().lower().replace(" ", "_")
    png_path = cache / f"{safe}.png"
    meta_path = cache / f"{safe}.json"

    # Cache hit
    if png_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        return {"path": str(png_path), **meta}

    try:
        build = requests.get(f"{_API}/", timeout=_TIMEOUT).json().get("build")
        if not build:
            return None

        # Try the full name, then the genus.
        candidates = [scientific_name]
        genus = scientific_name.strip().split()[0]
        if genus.lower() != scientific_name.strip().lower():
            candidates.append(genus)

        item = None
        for cand in candidates:
            item = _query_images(cand, build)
            if item:
                break
        if not item:
            return None

        rasters = item.get("_links", {}).get("rasterFiles") or []
        if not rasters:
            return None
        best = max(rasters, key=lambda rf: _area(rf.get("sizes", "0x0")))

        img = requests.get(best["href"], timeout=_TIMEOUT)
        img.raise_for_status()
        png_path.write_bytes(img.content)

        self_href = (item.get("_links", {}).get("self") or {}).get("href", "")
        # API href is api.phylopic.org/images/<uuid>; web page is phylopic.org/images/<uuid>
        page_url = self_href.replace("api.phylopic.org", "www.phylopic.org") if self_href else ""
        meta = {
            "attribution": item.get("attribution") or "",
            "license": (item.get("_links", {}).get("license") or {}).get("href", ""),
            "page_url": page_url,
        }
        meta_path.write_text(json.dumps(meta))
        return {"path": str(png_path), **meta}

    except Exception as e:
        logger.warning("PhyloPic fetch failed for %r: %s", scientific_name, e)
        return None
