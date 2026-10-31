"""
emailer.py
----------
Sends a summary of pending approvals via email. Credentials come exclusively
from environment variables (.env), never from config.yaml.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


class EmailConfigError(Exception):
    pass


def send_approval_summary(recipients: list[str], subject: str, pending: list[dict],
                           excel_attachment_path: str | None = None) -> None:
    server = os.getenv("SMTP_SERVER")
    port = os.getenv("SMTP_PORT")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")

    missing = [n for n, v in [("SMTP_SERVER", server), ("SMTP_PORT", port),
                               ("SMTP_USERNAME", username), ("SMTP_PASSWORD", password)] if not v]
    if missing:
        raise EmailConfigError(
            f"Missing email credentials in .env: {', '.join(missing)}. "
            f"Copy .env.example to .env and fill in your SMTP details."
        )

    lines = ["The following expenses need your review:\n"]
    for item in pending:
        lines.append(
            f"- [{item['status']}] {item.get('vendor') or 'Unknown vendor'} — "
            f"${item.get('total_amount', 0):,.2f} ({item.get('invoice_number') or 'no #'})"
        )
        for reason in (item.get("flag_reasons") or "").split(", "):
            if reason:
                lines.append(f"    reason: {reason}")
    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = username
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if excel_attachment_path:
        p = Path(excel_attachment_path)
        with open(p, "rb") as f:
            part = MIMEApplication(f.read(), Name=p.name)
        part["Content-Disposition"] = f'attachment; filename="{p.name}"'
        msg.attach(part)

    with smtplib.SMTP(server, int(port)) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.sendmail(username, recipients, msg.as_string())

    logger.info("Approval summary emailed to: %s", recipients)
