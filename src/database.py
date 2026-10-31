"""
database.py
------------
SQLite persistence for processed invoice/expense records.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file         TEXT NOT NULL,
    vendor              TEXT,
    invoice_number      TEXT,
    invoice_date        TEXT,
    total_amount        REAL,
    extraction_method   TEXT,
    status              TEXT NOT NULL,        -- Auto-Approved / Needs Approval / Flagged - Duplicate / Flagged - Anomaly / Needs Manual Review
    flag_reasons        TEXT,                 -- human-readable, comma-separated
    raw_text            TEXT,
    processed_at        TEXT NOT NULL,
    reviewed            INTEGER NOT NULL DEFAULT 0,   -- 0 = pending human review, 1 = reviewed
    review_decision     TEXT                   -- "approved" / "rejected", set by a human via CLI
);

CREATE INDEX IF NOT EXISTS idx_invoices_vendor ON invoices (vendor);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices (status);
"""


@dataclass
class InvoiceRecord:
    source_file: str
    vendor: Optional[str]
    invoice_number: Optional[str]
    invoice_date: Optional[str]
    total_amount: Optional[float]
    extraction_method: str
    status: str
    flag_reasons: list[str] = field(default_factory=list)
    raw_text: str = ""
    processed_at: str = ""
    id: Optional[int] = None
    reviewed: bool = False
    review_decision: Optional[str] = None


class Database:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def insert_invoice(self, record: InvoiceRecord) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO invoices
                (source_file, vendor, invoice_number, invoice_date, total_amount,
                 extraction_method, status, flag_reasons, raw_text, processed_at,
                 reviewed, review_decision)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.source_file, record.vendor, record.invoice_number,
                    record.invoice_date, record.total_amount, record.extraction_method,
                    record.status, ", ".join(record.flag_reasons), record.raw_text,
                    record.processed_at, int(record.reviewed), record.review_decision,
                ),
            )
            return cur.lastrowid

    def fetch_vendor_history(self, vendor: str, exclude_id: Optional[int] = None) -> list[dict]:
        query = "SELECT * FROM invoices WHERE vendor = ?"
        params: list = [vendor]
        if exclude_id is not None:
            query += " AND id != ?"
            params.append(exclude_id)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def fetch_vendor_names(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT vendor FROM invoices WHERE vendor IS NOT NULL "
                "GROUP BY vendor ORDER BY vendor COLLATE NOCASE"
            ).fetchall()
        return [row["vendor"] for row in rows]

    def fetch_vendor_profile(self, vendor: str):
        from vendor_intelligence import build_vendor_profile

        return build_vendor_profile(vendor, self.fetch_vendor_history(vendor))

    def fetch_vendor_profiles(self) -> list:
        return [self.fetch_vendor_profile(vendor) for vendor in self.fetch_vendor_names()]

    def fetch_all(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM invoices ORDER BY processed_at DESC").fetchall()
        return [dict(r) for r in rows]

    def fetch_pending_approval(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM invoices WHERE reviewed = 0 AND status != 'Auto-Approved' "
                "ORDER BY processed_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_reviewed(self, invoice_id: int, decision: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE invoices SET reviewed = 1, review_decision = ? WHERE id = ?",
                (decision, invoice_id),
            )
            return cur.rowcount > 0

    def get_by_id(self, invoice_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        return dict(row) if row else None
