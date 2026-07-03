#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Table of Contents Extraction Utility

Extracts document structure (table of contents, section headings) from PDFs
using pypdf's outline metadata. This is a standalone utility separate from
the PDFToMarkdownConverter to maintain single responsibility.

Usage:
    from functionalities.extraction.utils.toc_extractor import extract_toc_from_pdf

    toc_text = extract_toc_from_pdf(pdf_bytes)
    if toc_text:
        print(f"Found TOC with {len(toc_text)} characters")
    else:
        print("No TOC found in PDF")
"""

import io
import logging
from typing import Optional, List, Any
from pypdf import PdfReader

logger = logging.getLogger(__name__)


def extract_toc_from_pdf(pdf_bytes: bytes) -> Optional[str]:
    """
    Extract table of contents from PDF using outline metadata.

    This function attempts to extract the document's TOC from the PDF's
    embedded outline/bookmarks structure. Many academic papers and
    well-structured documents include this metadata.

    Args:
        pdf_bytes: Binary PDF content

    Returns:
        Formatted TOC string with hierarchical structure, or None if no TOC exists

    Example output:
        ```
        1. Introduction
        2. Materials and Methods
           2.1 Study Area
           2.2 Sample Collection
        3. Results
           3.1 Morphological Characteristics
           3.2 Behavioral Observations
        4. Discussion
        5. Conclusions
        ```
    """
    try:
        pdf_file = io.BytesIO(pdf_bytes)
        pdf_reader = PdfReader(pdf_file)

        outline = pdf_reader.outline

        if outline is None:
            return None

        if hasattr(outline, '__len__') and len(outline) == 0:
            return None

        toc_lines = []
        _format_outline_items(outline, toc_lines, level=0)

        if not toc_lines:
            return None

        return "\n".join(toc_lines)

    except Exception as e:
        logger.warning("Failed to extract TOC from PDF: %s", e)
        return None


def _format_outline_items(
    items: List[Any],
    toc_lines: List[str],
    level: int = 0,
    parent_number: str = ""
) -> None:
    """
    Recursively format outline items with proper indentation and numbering.

    Args:
        items: List of outline items (can be nested)
        toc_lines: Output list to append formatted lines to
        level: Current nesting level (0 = top level)
        parent_number: Number prefix from parent level (e.g., "2.1")
    """
    counter = 1

    for item in items:
        # pypdf outline items can be Destination objects or nested lists
        if hasattr(item, 'title'):
            title = item.title

            if parent_number:
                number = f"{parent_number}.{counter}"
            else:
                number = str(counter)

            indent = "   " * level  # 3 spaces per level
            line = f"{indent}{number}. {title}"
            toc_lines.append(line)

            counter += 1

        elif isinstance(item, list):
            _format_outline_items(
                item,
                toc_lines,
                level=level + 1,
                parent_number=parent_number if parent_number else str(counter - 1)
            )


def extract_abstract_and_keywords(markdown_text: str) -> Optional[str]:
    """
    Extract abstract and keywords sections from markdown text.

    Academic papers almost always contain an abstract and keywords,
    even when they lack formal TOC structure. These provide strong
    signals for topic relevance analysis.

    Args:
        markdown_text: Markdown-formatted text from PDF

    Returns:
        Formatted string with abstract and/or keywords, or None if neither found
    """
    import re

    parts = []

    # --- Extract Abstract ---
    abstract_patterns = [
        r'(?:^|\n)#{1,3}\s*(?:ABSTRACT|Abstract)\s*\n+(.*?)(?=\n#{1,3}\s|\n(?:Keywords|KEYWORDS|Key\s*words|KEY\s*WORDS))',
        r'(?:^|\n)(?:ABSTRACT|Abstract)\s*\n+(.*?)(?=\n#{1,3}\s|\n(?:Keywords|KEYWORDS|Key\s*words|KEY\s*WORDS|INTRODUCTION|Introduction|\d+\.\s))',
        r'(?:^|\n)(?:ABSTRACT|Abstract)[:\.\s—–-]\s*(.*?)(?=\n#{1,3}\s|\n(?:Keywords|KEYWORDS|Key\s*words|KEY\s*WORDS|INTRODUCTION|Introduction|\d+\.\s))',
    ]

    abstract_text = None
    for pattern in abstract_patterns:
        match = re.search(pattern, markdown_text, re.DOTALL | re.MULTILINE)
        if match:
            abstract_text = match.group(1).strip()
            if len(abstract_text) > 50 and len(abstract_text) < 5000:
                break
            abstract_text = None

    if abstract_text:
        abstract_text = re.sub(r'\s+', ' ', abstract_text).strip()
        if len(abstract_text) > 2000:
            abstract_text = abstract_text[:2000] + "..."
        parts.append(f"ABSTRACT:\n{abstract_text}")

    # --- Extract Keywords ---
    keyword_patterns = [
        r'(?:^|\n)\s*(?:Keywords|KEYWORDS|Key\s*words|KEY\s*WORDS)[:\s—–-]\s*(.+?)(?=\n#{1,3}\s|\n\n|\n(?:INTRODUCTION|Introduction|\d+\.\s))',
        r'(?:^|\n)#{1,3}\s*(?:Keywords|Key\s*words)\s*\n+(.+?)(?=\n#{1,3}\s|\n\n)',
    ]

    keywords_text = None
    for pattern in keyword_patterns:
        match = re.search(pattern, markdown_text, re.DOTALL | re.MULTILINE)
        if match:
            keywords_text = match.group(1).strip()
            if len(keywords_text) > 10 and len(keywords_text) < 1000:
                break
            keywords_text = None

    if keywords_text:
        keywords_text = re.sub(r'\s+', ' ', keywords_text).strip()
        parts.append(f"KEYWORDS:\n{keywords_text}")

    if not parts:
        return None

    return "\n\n".join(parts)


def extract_section_headings_from_text(markdown_text: str, max_headings: int = 50) -> Optional[str]:
    """
    Fallback: Extract section headings from markdown text when no TOC metadata exists.

    This is a simple pattern-based approach that looks for markdown headings.
    Not as reliable as TOC metadata, but better than nothing.

    Args:
        markdown_text: Markdown-formatted text from PDF
        max_headings: Maximum number of headings to extract (prevents overwhelming output)

    Returns:
        Formatted list of section headings, or None if none found
    """
    import re

    try:
        heading_pattern = r'^(##|###)\s+(.+)$'

        headings = []
        for line in markdown_text.split('\n'):
            match = re.match(heading_pattern, line.strip())
            if match:
                level = len(match.group(1)) - 1  # ## = level 1, ### = level 2
                heading_text = match.group(2).strip()

                if heading_text.lower().startswith('page '):
                    continue

                indent = "   " * (level - 1)
                headings.append(f"{indent}{heading_text}")

                if len(headings) >= max_headings:
                    break

        if not headings:
            return None

        return "\n".join(headings)

    except Exception as e:
        logger.warning("Failed to extract headings from text: %s", e)
        return None


def get_document_structure(pdf_bytes: bytes, markdown_text: Optional[str] = None) -> Optional[str]:
    """
    Comprehensive function to get document structure using all available methods.

    Combines multiple signals for the best topic analysis:
    1. PDF outline metadata (TOC structure)
    2. Markdown heading extraction (section names)
    3. Abstract and keywords (content signals)

    All found signals are combined into a single output. This means even if
    a PDF has a TOC, we still extract abstract/keywords to give the AI
    richer context for topic scoring.

    Args:
        pdf_bytes: Binary PDF content
        markdown_text: Optional pre-converted markdown text (if available)

    Returns:
        Document structure as formatted text, or None if all extraction fails
    """
    sections = []

    # 1. Try PDF outline (TOC metadata)
    toc = extract_toc_from_pdf(pdf_bytes)
    if toc:
        sections.append(f"TABLE OF CONTENTS:\n{toc}")

    # 2. Ensure we have markdown for abstract/keywords/headings extraction
    if not markdown_text:
        try:
            from functionalities.extraction.converters.pdf_to_markdown import PDFToMarkdownConverter

            converter = PDFToMarkdownConverter()
            result = converter.run(pdf_bytes=pdf_bytes)

            if result.get('extraction_status') == 'success':
                markdown_text = result.get('markdown_text', '')

        except Exception as e:
            logger.warning("Failed to convert PDF to markdown: %s", e)

    # 3. Extract abstract and keywords from markdown
    if markdown_text:
        abstract_keywords = extract_abstract_and_keywords(markdown_text)
        if abstract_keywords:
            sections.append(abstract_keywords)

        # 4. Extract headings (only if no TOC found, to avoid redundancy)
        if not toc:
            headings = extract_section_headings_from_text(markdown_text)
            if headings:
                sections.append(f"SECTION HEADINGS:\n{headings}")

    if not sections:
        return None

    return "\n\n---\n\n".join(sections)
