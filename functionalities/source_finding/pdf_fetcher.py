#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
PDF Fetcher Utility
Fetches PDFs from source URLs using Haystack's LinkContentFetcher.

Strategy:
  1. Try pdf_url (direct PDF link from open-access APIs) — fastest path
  2. Fall back to url (the webpage) — LinkContentFetcher may resolve the PDF
     from the page's content-type or follow PDF links

Safe to call from background threads — no Streamlit or session state access.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF"
_PDF_MIME = "application/pdf"


def fetch_pdf_from_url(
    url: str,
    timeout: int = 15,
) -> tuple[Optional[bytes], str, Optional[str]]:
    """
    Attempt to fetch a PDF from a URL using Haystack's LinkContentFetcher.

    Args:
        url:     URL to fetch — either a direct PDF link or a webpage URL.
        timeout: Request timeout in seconds.

    Returns:
        (pdf_bytes, 'done', None)       — valid PDF fetched
        (None, 'blocked', error_msg)    — access denied or non-PDF content
        (None, 'error', error_msg)      — network/unexpected failure
    """
    try:
        from haystack.components.fetchers import LinkContentFetcher
    except ImportError:
        return None, "error", "haystack-ai is not installed."

    try:
        fetcher = LinkContentFetcher(
            raise_on_failure=False,
            timeout=timeout,
        )
        result = fetcher.run(urls=[url])
        streams = result.get("streams", [])
    except Exception as e:
        return None, "error", f"Fetch failed: {e}"

    if not streams:
        return None, "blocked", (
            "No content returned. Site may block automated access or require login."
        )

    stream = streams[0]
    content: bytes = stream.data

    if not content:
        return None, "blocked", "Empty response from server."

    # Check MIME type first (most reliable)
    content_type: str = stream.meta.get("content_type", "") or ""
    if _PDF_MIME in content_type:
        logger.debug("Fetched PDF via content-type from %s (%d bytes)", url, len(content))
        return content, "done", None

    # Fall back to magic bytes check
    if content.startswith(_PDF_MAGIC):
        logger.debug("Fetched PDF via magic bytes from %s (%d bytes)", url, len(content))
        return content, "done", None

    # Got HTML — webpage without a direct PDF
    return None, "blocked", (
        "Source returned a webpage instead of a PDF. "
        "The paper may be behind a paywall or require institutional access. "
        "Upload the PDF manually."
    )


def fetch_pdf_for_source(
    pdf_url: Optional[str],
    url: Optional[str],
    timeout: int = 15,
) -> tuple[Optional[bytes], str, Optional[str]]:
    """
    Try pdf_url first, fall back to url if that fails or is absent.

    Returns same 3-tuple as fetch_pdf_from_url.
    """
    first_result: tuple[Optional[bytes], str, Optional[str]] | None = None

    # Try direct PDF link first
    if pdf_url:
        first_result = fetch_pdf_from_url(pdf_url, timeout=timeout)
        if first_result[1] == "done":
            return first_result
        logger.debug("pdf_url fetch %s for %s, trying page url", first_result[1], pdf_url)

    # Fall back to webpage URL (skip if it's the same as pdf_url — already tried above)
    if url and url != pdf_url:
        return fetch_pdf_from_url(url, timeout=timeout)

    # Both paths exhausted: return the first attempt's failure reason if available
    if first_result is not None:
        return first_result
    return None, "error", "No URL available to fetch PDF from."
