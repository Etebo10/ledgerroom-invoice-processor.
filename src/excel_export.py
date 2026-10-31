"""
excel_export.py
-----------------
Writes the full invoice log to an Excel file, color-coded by status so a
human scanning the sheet can spot what needs attention without reading
every row.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from rules_engine import (
    STATUS_AUTO_APPROVED, STATUS_FLAGGED_ANOMALY, STATUS_FLAGGED_DUPLICATE,
    STATUS_NEEDS_APPROVAL, STATUS_NEEDS_MANUAL_REVIEW,
)

STATUS_COLORS = {
    STATUS_AUTO_APPROVED: "DCEEE1",             # soft green
    STATUS_NEEDS_APPROVAL: "FCEFD9",            # soft amber
    STATUS_FLAGGED_DUPLICATE: "FBDDDA",         # soft red
    STATUS_FLAGGED_ANOMALY: "FBDDDA",           # soft red
    STATUS_NEEDS_MANUAL_REVIEW: "E6E6EA",       # soft grey
}

HEADER_FILL = "1B2432"
HEADERS = [
    "ID", "Status", "Vendor", "Invoice #", "Invoice Date", "Amount",
    "Extraction Method", "Flag Reasons", "Source File", "Processed At", "Reviewed",
]


def export_to_excel(records: list[dict], out_path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Expense Log"

    for col_idx, header in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="left")

    for row_idx, record in enumerate(records, start=2):
        status = record.get("status", "")
        values = [
            record.get("id"),
            status,
            record.get("vendor") or "(unknown)",
            record.get("invoice_number") or "(unknown)",
            record.get("invoice_date") or "(unknown)",
            record.get("total_amount"),
            record.get("extraction_method"),
            record.get("flag_reasons") or "",
            record.get("source_file"),
            record.get("processed_at"),
            "Yes" if record.get("reviewed") else "No",
        ]
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            fill_color = STATUS_COLORS.get(status)
            if fill_color:
                cell.fill = PatternFill("solid", fgColor=fill_color)
            if HEADERS[col_idx - 1] == "Amount" and value is not None:
                cell.number_format = '"$"#,##0.00'

    # Reasonable column widths so the sheet is readable without manual resizing
    widths = [6, 26, 24, 14, 14, 12, 16, 45, 22, 20, 10]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.freeze_panes = "A2"

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
