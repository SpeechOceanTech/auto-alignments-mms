import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from alignment_web.app import create_app
from alignment_web.auth import AuthStore


class AccountJobIntegrationTest(unittest.TestCase):
    def test_verified_sessions_and_job_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            sent = {}
            auth = AuthStore(Path(temp) / 'accounts.sqlite3', b'x' * 32,
                             lambda email, code: sent.update({email: code}))

            def runner(audio, text, language, output):
                self.assertEqual(language, 'zh_cn')
                results = {}
                for kind in ('csv', 'textgrid', 'txt'):
                    path = output / ('actual.' + kind)
                    path.write_text('id,start,end,text\n1,0,1,你好\n' if kind == 'csv' else kind)
                    results[kind] = path
                return results

            app = create_app(data_dir=temp, runner=runner, auth_store=auth,
                             converter=lambda source, target: target.write_bytes(source.read_bytes()))
            with TestClient(app) as alice:
                bob = TestClient(app)
                self.assertEqual(alice.get('/v1/jobs').status_code, 401)

                def login(client, email):
                    self.assertEqual(client.post('/api/auth/request-code', json={'email': email}).status_code, 200)
                    response = client.post('/api/auth/verify-code', json={'email': email, 'code': sent[email]})
                    self.assertEqual(response.status_code, 200)
                    return {'x-csrf-token': response.json()['csrf_token']}

                alice_headers = login(alice, 'alice@dataoceanai.com')
                bob_headers = login(bob, 'bob@dataoceanai.com')
                admin = TestClient(app)
                admin_headers = login(admin, 'duhu@dataoceanai.com')
                files = {'audio': ('speech.wav', b'audio', 'audio/wav')}
                form = {'language': '中文', 'text': '你好'}
                self.assertEqual(alice.post('/v1/jobs', data=form, files=files).status_code, 403)
                created = alice.post('/v1/jobs', data=form, files=files, headers=alice_headers)
                self.assertEqual(created.status_code, 202)
                job_id = created.json()['job_id']
                for _ in range(200):
                    job = alice.get('/v1/jobs/' + job_id).json()
                    if job['status'] == 'completed':
                        break
                    time.sleep(.01)
                self.assertEqual(job['status'], 'completed')
                self.assertEqual(job['language'], 'zh_cn')
                self.assertEqual(bob.get('/v1/jobs').json()['total'], 0)
                self.assertNotIn('owner_username', alice.get('/v1/jobs').json()['jobs'][0])
                self.assertEqual(admin.get('/v1/jobs').json()['jobs'][0]['owner_username'], 'alice')
                # Simulate a user key issued before key management became admin-only.
                alice_id = alice.get('/api/auth/me').json()['user']['id']
                legacy_key = auth.create_api_key(alice_id, 'legacy')
                api = TestClient(app)
                self.assertEqual(api.get('/v1/jobs/' + job_id, headers={'authorization': 'Bearer ' + legacy_key['token']}).status_code, 401)
                key = admin.post('/api/auth/api-keys', json={'name': 'test'}, headers=admin_headers)
                self.assertEqual(key.status_code, 200)
                token = key.json()['token']
                bearer = {'authorization': 'Bearer ' + token}
                self.assertEqual(api.get('/v1/jobs/' + job_id, headers=bearer).status_code, 200)
                self.assertEqual(api.get('/api/auth/api-keys', headers=bearer).status_code, 403)
                for suffix in ('', '/input/audio', '/sentences', '/artifacts/csv'):
                    self.assertEqual(bob.get('/v1/jobs/' + job_id + suffix).status_code, 404)
                self.assertEqual(bob.delete('/v1/jobs/' + job_id, headers=bob_headers).status_code, 404)
                self.assertEqual(alice.delete('/v1/jobs/' + job_id).status_code, 403)
                self.assertEqual(alice.delete('/v1/jobs/' + job_id, headers=alice_headers).status_code, 403)
                self.assertEqual(api.delete('/v1/jobs/' + job_id, headers={'authorization': 'Bearer ' + legacy_key['token']}).status_code, 401)
                self.assertEqual(admin.delete('/v1/jobs/' + job_id, headers=admin_headers).status_code, 200)
                self.assertEqual(alice.delete('/api/auth/api-keys/' + legacy_key['key']['id'], headers=alice_headers).status_code, 403)
                self.assertEqual(admin.delete('/api/auth/api-keys/' + key.json()['key']['id'], headers=admin_headers).status_code, 200)
                self.assertEqual(api.get('/v1/jobs', headers=bearer).status_code, 401)


if __name__ == '__main__':
    unittest.main()
