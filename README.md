# ESS Tender Finder — Final bounded build

A Streamlit application for locating and cropping English tender notices related to security, manpower, housekeeping and facility services.

## Reliability controls

- 12-second page download timeout
- 18-second Tesseract timeout per page
- at most two concurrent OCR jobs
- one OCR pass per page
- no full-page fallback in the results
- tender and service keywords must occur in the same compact newspaper region

## Online support

- Samaja: direct page-image connector
- Sambad: direct page-image connector
- Dharitri and Prameya: Upload fallback because their interactive readers are not dependable on free cloud hosting

## Deploy

Upload all files to the repository root and reboot the Streamlit app. Main file: `app.py`.

## First test

Samaja → Bhubaneswar → 8 pages → 2 workers.
