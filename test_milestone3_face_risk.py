"""
Milestone 3 face and risk regression test.
The repository fixture is text-only, so this verifies the required safe
undetected-face path and persisted risk derivation. Pass the screening ID
again after restarting Flask to verify restart persistence.
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


def verify(session, screening_id):
    report = session.get(f"{BASE_URL}/screening/{screening_id}").json()
    face = session.post(f"{BASE_URL}/face-verify", json={"screening_id": screening_id}).json()
    risk = session.post(f"{BASE_URL}/risk-score", json={"screening_id": screening_id}).json()
    history = session.get(f"{BASE_URL}/screening-history").json()
    dashboard = session.get(f"{BASE_URL}/dashboard-stats").json()

    assert report["prototype"] is False
    assert face["face_source"] == "REAL"
    assert face["detected"] is False
    assert "Face comparison could not be completed" in risk["reasons"]
    assert risk["risk_source"] == "REAL"
    assert risk["score"] == report["risk"]["score"]
    validation_points = sum(25 if item["status"] == "FAIL" else 10 if item["status"] == "REVIEW" else 0 for item in report["validation"])
    expected_score = min(100, validation_points + round(report["tampering"]["risk"] * 0.35) + 20)
    assert risk["score"] == expected_score
    assert any(row["screening_id"] == screening_id for row in history)
    assert dashboard["total"] >= 1

    connection = sqlite3.connect(Path(__file__).parent / "screening.db")
    counts = [
        connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE screening_id = ?", (screening_id,)
        ).fetchone()[0]
        for table in ("face_results", "risk_assessments")
    ]
    connection.close()
    assert counts == [1, 1]
    print(f"Face failure and derived risk verified: {screening_id}")


def create_and_verify(session):
    with TEST_IMAGE_PATH.open("rb") as document:
        response = session.post(
            f"{BASE_URL}/upload",
            files={"document": ("milestone3-face-failure.png", document, "image/png")},
            data={"document_type": "Passport"},
        )
    response.raise_for_status()
    screening_id = response.json()["screening_id"]
    verify(session, screening_id)
    print(f"Restart check: rerun this command with {screening_id} after restarting Flask.")
    return screening_id


if __name__ == "__main__":
    session = login()
    if len(sys.argv) > 1:
        verify(session, sys.argv[1])
    else:
        create_and_verify(session)
    print("Milestone 3 face/risk test passed.")
