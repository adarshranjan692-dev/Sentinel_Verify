# AI-Based Fake Identity & Document Screening System

A Flask, SQLite and Bootstrap 5 decision-support application for authorized security personnel. It combines real OCR/OpenCV evidence with deterministic risk scoring and an optional, governed Logistic Regression screening signal. ML never replaces deterministic evidence or human verification.

## Run with Docker

Prerequisites: Docker Desktop and Git. Python, Tesseract, Poppler, NumPy, OpenCV, scikit-learn, and pip are installed inside the image.

```powershell
git clone https://github.com/adarshranjan692-dev/Sentinel_Verify.git
cd Sentinel_Verify
docker compose up --build
```

Open http://localhost:5000. Docker installs Linux Tesseract and Poppler automatically, publishes Flask on `0.0.0.0:5000`, and persists `screening.db`, `uploads/`, and `models/` through the project-directory mounts. The container health check uses `/diagnostics`.

Useful commands:

```powershell
docker compose up -d
docker compose ps
docker compose logs -f
docker compose down
```

`docker compose down` stops and removes the container but does not delete the persisted database, uploads, or model artifacts. Do not use volume-removal commands for the normal demo workflow.

For custom secrets, copy `.env.example` to `.env` and set `SENTINEL_SECRET_KEY`. Docker supplies Linux defaults for `TESSERACT_CMD=/usr/bin/tesseract` and `POPPLER_PATH=/usr/bin`; these must not be replaced with Windows paths.

## Installation and environment

```powershell
cd "C:\Users\acer\Desktop\HTML Tutorial\Ai fake documents verification"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. Demo login: `demo@screening.local` / `demo123`. Governance demo accounts are `reviewer@trustid.local` / `reviewer123` and `admin@trustid.local` / `admin123`. Set `SENTINEL_SECRET_KEY` in the environment before deployment; the fallback key is for local development only.

Pinned Python dependencies include Flask, NumPy, OpenCV, Pillow, pytesseract, pdf2image, scikit-learn, joblib, and requests. Verify them with `python -m pip check`.

## Tesseract and Poppler

Tesseract is required for real image OCR. This machine uses `C:\Program Files\Tesseract-OCR\tesseract.exe`. To configure another installation, set `TESSERACT_CMD` to the executable path before starting Flask.

Poppler is required for PDF OCR through `pdf2image`. It was installed on Windows with:

```powershell
winget install --id oschwartz10612.Poppler --exact --accept-package-agreements --accept-source-agreements
```

Open a new PowerShell after installation so the PATH change is visible. The application also accepts `POPPLER_PATH`, which must point to the Poppler `Library\\bin` directory containing `pdftoppm.exe`. For the winget package on this machine:

```powershell
$env:POPPLER_PATH = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe\poppler-25.07.0\Library\bin"
```

Check runtime availability without authenticating:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/diagnostics
```

The response reports `ocr`, `tesseract`, and `pdf_ocr` as `AVAILABLE` or `UNAVAILABLE`. The application never marks PDF OCR available merely because `pdf2image` is installed.

## Configuration and database

Supported environment variables are `SENTINEL_SECRET_KEY`, `TESSERACT_CMD`, and `POPPLER_PATH`. SQLite tables are created additively on startup in `screening.db`; existing screening data is not reset. Uploaded files are stored under `uploads/`, and trained artifacts are stored under `models/`.

## Project structure

- `app.py` - Flask app, SQLite schema, screening pipeline and API routes
- `trustid.py` - structured evidence, feature builder, human review, dataset versioning and governed ML lifecycle
- `models/` - persisted Logistic Regression artifacts created after admin activation
- `Frontend/index.html` - responsive single-page dashboard application
- `Frontend/app.css` - security-tech visual system and responsive layout
- `Frontend/app.js` - navigation, upload flow, charts, filters and API integration
- `screening.db` - created automatically on first run
- `uploads/` - private server-side storage for validated uploads, created automatically

## API

Existing screening APIs remain available: `POST /login`, `POST /upload`, `POST /ocr`, `POST /validate`, `POST /tampering`, `POST /face-verify`, `POST /risk-score`, `GET /screening-history`, `GET /screening/<id>`, and `GET /dashboard-stats`.

TrustID governance APIs: `GET /diagnostics`, `GET /reviews`, `POST /review`, admin-only `GET /references`, `POST /references`, `PUT /references/<id>`, `GET /datasets`, `POST /datasets`, `POST /datasets/<version>/publish`, `GET /models`, `POST /models/train`, `POST /models/<version>/approve`, `POST /models/<version>/activate`, `POST /models/<version>/archive`, and `GET /audit`.

## Demonstration workflow

1. Login and upload the OCR fixture or another supported image/PDF.
2. Review the result dashboard: classification, OCR, fields, validation, MRZ state, image analysis, face state, Trusted Reference state, deterministic risk, ML state, human-review state, and model/dataset lineage.
3. Use the Reviewer account to assign labels to cases. Only explicitly reviewed labels enter training data.
4. Use the Admin account to create a dataset, publish it, train a model, inspect actual metrics, approve it, and activate it.
5. Screen a new case. Its result records the active model and dataset versions and displays actual probability and coefficient-based feature influences.
6. Use the governance audit history to show screening, review, dataset, training, approval, activation, and reference transitions.

The trainer requires at least four trusted samples in each of `GENUINE`, `SUSPICIOUS`, and `FRAUDULENT`. It does not generate labels or fabricate metrics. `UNCERTAIN` samples remain excluded from training.

## Limitations

The Trusted Reference store is project-owned and is not a government database. MRZ support currently covers the two-line TD3 passport format; unsupported layouts are reported as unavailable/unsupported rather than accepted. Face matching and OpenCV image analysis are advisory prototype signals, not biometric-grade identity verification or forensic certification. `CLEAR` means no elevated signal in this screening pipeline, not certified authenticity.

## Governed ML workflow

1. Screen cases through the normal upload pipeline. Each case stores structured evidence and a reproducible feature snapshot.
2. A Reviewer or Admin assigns a trusted label: `GENUINE`, `SUSPICIOUS`, `FRAUDULENT`, or `UNCERTAIN`.
3. An Admin creates and publishes a dataset version. Published versions are immutable.
4. An Admin trains and evaluates Logistic Regression. The trainer requires at least 4 samples in each trainable class.
5. An Admin approves and activates the evaluated model. Activation is enforced by the backend.
6. Future screenings receive actual model predictions, probabilities, and coefficient-based feature influences. Without an active model, the result is `model_status: NOT_AVAILABLE`.

All automated signals are advisory only. The system does not determine guilt or make final border-entry decisions. Any flagged result requires authorized manual review.

Security notes: login uses hashed passwords and Flask sessions. Governance permissions are enforced server-side. Uploads are limited to 10 MB and PNG, JPG, WEBP, or PDF files, then saved with generated server-side names outside the public frontend directory. Training uses structured features rather than raw OCR/document images. Flask debug mode is disabled by default.
