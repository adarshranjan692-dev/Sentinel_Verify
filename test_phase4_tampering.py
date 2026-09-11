"""
Phase 4: Real Image Tampering Detection Test
Test the image forensics analysis pipeline
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

def test_tampering_analysis(session, screening_id):
    """Test real tampering analysis from uploaded image"""
    payload = {
        "screening_id": screening_id
    }
    
    response = session.post(f"{BASE_URL}/tampering", json=payload)
    if response.status_code != 200:
        print("❌ Tampering analysis failed:", response.json())
        return False
    
    data = response.json()
    tampering_source = data.get('tampering_source', 'UNKNOWN')
    risk_score = data.get('risk', 'N/A')
    status = data.get('status', 'Unknown')
    regions = data.get('regions', [])
    explanation = data.get('explanation', '')
    
    print(f"\n📋 Tampering Analysis Results:")
    print(f"   Source: {tampering_source}")
    print(f"   Risk Score: {risk_score}/100")
    print(f"   Status: {status}")
    
    print(f"\n   Detected Issues:")
    for region in regions:
        print(f"     • {region}")
    
    print(f"\n   Analysis Details:")
    print(f"     {explanation[:150]}...")
    
    # Check if it's real analysis
    if tampering_source != 'REAL':
        print(f"\n❌ Expected REAL tampering analysis, got {tampering_source}")
        return False
    
    if not isinstance(risk_score, (int, float)):
        print(f"❌ Expected numeric risk score, got {type(risk_score)}")
        return False
    
    return True

def test_full_pipeline(session, screening_id):
    """Test that OCR + Validation + Tampering all work together"""
    
    print(f"\n" + "=" * 70)
    print("Complete Pipeline Test (OCR + Validation + Tampering)")
    print("=" * 70)
    
    # Test OCR
    ocr_payload = {
        "screening_id": screening_id,
        "document_type": "Passport"
    }
    ocr_response = session.post(f"{BASE_URL}/ocr", json=ocr_payload)
    if ocr_response.status_code != 200:
        print("❌ OCR failed")
        return False
    ocr_data = ocr_response.json()
    print(f"✅ OCR: {ocr_data.get('ocr_source')} (confidence: {ocr_data.get('confidence')}%)")
    
    # Test Validation
    validate_payload = {
        "screening_id": screening_id,
        "document_type": "Passport"
    }
    validate_response = session.post(f"{BASE_URL}/validate", json=validate_payload)
    if validate_response.status_code != 200:
        print("❌ Validation failed")
        return False
    validate_data = validate_response.json()
    passed_checks = sum(1 for c in validate_data.get('checks', []) if c['status'] == 'PASS')
    print(f"✅ Validation: {validate_data.get('source')} ({passed_checks} checks passed)")
    
    # Test Tampering
    tampering_payload = {
        "screening_id": screening_id
    }
    tampering_response = session.post(f"{BASE_URL}/tampering", json=tampering_payload)
    if tampering_response.status_code != 200:
        print("❌ Tampering analysis failed")
        return False
    tampering_data = tampering_response.json()
    print(f"✅ Tampering: {tampering_data.get('tampering_source')} (risk: {tampering_data.get('risk')}/100)")
    
    return True

if __name__ == "__main__":
    print("=" * 70)
    print("Phase 4: Real Image Tampering Detection Test")
    print("=" * 70)
    
    session = login()
    if not session:
        exit(1)
    
    # Step 1: Upload image
    screening_id = upload_test_image(session)
    if not screening_id:
        exit(1)
    
    # Step 2: Test tampering analysis
    print("\n📊 Testing Real Tampering Analysis...")
    success = test_tampering_analysis(session, screening_id)
    
    if not success:
        exit(1)
    
    # Step 3: Test full pipeline
    print("\n")
    pipeline_success = test_full_pipeline(session, screening_id)
    
    print("\n" + "=" * 70)
    if pipeline_success:
        print("✅ Phase 4 Real Tampering Detection WORKING!")
        print("=" * 70)
        print("\nThe pipeline successfully:")
        print("  1. Uploaded a document image")
        print("  2. Extracted text using real Tesseract OCR")
        print("  3. Validated extracted fields with real rules")
        print("  4. Analyzed image for tampering indicators using OpenCV")
        print("  5. Returned real tampering analysis results")
        print("\nNow have 3 real data layers:")
        print("  • Real OCR extraction")
        print("  • Real validation checking")
        print("  • Real tampering/forensics analysis")
    else:
        print("❌ Phase 4 Test FAILED")
        print("=" * 70)
    
    exit(0 if pipeline_success else 1)
