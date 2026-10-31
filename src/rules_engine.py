"""
rules_engine.py
-----------------
Decides what happens to a parsed invoice: auto-approve it, or flag it for
human review and why. Three independent checks run every time, and any
one of them can flag a document -- flags accumulate rather than overwrite,
so a large *and* duplicate invoice shows both reasons.

1. Approval threshold  -- amount >= configured limit needs sign-off.
2. Duplicate detection -- same vendor + same amount within N days is very
   likely a duplicate submission (a common real accidental-double-payment
   scenario).
3. Anomaly detection    -- amount far above that vendor's historical average
   (z-score) gets flagged even if it's under the flat approval threshold,
   since "unusual for THIS vendor" matters as much as "large in absolute
   terms".
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from database import Database
from field_parser import ParsedInvoice

STATUS_AUTO_APPROVED = "Auto-Approved"
STATUS_NEEDS_APPROVAL = "Needs Approval"
STATUS_FLAGGED_DUPLICATE = "Flagged - Possible Duplicate"
STATUS_FLAGGED_ANOMALY = "Flagged - Unusual Amount"
STATUS_NEEDS_MANUAL_REVIEW = "Needs Manual Review - Extraction Incomplete"


@dataclass
class RuleResult:
    status: str
    reasons: list[str]


def evaluate(parsed: ParsedInvoice, db: Database, cfg: dict, exclude_id: Optional[int] = None) -> RuleResult:
    reasons: list[str] = []

    # If extraction itself was incomplete, that overrides everything else --
    # we can't safely apply amount-based rules to data we're not confident in.
    if parsed.needs_manual_review:
        return RuleResult(status=STATUS_NEEDS_MANUAL_REVIEW, reasons=list(parsed.review_reasons))

    vendor = parsed.vendor
    amount = parsed.total_amount
    history = db.fetch_vendor_history(vendor, exclude_id=exclude_id) if vendor else []

    is_duplicate = _check_duplicate(parsed, history, cfg["duplicate_window_days"])
    if is_duplicate:
        reasons.append(
            f"Same vendor and amount (${amount:,.2f}) seen within the last "
            f"{cfg['duplicate_window_days']} days -- possible duplicate submission"
        )

    is_anomaly = _check_anomaly(amount, history, cfg["anomaly_zscore_threshold"], cfg["anomaly_min_history"])
    if is_anomaly:
        reasons.append(
            f"Amount (${amount:,.2f}) is unusually high compared to this vendor's history"
        )

    over_threshold = amount is not None and amount >= cfg["auto_approve_under"]
    if over_threshold:
        reasons.append(
            f"Amount (${amount:,.2f}) is at or above the ${cfg['auto_approve_under']:,.2f} approval threshold"
        )

    if is_duplicate:
        status = STATUS_FLAGGED_DUPLICATE
    elif is_anomaly:
        status = STATUS_FLAGGED_ANOMALY
    elif over_threshold:
        status = STATUS_NEEDS_APPROVAL
    else:
        status = STATUS_AUTO_APPROVED

    return RuleResult(status=status, reasons=reasons)


def _check_duplicate(parsed: ParsedInvoice, history: list[dict], window_days: int) -> bool:
    if parsed.total_amount is None or parsed.invoice_date is None:
        return False
    try:
        this_date = datetime.fromisoformat(parsed.invoice_date)
    except ValueError:
        return False

    for record in history:
        if record.get("total_amount") is None or record.get("invoice_date") is None:
            continue
        if abs(record["total_amount"] - parsed.total_amount) > 0.01:
            continue
        try:
            other_date = datetime.fromisoformat(record["invoice_date"])
        except ValueError:
            continue
        if abs((this_date - other_date).days) <= window_days:
            return True
    return False


def _check_anomaly(amount: Optional[float], history: list[dict], z_threshold: float, min_history: int) -> bool:
    if amount is None:
        return False
    past_amounts = [r["total_amount"] for r in history if r.get("total_amount") is not None]
    if len(past_amounts) < min_history:
        return False  # not enough history to judge what's "normal" for this vendor

    mean = statistics.mean(past_amounts)
    stdev = statistics.pstdev(past_amounts)
    if stdev == 0:
        return amount > mean * 2  # no variance in history -- fall back to a simple 2x-mean check

    z = (amount - mean) / stdev
    return z >= z_threshold
