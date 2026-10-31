"""
sample_invoices.py
-------------------
Generates realistic-looking invoice PDFs and receipt images so the OCR
pipeline can be tested end-to-end without needing real company documents.

Importantly, these are rendered as actual PDF/image documents (not raw text)
-- the pipeline has to genuinely read them via text-extraction or OCR, the
same as it would with a real scanned invoice. A few intentional duplicates
and one oversized outlier are seeded in so the rules engine (duplicate /
anomaly / approval-threshold detection) has something real to catch.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

ITEMS_BY_VENDOR = {
    "Acme Office Supplies": ["Printer Paper (10 reams)", "Ink Cartridges", "Desk Organizers", "Sticky Notes Bulk Pack"],
    "Blue Ridge Logistics": ["Freight — Regional Route", "Warehouse Storage Fee", "Expedited Shipping"],
    "Northstar Consulting": ["Strategy Workshop — 1 Day", "Q3 Advisory Retainer", "Market Analysis Report"],
    "Metro Print & Design": ["Business Card Printing", "Trade Show Banner", "Brochure Design & Print"],
    "Skyline Software Inc.": ["Annual License Renewal", "Additional User Seats", "Priority Support Add-on"],
}


def _random_invoice_number(rng: random.Random) -> str:
    return f"INV-{rng.randint(10000, 99999)}"


def _draw_invoice_pdf(path: Path, vendor: str, invoice_number: str, invoice_date: date,
                       items: list[tuple[str, float]], total: float, company_name: str) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.75 * inch, height - 1 * inch, vendor)
    c.setFont("Helvetica", 10)
    c.drawString(0.75 * inch, height - 1.25 * inch, "123 Commerce St, Suite 200")

    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.75 * inch, height - 1.8 * inch, "INVOICE")

    c.setFont("Helvetica", 10)
    c.drawString(0.75 * inch, height - 2.05 * inch, f"Invoice Number: {invoice_number}")
    c.drawString(0.75 * inch, height - 2.25 * inch, f"Invoice Date: {invoice_date.strftime('%B %d, %Y')}")
    c.drawString(0.75 * inch, height - 2.45 * inch, f"Bill To: {company_name}")

    y = height - 3.0 * inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y, "Description")
    c.drawString(5.5 * inch, y, "Amount")
    c.line(0.75 * inch, y - 0.08 * inch, 7.75 * inch, y - 0.08 * inch)

    c.setFont("Helvetica", 10)
    y -= 0.3 * inch
    for desc, amount in items:
        c.drawString(0.75 * inch, y, desc)
        c.drawRightString(7.5 * inch, y, f"${amount:,.2f}")
        y -= 0.25 * inch

    y -= 0.15 * inch
    c.line(5.0 * inch, y, 7.75 * inch, y)
    y -= 0.25 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(5.0 * inch, y, "Total Amount Due:")
    c.drawRightString(7.5 * inch, y, f"${total:,.2f}")

    y -= 0.5 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.75 * inch, y, "Payment due within 30 days. Thank you for your business.")

    c.save()


def _draw_receipt_image(path: Path, vendor: str, invoice_number: str, invoice_date: date,
                         items: list[tuple[str, float]], total: float) -> None:
    width, height = 500, 700
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_reg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except OSError:
        font_bold = font_reg = font_small = ImageFont.load_default()

    y = 30
    draw.text((30, y), vendor, font=font_bold, fill="black")
    y += 35
    draw.text((30, y), f"Receipt #: {invoice_number}", font=font_small, fill="black")
    y += 20
    draw.text((30, y), f"Date: {invoice_date.strftime('%m/%d/%Y')}", font=font_small, fill="black")
    y += 30
    draw.line((30, y, 470, y), fill="black", width=1)
    y += 15

    for desc, amount in items:
        draw.text((30, y), desc, font=font_reg, fill="black")
        draw.text((380, y), f"${amount:,.2f}", font=font_reg, fill="black")
        y += 25

    y += 10
    draw.line((30, y, 470, y), fill="black", width=1)
    y += 15
    draw.text((30, y), "TOTAL:", font=font_bold, fill="black")
    draw.text((380, y), f"${total:,.2f}", font=font_bold, fill="black")
    y += 40
    draw.text((30, y), "Thank you for your purchase!", font=font_small, fill="black")

    img.save(path)


def generate_sample_documents(cfg: dict, company_name: str, out_dir: str) -> list[str]:
    n = cfg.get("num_invoices", 12)
    vendors = cfg.get("vendors", list(ITEMS_BY_VENDOR.keys()))
    rng = random.Random(cfg.get("seed"))

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    written = []
    generated_invoices = []  # (vendor, invoice_number, date, items, total) -- used to seed a duplicate

    for i in range(n):
        vendor = rng.choice(vendors)
        item_pool = ITEMS_BY_VENDOR.get(vendor, ["Miscellaneous Service"])
        num_items = rng.randint(1, 3)
        items = []
        for desc in rng.sample(item_pool, min(num_items, len(item_pool))):
            amount = round(rng.uniform(40, 450), 2)
            items.append((desc, amount))

        total = round(sum(a for _, a in items), 2)

        # Seed one intentional anomaly: a single huge invoice from the first vendor
        if i == n - 1:
            vendor = vendors[0]
            items = [("Emergency Bulk Restock — Full Warehouse Order", 8400.00)]
            total = 8400.00

        invoice_number = _random_invoice_number(rng)
        invoice_date = date.today() - timedelta(days=rng.randint(0, 25))

        generated_invoices.append((vendor, invoice_number, invoice_date, items, total))

        if i % 2 == 0:
            path = out_path / f"invoice_{i:02d}.pdf"
            _draw_invoice_pdf(path, vendor, invoice_number, invoice_date, items, total, company_name)
        else:
            path = out_path / f"receipt_{i:02d}.png"
            _draw_receipt_image(path, vendor, invoice_number, invoice_date, items, total)
        written.append(str(path))

    # Seed one intentional duplicate: re-render an earlier invoice as a new file
    if generated_invoices:
        dup_vendor, dup_num, dup_date, dup_items, dup_total = generated_invoices[0]
        dup_path = out_path / "invoice_duplicate.pdf"
        _draw_invoice_pdf(dup_path, dup_vendor, dup_num, dup_date, dup_items, dup_total, company_name)
        written.append(str(dup_path))

    return written
