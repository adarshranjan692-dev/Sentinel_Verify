import io
from pathlib import Path
import tempfile
import unittest

import app


class TrustIdGovernanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        app.DATABASE = root / "screening.db"
        app.UPLOAD_DIR = root / "uploads"
        app.BASE_DIR = root
        app.init_db()
        app.seed_demo_data()
        app.app.config["TESTING"] = True
        cls.image = Path(__file__).parent / "uploads" / "test_ocr_image.png"

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def login(self, username, password):
        client = app.app.test_client()
        response = client.post("/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200)
        return client

    def create_case(self, client, expected_model_status="NOT_AVAILABLE"):
        with self.image.open("rb") as source:
            response = client.post(
                "/upload",
                data={"document_type": "Passport", "document": (io.BytesIO(source.read()), "case.png", "image/png")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["ml"]["model_status"], expected_model_status)
        self.assertEqual(len(result["features"]), 17)
        return result["screening_id"]

    def test_governed_model_lifecycle(self):
        reviewer = self.login("reviewer@trustid.local", "reviewer123")
        self.assertEqual(reviewer.get("/references").status_code, 403)
        self.assertEqual(reviewer.post("/references", json={"document_type": "Passport", "document_number": "REF12345", "fields": {}}).status_code, 403)
        cases = [self.create_case(reviewer) for _ in range(12)]
        labels = ["GENUINE"] * 4 + ["SUSPICIOUS"] * 4 + ["FRAUDULENT"] * 4
        for screening_id, label in zip(cases, labels):
            response = reviewer.post("/review", json={"screening_id": screening_id, "trusted_label": label, "notes": "Reviewed test evidence"})
            self.assertEqual(response.status_code, 200)

        forbidden = reviewer.post("/models/train", json={"dataset_version": "missing"})
        self.assertEqual(forbidden.status_code, 403)
        admin = self.login("admin@trustid.local", "admin123")
        reference = admin.post("/references", json={"document_type": "Passport", "document_number": "REF12345", "fields": {"name": "REFERENCE USER"}})
        self.assertEqual(reference.status_code, 201)
        self.assertEqual(admin.get("/references?q=Passport").status_code, 200)
        dataset = admin.post("/datasets").get_json()["version"]
        self.assertEqual(admin.post(f"/datasets/{dataset}/publish").status_code, 200)
        trained = admin.post("/models/train", json={"dataset_version": dataset})
        self.assertEqual(trained.status_code, 201)
        model = trained.get_json()["version"]
        self.assertEqual(trained.get_json()["evaluation"]["sample_count"], 12)
        self.assertEqual(admin.post(f"/models/{model}/approve").status_code, 200)
        self.assertEqual(admin.post(f"/models/{model}/activate").status_code, 200)
        active_case = self.create_case(admin, expected_model_status="ACTIVE")
        result = admin.get(f"/screening/{active_case}").get_json()
        self.assertEqual(result["ml"]["model_status"], "ACTIVE")
        self.assertEqual(result["ml"]["model_version"], model)
        self.assertEqual(result["ml"]["dataset_version"], dataset)
        self.assertTrue(result["ml"]["top_feature_influences"])
        history = admin.get("/audit").get_json()
        self.assertTrue(any(item["action"] == "MODEL_ACTIVATED" for item in history))


if __name__ == "__main__":
    unittest.main()
