"""
field_parser.py
-----------------
Turns raw extracted text (from a PDF or OCR'd image) into structured fields:
vendor name, invoice number, date, and total amount.

This is inherently heuristic -- invoices/receipts have no fixed format --
so every field comes with a confidence flag, and the parser is deliberately
conservative: it's better to leave a field blank (and flag the document for
manual review) than to silently guess wrong on a dollar amount.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# Ordered by specificity -- more explicit labels are tried first so
# "Total Amount Due: $8,400.00" wins over just grabbing the last number seen.
TOTAL_PATTERNS = [
    r"total\s+amount\s+due\s*:?\s*(?:US)?\$?\s*([\d,]+(?:\.\d{2})?)",
    r"amount\s+due\s*:?\s*(?:US)?\$?\s*([\d,]+(?:\.\d{2})?)",
    r"balance\s+due\s*:?\s*(?:US)?\$?\s*([\d,]+(?:\.\d{2})?)",
    r"grand\s+total\s*:?\s*(?:US)?\$?\s*([\d,]+(?:\.\d{2})?)",
    r"^total\s*:?\s*(?:US)?\$?\s*([\d,]+(?:\.\d{2})?)",
    r"\btotal\b\s*:?\s*(?:US)?\$?\s*([\d,]+(?:\.\d{2})?)",
]

INVOICE_NUMBER_PATTERNS = [
    r"invoice\s*(?:number|#|no\.?)\s*:?\s*([A-Za-z0-9\-]+)",
    r"receipt\s*#\s*:?\s*([A-Za-z0-9\-]+)",
    r"^\s*#\s*([A-Za-z0-9\-]+)",
    r"\b(INV-\d{4,})\b",
]

DATE_PATTERNS = [
    (r"(\d{1,2})/(\d{1,2})/(\d{4})", "%m/%d/%Y"),               # 08/17/2026
    (r"([A-Za-z]+ \d{1,2},? \d{4})", "%B %d, %Y"),                # August 17, 2026
    (r"([A-Za-z]{3} \d{1,2},? \d{4})", "%b %d, %Y"),              # Sep 3, 2026
]


@dataclass
class ParsedInvoice:
    vendor: Optional[str]
    invoice_number: Optional[str]
    invoice_date: Optional[str]  # ISO format string, or None
    total_amount: Optional[float]
    raw_text: str
    needs_manual_review: bool
    review_reasons: list[str]


def parse_invoice_text(text: str, known_vendors: list[str] | None = None) -> ParsedInvoice:
    reasons = []

    vendor = _find_vendor(text, known_vendors)
    if vendor is None:
        reasons.append("Could not confidently identify vendor name")

    invoice_number = _find_first_match(text, INVOICE_NUMBER_PATTERNS)
    if invoice_number is None:
        reasons.append("No invoice/receipt number found")

    invoice_date = _find_date(text)
    if invoice_date is None:
        reasons.append("No parseable date found")

    total_amount = _find_total(text)
    if total_amount is None:
        reasons.append("Could not confidently identify a total amount")

    return ParsedInvoice(
        vendor=vendor,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        total_amount=total_amount,
        raw_text=text,
        needs_manual_review=len(reasons) > 0,
        review_reasons=reasons,
    )


def _find_vendor(text: str, known_vendors: list[str] | None) -> Optional[str]:
    # Strategy 1: if we have a list of known vendors (e.g. from procurement
    # records), match against it -- most reliable when available.
    if known_vendors:
        for vendor in known_vendors:
            if vendor.lower() in text.lower():
                return vendor

    # Strategy 2: fall back to "first non-empty line of the document", which
    # is where a vendor name/logo text almost always sits on an invoice.
    for line in text.strip().splitlines():
        cleaned = line.strip()
        if len(cleaned) >= 3 and not cleaned.lower().startswith(("invoice", "receipt", "date")):
            return cleaned
    return None


def _find_first_match(text: str, patterns: list[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def _find_total(text: str) -> Optional[float]:
    for pattern in TOTAL_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            raw = match.group(1).replace(",", "")
            try:
                return float(raw)
            except ValueError:
                continue
    return None


def _find_date(text: str) -> Optional[str]:
    for pattern, fmt in DATE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            if fmt == "%m/%d/%Y" and int(match.group(1)) > 12:
                fmt = "%d/%m/%Y"
            raw = match.group(0) if "/" in match.group(0) else match.group(1)
            try:
                parsed = datetime.strptime(raw.replace(",", ""), fmt.replace(",", ""))
                return parsed.date().isoformat()
            except ValueError:
                continue
    return None
