import unittest

from alignment_languages import COMMON_LANGUAGES, canonical_locale, normalize_language


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
        self.assertEqual(normalize_language("英语"), "eng")
        self.assertEqual(normalize_language("Japanese"), "jpn")
        self.assertEqual(normalize_language("or_in"), "ory")

    def test_free_input_and_invalid_values(self):
        self.assertEqual(normalize_language("KIK"), "kik")
        self.assertEqual(canonical_locale("KIK"), "kik")
        self.assertEqual(canonical_locale("中文"), "zh_cn")
        self.assertEqual(canonical_locale("cmn"), "zh_cn")
        self.assertEqual(canonical_locale("EN-GB"), "en_gb")
        self.assertEqual(canonical_locale("英语（英国）"), "en_gb")
        self.assertEqual(canonical_locale("en-JM"), "en_jm")
        self.assertEqual(normalize_language("en-JM"), "eng")
        for value in ("", "unknown", "xx", "en_us;echo", "ébc", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_language(value)

    def test_choices_are_distinct_and_usable(self):
        codes = [item["code"] for item in COMMON_LANGUAGES]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertGreater(len(codes), 120)
        for item in COMMON_LANGUAGES:
            self.assertEqual(canonical_locale(item['code']), item['code'])
            self.assertEqual(normalize_language(item['code']), item['iso'])
            self.assertEqual(canonical_locale(item['name']), item['code'])


if __name__ == "__main__":
    unittest.main()
