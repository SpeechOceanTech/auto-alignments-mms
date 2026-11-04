import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alignment_web.auth import require_account
from alignment_web.language_check import check_language, router

ENGLISH = ('Today we are going to discuss how to make the work more efficient and how '
           'everyone can cooperate to achieve better results together. ') * 4
FRENCH = ('Nous allons maintenant discuter des différentes façons de travailler ensemble '
          'et de trouver des solutions pour améliorer notre projet. ') * 4
RUSSIAN = ('Мы сегодня подробно обсудим различные способы работы вместе, чтобы найти '
           'подходящие решения и достичь хороших результатов. ') * 4
CHINESE = '我们今天讨论如何更好地合作并寻找解决问题的方法，希望大家积极参与讨论并提出自己的建议。' * 4


class LanguageCheckTest(unittest.TestCase):
    def test_different_scripts_and_same_script_languages(self):
        self.assertEqual(check_language('zh_cn', ENGLISH)['status'], 'mismatch')
        self.assertEqual(check_language('en_us', RUSSIAN)['status'], 'mismatch')
        result = check_language('en_us', FRENCH)
        self.assertEqual(result['status'], 'mismatch')
        self.assertEqual(result['detected_language'], 'fr_fr')
        self.assertIn('法语', result['message'])
        self.assertEqual(check_language('en_us', ENGLISH)['status'], 'match')
        self.assertEqual(check_language('ru_ru', RUSSIAN)['status'], 'match')

    def test_ids_and_unspoken_annotations_do_not_override_text(self):
        line = 'VeryLongEnglishIdentifierThatMustNotAffectDetection' * 6
        text = f'{line}\t{CHINESE}【{ENGLISH}】\n'
        self.assertNotEqual(check_language('zh_cn', text)['status'], 'mismatch')
        self.assertEqual(check_language('en_us', text)['status'], 'mismatch')

    def test_short_and_ambiguous_are_not_flagged(self):
        for text in ('Hello!', '你好', '1234567890', '【' + ENGLISH + '】'):
            self.assertEqual(check_language('zh_cn', text)['status'], 'uncertain')
        self.assertEqual(check_language('ja_jp', CHINESE)['status'], 'uncertain')
        self.assertEqual(check_language('yue_hk', CHINESE)['status'], 'uncertain')
        self.assertEqual(check_language('xyz', ENGLISH)['status'], 'uncertain')
        # Arabic-script Jawi is a valid way to write Malay.
        jawi = 'ملايو جاوي بهاس دان توليسن ماليسيا يڠ اونتوق كيتا ' * 4
        self.assertNotEqual(check_language('ms_my', jawi)['status'], 'mismatch')
        self.assertEqual(check_language('xyz', RUSSIAN)['status'], 'uncertain')

    def test_malay_and_english_are_checked_conservatively(self):
        result = check_language('ms_my', ENGLISH)
        self.assertEqual(result['status'], 'mismatch')
        self.assertEqual(result['detected_language'], 'en_us')
        self.assertIn('英语', result['message'])
        malay = ('Pada hari ini kami akan membincangkan bagaimana kita dapat meningkatkan '
                 'kerjasama antara semua anggota masyarakat untuk menjadikan kehidupan '
                 'lebih baik dan lebih selamat. Setiap orang mempunyai tanggungjawab '
                 'masing-masing untuk menjaga kebersihan dan membantu jiran-jiran. ') * 4
        self.assertNotEqual(check_language('ms_my', malay)['status'], 'mismatch')
        # Mixed text and Jawi should not be mistaken for pure English.
        self.assertNotEqual(check_language('ms_my', ENGLISH + malay + ENGLISH)['status'], 'mismatch')
        self.assertNotEqual(check_language('ms_my', ENGLISH + 'ملايو جاوي بهاس دان توليسن' + ENGLISH)['status'], 'mismatch')
        self.assertEqual(check_language('ms_my', 'Hello and welcome')['status'], 'uncertain')

    def test_close_languages_do_not_trigger_false_warning(self):
        self.assertNotEqual(check_language('uk_ua', RUSSIAN)['status'], 'mismatch')

    def test_http_contract_and_required_language(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_account] = lambda: {'id': 'test'}
        with TestClient(app) as client:
            response = client.post('/v1/language-check', json={'language': 'en_us', 'text': FRENCH})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'mismatch')
            self.assertEqual(client.post('/v1/language-check', json={'language': '', 'text': ENGLISH}).status_code, 400)
            self.assertEqual(client.post('/v1/language-check', json={'language': 'en_us', 'text': ''}).status_code, 400)
            self.assertEqual(client.post('/v1/language-check', json={'text': ENGLISH}).status_code, 422)
            self.assertEqual(client.post('/v1/language-check', json={'language': 'en_us', 'text': 'a' * (2 * 1024 * 1024 + 1)}).status_code, 413)
        app.dependency_overrides.clear()
        app.state.auth_store = None
        with TestClient(app) as client:
            # No auth_store is installed: the service must never permit an anonymous check.
            self.assertGreaterEqual(client.post('/v1/language-check', json={'language': 'en_us', 'text': ENGLISH}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
