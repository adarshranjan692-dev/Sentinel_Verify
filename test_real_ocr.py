"""
Test real OCR with uploaded test image
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
    print(f"✅ Image uploaded successfully")
    print(f"   Screening ID: {screening_id}")
    print(f"   File: {TEST_IMAGE_PATH.name}")
    return screening_id

def test_real_ocr(session, screening_id):
    """Test if OCR returns real extracted text"""
    payload = {
        "screening_id": screening_id,
        "document_type": "Passport",
        "filename": "test_ocr_image.png"
    }
    
    response = session.post(f"{BASE_URL}/ocr", json=payload)
    if response.status_code != 200:
        print("❌ OCR call failed:", response.json())
        return False
    
    data = response.json()
    ocr_source = data.get('ocr_source', 'UNKNOWN')
    confidence = data.get('confidence')
    fields = data.get('fields', {})
    
    print(f"\n📋 OCR Response:")
    print(f"   OCR Source: {ocr_source}")
    print(f"   Confidence: {confidence}%")
    print(f"   Fields: {json.dumps(fields, indent=6)}")
    
    # Check if it's real OCR
    if ocr_source == 'REAL':
        print("\n✅ REAL OCR WORKING!")
        
        # Check if any actual text was extracted
        raw_text = fields.get('raw_text', '')
        if raw_text:
            print(f"\n📝 Extracted text preview:")
            print(f"   {raw_text[:200]}...")
            
            # Check for expected keywords
            keywords = ['PASSPORT', 'NAME', 'DATE', 'NATIONALITY', 'SMITH']
            found_keywords = [kw for kw in keywords if kw.upper() in raw_text.upper()]
            
            if found_keywords:
                print(f"\n✅ Found expected keywords: {', '.join(found_keywords)}")
                return True
            else:
                print(f"\n⚠️  No expected keywords found in extracted text")
                return False
        else:
            print("\n❌ No text extracted")
            return False
    else:
        print(f"\n❌ Got {ocr_source} instead of REAL OCR")
        print("   Tesseract may not be accessible to Flask process")
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("Phase 2 Real OCR Test - Image Upload & Extraction")
    print("=" * 70)
    
    session = login()
    if not session:
        exit(1)
    
    screening_id = upload_test_image(session)
    if not screening_id:
        exit(1)
    
    success = test_real_ocr(session, screening_id)
    
    print("\n" + "=" * 70)
    if success:
        print("✅ Phase 2 Real OCR is WORKING!")
        print("=" * 70)
        print("\nThe OCR endpoint successfully:")
        print("  • Received uploaded image file")
        print("  • Called Tesseract OCR on it")
        print("  • Extracted real text from the image")
        print("  • Returned ocr_source: REAL")
    else:
        print("❌ Phase 2 Real OCR Test FAILED")
        print("=" * 70)
    
    exit(0 if success else 1)
