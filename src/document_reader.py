"""
document_reader.py
--------------------
Extracts raw text from an invoice/receipt file, whether it's a PDF or an
image. For PDFs, tries native text extraction first (fast, perfectly
accurate for digitally-generated PDFs) and only falls back to OCR if no
text layer is found (i.e. a scanned document) -- this mirrors the guidance
in the pdf-reading skill: check for a text layer before reaching for OCR.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

logger = logging.getLogger(__name__)


class DocumentReadError(Exception):
    pass


@dataclass
class ExtractedDocument:
    source_path: str
    text: str
    extraction_method: str  # "pdf_text" or "ocr"


def extract_text(path: str, ocr_dpi: int = 300, ocr_lang: str = "eng",
                 tesseract_cmd: str | None = None) -> ExtractedDocument:
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        return _extract_from_pdf(path, ocr_dpi, ocr_lang, tesseract_cmd)
    elif ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        return _extract_from_image(path, ocr_lang, tesseract_cmd)
    else:
        raise DocumentReadError(f"Unsupported file type '{ext}' for {path}")


def _extract_from_pdf(path: str, ocr_dpi: int, ocr_lang: str,
                      tesseract_cmd: str | None) -> ExtractedDocument:
    # Step 1: try native text extraction (works for digitally-generated PDFs)
    try:
        with pdfplumber.open(path) as pdf:
            text_parts = [page.extract_text() or "" for page in pdf.pages]
        native_text = "\n".join(text_parts).strip()
    except Exception as e:
        logger.warning("Native text extraction failed for %s (%s); falling back to OCR.", path, e)
        native_text = ""

    if len(native_text) > 20:  # a real text layer will have far more than 20 chars
        return ExtractedDocument(source_path=path, text=native_text, extraction_method="pdf_text")

    # Step 2: no usable text layer -> this is a scanned PDF, rasterize + OCR
    logger.info("No text layer found in %s -- treating as scanned, running OCR.", path)
    _configure_tesseract(tesseract_cmd)
    try:
        pages = convert_from_path(path, dpi=ocr_dpi)
    except Exception as e:
        raise DocumentReadError(f"Failed to rasterize PDF {path} for OCR: {e}") from e

    ocr_text_parts = [pytesseract.image_to_string(page, lang=ocr_lang) for page in pages]
    return ExtractedDocument(source_path=path, text="\n".join(ocr_text_parts), extraction_method="ocr")


def _extract_from_image(path: str, ocr_lang: str, tesseract_cmd: str | None) -> ExtractedDocument:
    try:
        img = Image.open(path)
        # Light preprocessing: grayscale improves OCR accuracy on most receipts/scans
        img = img.convert("L")
        _configure_tesseract(tesseract_cmd)
        text = pytesseract.image_to_string(img, lang=ocr_lang)
    except pytesseract.pytesseract.TesseractNotFoundError as e:
        raise DocumentReadError(_tesseract_install_message(tesseract_cmd)) from e
    except Exception as e:
        raise DocumentReadError(f"OCR failed for image {path}: {e}") from e

    return ExtractedDocument(source_path=path, text=text, extraction_method="ocr")


def _configure_tesseract(tesseract_cmd: str | None = None) -> None:
    command = tesseract_cmd or shutil.which("tesseract")
    if not command:
        raise DocumentReadError(_tesseract_install_message(tesseract_cmd))
    if tesseract_cmd and not Path(tesseract_cmd).is_file():
        raise DocumentReadError(
            f"Configured Tesseract executable was not found: {tesseract_cmd}. "
            "Set ocr.tesseract_cmd to the full path to tesseract.exe."
        )
    pytesseract.pytesseract.tesseract_cmd = command


def _tesseract_install_message(tesseract_cmd: str | None) -> str:
    if tesseract_cmd:
        return (
            f"Tesseract could not be started from '{tesseract_cmd}'. "
            "Confirm that ocr.tesseract_cmd points to tesseract.exe."
        )
    return (
        "Tesseract OCR is not installed or is not on PATH. On Windows, install "
        "Tesseract (for example, the UB Mannheim build), then either add its "
        "install folder to PATH or set ocr.tesseract_cmd in config/config.yaml "
        "to the full path of tesseract.exe."
    )
