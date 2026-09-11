import unittest

from trustid import analyze_mrz


VALID_TD3 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\nL898902C36UTO7408122F1204159ZE184226B<<<<<10"


class TrustIdMrzTest(unittest.TestCase):
    def test_valid_td3_passport(self):
        result = analyze_mrz(VALID_TD3)
        self.assertTrue(result["available"])
        self.assertTrue(result["parsed"])
        self.assertEqual(result["format"], "TD3")
        self.assertFalse(result["mrz_mismatch"])
        self.assertTrue(all(item["passed"] for item in result["check_results"]))

    def test_invalid_check_digit(self):
        result = analyze_mrz(VALID_TD3.replace("L898902C36", "L898902C37", 1))
        self.assertTrue(result["mrz_mismatch"])
        self.assertTrue(any("check digit" in error.lower() for error in result["mrz_errors"]))

    def test_missing_mrz(self):
        result = analyze_mrz("NAME: TEST PERSON")
        self.assertFalse(result["available"])
        self.assertEqual(result["mrz_consistency"], "NOT_AVAILABLE")

    def test_unsupported_layout_is_not_accepted(self):
        result = analyze_mrz("ID<<<<<<<<<<<<<<1234567890<<<<<<<<<<<<")
        self.assertTrue(result["available"])
        self.assertFalse(result["parsed"])
        self.assertTrue(result["mrz_mismatch"])

    def test_visible_field_mismatch(self):
        result = analyze_mrz(VALID_TD3, {"passport_number": "WRONG123", "nationality": "UTO"})
        self.assertTrue(result["mrz_mismatch"])
        self.assertTrue(any("Passport Number" in error for error in result["mrz_errors"]))


if __name__ == "__main__":
    unittest.main()
