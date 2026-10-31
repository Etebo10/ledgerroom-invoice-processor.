# Ledgerroom — Invoice & Expense Processor

A practical invoice operations workspace built with Python, Flask, HTML, CSS and vanilla JavaScript. Upload invoices and receipts, extract key fields, apply approval rules, review exceptions, understand vendor history and export the expense register.

## What it does

- Accepts PDF, JPG, JPEG, PNG, TIFF and BMP documents.
- Extracts text from digitally generated PDFs first; uses Tesseract OCR for scans and photos.
- Parses vendor, invoice number, invoice date and total amount.
- Applies configurable approval threshold, duplicate and vendor anomaly checks.
- Sends uncertain extractions to manual review instead of guessing.
- Stores invoice history in SQLite and exports a colour-coded Excel register.
- Provides a responsive web workspace with overview metrics, invoice search/filtering, approval/rejection actions and vendor intelligence.

## Run locally

Python 3.10+ is recommended.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000.

## Upload documents

Use **Add documents** in the web app. You can select multiple documents at once (25 MB combined limit). Supported types are PDF, JPG, JPEG, PNG, TIFF and BMP. The processor reads the documents, applies the rules, stores the results and refreshes the dashboard.

You can also use the original CLI:

```bash
python src/main.py generate-sample-invoices
python src/main.py process
python src/main.py list-pending
python src/main.py list-vendors
python src/main.py approve 3
python src/main.py reject 3
```

Sample invoices are created in `data/inbox/`. Processed documents move to `data/processed/`; unreadable documents move to `data/failed/`.

## OCR setup

Native-text PDFs do not require OCR. Scanned PDFs and images require the Tesseract application in addition to the Python packages. Install Tesseract and make sure `tesseract` is on your system PATH. For scanned PDFs, Poppler is also required by `pdf2image`.

If Tesseract is installed in a non-standard location, set `ocr.tesseract_cmd` in `config/config.yaml` to its executable path. The default is `null`, which lets the application find Tesseract on PATH.

## Configure approval rules

Edit `config/config.yaml`:

```yaml
company:
  name: "Your Company"
approval:
  auto_approve_under: 3500.00
  currency_symbol: "$"
  duplicate_window_days: 30
  anomaly_zscore_threshold: 2.5
  anomaly_min_history: 3
```

An invoice below the threshold can be auto-approved if extraction is complete and no duplicate/anomaly rule is triggered. Change the currency symbol and threshold to suit your business; this setting changes display and rule explanations, not currency conversion.

## Email notifications

Copy `.env.example` to `.env`, add SMTP credentials and recipient details, then set `email.enabled: true` in `config/config.yaml`. Keep `.env` out of source control.

## Deploy as a Render Web Service

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn app:app`
- **Runtime:** Python

Set a persistent disk or external database/object storage before relying on long-term document retention. Render's default filesystem is ephemeral; SQLite, uploaded documents and generated Excel files stored there may be lost on restart or redeploy. OCR on Render also requires system packages (Tesseract and Poppler), which are not installed by `requirements.txt` alone.

## Important security note

This starter web interface does not include user authentication or role-based access control. Do not expose it publicly with confidential financial documents until authentication, access controls, CSRF protections and durable storage have been added. The upload endpoint processes files on the server and should be restricted to trusted users.

## Project structure

```text
app.py                    # Flask web app and JSON API
templates/index.html      # Web workspace
static/css/styles.css    # Responsive visual system
static/js/app.js         # Frontend interactions
config/config.yaml        # Paths, rules, OCR and email settings
src/                      # Existing Python processing engine
data/                     # Inbox, processed/failed files and SQLite DB
output/                   # Excel expense log
```
