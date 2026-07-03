#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
PDF to Markdown Converter Component

Converts PDF bytes to markdown-formatted text for AI processing.
Uses pymupdf (fitz) for table-aware extraction and falls back to pypdf for plain text.

Requirements:
    pip install pymupdf pypdf

Note: This is a text extractor. For scanned PDFs (image-only), OCR would be needed.
"""

import io
from typing import Dict, Any, Optional
from haystack import component

try:
    from pypdf import PdfReader
    _PYPDF_AVAILABLE = True
except ImportError:
    _PYPDF_AVAILABLE = False

try:
    import fitz  # pymupdf
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

if not _PYPDF_AVAILABLE and not _FITZ_AVAILABLE:
    raise ImportError(
        "At least one of pypdf or pymupdf is required for PDF processing."
    )


@component
class PDFToMarkdownConverter:
    """
    Haystack component that converts PDF bytes to markdown text.

    This component extracts text from PDF files and structures it in markdown format
    to make it easier for AI models to process and understand the document structure.
    """

    def __init__(self):
        """Initialize the PDF to Markdown converter."""
        pass

    @component.output_types(
        markdown_text=str,
        extraction_status=str,
        error_message=Optional[str],
        page_count=int,
        character_count=int
    )
    def run(
        self,
        pdf_bytes: bytes,
        source_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Convert PDF bytes to markdown text.

        Args:
            pdf_bytes: Binary PDF content (from file upload or download)
            source_metadata: Optional metadata dict with URL, title, domain

        Returns:
            Dict containing:
                - markdown_text: Extracted text formatted as markdown
                - extraction_status: "success" or "failed"
                - error_message: Error description if failed, None otherwise
                - page_count: Number of pages processed
                - character_count: Total characters extracted
        """
        try:
            # Create PDF reader from bytes
            pdf_file = io.BytesIO(pdf_bytes)
            pdf_reader = PdfReader(pdf_file)

            page_count = len(pdf_reader.pages)

            if page_count == 0:
                return {
                    "markdown_text": "",
                    "extraction_status": "failed",
                    "error_message": "PDF contains no pages",
                    "page_count": 0,
                    "character_count": 0
                }

            # Build markdown document
            markdown_parts = []

            # Add title if available from metadata
            if source_metadata and source_metadata.get('title'):
                markdown_parts.append(f"# {source_metadata['title']}\n")
                if source_metadata.get('url'):
                    markdown_parts.append(f"**Source:** {source_metadata['url']}\n")
                markdown_parts.append("\n---\n\n")

            # Extract text from each page.
            # pymupdf preferred over pypdf — better unicode/ligature handling.
            # Table detection intentionally removed: find_tables() misdetects
            # figures as tables, injecting garbage pipe-table markdown that
            # pollutes retrieval with study-specific noise unusable for IAS management.
            if _FITZ_AVAILABLE:
                fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                for page_num in range(len(fitz_doc)):
                    page_text = fitz_doc[page_num].get_text("text")
                    if page_text.strip():
                        markdown_parts.append(f"## Page {page_num + 1}\n\n")
                        markdown_parts.append(f"{self._clean_text(page_text)}\n\n")
                fitz_doc.close()
            else:
                for page_num, page in enumerate(pdf_reader.pages, start=1):
                    page_text = page.extract_text()
                    if page_text.strip():
                        markdown_parts.append(f"## Page {page_num}\n\n")
                        cleaned_text = self._clean_text(page_text)
                        markdown_parts.append(f"{cleaned_text}\n\n")

            # Combine all parts
            markdown_text = "".join(markdown_parts)
            character_count = len(markdown_text)

            # Check if we actually extracted any content
            if character_count < 50:  # Arbitrary minimum
                return {
                    "markdown_text": markdown_text,
                    "extraction_status": "failed",
                    "error_message": "Extracted text is too short - PDF may be image-based or corrupted",
                    "page_count": page_count,
                    "character_count": character_count
                }

            return {
                "markdown_text": markdown_text,
                "extraction_status": "success",
                "error_message": None,
                "page_count": page_count,
                "character_count": character_count
            }

        except Exception as e:
            return {
                "markdown_text": "",
                "extraction_status": "failed",
                "error_message": f"PDF extraction error: {str(e)}",
                "page_count": 0,
                "character_count": 0
            }

    def _clean_text(self, text: str) -> str:
        """
        Clean extracted text to improve readability.

        Args:
            text: Raw extracted text from PDF

        Returns:
            Cleaned text with improved formatting
        """
        import re as _re
        _LINE_NUMBER = _re.compile(r'^\d{1,4}$')

        # Remove excessive whitespace; drop bare PDF line-number artefacts
        lines = text.split('\n')
        cleaned_lines = []

        for line in lines:
            line = line.strip()
            # Drop standalone numeric lines — PDF extractors emit page line numbers
            # (e.g. "486\n487\n") as separate lines that corrupt retrieved passages.
            if line and _LINE_NUMBER.match(line):
                continue
            if line:
                cleaned_lines.append(line)

        # Rejoin with single newlines
        cleaned_text = '\n'.join(cleaned_lines)

        # Replace multiple spaces with single space
        import re
        cleaned_text = re.sub(r' +', ' ', cleaned_text)

        # Try to detect section headers and format them as markdown headers.
        # paragraph_resolver skips any segment starting with '#', so marking
        # headings here prevents them from being indexed as extractable paragraphs.
        formatted_lines = []
        for line in cleaned_text.split('\n'):
            # ALL-CAPS short lines (e.g. "INTRODUCTION", "RESULTS")
            # Exclude lines that start with a digit — these are page footers like
            # "188 F. GHERARDI" that PDF extractors emit at the bottom of each page.
            is_allcaps_header = (
                len(line) < 80
                and line.isupper()
                and len(line.split()) <= 10
                and not re.match(r'^\d', line)
            )
            # Numbered section headings: "4. Conclusions", "2.1 Materials and Methods"
            # Requires a capital letter after the number so "30 degrees..." doesn't match.
            is_numbered_header = (
                bool(re.match(r'^\d+(\.\d+)*\.?\s+[A-Z]', line))
                and len(line.split()) <= 10
                and len(line) < 80
            )
            if is_allcaps_header or is_numbered_header:
                formatted_lines.append(f"\n### {line}\n")
            else:
                formatted_lines.append(line)

        return '\n'.join(formatted_lines)
