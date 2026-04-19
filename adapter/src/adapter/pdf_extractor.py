# SPDX-License-Identifier: MIT
"""In-memory PDF text extraction for the adapter.

Extracts text page-by-page from raw PDF bytes using ``pdfplumber``.
This mirrors the logic in Retriva's ``pdf_parser.py`` but operates on
in-memory bytes (from ``FetchedFile.content``) rather than filesystem paths.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pdfplumber

from adapter.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PdfPage:
    """A single page extracted from a PDF file."""

    page_number: int  # 1-indexed
    text: str


@dataclass(frozen=True, slots=True)
class PdfExtractionResult:
    """Result of extracting text from a PDF."""

    title: str
    pages: list[PdfPage]  # only pages with extractable text
    total_pages: int
    skipped_pages: int


# ---------------------------------------------------------------------------
# Title derivation (mirrors Retriva's heuristic)
# ---------------------------------------------------------------------------

_RE_HEADING = re.compile(r"^[A-Z][A-Za-z0-9 :—\-–/]{5,80}$", re.MULTILINE)


def _derive_title(
    metadata: dict[str, str],
    first_page_text: str,
    filename: str,
) -> str:
    """Derive a human-readable document title with fallback chain.

    1. PDF metadata ``Title`` field (if non-empty and not a generic path)
    2. First heading-like line from page 1 text
    3. Filename stem as fallback
    """
    # 1. PDF metadata title
    meta_title = metadata.get("Title", "").strip()
    if meta_title and not meta_title.startswith("/") and len(meta_title) > 3:
        return meta_title

    # 2. First heading-like line from page 1
    if first_page_text:
        match = _RE_HEADING.search(first_page_text[:500])
        if match:
            return match.group(0).strip()

    # 3. Filename stem
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return stem.replace("_", " ").replace("-", " ").title()


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_pdf(content: bytes, filename: str) -> PdfExtractionResult | None:
    """Extract text page-by-page from raw PDF bytes.

    Returns ``None`` if the PDF is unreadable (encrypted, corrupt, etc.).
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(content))
    except Exception as e:
        logger.warning(f"pdf_open_failed filename={filename} error={e}")
        return None

    pages: list[PdfPage] = []
    total_pages = 0

    try:
        total_pages = len(pdf.pages)

        for i, page in enumerate(pdf.pages):
            try:
                text = page.extract_text() or ""
            except Exception as e:
                logger.debug(
                    f"pdf_page_extract_error filename={filename} "
                    f"page={i + 1} error={e}"
                )
                text = ""

            text = text.strip()
            if text:
                pages.append(PdfPage(page_number=i + 1, text=text))
            else:
                logger.debug(
                    f"pdf_page_empty filename={filename} page={i + 1}"
                )
    finally:
        pdf.close()

    if not pages:
        logger.warning(f"pdf_no_text filename={filename} total_pages={total_pages}")
        return None

    # Derive title from metadata + first page
    metadata: dict[str, str] = {}
    try:
        pdf2 = pdfplumber.open(io.BytesIO(content))
        raw_meta = pdf2.metadata or {}
        metadata = {
            str(k): str(v) for k, v in raw_meta.items() if v is not None
        }
        pdf2.close()
    except Exception:
        pass

    title = _derive_title(metadata, pages[0].text, filename)
    skipped = total_pages - len(pages)

    logger.info(
        f"pdf_extracted filename={filename} title={title} "
        f"pages={len(pages)}/{total_pages} skipped={skipped}"
    )

    return PdfExtractionResult(
        title=title,
        pages=pages,
        total_pages=total_pages,
        skipped_pages=skipped,
    )
