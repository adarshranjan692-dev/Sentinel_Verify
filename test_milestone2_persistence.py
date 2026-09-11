"""
Milestone 2 persistence regression test.
Run without arguments to create and verify a fresh persisted screening.
Run with a screening ID after restarting Flask to verify restart retrieval.
"""
import sqlite3
import sys
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:5000"
CREDENTIALS = {"username": "demo@screening.local", "password": "demo123"}
TEST_IMAGE_PATH = Path(__file__).parent / "uploads" / "test_ocr_image.png"


def login():
    session = requests.Session()
    response = session.post(f"{BASE_URL}/login", json=CREDENTIALS)
    response.raise_for_status()
    return session


def verify_persisted_screening(session, screening_id):
    report = session.get(f"{BASE_URL}/screening/{screening_id}").json()
    ocr = session.post(f"{BASE_URL}/ocr", json={"screening_id": screening_id}).json()
    validation = session.post(
        f"{BASE_URL}/validate",
        json={"screening_id": screening_id, "document_type": "Passport"},
    ).json()
    tampering = session.post(
        f"{BASE_URL}/tampering", json={"screening_id": screening_id}
    ).json()
    history = session.get(f"{BASE_URL}/screening-history").json()
    dashboard = session.get(f"{BASE_URL}/dashboard-stats").json()

    assert report["prototype"] is False
    assert report["ocr"]["ocr_source"] == "REAL"
    assert report["tampering"]["tampering_source"] == "REAL"
    assert ocr["ocr_source"] == "REAL"
    assert validation["source"] == "REAL"
    assert tampering["tampering_source"] == "REAL"
    assert len(report["validation"]) == 4
    assert any(row["screening_id"] == screening_id for row in history)
    assert any(row["screening_id"] == screening_id for row in dashboard["recent"])

    connection = sqlite3.connect(Path(__file__).parent / "screening.db")
    stored_filename = connection.execute(
        "SELECT filename FROM documents WHERE screening_id = ?", (screening_id,)
    ).fetchone()[0]
    result_counts = [
        connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE screening_id = ?", (screening_id,)
        ).fetchone()[0]
        for table in (
            "ocr_results",
            "validation_results",
            "tampering_results",
            "face_results",
            "risk_assessments",
        )
    ]
    connection.close()

    assert (Path(__file__).parent / "uploads" / stored_filename).exists()
    assert result_counts == [1, 1, 1, 1, 1]
    print(f"Persisted screening verified: {screening_id}")
    return report


def create_and_verify(session):
    with TEST_IMAGE_PATH.open("rb") as document:
        response = session.post(
            f"{BASE_URL}/upload",
            files={"document": ("milestone2-renamed.png", document, "image/png")},
            data={"document_type": "Passport"},
        )
    response.raise_for_status()
    screening_id = response.json()["screening_id"]
    verify_persisted_screening(session, screening_id)
    print(f"Restart check: rerun this command with {screening_id} after restarting Flask.")
    return screening_id


if __name__ == "__main__":
    session = login()
    if len(sys.argv) > 1:
        verify_persisted_screening(session, sys.argv[1])
    else:
        create_and_verify(session)
    print("Milestone 2 persistence test passed.")
