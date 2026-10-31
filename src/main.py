"""
main.py
-------
CLI entry point.

Usage:
    python src/main.py generate-sample-invoices   # creates demo PDFs/images to test with
    python src/main.py process                    # scan inbox, extract, apply rules, export
    python src/main.py list-pending                # show items awaiting human review
    python src/main.py list-vendors                # show vendor intelligence summary
    python src/main.py vendor-profile <vendor>     # show one vendor's profile
    python src/main.py approve <id>                # mark an item as approved
    python src/main.py reject <id>                 # mark an item as rejected
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))

from database import Database  # noqa: E402
from pipeline import process_inbox  # noqa: E402
from sample_invoices import generate_sample_documents  # noqa: E402


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> None:
    log_cfg = config.get("logging", {})
    log_path = Path(log_cfg.get("file", "logs/pipeline.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path)],
    )


def cmd_generate_sample_invoices(config: dict) -> None:
    files = generate_sample_documents(
        config["sample_data"], config["company"]["name"], config["paths"]["inbox_dir"],
    )
    print(f"\n✓ Generated {len(files)} sample document(s) in {config['paths']['inbox_dir']}:")
    for f in files:
        print(f"  - {Path(f).name}")
    print("\nRun 'python src/main.py process' to run them through the pipeline.")


def cmd_process(config: dict) -> None:
    results = process_inbox(config)
    print(f"\n✓ Processed {results['processed']} document(s) "
          f"({results['auto_approved']} auto-approved, {results['flagged']} flagged for review)")
    if results["failed"]:
        print(f"✗ {results['failed']} document(s) failed to read -- moved to data/failed for manual review")
    print(f"✓ Excel log updated: {results['excel_log_path']}")
    print(f"  {results['pending_approval_count']} item(s) currently awaiting approval")
    if results.get("emailed"):
        print("✓ Approval summary emailed.")


def cmd_list_pending(config: dict) -> None:
    db = Database(config["paths"]["database_path"])
    pending = db.fetch_pending_approval()
    if not pending:
        print("Nothing pending -- all clear.")
        return
    print(f"\n{len(pending)} item(s) awaiting review:\n")
    for item in pending:
        print(f"  [{item['id']}] {item['status']}")
        print(f"      Vendor: {item.get('vendor') or '(unknown)'}  "
              f"Amount: ${item.get('total_amount') or 0:,.2f}  "
              f"Date: {item.get('invoice_date') or '(unknown)'}")
        if item.get("flag_reasons"):
            print(f"      Reasons: {item['flag_reasons']}")
        print()


def cmd_list_vendors(config: dict) -> None:
    db = Database(config["paths"]["database_path"])
    profiles = db.fetch_vendor_profiles()
    if not profiles:
        print("No vendor history yet.")
        return
    print(f"\n{len(profiles)} vendor profile(s):\n")
    for profile in profiles:
        signals = f" | Signals: {'; '.join(profile.risk_signals)}" if profile.risk_signals else ""
        print(
            f"  {profile.vendor} | {profile.invoice_count} invoice(s) | "
            f"Spend: ${profile.total_spend:,.2f} | Average: ${profile.average_invoice:,.2f}"
            f"{signals}"
        )


def cmd_vendor_profile(config: dict, vendor: str) -> None:
    db = Database(config["paths"]["database_path"])
    profile = db.fetch_vendor_profile(vendor)
    if profile.invoice_count == 0:
        print(f"No invoice history found for vendor '{vendor}'.")
        sys.exit(1)

    print(f"\nVendor profile: {profile.vendor}\n")
    print(f"  Invoices:                 {profile.invoice_count}")
    print(f"  Total spend:              ${profile.total_spend:,.2f}")
    print(f"  Average invoice:          ${profile.average_invoice:,.2f}")
    print(f"  Median invoice:           ${profile.median_invoice:,.2f}")
    print(f"  Invoice range:            ${profile.minimum_invoice:,.2f} - ${profile.maximum_invoice:,.2f}")
    print(f"  Spend standard deviation: ${profile.spend_standard_deviation:,.2f}")
    print(f"  Auto-approval rate:       {profile.auto_approval_rate:.1f}%")
    print(f"  Reviewed:                 {profile.reviewed_count}")
    print(f"  Rejected:                 {profile.rejected_count}")
    print(f"  Manual reviews:           {profile.manual_review_count}")
    print(f"  Last invoice:             {profile.last_invoice_date or '(unknown)'}")
    print(f"  Days since last invoice:  {profile.days_since_last_invoice if profile.days_since_last_invoice is not None else '(unknown)'}")
    print(f"  Common extraction method: {profile.dominant_extraction_method or '(unknown)'}")
    if profile.risk_signals:
        print("  Risk signals:")
        for signal in profile.risk_signals:
            print(f"    - {signal}")


def cmd_review(config: dict, invoice_id: int, decision: str) -> None:
    db = Database(config["paths"]["database_path"])
    record = db.get_by_id(invoice_id)
    if not record:
        print(f"✗ No invoice found with id {invoice_id}")
        sys.exit(1)
    db.mark_reviewed(invoice_id, decision)
    print(f"✓ Invoice {invoice_id} ({record.get('vendor')}, ${record.get('total_amount'):,.2f}) marked as {decision}.")

    # Re-export so the Excel log reflects the review immediately
    all_records = db.fetch_all()
    from excel_export import export_to_excel
    export_to_excel(all_records, config["paths"]["excel_log_path"])


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Invoice & Expense Processor")
    parser.add_argument("command", choices=[
        "generate-sample-invoices", "process", "list-pending", "list-vendors",
        "vendor-profile", "approve", "reject",
    ])
    parser.add_argument("target", nargs="?", help="Vendor name or invoice ID, depending on command")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config)

    if args.command == "generate-sample-invoices":
        cmd_generate_sample_invoices(config)
    elif args.command == "process":
        cmd_process(config)
    elif args.command == "list-pending":
        cmd_list_pending(config)
    elif args.command == "list-vendors":
        cmd_list_vendors(config)
    elif args.command == "vendor-profile":
        if args.target is None:
            print("Usage: python src/main.py vendor-profile <vendor>")
            sys.exit(1)
        cmd_vendor_profile(config, args.target)
    elif args.command in ("approve", "reject"):
        if args.target is None:
            print(f"Usage: python src/main.py {args.command} <invoice_id>")
            sys.exit(1)
        try:
            invoice_id = int(args.target)
        except ValueError:
            print(f"Invoice ID must be an integer, got '{args.target}'")
            sys.exit(1)
        cmd_review(config, invoice_id, "approved" if args.command == "approve" else "rejected")


if __name__ == "__main__":
    main()
