"""Bounded, inert text extraction for public Research Desk PDFs."""
from __future__ import annotations

import io
import re
import threading
from dataclasses import dataclass


MAX_PDF_PAGES = 48
MAX_PDF_EXTRACTED_CHARS = 24000
MAX_PDF_PAGE_CHARS = 8000
MAX_PDF_STREAM_OUTPUT_BYTES = 8 * 1024 * 1024
_FILTER_LIMITS = (
    "ZLIB_MAX_OUTPUT_LENGTH",
    "LZW_MAX_OUTPUT_LENGTH",
    "RUN_LENGTH_MAX_OUTPUT_LENGTH",
    "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
    "MAX_DECLARED_STREAM_LENGTH",
    "JBIG2_MAX_OUTPUT_LENGTH",
)
_PARSE_LOCK = threading.RLock()


class PDFResearchError(ValueError):
    """A PDF could not cross the inert public-evidence boundary."""


@dataclass(frozen=True)
class PDFResearchText:
    title: str
    text: str
    page_count: int
    extracted_pages: tuple[int, ...]
    extraction_truncated: bool


def _resolved(value):
    getter = getattr(value, "get_object", None)
    return getter() if callable(getter) else value


def _active_content_present(reader) -> bool:
    root = _resolved(reader.trailer.get("/Root"))
    if not hasattr(root, "get"):
        return False
    if root.get("/OpenAction") is not None or root.get("/AA") is not None:
        return True
    names = _resolved(root.get("/Names"))
    if hasattr(names, "get") and (
            names.get("/JavaScript") is not None
            or names.get("/EmbeddedFiles") is not None):
        return True
    return False


def _clean_page_text(value: str) -> str:
    text = str(value or "").replace("\x00", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    # Keep host page boundaries unique even when untrusted source text tries
    # to resemble one. Navigation recognizes only the bracketed host form.
    text = re.sub(
        r"(?m)^\[PDF page ([1-9][0-9]*) of ([1-9][0-9]*)\]$",
        r"[source text resembling PDF page \1 of \2]", text)
    return text


def extract_pdf_text(raw: bytes) -> PDFResearchText:
    """Extract page-marked text while bounding pages and stream expansion."""
    data = bytes(raw or b"")
    if not data.startswith(b"%PDF-"):
        raise PDFResearchError("research PDF signature is invalid")
    try:
        from pypdf import PdfReader, filters
    except ImportError as exc:
        raise PDFResearchError(
            "public PDF reading needs the pinned pypdf dependency") from exc

    with _PARSE_LOCK:
        prior_limits = {
            name: getattr(filters, name) for name in _FILTER_LIMITS
            if hasattr(filters, name)}
        try:
            for name in prior_limits:
                setattr(filters, name, MAX_PDF_STREAM_OUTPUT_BYTES)
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise PDFResearchError("encrypted research PDFs are not admitted")
            page_count = len(reader.pages)
            if page_count < 1:
                raise PDFResearchError("research PDF contained no pages")
            if page_count > MAX_PDF_PAGES:
                raise PDFResearchError(
                    f"research PDF exceeded the {MAX_PDF_PAGES}-page boundary")
            if _active_content_present(reader):
                raise PDFResearchError(
                    "research PDF contains active or embedded content")

            pieces = []
            extracted_pages = []
            used = 0
            truncated = False
            for number, page in enumerate(reader.pages, 1):
                if page.get("/AA") is not None:
                    raise PDFResearchError(
                        "research PDF page contains an additional action")
                page_text = _clean_page_text(page.extract_text() or "")
                if not page_text:
                    continue
                if len(page_text) > MAX_PDF_PAGE_CHARS:
                    page_text = page_text[:MAX_PDF_PAGE_CHARS].rstrip()
                    truncated = True
                marker = f"[PDF page {number} of {page_count}]\n"
                remaining = MAX_PDF_EXTRACTED_CHARS - used
                if remaining <= len(marker):
                    truncated = True
                    break
                section = marker + page_text[:remaining - len(marker)]
                if len(section) < len(marker) + len(page_text):
                    truncated = True
                pieces.append(section.rstrip())
                extracted_pages.append(number)
                used += len(section) + 2
                if used >= MAX_PDF_EXTRACTED_CHARS:
                    truncated = True
                    break
            if not pieces:
                raise PDFResearchError(
                    "research PDF has no extractable text; OCR is not admitted")
            metadata = reader.metadata
            title = " ".join(str(getattr(
                metadata, "title", "") or "").split())[:300]
            return PDFResearchText(
                title=title,
                text="\n\n".join(pieces)[:MAX_PDF_EXTRACTED_CHARS],
                page_count=page_count,
                extracted_pages=tuple(extracted_pages),
                extraction_truncated=truncated,
            )
        except PDFResearchError:
            raise
        except Exception as exc:
            raise PDFResearchError("research PDF parsing failed closed") from exc
        finally:
            for name, value in prior_limits.items():
                setattr(filters, name, value)
