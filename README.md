
# ESS Tender Intelligence

A free Streamlit application for screening Odisha e-paper pages for English tender,
corrigendum and outsourcing notices related to security, manpower, housekeeping and
facility-management services.

## Why the previous app did not work

The previous `app.py` in the repository was effectively collapsed into a small number
of extremely long lines. Python comments then swallowed code that should have appeared
on later lines, producing invalid or incomplete execution. It also depended entirely
on newspaper URL patterns, with no robust upload fallback.

## Features

- Date, newspaper and city/edition selection
- Samaja and Sambad direct-page connectors
- Dharitri listing-page connector
- Parallel download and English OCR
- Two-stage filtering: tender term + service term
- Notice-area crop, full-page preview and visual safety review
- Per-cutout download and ZIP download
- Mobile Web Share button for manually choosing WhatsApp
- PDF/JPG/PNG upload fallback
- No paid API

## Deploy free on Streamlit Community Cloud

1. Open your GitHub repository.
2. Replace its existing files with:
   - `app.py`
   - `requirements.txt`
   - `packages.txt`
3. Commit the changes.
4. In Streamlit Community Cloud, reboot the app.
5. Confirm that the app is public if you want to use it without signing in.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Install Tesseract separately on Windows and ensure it is available on PATH.

## WhatsApp limitation

A web application cannot silently attach and send an image to a private WhatsApp chat
without an approved API or browser automation. The free and safe workflow is:

1. App generates the cutout.
2. On phone, tap **Share image from phone**.
3. Select WhatsApp.
4. Select the chat named **You**.
5. Tap Send.

On desktop, download the cutout and attach it in WhatsApp Web.

## Reliability

Publisher websites may change paths, HTML, access rules or image formats. When an
online connector fails, download the newspaper PDF/page images in your browser and
use the **Upload fallback** tab. Prameya is intentionally handled this way because
interactive tiled viewers are less stable to automate.

Use the tool for internal screening and always verify the original notice.


## v1.1 free-hosting stability fix

- OCR width reduced to lower memory usage
- Default page limit reduced to 10
- Default workers reduced to 2
- Visible error and connection messages added
- Recommended first test: one newspaper, 8 pages, one worker


## v1.2 — Faster OCR and real notice cropping

- Uses one OCR call per page instead of two
- OCR runs on a lightweight preview while exports use the original page
- Spatial keyword clustering replaces full-page OCR-block cropping
- Tender and service keywords must be close to one another
- Exported cutouts are limited to a practical newspaper-ad region
- Whole-word matching reduces false positives
- Default scan: 12 pages and 3 workers

Recommended first test: Samaja, Bhubaneswar, 12 pages, 3 workers.
If Streamlit Community Cloud restarts, reduce workers to 2.
