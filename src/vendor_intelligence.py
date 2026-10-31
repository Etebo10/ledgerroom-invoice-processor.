"""
vendor_intelligence.py
----------------------
Builds explainable vendor profiles from processed invoice history.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class VendorProfile:
    vendor: str
    invoice_count: int
    total_spend: float
    average_invoice: float
    median_invoice: float
    minimum_invoice: float
    maximum_invoice: float
    spend_standard_deviation: float
    reviewed_count: int
    rejected_count: int
    manual_review_count: int
    auto_approval_rate: float
    last_invoice_date: Optional[str]
    days_since_last_invoice: Optional[int]
    dominant_extraction_method: Optional[str]
    risk_signals: list[str]


def build_vendor_profile(vendor: str, records: list[dict], today: Optional[date] = None) -> VendorProfile:
    amounts = [float(record["total_amount"]) for record in records if record.get("total_amount") is not None]
    invoice_count = len(records)
    total_spend = sum(amounts)
    average_invoice = statistics.mean(amounts) if amounts else 0.0
    median_invoice = statistics.median(amounts) if amounts else 0.0
    minimum_invoice = min(amounts) if amounts else 0.0
    maximum_invoice = max(amounts) if amounts else 0.0
    spend_standard_deviation = statistics.pstdev(amounts) if len(amounts) > 1 else 0.0

    reviewed_count = sum(1 for record in records if record.get("reviewed"))
    rejected_count = sum(1 for record in records if record.get("review_decision") == "rejected")
    manual_review_count = sum(
        1 for record in records if "Manual Review" in (record.get("status") or "")
    )
    auto_approved_count = sum(1 for record in records if record.get("status") == "Auto-Approved")

    dated_records = []
    for record in records:
        try:
            dated_records.append((date.fromisoformat(record["invoice_date"]), record["invoice_date"]))
        except (KeyError, TypeError, ValueError):
            continue
    last_invoice_date = max(dated_records)[1] if dated_records else None
    reference_date = today or date.today()
    days_since_last_invoice = (
        (reference_date - max(dated_records)[0]).days if dated_records else None
    )

    methods = [record.get("extraction_method") for record in records if record.get("extraction_method")]
    dominant_extraction_method = max(set(methods), key=methods.count) if methods else None

    risk_signals = []
    if rejected_count:
        risk_signals.append(f"{rejected_count} rejected invoice(s)")
    if manual_review_count:
        risk_signals.append(f"{manual_review_count} incomplete extraction(s)")
    if maximum_invoice >= average_invoice * 2 and invoice_count > 1:
        risk_signals.append("largest invoice is at least 2x the vendor average")
    if dominant_extraction_method == "ocr":
        risk_signals.append("mostly OCR-derived documents")

    return VendorProfile(
        vendor=vendor,
        invoice_count=invoice_count,
        total_spend=total_spend,
        average_invoice=average_invoice,
        median_invoice=median_invoice,
        minimum_invoice=minimum_invoice,
        maximum_invoice=maximum_invoice,
        spend_standard_deviation=spend_standard_deviation,
        reviewed_count=reviewed_count,
        rejected_count=rejected_count,
        manual_review_count=manual_review_count,
        auto_approval_rate=(auto_approved_count / invoice_count * 100) if invoice_count else 0.0,
        last_invoice_date=last_invoice_date,
        days_since_last_invoice=days_since_last_invoice,
        dominant_extraction_method=dominant_extraction_method,
        risk_signals=risk_signals,
    )