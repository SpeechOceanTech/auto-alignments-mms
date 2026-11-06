import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alignment_web.alignment_precheck import check_alignment_density, router
from alignment_web.auth import require_account


class AlignmentPrecheckTest(unittest.TestCase):
    def test_mandarin_high_density_warns_and_boundary_does_not(self):
        text = '说' * 61
        result = check_alignment_density('zh_cn', text, 10)
        self.assertEqual(result['status'], 'warning')
        self.assertEqual(result['character_count'], 61)
        self.assertEqual(result['characters_per_second'], 6.1)
        self.assertEqual(check_alignment_density('zh_cn', '说' * 60, 10)['status'], 'ok')

    def test_excludes_ids_annotations_and_first_header(self):
        text = '\ufeffB角色ID\tB内容\n' + ('汉字' * 50) + '\t你好【' + ('标注' * 50) + '】'
        result = check_alignment_density('zh_cn', text, 1)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['character_count'], 2)

    def test_unknown_is_not_passed(self):
        for language, text, duration in [
            ('zh_cn', '你好', None), ('zh_cn', '你好', 0),
            ('zh_cn', 'hello world', 10), ('en_us', 'hello world', 10),
        ]:
            with self.subTest(language=language, duration=duration):
                self.assertEqual(check_alignment_density(language, text, duration)['status'], 'unknown')

    def test_http_auth_validation_and_contract(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_account] = lambda: {'id': 'test'}
        with TestClient(app) as client:
            response = client.post('/v1/alignment-precheck', json={'language': 'zh_cn', 'text': '你' * 61, 'duration_seconds': 10})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'warning')
            self.assertEqual(client.post('/v1/alignment-precheck', json={'language': 'zh_cn', 'text': '你好', 'duration_seconds': None}).json()['status'], 'unknown')
            self.assertEqual(client.post('/v1/alignment-precheck', json={'language': '', 'text': '你好', 'duration_seconds': 1}).status_code, 400)
            self.assertEqual(client.post('/v1/alignment-precheck', json={'language': 'zh_cn', 'text': '', 'duration_seconds': 1}).status_code, 400)
            self.assertEqual(client.post('/v1/alignment-precheck', json={'language': 'zh_cn', 'text': 'x' * (2 * 1024 * 1024 + 1)}).status_code, 413)
        app.dependency_overrides.clear()
        app.state.auth_store = None
        with TestClient(app) as client:
            self.assertGreaterEqual(client.post('/v1/alignment-precheck', json={'language': 'zh_cn', 'text': '你好'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
