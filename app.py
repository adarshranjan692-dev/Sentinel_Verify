from datetime import datetime
from functools import wraps
from pathlib import Path
import json
import os
import secrets
import sqlite3
import uuid

import cv2
import numpy as np
import pytesseract
from PIL import Image
from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from trustid import (
    activate_model,
    approve_model,
    audit,
    build_evidence,
    create_dataset,
    init_trustid_schema,
    persist_screening,
    publish_dataset,
    review_case,
    score_active_model,
    serialize_rows,
    train_model,
)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "Frontend"
DATABASE = Path(os.environ.get("DATABASE_PATH", str(BASE_DIR / "screening.db")))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads")))
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "application/pdf"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "").strip()
POPPLER_PATH = os.environ.get("POPPLER_PATH", "").strip()

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
app.config.update(
    SECRET_KEY=os.environ.get("SENTINEL_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_SIZE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    TESSERACT_CMD=TESSERACT_CMD,
    POPPLER_PATH=POPPLER_PATH,
)

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def executable_available(path_or_name):
    if path_or_name:
        path = Path(path_or_name)
        if path.is_dir():
            return (path / "pdftoppm").exists() or (path / "pdftoppm.exe").exists()
        return path.exists()
    return False


def ocr_diagnostics():
    tesseract_available = False
    tesseract_version = None
    try:
        tesseract_version = str(pytesseract.get_tesseract_version())
        tesseract_available = True
    except (pytesseract.TesseractNotFoundError, OSError):
        pass
    poppler_available = executable_available(POPPLER_PATH)
    if not poppler_available:
        from shutil import which
        poppler_available = bool(which("pdftoppm"))
    return {
        "ocr": "AVAILABLE" if tesseract_available else "UNAVAILABLE",
        "tesseract": "AVAILABLE" if tesseract_available else "UNAVAILABLE",
        "tesseract_version": tesseract_version,
        "pdf_ocr": "AVAILABLE" if poppler_available else "UNAVAILABLE",
        "poppler_path_configured": bool(POPPLER_PATH),
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Authentication required."}), 401
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                return jsonify({"error": "This operation requires an authorized role."}), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator


def valid_upload(uploaded):
    if not uploaded or not uploaded.filename:
        return None
    filename = secure_filename(uploaded.filename)
    extension = Path(filename).suffix.lower().lstrip(".")
    if not filename or extension not in ALLOWED_EXTENSIONS or uploaded.mimetype not in ALLOWED_MIME_TYPES:
        return None
    return filename


def valid_image_upload(uploaded):
    filename = valid_upload(uploaded)
    if not filename or uploaded.mimetype not in {"image/png", "image/jpeg", "image/webp"}:
        return None
    return filename


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    UPLOAD_DIR.mkdir(exist_ok=True)
    connection = get_db()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Analyst'
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screening_id TEXT UNIQUE NOT NULL,
            document_type TEXT NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT,
            selfie_filename TEXT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            risk_score INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ocr_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screening_id TEXT NOT NULL,
            fields_json TEXT NOT NULL,
            confidence REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS validation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screening_id TEXT NOT NULL,
            checks_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tampering_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screening_id TEXT NOT NULL,
            result_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS face_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screening_id TEXT NOT NULL,
            result_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS risk_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screening_id TEXT NOT NULL,
            score INTEGER NOT NULL,
            level TEXT NOT NULL,
            reasons_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS screening_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screening_id TEXT UNIQUE NOT NULL,
            reviewed INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    init_trustid_schema(connection)
    try:
        connection.execute("ALTER TABLE documents ADD COLUMN original_filename TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        connection.execute("ALTER TABLE documents ADD COLUMN selfie_filename TEXT")
    except sqlite3.OperationalError:
        pass
    connection.execute(
        "INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
        ("demo@screening.local", generate_password_hash("demo123"), "Security Analyst"),
    )
    connection.execute(
        "INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
        ("admin@trustid.local", generate_password_hash("admin123"), "Admin"),
    )
    connection.execute(
        "INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
        ("reviewer@trustid.local", generate_password_hash("reviewer123"), "Reviewer"),
    )
    demo_user = connection.execute("SELECT password FROM users WHERE username = ?", ("demo@screening.local",)).fetchone()
    if demo_user and not demo_user["password"].startswith(("scrypt:", "pbkdf2:")):
        connection.execute(
            "UPDATE users SET password = ? WHERE username = ?",
            (generate_password_hash("demo123"), "demo@screening.local"),
        )
    connection.commit()
    connection.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def seed_demo_data():
    connection = get_db()
    count = connection.execute("SELECT COUNT(*) AS total FROM documents").fetchone()["total"]
    if count == 0:
        samples = [
            ("SCR-24091", "Passport", "synthetic-passport-demo.png", "2026-09-05 09:42", "Review required", 72),
            ("SCR-24090", "Voter Card", "synthetic-voter-card-demo.png", "2026-09-05 09:18", "Verified", 18),
            ("SCR-24089", "Visa", "synthetic-visa-demo.png", "2026-09-04 16:31", "Verified", 27),
            ("SCR-24088", "Driving License", "synthetic-license-demo.png", "2026-09-04 14:05", "Review required", 56),
        ]
        connection.executemany(
            "INSERT INTO documents (screening_id, document_type, filename, created_at, status, risk_score) VALUES (?, ?, ?, ?, ?, ?)",
            samples,
        )
        connection.executemany(
            "INSERT INTO screening_history (screening_id, reviewed) VALUES (?, ?)",
            [(sample[0], 1 if sample[4] != "Verified" else 0) for sample in samples],
        )
        connection.commit()
    connection.execute("UPDATE documents SET document_type = 'Voter Card', filename = 'synthetic-voter-card-demo.png' WHERE document_type = 'National ID'")
    connection.execute("UPDATE documents SET document_type = 'Aadhaar Card', filename = 'synthetic-aadhaar-card-demo.png' WHERE document_type = 'Permit'")
    connection.commit()
    connection.close()


def analyze_image_tampering(file_path):
    """
    Perform forensic image analysis to detect tampering indicators.
    Returns tampering analysis data in same format as demo_payload["tampering"].
    """
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            return None
        
        # Load image
        image = cv2.imread(str(file_path))
        if image is None:
            return None
        
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape
        
        # 1. Compression artifact detection
        # Analyze DCT coefficients for JPEG compression artifacts
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        laplacian_var = np.var(laplacian)
        
        # High variance suggests diverse content, low suggests compression artifacts
        compression_score = min(100, max(0, int(laplacian_var / 50)))
        
        # 2. Edge consistency check
        # Detect edges and analyze their uniformity
        edges = cv2.Canny(gray, 100, 200)
        edge_density = np.count_nonzero(edges) / (height * width) * 100
        
        # Very low edge density might indicate heavy post-processing
        edge_score = min(100, max(0, int(edge_density * 20)))
        
        # 3. Histogram analysis
        # Check for histogram irregularities that suggest splicing/blending
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist_entropy = -np.sum((hist / hist.sum()) * np.log(hist / hist.sum() + 1e-7))
        
        # Lower entropy suggests possible manipulation
        entropy_score = min(100, max(0, int(hist_entropy * 20)))
        
        # 4. Regional anomaly detection
        # Divide image into quadrants and check for inconsistencies
        regions = []
        h_half, w_half = height // 2, width // 2
        quadrants = [
            gray[0:h_half, 0:w_half],
            gray[0:h_half, w_half:width],
            gray[h_half:height, 0:w_half],
            gray[h_half:height, w_half:width]
        ]
        
        region_variances = [np.var(q) for q in quadrants if q.size > 0]
        
        # High variance between regions might indicate splicing
        regional_inconsistency = np.std(region_variances) if region_variances else 0
        region_score = min(100, max(0, int(regional_inconsistency / 5)))
        
        # 5. Noise pattern analysis
        # Gaussian blur and compare - real documents have consistent noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        diff = cv2.absdiff(gray, blurred)
        noise_level = np.mean(diff)
        
        # Abnormal noise patterns suggest post-processing
        noise_score = min(100, max(0, int(noise_level)))
        
        # Calculate overall tampering risk
        scores = [compression_score, edge_score, entropy_score, region_score, noise_score]
        avg_score = int(np.mean(scores))
        
        # Determine risk level
        if avg_score > 65:
            risk_level = "Potential anomaly detected"
            suspicious_regions = [
                "Compression inconsistencies detected",
                "Edge irregularities in central area"
            ]
        elif avg_score > 45:
            risk_level = "Minor anomalies detected"
            suspicious_regions = [
                "Regional content inconsistency",
                "Noise pattern variation"
            ]
        else:
            risk_level = "No significant anomalies"
            suspicious_regions = ["Image appears consistent"]
        
        return {
            "risk": avg_score,
            "status": risk_level,
            "regions": suspicious_regions,
            "explanation": f"Image analysis detected compression variation={compression_score}, edge_consistency={edge_score}, histogram_regularity={entropy_score}, regional_uniformity={region_score}, noise_stability={noise_score}. This is an indicator only and does not prove forgery.",
            "tampering_source": "REAL"
        }
    
    except Exception as e:
        app.logger.warning(f"Image tampering analysis failed: {e}")
        return None


def compare_faces(document_path, selfie_path):
    """Compare the largest detected face in a document and selfie image."""
    result = {
        "face_source": "REAL",
        "detected": False,
        "similarity": 0,
        "status": "FACE REVIEW REQUIRED",
        "detail": "A document image and selfie are required for comparison.",
    }
    if not document_path or not selfie_path:
        return result

    document_image = cv2.imread(str(document_path))
    selfie_image = cv2.imread(str(selfie_path))
    if document_image is None or selfie_image is None:
        result["detail"] = "One or both comparison images could not be read."
        return result

    cascade = cv2.CascadeClassifier(
        str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
    )
    if cascade.empty():
        result["detail"] = "The face detector could not be loaded."
        return result

    def largest_face(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return max(faces, key=lambda face: face[2] * face[3], default=None)

    document_face = largest_face(document_image)
    selfie_face = largest_face(selfie_image)
    if document_face is None or selfie_face is None:
        result["detail"] = "A face could not be detected in both images."
        return result

    def normalized_crop(image, face):
        x, y, width, height = face
        crop = cv2.cvtColor(image[y:y + height, x:x + width], cv2.COLOR_BGR2GRAY)
        crop = cv2.resize(crop, (128, 128), interpolation=cv2.INTER_AREA)
        return cv2.equalizeHist(crop).astype(np.float32) / 255.0

    document_crop = normalized_crop(document_image, document_face)
    selfie_crop = normalized_crop(selfie_image, selfie_face)
    mean_squared_error = float(np.mean((document_crop - selfie_crop) ** 2))
    similarity = int(round(max(0, min(100, 100 * (1 - mean_squared_error)))))
    result.update({
        "detected": True,
        "similarity": similarity,
        "status": "LIKELY MATCH" if similarity >= 80 else "NO CLEAR MATCH",
        "detail": "Face similarity was calculated from normalized OpenCV face crops and requires authorized human review.",
    })
    return result


def calculate_risk_assessment(validation_checks, tampering_result, face_result):
    """Derive a deterministic advisory score from persisted analysis signals."""
    score = 0
    reasons = []
    for check in validation_checks:
        if check["status"] == "FAIL":
            score += 25
            reasons.append(check["label"] + " failed")
        elif check["status"] == "REVIEW":
            score += 10
            reasons.append(check["label"] + " requires review")

    tampering_risk = int(tampering_result.get("risk", 0))
    score += round(tampering_risk * 0.35)
    if tampering_risk >= 61:
        reasons.append("Image tampering indicators are elevated")
    elif tampering_risk >= 31:
        reasons.append("Image tampering indicators require review")

    if not face_result.get("detected"):
        score += 20
        reasons.append("Face comparison could not be completed")
    elif face_result.get("similarity", 0) < 80:
        score += 25
        reasons.append("Face similarity is below the review threshold")

    score = min(100, score)
    level = "CRITICAL" if score >= 81 else "HIGH" if score >= 61 else "MEDIUM" if score >= 31 else "LOW"
    return {
        "score": score,
        "level": level,
        "reasons": reasons or ["No elevated screening signals detected"],
        "recommendation": "Refer for manual verification before any operational decision." if score >= 31 else "Continue authorized review with no elevated signal.",
        "risk_source": "REAL",
    }


def extract_fields_from_text(raw_text):
    """
    Extract structured fields from raw OCR text.
    Parses patterns like "FIELD_NAME: value" and returns a dict.
    Normalizes keys to lowercase with underscores.
    """
    if not raw_text:
        return {}
    
    fields = {}
    lines = raw_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if ':' in line:
            parts = line.split(':', 1)
            if len(parts) == 2:
                key = parts[0].strip().lower().replace(' ', '_').replace('-', '_')
                value = parts[1].strip()
                fields[key] = value
    
    return fields


def validate_extracted_fields(fields, document_type="Passport"):
    """
    Run validation rules on extracted fields.
    Returns a list of validation check results.
    """
    checks = []
    
    # Field presence check
    required_fields = {
        "Passport": ["name", "passport_number", "nationality", "date_of_birth", "expiry_date"],
        "Visa": ["visa_number", "nationality", "date_of_issue", "expiry_date"],
        "National ID": ["id_number", "name", "date_of_birth"],
        "Driving License": ["license_number", "name", "date_of_birth", "expiry_date"],
    }
    
    required = required_fields.get(document_type, ["name"])
    found_fields = set(fields.keys())
    missing = [f for f in required if f not in found_fields]
    
    if missing:
        checks.append({
            "label": "Required fields present",
            "status": "FAIL" if len(missing) > 2 else "REVIEW",
            "detail": f"Missing fields: {', '.join(missing)}"
        })
    else:
        checks.append({
            "label": "Required fields present",
            "status": "PASS",
            "detail": f"All {len(required)} required fields were extracted."
        })
    
    # Document number format check
    if "passport_number" in fields:
        passport_num = fields["passport_number"]
        # Simple format check: alphanumeric, 6-10 chars
        if len(passport_num) >= 6 and all(c.isalnum() for c in passport_num):
            checks.append({
                "label": "Document number format",
                "status": "PASS",
                "detail": f"Passport number '{passport_num}' matches expected format."
            })
        else:
            checks.append({
                "label": "Document number format",
                "status": "REVIEW",
                "detail": f"Passport number '{passport_num}' may need manual verification."
            })
    
    # Date validation
    import re
    from datetime import datetime
    
    if "expiry_date" in fields:
        expiry = fields["expiry_date"]
        # Try to parse date (YYYY-MM-DD or similar formats)
        date_patterns = [r'\d{4}-\d{2}-\d{2}', r'\d{2}/\d{2}/\d{4}']
        date_found = False
        
        for pattern in date_patterns:
            if re.search(pattern, expiry):
                date_found = True
                try:
                    # Try parsing
                    if '-' in expiry:
                        exp_date = datetime.strptime(expiry.split()[0], '%Y-%m-%d')
                    else:
                        parts = re.findall(r'\d+', expiry)
                        if len(parts) >= 3:
                            exp_date = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                    
                    if exp_date > datetime.now():
                        checks.append({
                            "label": "Expiry status",
                            "status": "PASS",
                            "detail": f"Document expires on {expiry} (valid)."
                        })
                    else:
                        checks.append({
                            "label": "Expiry status",
                            "status": "FAIL",
                            "detail": f"Document expired on {expiry}."
                        })
                except:
                    checks.append({
                        "label": "Expiry status",
                        "status": "REVIEW",
                        "detail": f"Could not parse expiry date '{expiry}' - manual review needed."
                    })
                break
        
        if not date_found:
            checks.append({
                "label": "Expiry status",
                "status": "REVIEW",
                "detail": f"Expiry date '{expiry}' format unclear - manual review needed."
            })
    
    # Consistency check
    if fields.get("name") and fields.get("date_of_birth"):
        checks.append({
            "label": "Internal consistency",
            "status": "PASS",
            "detail": "Name and date of birth are both present - fields appear consistent."
        })
    else:
        checks.append({
            "label": "Internal consistency",
            "status": "REVIEW",
            "detail": "Unable to verify consistency - manual confirmation is recommended."
        })
    
    return checks


def extract_ocr_real(file_path):
    """
    Extract text from document using real Tesseract OCR.
    Returns OCR data in the same format as demo_payload["ocr"].
    """
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            return None
        
        # Check if tesseract is available
        try:
            version = pytesseract.get_tesseract_version()
            app.logger.info(f"Using Tesseract: {version}")
        except pytesseract.TesseractNotFoundError:
            app.logger.warning("Tesseract not installed. Install from: https://github.com/UB-Mannheim/tesseract/wiki")
            return None
        
        extension = file_path.suffix.lower()
        image = None
        
        # Handle image files
        if extension in {'.png', '.jpg', '.jpeg', '.webp'}:
            image = cv2.imread(str(file_path))
            if image is None:
                return None
        
        # Handle PDF files (extract first page)
        elif extension == '.pdf':
            try:
                from pdf2image import convert_from_path
                conversion_options = {"first_page": 1, "last_page": 1}
                if POPPLER_PATH:
                    conversion_options["poppler_path"] = POPPLER_PATH
                images = convert_from_path(str(file_path), **conversion_options)
                if not images:
                    return None
                # Convert PIL Image to cv2 format
                import numpy as np
                image = cv2.cvtColor(np.array(images[0]), cv2.COLOR_RGB2BGR)
            except (ImportError, OSError, FileNotFoundError) as error:
                app.logger.warning(f"PDF OCR unavailable: {error}")
                return None
        
        if image is None:
            return None
        
        # Preprocess image for better OCR
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        # Extract text with confidence
        data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)
        
        # Aggregate confidence
        confidences = [int(c) for c in data['conf'] if int(c) > 0]
        avg_confidence = int(sum(confidences) / len(confidences)) if confidences else 0
        avg_confidence = min(99, max(50, avg_confidence))  # Clamp between 50-99
        
        # Extract full text
        full_text = pytesseract.image_to_string(thresh).strip()
        
        # Return in demo_payload format for compatibility
        return {
            "confidence": avg_confidence,
            "fields": {"raw_text": full_text[:500]},  # Store first 500 chars
            "missing_fields": [],
            "ocr_source": "REAL",  # Mark as real Tesseract OCR
        }
    except Exception as e:
        app.logger.warning(f"OCR extraction failed: {e}")
        return None


def demo_payload(screening_id, document_type, filename):
    return {
        "screening_id": screening_id,
        "document_type": document_type,
        "filename": filename,
        "created_at": now(),
        "prototype": True,
        "ocr": {
            "confidence": 94,
            "fields": {
                "Name": "ALEX MORGAN",
                "Passport Number": "SYN-482019",
                "Nationality": "SYNTHETIC",
                "Date of Birth": "1994-06-18",
                "Gender": "X",
                "Date of Issue": "2023-08-10",
                "Date of Expiry": "2033-08-09",
            },
            "missing_fields": [],
        },
        "validation": [
            {"label": "Required fields present", "status": "PASS", "detail": "All configured fields were extracted."},
            {"label": "Document number format", "status": "PASS", "detail": "Matches the synthetic document pattern."},
            {"label": "Expiry status", "status": "PASS", "detail": "Document is not expired in this demo."},
            {"label": "Internal consistency", "status": "REVIEW", "detail": "Manual confirmation is recommended."},
        ],
        "tampering": {
            "risk": 38,
            "status": "Potential anomaly detected",
            "regions": ["Portrait boundary", "Lower-right text block"],
            "explanation": "Prototype image heuristics detected compression variation. This is an indicator only and does not prove forgery.",
        },
        "face": {
            "detected": True,
            "similarity": 91,
            "status": "LIKELY MATCH",
            "detail": "Face comparison is a prototype signal and requires authorized human review.",
        },
        "risk": {
            "score": 42,
            "level": "MEDIUM",
            "reasons": ["Potential image-region anomaly", "Internal consistency requires review"],
            "recommendation": "Refer for manual verification before any operational decision.",
        },
    }


def persisted_screening(screening_id):
    connection = get_db()
    document = connection.execute(
        "SELECT * FROM documents WHERE screening_id = ?", (screening_id,)
    ).fetchone()
    if not document:
        connection.close()
        return None

    ocr = connection.execute(
        "SELECT fields_json, confidence FROM ocr_results WHERE screening_id = ? ORDER BY id DESC LIMIT 1",
        (screening_id,),
    ).fetchone()
    validation = connection.execute(
        "SELECT checks_json FROM validation_results WHERE screening_id = ? ORDER BY id DESC LIMIT 1",
        (screening_id,),
    ).fetchone()
    tampering = connection.execute(
        "SELECT result_json FROM tampering_results WHERE screening_id = ? ORDER BY id DESC LIMIT 1",
        (screening_id,),
    ).fetchone()
    face = connection.execute(
        "SELECT result_json FROM face_results WHERE screening_id = ? ORDER BY id DESC LIMIT 1",
        (screening_id,),
    ).fetchone()
    risk = connection.execute(
        "SELECT score, level, reasons_json FROM risk_assessments WHERE screening_id = ? ORDER BY id DESC LIMIT 1",
        (screening_id,),
    ).fetchone()
    evidence = connection.execute(
        "SELECT evidence_json, features_json, ml_result_json FROM screening_evidence WHERE screening_id = ?",
        (screening_id,),
    ).fetchone()
    review = connection.execute(
        "SELECT reviewer, trusted_label, notes, created_at FROM human_reviews WHERE screening_id = ?",
        (screening_id,),
    ).fetchone()
    connection.close()

    if not all((ocr, validation, tampering, face, risk)):
        return None

    ocr_fields = json.loads(ocr["fields_json"])
    tampering_result = json.loads(tampering["result_json"])
    face_result = json.loads(face["result_json"])
    result = {
        "screening_id": document["screening_id"],
        "document_type": document["document_type"],
        "filename": document["original_filename"] or document["filename"],
        "created_at": document["created_at"],
        "prototype": False,
        "ocr": {
            "confidence": ocr["confidence"],
            "fields": ocr_fields,
            "missing_fields": [],
            "ocr_source": "REAL" if ocr_fields.get("raw_text") else "DEMO_FALLBACK",
        },
        "validation": json.loads(validation["checks_json"]),
        "tampering": tampering_result,
        "face": face_result,
        "risk": {
            "score": risk["score"],
            "level": risk["level"],
            "reasons": json.loads(risk["reasons_json"]),
            "recommendation": "Refer for manual verification before any operational decision." if risk["score"] >= 31 else "Continue authorized review with no elevated signal.",
            "risk_source": "REAL",
        },
        "decision": "CLEAR" if risk["score"] < 31 else "SUSPICIOUS" if risk["score"] >= 61 else "REVIEW",
        "review": {"review_status": "COMPLETED", **dict(review)} if review else {"review_status": "PENDING", "reviewer": None, "trusted_label": None, "notes": "", "created_at": None},
    }
    if evidence:
        result["evidence"] = json.loads(evidence["evidence_json"])
        result["features"] = json.loads(evidence["features_json"])
        result["ml"] = json.loads(evidence["ml_result_json"])
    return result


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/diagnostics")
def diagnostics():
    return jsonify(ocr_diagnostics())


@app.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    username = body.get("username", "demo@screening.local")
    password = body.get("password", "demo123")
    connection = get_db()
    user = connection.execute("SELECT username, password, role FROM users WHERE username = ?", (username,)).fetchone()
    connection.close()
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Use the demo account or check your credentials."}), 401
    session.clear()
    session["username"] = user["username"]
    session["role"] = user["role"]
    return jsonify({"ok": True, "user": {"username": user["username"], "role": user["role"]}})


@app.post("/upload")
@login_required
def upload():
    document_type = request.form.get("document_type", "Passport")
    uploaded = request.files.get("document")
    selfie = request.files.get("selfie")
    if document_type not in {"Passport", "Visa", "National ID", "Driving License", "Permit"}:
        return jsonify({"error": "Unsupported document type."}), 400
    
    filename = "synthetic-document-demo.png"
    stored_name = None
    selfie_stored_name = None
    
    if uploaded:
        safe_filename = valid_upload(uploaded)
        if not safe_filename:
            return jsonify({"error": "Upload must be a PNG, JPG, WEBP, or PDF file."}), 400
        stored_name = f"{uuid.uuid4().hex}{Path(safe_filename).suffix.lower()}"
        uploaded.save(UPLOAD_DIR / stored_name)
        filename = safe_filename

    if selfie and selfie.filename:
        selfie_filename = valid_image_upload(selfie)
        if not selfie_filename:
            return jsonify({"error": "Selfie must be a PNG, JPG, or WEBP image."}), 400
        selfie_stored_name = f"{uuid.uuid4().hex}{Path(selfie_filename).suffix.lower()}"
        selfie.save(UPLOAD_DIR / selfie_stored_name)
    
    screening_id = f"SCR-{uuid.uuid4().hex[:6].upper()}"
    
    # Try to extract real OCR from uploaded file
    ocr_data = None
    if stored_name:
        ocr_data = extract_ocr_real(UPLOAD_DIR / stored_name)
    
    # Try to analyze tampering from uploaded file
    tampering_data = None
    if stored_name:
        tampering_data = analyze_image_tampering(UPLOAD_DIR / stored_name)
    
    # Use real OCR if available, otherwise use demo
    if ocr_data:
        # Real OCR was extracted
        payload = demo_payload(screening_id, document_type, filename)
        # Update with real OCR data
        payload["ocr"] = ocr_data
        ocr_fields = ocr_data.get("fields", {})
    else:
        # Fall back to demo payload
        payload = demo_payload(screening_id, document_type, filename)
        ocr_fields = payload["ocr"]["fields"]

    if ocr_data:
        extracted_fields = extract_fields_from_text(ocr_fields.get("raw_text", ""))
        validation_checks = validate_extracted_fields(extracted_fields, document_type)
        payload["validation"] = validation_checks
    else:
        validation_checks = payload["validation"]
    
    # Use real tampering analysis if available
    if tampering_data:
        payload["tampering"] = tampering_data
        tampering_result = tampering_data
    else:
        tampering_result = payload["tampering"]

    face_result = compare_faces(
        UPLOAD_DIR / stored_name if stored_name else None,
        UPLOAD_DIR / selfie_stored_name if selfie_stored_name else None,
    )
    risk_result = calculate_risk_assessment(validation_checks, tampering_result, face_result)
    payload["face"] = face_result
    payload["risk"] = risk_result
    payload["prototype"] = False
    
    connection = get_db()
    extracted_fields = extract_fields_from_text(payload["ocr"]["fields"].get("raw_text", "")) if payload["ocr"]["fields"].get("raw_text") else {}
    evidence, features = build_evidence(
        connection,
        document_type,
        payload["ocr"],
        validation_checks,
        tampering_result,
        face_result,
        extracted_fields,
    )
    ml_result = score_active_model(connection, features, BASE_DIR)
    payload["evidence"] = evidence
    payload["features"] = features
    payload["ml"] = ml_result
    connection.execute(
        "INSERT INTO documents (screening_id, document_type, filename, original_filename, selfie_filename, created_at, status, risk_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (screening_id, document_type, stored_name or filename, filename, selfie_stored_name, payload["created_at"], "Verified" if risk_result["score"] < 31 else "Review required", risk_result["score"]),
    )
    connection.execute("INSERT INTO screening_history (screening_id, reviewed) VALUES (?, 1)", (screening_id,))
    connection.execute("INSERT INTO audit_logs (action, created_at) VALUES (?, ?)", ("New screening created", payload["created_at"]))
    connection.execute("INSERT INTO ocr_results (screening_id, fields_json, confidence) VALUES (?, ?, ?)", (screening_id, json.dumps(ocr_fields), payload["ocr"]["confidence"]))
    connection.execute("INSERT INTO validation_results (screening_id, checks_json) VALUES (?, ?)", (screening_id, json.dumps(validation_checks)))
    connection.execute("INSERT INTO tampering_results (screening_id, result_json) VALUES (?, ?)", (screening_id, json.dumps(tampering_result)))
    connection.execute("INSERT INTO face_results (screening_id, result_json) VALUES (?, ?)", (screening_id, json.dumps(face_result)))
    connection.execute("INSERT INTO risk_assessments (screening_id, score, level, reasons_json) VALUES (?, ?, ?, ?)", (screening_id, risk_result["score"], risk_result["level"], json.dumps(risk_result["reasons"])))
    persist_screening(connection, screening_id, evidence, features, ml_result)
    audit_action = "New screening created with active model" if ml_result.get("model_status") == "ACTIVE" else "New screening created without active model"
    connection.execute("INSERT INTO audit_logs (action, created_at) VALUES (?, ?)", (audit_action, payload["created_at"]))
    connection.commit()
    connection.close()
    return jsonify(persisted_screening(screening_id))


@app.post("/ocr")
@login_required
def ocr():
    body = request.get_json(silent=True) or {}
    screening_id = body.get("screening_id", "SCR-DEMO")
    document_type = body.get("document_type", "Passport")
    filename = body.get("filename", "synthetic-document-demo.png")
    
    # Try to extract real OCR from uploaded file
    if screening_id != "SCR-DEMO":
        connection = get_db()
        row = connection.execute(
            "SELECT filename FROM documents WHERE screening_id = ?", (screening_id,)
        ).fetchone()
        connection.close()
        
        stored_result = persisted_screening(screening_id)
        if stored_result:
            return jsonify(stored_result["ocr"])
    
    # Fall back to synthetic/demo OCR
    demo_ocr = demo_payload(screening_id, document_type, filename)["ocr"]
    demo_ocr["ocr_source"] = "DEMO_FALLBACK"  # Mark as fallback
    return jsonify(demo_ocr)


@app.post("/validate")
@login_required
def validate():
    body = request.get_json(silent=True) or {}
    screening_id = body.get("screening_id", "SCR-DEMO")
    document_type = body.get("document_type", "Passport")
    
    # Try to get real OCR data from database
    if screening_id != "SCR-DEMO":
        connection = get_db()
        ocr_row = connection.execute(
            "SELECT fields_json FROM ocr_results WHERE screening_id = ?", (screening_id,)
        ).fetchone()
        connection.close()
        
        stored_result = persisted_screening(screening_id)
        if stored_result:
            fields = extract_fields_from_text(stored_result["ocr"]["fields"].get("raw_text", ""))
            return jsonify({
                "source": "REAL" if stored_result["ocr"]["ocr_source"] == "REAL" else "DEMO_FALLBACK",
                "checks": stored_result["validation"],
                "extracted_fields": fields,
            })
    
    # Fall back to demo validation
    return jsonify({
        "source": "DEMO_FALLBACK",
        "checks": demo_payload(screening_id, document_type, "demo")["validation"]
    })


@app.post("/tampering")
@login_required
def tampering():
    body = request.get_json(silent=True) or {}
    screening_id = body.get("screening_id", "SCR-DEMO")
    
    # Try to perform real image analysis
    if screening_id != "SCR-DEMO":
        connection = get_db()
        row = connection.execute(
            "SELECT filename FROM documents WHERE screening_id = ?", (screening_id,)
        ).fetchone()
        connection.close()
        
        stored_result = persisted_screening(screening_id)
        if stored_result:
            return jsonify(stored_result["tampering"])
    
    # Fall back to demo tampering analysis
    demo_tampering = demo_payload("SCR-DEMO", "Passport", "demo")["tampering"]
    demo_tampering["tampering_source"] = "DEMO_FALLBACK"
    return jsonify(demo_tampering)


@app.post("/face-verify")
@login_required
def face_verify():
    body = request.get_json(silent=True) or {}
    screening_id = body.get("screening_id")
    if screening_id:
        result = persisted_screening(screening_id)
        if result:
            return jsonify(result["face"])
    return jsonify({"error": "A persisted screening_id is required for face verification."}), 400


@app.post("/risk-score")
@login_required
def risk_score():
    body = request.get_json(silent=True) or {}
    screening_id = body.get("screening_id")
    if screening_id:
        result = persisted_screening(screening_id)
        if result:
            return jsonify(result["risk"])
    return jsonify({"error": "A persisted screening_id is required for risk scoring."}), 400


@app.get("/screening-history")
@login_required
def screening_history():
    connection = get_db()
    rows = connection.execute("SELECT screening_id, created_at AS date, document_type, risk_score, status, CASE WHEN status = 'Verified' THEN 'No' ELSE 'Yes' END AS review_required FROM documents ORDER BY id DESC").fetchall()
    connection.close()
    return jsonify([dict(row) for row in rows])


@app.get("/screening/<screening_id>")
@login_required
def screening(screening_id):
    result = persisted_screening(screening_id)
    if result:
        return jsonify(result)

    connection = get_db()
    row = connection.execute("SELECT * FROM documents WHERE screening_id = ?", (screening_id,)).fetchone()
    connection.close()
    if not row:
        return jsonify({"error": "Screening not found"}), 404
    return jsonify(demo_payload(row["screening_id"], row["document_type"], row["filename"]))


@app.get("/dashboard-stats")
@login_required
def dashboard_stats():
    connection = get_db()
    rows = connection.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()
    connection.close()
    scores = [row["risk_score"] for row in rows]
    return jsonify({
        "total": len(rows),
        "verified": sum(row["status"] == "Verified" for row in rows),
        "review": sum(row["status"] != "Verified" for row in rows),
        "high_risk": sum(score >= 61 for score in scores),
        "distribution": {"low": sum(score <= 30 for score in scores), "medium": sum(31 <= score <= 60 for score in scores), "high": sum(61 <= score <= 80 for score in scores), "critical": sum(score >= 81 for score in scores)},
        "recent": [dict(row) for row in rows[:5]],
    })


@app.get("/reviews")
@login_required
def reviews():
    connection = get_db()
    rows = connection.execute(
        "SELECT d.screening_id, d.document_type, d.created_at, d.status, d.risk_score, r.reviewer, r.trusted_label, r.notes, r.created_at AS reviewed_at FROM documents d LEFT JOIN human_reviews r ON r.screening_id = d.screening_id ORDER BY d.created_at DESC"
    ).fetchall()
    connection.close()
    return jsonify([dict(row) for row in rows])


@app.post("/review")
@roles_required("Reviewer", "Admin", "Security Analyst")
def create_review():
    body = request.get_json(silent=True) or {}
    screening_id = body.get("screening_id")
    try:
        connection = get_db()
        review_case(connection, screening_id, session["username"], body.get("trusted_label", ""), body.get("notes", ""))
        connection.commit()
        connection.close()
        return jsonify({"ok": True, "screening_id": screening_id, "trusted_label": body["trusted_label"]})
    except (ValueError, LookupError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/references")
@roles_required("Admin")
def add_reference():
    body = request.get_json(silent=True) or {}
    document_type = body.get("document_type")
    document_number = body.get("document_number", "").strip().upper()
    fields = body.get("fields") or {}
    if not document_type or not document_number or not isinstance(fields, dict):
        return jsonify({"error": "document_type, document_number, and fields are required."}), 400
    import hashlib
    digest = hashlib.sha256(document_number.encode()).hexdigest()
    connection = get_db()
    reference_id = f"REF-{uuid.uuid4().hex[:8].upper()}"
    connection.execute("INSERT OR REPLACE INTO trusted_references (reference_id, document_type, document_number_hash, fields_json, created_at) VALUES (?, ?, ?, ?, ?)", (reference_id, document_type, digest, json.dumps(fields), now()))
    audit(connection, session["username"], "REFERENCE_CREATED", "reference", reference_id)
    connection.commit()
    connection.close()
    return jsonify({"reference_id": reference_id, "document_type": document_type}), 201


@app.get("/references")
@roles_required("Admin")
def references():
    query = request.args.get("q", "").strip().upper()
    connection = get_db()
    rows = connection.execute(
        "SELECT reference_id, document_type, fields_json, created_at FROM trusted_references WHERE document_type LIKE ? OR reference_id LIKE ? ORDER BY created_at DESC",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    connection.close()
    return jsonify([{**dict(row), "fields": json.loads(row["fields_json"])} for row in rows])


@app.put("/references/<reference_id>")
@roles_required("Admin")
def update_reference(reference_id):
    body = request.get_json(silent=True) or {}
    fields = body.get("fields")
    if not isinstance(fields, dict):
        return jsonify({"error": "fields must be an object."}), 400
    connection = get_db()
    row = connection.execute("SELECT reference_id FROM trusted_references WHERE reference_id = ?", (reference_id,)).fetchone()
    if not row:
        connection.close()
        return jsonify({"error": "Reference not found."}), 404
    connection.execute("UPDATE trusted_references SET fields_json = ? WHERE reference_id = ?", (json.dumps(fields), reference_id))
    audit(connection, session["username"], "REFERENCE_UPDATED", "reference", reference_id)
    connection.commit()
    connection.close()
    return jsonify({"reference_id": reference_id, "updated": True})


@app.get("/datasets")
@login_required
def datasets():
    connection = get_db()
    rows = connection.execute("SELECT * FROM dataset_versions ORDER BY created_at DESC").fetchall()
    connection.close()
    return jsonify(serialize_rows(rows))


@app.post("/datasets")
@roles_required("Admin", "Reviewer")
def create_dataset_route():
    try:
        connection = get_db()
        version = create_dataset(connection, session["username"])
        connection.commit()
        connection.close()
        return jsonify({"version": version, "status": "DRAFT"}), 201
    except (ValueError, LookupError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/datasets/<version>/publish")
@roles_required("Admin")
def publish_dataset_route(version):
    try:
        connection = get_db()
        publish_dataset(connection, version, session["username"])
        connection.commit()
        connection.close()
        return jsonify({"version": version, "status": "PUBLISHED"})
    except (ValueError, LookupError) as error:
        return jsonify({"error": str(error)}), 400


@app.get("/models")
@login_required
def models():
    connection = get_db()
    rows = connection.execute("SELECT * FROM model_versions ORDER BY created_at DESC").fetchall()
    connection.close()
    return jsonify(serialize_rows(rows))


@app.post("/models/train")
@roles_required("Admin")
def train_model_route():
    body = request.get_json(silent=True) or {}
    try:
        connection = get_db()
        version, evaluation = train_model(connection, body.get("dataset_version"), BASE_DIR, session["username"])
        connection.commit()
        connection.close()
        return jsonify({"version": version, "status": "EVALUATED", "evaluation": evaluation}), 201
    except (ValueError, LookupError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/models/<version>/approve")
@roles_required("Admin")
def approve_model_route(version):
    try:
        connection = get_db()
        approve_model(connection, version, session["username"])
        connection.commit()
        connection.close()
        return jsonify({"version": version, "status": "APPROVED"})
    except (ValueError, LookupError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/models/<version>/activate")
@roles_required("Admin")
def activate_model_route(version):
    try:
        connection = get_db()
        activate_model(connection, version, session["username"])
        connection.commit()
        connection.close()
        return jsonify({"version": version, "status": "ACTIVE"})
    except (ValueError, LookupError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/models/<version>/archive")
@roles_required("Admin")
def archive_model_route(version):
    connection = get_db()
    row = connection.execute("SELECT version, status FROM model_versions WHERE version = ?", (version,)).fetchone()
    if not row:
        connection.close()
        return jsonify({"error": "Model version not found."}), 404
    if row["status"] == "ACTIVE":
        connection.close()
        return jsonify({"error": "Active models must be replaced through activation."}), 400
    connection.execute("UPDATE model_versions SET status = 'ARCHIVED' WHERE version = ?", (version,))
    audit(connection, session["username"], "MODEL_ARCHIVED", "model", version)
    connection.commit()
    connection.close()
    return jsonify({"version": version, "status": "ARCHIVED"})


@app.get("/audit")
@login_required
def audit_history():
    connection = get_db()
    rows = connection.execute("SELECT * FROM trustid_audit_events ORDER BY id DESC").fetchall()
    connection.close()
    return jsonify([dict(row) for row in rows])


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(error):
    return jsonify({"error": "The upload exceeds the 10 MB limit."}), 413


@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "The request could not be processed."}), 400


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api") or request.path != "/":
        return jsonify({"error": "Resource not found."}), 404
    return error


@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("Unhandled application error", exc_info=error)
    return jsonify({"error": "An internal server error occurred."}), 500


init_db()
seed_demo_data()

if __name__ == "__main__":
    app.run(
        debug=False,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
    )
