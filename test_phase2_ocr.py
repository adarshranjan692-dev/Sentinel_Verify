"""
Phase 2 OCR Integration Test
Test the real OCR vs fallback behavior
"""
import requests
import json

BASE_URL = "http://127.0.0.1:5000"
CREDENTIALS = {"username": "demo@screening.local", "password": "demo123"}

def login():
    """Authenticate and get session"""
    response = requests.post(f"{BASE_URL}/login", json=CREDENTIALS)
    if response.status_code != 200:
        print("❌ Login failed:", response.json())
        return None
    print("✅ Logged in successfully")
    return response.cookies

def test_demo_ocr(cookies):
    """Test OCR with demo screening (should use fallback)"""
    payload = {
        "screening_id": "SCR-DEMO",
        "document_type": "Passport",
        "filename": "synthetic-document-demo.png"
    }
    response = requests.post(f"{BASE_URL}/ocr", json=payload, cookies=cookies)
    if response.status_code != 200:
        print("❌ Demo OCR failed:", response.json())
        return None
    
    data = response.json()
    print("\n📋 DEMO OCR Result:")
    print(f"  OCR Source: {data.get('ocr_source', 'UNKNOWN')}")
    print(f"  Confidence: {data.get('confidence')}%")
    print(f"  Fields: {json.dumps(data.get('fields', {}), indent=4)}")
    return data

def test_real_ocr_no_file(cookies):
    """Test OCR with non-existent file (should use fallback)"""
    payload = {
        "screening_id": "SCR-TEST123",  # This ID won't exist in DB
        "document_type": "Passport",
        "filename": "nonexistent.png"
    }
    response = requests.post(f"{BASE_URL}/ocr", json=payload, cookies=cookies)
    if response.status_code != 200:
        print("❌ Real OCR test failed:", response.json())
        return None
    
    data = response.json()
    print("\n📋 REAL OCR Test (No File) Result:")
    print(f"  OCR Source: {data.get('ocr_source', 'UNKNOWN')}")
    print(f"  Confidence: {data.get('confidence')}%")
    print(f"  Fields: {json.dumps(data.get('fields', {}), indent=4)}")
    return data

if __name__ == "__main__":
    print("=" * 60)
    print("Phase 2 OCR Integration Test")
    print("=" * 60)
    
    cookies = login()
    if not cookies:
        exit(1)
    
    # Test 1: Demo OCR (should be DEMO_FALLBACK)
    demo_result = test_demo_ocr(cookies)
    assert demo_result.get('ocr_source') == 'DEMO_FALLBACK', \
        f"Expected DEMO_FALLBACK, got {demo_result.get('ocr_source')}"
    print("✅ Demo OCR correctly marked as DEMO_FALLBACK")
    
    # Test 2: Real OCR with no file (should fallback to demo)
    no_file_result = test_real_ocr_no_file(cookies)
    assert no_file_result.get('ocr_source') == 'DEMO_FALLBACK', \
        f"Expected DEMO_FALLBACK for missing file, got {no_file_result.get('ocr_source')}"
    print("✅ Missing file correctly falls back to DEMO_FALLBACK")
    
    print("\n" + "=" * 60)
    print("✅ Phase 2 OCR Integration Tests Passed!")
    print("=" * 60)
    print("\n📝 Next Steps:")
    print("  1. Install Tesseract-OCR on Windows:")
    print("     https://github.com/UB-Mannheim/tesseract/wiki")
    print("  2. Upload an actual document to test REAL OCR processing")
    print("  3. The /ocr endpoint will automatically switch to real OCR")
    print("     when a real file is found and Tesseract is installed")
