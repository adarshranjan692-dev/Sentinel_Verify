"""
Phase 3 Validation Pipeline Test
Test the real OCR → field extraction → validation flow
"""
import requests
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:5000"
CREDENTIALS = {"username": "demo@screening.local", "password": "demo123"}
TEST_IMAGE_PATH = Path(__file__).parent / "uploads" / "test_ocr_image.png"

def login():
    """Authenticate and get session"""
    session = requests.Session()
    response = session.post(f"{BASE_URL}/login", json=CREDENTIALS)
    if response.status_code != 200:
        print("❌ Login failed:", response.json())
        return None
    print("✅ Logged in successfully")
    return session

def upload_test_image(session):
    """Upload test image and get screening_id"""
    if not TEST_IMAGE_PATH.exists():
        print(f"❌ Test image not found at {TEST_IMAGE_PATH}")
        return None
    
    with open(TEST_IMAGE_PATH, 'rb') as f:
        files = {'document': (TEST_IMAGE_PATH.name, f, 'image/png')}
        data = {'document_type': 'Passport'}
        response = session.post(f"{BASE_URL}/upload", files=files, data=data)
    
    if response.status_code != 200:
        print("❌ Upload failed:", response.json())
        return None
    
    result = response.json()
    screening_id = result.get('screening_id')
    print(f"✅ Image uploaded")
    print(f"   Screening ID: {screening_id}")
    return screening_id

def test_ocr_extraction(session, screening_id):
    """Test OCR extraction from uploaded image"""
    payload = {
        "screening_id": screening_id,
        "document_type": "Passport",
        "filename": "test_ocr_image.png"
    }
    
    response = session.post(f"{BASE_URL}/ocr", json=payload)
    if response.status_code != 200:
        print("❌ OCR failed:", response.json())
        return None
    
    data = response.json()
    ocr_source = data.get('ocr_source')
    raw_text = data.get('fields', {}).get('raw_text', '')
    
    print(f"\n📋 OCR Extraction Results:")
    print(f"   Source: {ocr_source}")
    print(f"   Confidence: {data.get('confidence')}%")
    print(f"   Extracted text: {raw_text[:100]}...")
    
    if ocr_source != "REAL":
        print(f"❌ Expected REAL OCR, got {ocr_source}")
        return None
    
    return data

def test_validation_pipeline(session, screening_id):
    """Test validation pipeline using real OCR data"""
    payload = {
        "screening_id": screening_id,
        "document_type": "Passport"
    }
    
    response = session.post(f"{BASE_URL}/validate", json=payload)
    if response.status_code != 200:
        print("❌ Validation failed:", response.json())
        return False
    
    data = response.json()
    source = data.get('source')
    checks = data.get('checks', [])
    extracted = data.get('extracted_fields', {})
    
    print(f"\n✅ Validation Pipeline Results:")
    print(f"   Data source: {source}")
    print(f"   Total checks: {len(checks)}")
    
    if source != "REAL":
        print(f"❌ Expected REAL validation source, got {source}")
        return False
    
    print(f"\n   Extracted Fields:")
    for field, value in extracted.items():
        print(f"     • {field}: {value}")
    
    print(f"\n   Validation Checks:")
    for check in checks:
        status_emoji = "✅" if check['status'] == "PASS" else "⚠️" if check['status'] == "REVIEW" else "❌"
        print(f"     {status_emoji} {check['label']}")
        print(f"        └─ {check['detail']}")
    
    # Count results
    passed = sum(1 for c in checks if c['status'] == 'PASS')
    review = sum(1 for c in checks if c['status'] == 'REVIEW')
    failed = sum(1 for c in checks if c['status'] == 'FAIL')
    
    print(f"\n   Summary: {passed} PASS, {review} REVIEW, {failed} FAIL")
    
    return True

if __name__ == "__main__":
    print("=" * 70)
    print("Phase 3: Real OCR → Validation Pipeline Test")
    print("=" * 70)
    
    session = login()
    if not session:
        exit(1)
    
    # Step 1: Upload image
    screening_id = upload_test_image(session)
    if not screening_id:
        exit(1)
    
    # Step 2: Test OCR extraction
    ocr_result = test_ocr_extraction(session, screening_id)
    if not ocr_result:
        exit(1)
    
    # Step 3: Test validation pipeline
    success = test_validation_pipeline(session, screening_id)
    
    print("\n" + "=" * 70)
    if success:
        print("✅ Phase 3 Real OCR → Validation Pipeline WORKING!")
        print("=" * 70)
        print("\nThe pipeline successfully:")
        print("  1. Uploaded a document image")
        print("  2. Extracted text using real Tesseract OCR")
        print("  3. Parsed extracted text into structured fields")
        print("  4. Ran validation rules on the extracted data")
        print("  5. Returned real validation results")
        print("\nThis is a complete end-to-end pipeline from image to validation.")
    else:
        print("❌ Phase 3 Test FAILED")
        print("=" * 70)
    
    exit(0 if success else 1)
