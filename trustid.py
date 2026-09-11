from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

FEATURE_SCHEMA_VERSION = "trustid-features-v1"
FEATURE_NAMES = [
    "ocr_completeness",
    "ocr_confidence",
    "classification_confidence",
    "validation_issue_count",
    "invalid_field_count",
    "missing_field_count",
    "expiry_signal",
    "mrz_mismatch",
    "tampering_count",
    "image_quality",
    "face_available",
    "face_similarity",
    "face_match",
    "reference_available",
    "reference_found",
    "reference_match",
    "field_mismatch_count",
]
VALID_LABELS = {"GENUINE", "SUSPICIOUS", "FRAUDULENT", "UNCERTAIN"}
TRAINABLE_LABELS = {"GENUINE", "SUSPICIOUS", "FRAUDULENT"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, sort_keys=True)


def init_trustid_schema(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS screening_evidence (
            screening_id TEXT PRIMARY KEY,
            evidence_json TEXT NOT NULL,
            features_json TEXT NOT NULL,
            ml_result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS human_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screening_id TEXT UNIQUE NOT NULL,
            reviewer TEXT NOT NULL,
            trusted_label TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dataset_versions (
            version TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            class_distribution_json TEXT NOT NULL,
            sample_ids_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            published_at TEXT
        );
        CREATE TABLE IF NOT EXISTS training_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_version TEXT NOT NULL,
            screening_id TEXT NOT NULL,
            document_type TEXT NOT NULL,
            features_json TEXT NOT NULL,
            trusted_label TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            UNIQUE(dataset_version, screening_id)
        );
        CREATE TABLE IF NOT EXISTS model_versions (
            version TEXT PRIMARY KEY,
            dataset_version TEXT NOT NULL,
            algorithm TEXT NOT NULL,
            feature_schema TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            status TEXT NOT NULL,
            evaluation_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            approved_by TEXT,
            approved_at TEXT,
            activated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS trusted_references (
            reference_id TEXT PRIMARY KEY,
            document_type TEXT NOT NULL,
            document_number_hash TEXT NOT NULL,
            fields_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(document_type, document_number_hash)
        );
        CREATE TABLE IF NOT EXISTS trustid_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    try:
        connection.execute("ALTER TABLE model_versions ADD COLUMN activated_by TEXT")
    except sqlite3.OperationalError:
        pass


def audit(connection, actor, action, entity_type, entity_id, details=None):
    connection.execute(
        "INSERT INTO trustid_audit_events (actor, action, entity_type, entity_id, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (actor, action, entity_type, entity_id, _json(details or {}), utc_now()),
    )


def classify_document(document_type, raw_text):
    normalized = (raw_text or "").upper()
    if document_type:
        label = document_type.upper()
    elif "PASSPORT" in normalized or "P<" in normalized:
        label = "PASSPORT"
    elif "DRIVING" in normalized or "DRIVER" in normalized:
        label = "DRIVING LICENSE"
    elif "PAN" in normalized:
        label = "PAN"
    else:
        label = "OTHER"
    return {"document_type": label, "classification_confidence": 1.0 if document_type else 0.72, "method": "RULE_BASED"}


def _mrz_check_digit(value, expected):
    weights = [7, 3, 1]
    total = 0
    for index, char in enumerate(value):
        if char.isdigit():
            number = int(char)
        elif char == "<":
            number = 0
        else:
            number = ord(char) - 55
        total += number * weights[index % 3]
    return total % 10 == int(expected)


def _mrz_digit_field(value):
    return value.replace("O", "0").replace("I", "1").replace("B", "8")


def _mrz_date(value):
    return f"20{value[0:2]}-{value[2:4]}-{value[4:6]}" if len(value) == 6 and value.isdigit() else None


def analyze_mrz(raw_text, visible_fields=None):
    lines = ["".join(line.split()).upper() for line in (raw_text or "").splitlines()]
    candidates = [line for line in lines if len(line) >= 30 and line.count("<") >= 2]
    result = {
        "available": bool(candidates),
        "parsed": False,
        "format": None,
        "mrz_mismatch": False,
        "mrz_errors": [],
        "mrz_consistency": "NOT_AVAILABLE",
        "check_results": [],
        "fields": {},
    }
    if not candidates:
        return result
    if len(candidates) >= 2 and len(candidates[-1]) >= 40:
        first, second = candidates[-2][:44].ljust(44, "<"), candidates[-1][:44].ljust(44, "<")
        result["format"] = "TD3"
        document_number = _mrz_digit_field(second[0:9]).rstrip("<")
        date_of_birth = _mrz_date(_mrz_digit_field(second[13:19]))
        expiry_date = _mrz_date(_mrz_digit_field(second[21:27]))
        result["fields"] = {"passport_number": document_number, "nationality": second[10:13].replace("<", ""), "date_of_birth": date_of_birth, "expiry_date": expiry_date, "name": first[5:].replace("<", " ").strip()}
        checks = [("document_number", second[0:9], second[9]), ("date_of_birth", second[13:19], second[19]), ("expiry_date", second[21:27], second[27])]
        for field, value, expected in checks:
            normalized = _mrz_digit_field(value)
            passed = expected.isdigit() and _mrz_check_digit(normalized, expected)
            result["check_results"].append({"field": field, "passed": passed})
            if not passed:
                result["mrz_errors"].append(f"{field.replace('_', ' ').title()} check digit mismatch")
        result["parsed"] = True
    else:
        result["format"] = "MRZ-LIKE"
        result["mrz_errors"].append("Unsupported MRZ layout; expected a TD3 passport MRZ.")
    if visible_fields and result["parsed"]:
        mismatches = []
        for field in ("passport_number", "nationality"):
            visible = str(visible_fields.get(field, "")).replace("<", "").strip().upper()
            mrz_value = str(result["fields"].get(field, "")).replace("<", "").strip().upper()
            if visible and mrz_value and visible != mrz_value:
                mismatches.append(f"{field.replace('_', ' ').title()} differs from MRZ")
        for field in ("date_of_birth", "expiry_date"):
            visible = str(visible_fields.get(field, "")).strip()
            mrz_value = result["fields"].get(field)
            if visible and mrz_value and visible[-6:].replace("-", "") != mrz_value[-6:].replace("-", ""):
                mismatches.append(f"{field.replace('_', ' ').title()} differs from MRZ")
        result["mrz_errors"].extend(mismatches)
    result["mrz_mismatch"] = bool(result["mrz_errors"])
    result["mrz_consistency"] = "MISMATCH" if result["mrz_mismatch"] else "CONSISTENT"
    return result


def compare_reference(connection, document_type, fields):
    document_number = fields.get("passport_number") or fields.get("license_number") or fields.get("id_number") or fields.get("document_number")
    result = {"reference_available": False, "reference_found": False, "reference_match": False, "field_mismatch_count": 0}
    if not document_number:
        return result
    digest = hashlib.sha256(document_number.strip().upper().encode()).hexdigest()
    rows = connection.execute("SELECT fields_json FROM trusted_references WHERE document_type = ? AND document_number_hash = ?", (document_type, digest)).fetchall()
    result["reference_available"] = True
    if not rows:
        return result
    reference_fields = json.loads(rows[0]["fields_json"])
    result["reference_found"] = True
    result["field_mismatch_count"] = sum(1 for key, value in reference_fields.items() if fields.get(key) and fields.get(key) != value)
    result["reference_match"] = result["field_mismatch_count"] == 0
    return result


def build_evidence(connection, document_type, ocr, validation, tampering, face, fields):
    raw_text = ocr.get("fields", {}).get("raw_text", "")
    classification = classify_document(document_type, raw_text)
    mrz = analyze_mrz(raw_text, fields)
    missing = sum(1 for item in validation if item.get("status") in {"FAIL", "REVIEW"} and "Missing fields" in item.get("detail", ""))
    invalid = sum(1 for item in validation if item.get("status") == "FAIL" and "Missing fields" not in item.get("detail", ""))
    reference = compare_reference(connection, document_type, fields)
    tampering_count = len(tampering.get("regions", [])) if tampering else 0
    face_available = bool(face and face.get("detected"))
    face_similarity = round(float(face.get("similarity", 0)) / 100, 4) if face_available else 0.0
    image_quality = round(max(0.0, min(1.0, 1.0 - float(tampering.get("risk", 0)) / 100)), 4) if tampering else 0.0
    evidence = {
        "document_type": classification["document_type"],
        "classification": classification,
        "ocr_completeness": round(min(1.0, len(raw_text) / 120), 4),
        "ocr_confidence": round(float(ocr.get("confidence", 0)) / 100, 4),
        "extracted_fields": fields,
        "validation": validation,
        "mrz": mrz,
        "tampering": tampering,
        "face": face,
        "reference": reference,
    }
    features = {
        "ocr_completeness": evidence["ocr_completeness"],
        "ocr_confidence": evidence["ocr_confidence"],
        "classification_confidence": classification["classification_confidence"],
        "validation_issue_count": sum(1 for item in validation if item.get("status") != "PASS"),
        "invalid_field_count": invalid,
        "missing_field_count": missing,
        "expiry_signal": 1 if any(item.get("label") == "Expiry status" and item.get("status") == "FAIL" for item in validation) else 0,
        "mrz_mismatch": int(mrz["mrz_mismatch"]),
        "tampering_count": tampering_count,
        "image_quality": image_quality,
        "face_available": int(face_available),
        "face_similarity": face_similarity,
        "face_match": int(face_available and face.get("similarity", 0) >= 80),
        "reference_available": int(reference["reference_available"]),
        "reference_found": int(reference["reference_found"]),
        "reference_match": int(reference["reference_match"]),
        "field_mismatch_count": reference["field_mismatch_count"],
    }
    return evidence, features


def _model_directory(base_dir):
    path = Path(base_dir) / "models"
    path.mkdir(exist_ok=True)
    return path


def score_active_model(connection, features, base_dir):
    row = connection.execute("SELECT * FROM model_versions WHERE status = 'ACTIVE' ORDER BY activated_at DESC LIMIT 1").fetchone()
    if not row:
        return {"model_status": "NOT_AVAILABLE", "reason": "ML screening unavailable - no active model."}
    try:
        import joblib
        artifact = joblib.load(row["artifact_path"])
        vector = [[features[name] for name in FEATURE_NAMES]]
        prediction = str(artifact.predict(vector)[0])
        probabilities = artifact.predict_proba(vector)[0]
        probability = float(max(probabilities))
        class_index = list(artifact.classes_).index(prediction)
        contributions = []
        coefficients = artifact.coef_[class_index] if len(artifact.coef_) > class_index else artifact.coef_[0]
        for name, coefficient, value in zip(FEATURE_NAMES, coefficients, vector[0]):
            contributions.append({"feature": name, "contribution": round(float(coefficient * value), 6), "value": value})
        contributions.sort(key=lambda item: abs(item["contribution"]), reverse=True)
        return {"model_status": "ACTIVE", "model_version": row["version"], "dataset_version": row["dataset_version"], "prediction": prediction, "probability": round(probability, 6), "confidence": round(probability, 6), "top_feature_influences": contributions[:5]}
    except Exception as error:
        return {"model_status": "ERROR", "model_version": row["version"], "error": str(error)}


def persist_screening(connection, screening_id, evidence, features, ml_result):
    connection.execute("INSERT OR REPLACE INTO screening_evidence (screening_id, evidence_json, features_json, ml_result_json, created_at) VALUES (?, ?, ?, ?, ?)", (screening_id, _json(evidence), _json(features), _json(ml_result), utc_now()))


def review_case(connection, screening_id, reviewer, label, notes=""):
    if label not in VALID_LABELS:
        raise ValueError("Trusted label must be GENUINE, SUSPICIOUS, FRAUDULENT, or UNCERTAIN.")
    case = connection.execute("SELECT screening_id FROM documents WHERE screening_id = ?", (screening_id,)).fetchone()
    if not case:
        raise LookupError("Screening not found.")
    connection.execute("INSERT INTO human_reviews (screening_id, reviewer, trusted_label, notes, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(screening_id) DO UPDATE SET reviewer=excluded.reviewer, trusted_label=excluded.trusted_label, notes=excluded.notes, created_at=excluded.created_at", (screening_id, reviewer, label, notes, utc_now()))
    audit(connection, reviewer, "HUMAN_REVIEW_RECORDED", "screening", screening_id, {"label": label})


def create_dataset(connection, actor):
    rows = connection.execute("SELECT r.*, d.document_type FROM human_reviews r JOIN documents d ON d.screening_id = r.screening_id WHERE r.trusted_label IN ('GENUINE', 'SUSPICIOUS', 'FRAUDULENT') AND NOT EXISTS (SELECT 1 FROM training_samples s WHERE s.screening_id = r.screening_id)").fetchall()
    if not rows:
        raise ValueError("No newly reviewed trainable cases are available.")
    version = f"dataset-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"
    distribution = Counter(row["trusted_label"] for row in rows)
    connection.execute("INSERT INTO dataset_versions (version, status, sample_count, class_distribution_json, sample_ids_json, created_at) VALUES (?, 'DRAFT', ?, ?, ?, ?)", (version, len(rows), _json(distribution), _json([row["screening_id"] for row in rows]), utc_now()))
    for row in rows:
        evidence = connection.execute("SELECT features_json FROM screening_evidence WHERE screening_id = ?", (row["screening_id"],)).fetchone()
        if not evidence:
            raise ValueError(f"No feature snapshot exists for {row['screening_id']}.")
        connection.execute("INSERT INTO training_samples (dataset_version, screening_id, document_type, features_json, trusted_label, reviewer, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (version, row["screening_id"], row["document_type"], evidence["features_json"], row["trusted_label"], row["reviewer"], row["created_at"]))
    audit(connection, actor, "DATASET_CREATED", "dataset", version, {"sample_count": len(rows), "class_distribution": dict(distribution)})
    return version


def publish_dataset(connection, version, actor):
    row = connection.execute("SELECT * FROM dataset_versions WHERE version = ?", (version,)).fetchone()
    if not row:
        raise LookupError("Dataset version not found.")
    if row["status"] != "DRAFT":
        raise ValueError("Only draft datasets can be published.")
    connection.execute("UPDATE dataset_versions SET status = 'PUBLISHED', published_at = ? WHERE version = ?", (utc_now(), version))
    audit(connection, actor, "DATASET_PUBLISHED", "dataset", version)


def train_model(connection, version, base_dir, actor):
    row = connection.execute("SELECT * FROM dataset_versions WHERE version = ? AND status = 'PUBLISHED'", (version,)).fetchone()
    if not row:
        raise LookupError("A published dataset version is required.")
    samples = connection.execute("SELECT * FROM training_samples WHERE dataset_version = ?", (version,)).fetchall()
    labels = [sample["trusted_label"] for sample in samples]
    counts = Counter(labels)
    if set(counts) != TRAINABLE_LABELS or any(counts[label] < 4 for label in TRAINABLE_LABELS):
        raise ValueError("Training requires at least 4 GENUINE, 4 SUSPICIOUS, and 4 FRAUDULENT trusted samples.")
    audit(connection, actor, "MODEL_TRAINING_STARTED", "dataset", version, {"sample_count": len(samples)})
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    import joblib
    matrix = [[json.loads(sample["features_json"])[name] for name in FEATURE_NAMES] for sample in samples]
    model = LogisticRegression(max_iter=2000, random_state=42)
    folds = StratifiedKFold(n_splits=4, shuffle=True, random_state=42)
    predicted = cross_val_predict(model, matrix, labels, cv=folds)
    evaluation = {"accuracy": round(float(accuracy_score(labels, predicted)), 6), "precision": round(float(precision_score(labels, predicted, average="macro", zero_division=0)), 6), "recall": round(float(recall_score(labels, predicted, average="macro", zero_division=0)), 6), "f1": round(float(f1_score(labels, predicted, average="macro", zero_division=0)), 6), "confusion_matrix": confusion_matrix(labels, predicted, labels=sorted(TRAINABLE_LABELS)).tolist(), "labels": sorted(TRAINABLE_LABELS), "sample_count": len(samples)}
    model.fit(matrix, labels)
    version_id = f"model-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"
    artifact_path = _model_directory(base_dir) / f"{version_id}.joblib"
    joblib.dump(model, artifact_path)
    connection.execute("INSERT INTO model_versions (version, dataset_version, algorithm, feature_schema, artifact_path, status, evaluation_json, created_at) VALUES (?, ?, ?, ?, ?, 'EVALUATED', ?, ?)", (version_id, version, "Logistic Regression", FEATURE_SCHEMA_VERSION, str(artifact_path), _json(evaluation), utc_now()))
    audit(connection, actor, "MODEL_TRAINED", "model", version_id, {"dataset_version": version})
    audit(connection, actor, "EVALUATION_COMPLETED", "model", version_id, evaluation)
    return version_id, evaluation


def approve_model(connection, version, actor):
    row = connection.execute("SELECT status FROM model_versions WHERE version = ?", (version,)).fetchone()
    if not row:
        raise LookupError("Model version not found.")
    if row["status"] != "EVALUATED":
        raise ValueError("Only evaluated models can be approved.")
    connection.execute("UPDATE model_versions SET status = 'APPROVED', approved_by = ?, approved_at = ? WHERE version = ?", (actor, utc_now(), version))
    audit(connection, actor, "MODEL_APPROVED", "model", version)


def activate_model(connection, version, actor):
    row = connection.execute("SELECT status FROM model_versions WHERE version = ?", (version,)).fetchone()
    if not row:
        raise LookupError("Model version not found.")
    if row["status"] != "APPROVED":
        raise ValueError("Only approved models can be activated.")
    connection.execute("UPDATE model_versions SET status = 'ARCHIVED' WHERE status = 'ACTIVE'")
    connection.execute("UPDATE model_versions SET status = 'ACTIVE', activated_at = ?, activated_by = ? WHERE version = ?", (utc_now(), actor, version))
    audit(connection, actor, "MODEL_ACTIVATED", "model", version)


def serialize_rows(rows):
    result = []
    for row in rows:
        item = dict(row)
        for key in ("class_distribution_json", "sample_ids_json", "evaluation_json"):
            if key in item:
                item[key[:-5]] = json.loads(item.pop(key))
        result.append(item)
    return result
