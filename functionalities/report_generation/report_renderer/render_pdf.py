# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
render_pdf.py — GIAS report rendering (Jinja2 → HTML → WeasyPrint → PDF).

Replaces the old Pandoc + XeLaTeX step. `build_report_context()` (in
context_builder.py) shapes the pipeline's cleaned output into the `report`
object; this module renders that object to PDF bytes.

Install: pip install weasyprint jinja2 markdown
WeasyPrint needs Pango/Cairo system libs (already present on Linux desktop;
for other deploys: apt-get install libpango-1.0-0 libpangocairo-1.0-0
libgdk-pixbuf2.0-0 libffi-dev).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "jinja"]),
)


def render_report_pdf(context: dict) -> bytes:
    """Render the report context to PDF bytes (matches the pipeline's
    in-memory pdf_bytes contract — no file is written)."""
    template = _env.get_template("report.html.jinja")
    # `assets` resolves {{ assets }}/guardias-logo.png to the bundled logo.
    html_str = template.render(report=context, assets=str(TEMPLATES_DIR))
    return HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        stylesheets=[str(TEMPLATES_DIR / "report.css")],
    )
