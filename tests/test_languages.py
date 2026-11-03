import unittest

from alignment_languages import COMMON_LANGUAGES, normalize_language


class LanguageTests(unittest.TestCase):
    def test_common_codes_and_legacy_aliases(self):
        self.assertEqual(normalize_language("ZH-CN"), "cmn")
        self.assertEqual(normalize_language(" en_GB "), "eng")
        self.assertEqual(normalize_language("th_th"), "tha")
        self.assertEqual(normalize_language("hr_hr"), "hrv")
        self.assertEqual(normalize_language("my_mm"), "mya")
        self.assertEqual(normalize_language("my_my"), "zsm")
        self.assertEqual(normalize_language("te_in"), "tel")
        self.assertEqual(normalize_language("kn_in"), "kan")

    def test_free_input_and_invalid_values(self):
        self.assertEqual(normalize_language("KIK"), "kik")
        for value in ("", "unknown", "xx", "en_us;echo", "ébc", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_language(value)

    def test_choices_are_distinct_and_usable(self):
        codes = [item["code"] for item in COMMON_LANGUAGES]
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            self.assertEqual(normalize_language(code), code)


if __name__ == "__main__":
    unittest.main()
