"""HTTP service tests with an in-process fake aligner, no model or GPU needed."""
import asyncio
import json
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from alignment_web.app import create_app
from alignment_web.auth import require_account


async def call(app, method, path, body=b'', headers=()):
    sent = []
    received = False
    async def receive():
        nonlocal received
        if not received:
            received = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        # FileResponse may listen for disconnect concurrently with streaming.
        await asyncio.sleep(60)
        return {'type': 'http.disconnect'}
    async def send(message):
        sent.append(message)
    path, _, query = path.partition('?')
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
             'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
             'query_string': query.encode(), 'root_path': '', 'headers': list(headers),
             'client': ('127.0.0.1', 12345), 'server': ('localhost', 80)}
    await app(scope, receive, send)
    start = next(item for item in sent if item['type'] == 'http.response.start')
    content = b''.join(item.get('body', b'') for item in sent if item['type'] == 'http.response.body')
    return start['status'], content


def form(fields, files=()):
    boundary = 'alignment-test-boundary'
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    for key, filename, data in files:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + data + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), [(b'content-type', f'multipart/form-data; boundary={boundary}'.encode())]


class WebTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        def runner(audio, text, language, output):
            if language == 'fr_fr':
                raise RuntimeError('backend failure')
            self.assertEqual(language, 'en_us')
            self.assertEqual(audio.read_bytes(), b'audio')
            self.assertEqual(text.read_text(), 'one\ntwo')
            result = {}
            for name in ('csv', 'textgrid', 'txt'):
                result[name] = output / ('actual.' + name)
                result[name].write_text('id,start,end,text\n1,0.123,0.456,one\n2,0.5,1.0,two\n' if name == 'csv' else name)
            return result
        self.app = create_app(data_dir=self.temp.name, runner=runner, max_audio_bytes=8,
                              converter=lambda source, target: target.write_bytes(source.read_bytes()))
        self.user = {'id': 'test-user', 'is_admin': False}
        self.app.dependency_overrides[require_account] = lambda: self.user
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()

    async def asyncTearDown(self):
        await self.lifespan.__aexit__(None, None, None)
        self.temp.cleanup()

    async def submit(self, language='en_us', audio=b'audio', text='one\ntwo'):
        body, headers = form({'language': language, 'text': text}, [('audio','file.wav',audio)])
        status, data = await call(self.app, 'POST', '/v1/jobs', body, headers)
        return status, json.loads(data)

    async def finished(self, job_id):
        for _ in range(200):
            status, data = await call(self.app, 'GET', '/v1/jobs/' + job_id)
            self.assertEqual(status, 200)
            job = json.loads(data)
            if job['status'] in ('completed', 'failed'):
                return job
            await asyncio.sleep(.01)
        self.fail('job did not finish')

    async def test_submit_results_and_delete(self):
        status, response = await self.submit()
        self.assertEqual(status, 202)
        job = await self.finished(response['job_id'])
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(set(job['artifacts']), {'csv', 'textgrid', 'txt'})
        url = '/v1/jobs/' + job['id']
        directory = Path(self.temp.name) / 'jobs' / job['id']
        self.assertEqual({p.name for p in directory.iterdir()}, {'normalized.wav', 'input.txt', 'output'})
        status, content = await call(self.app, 'GET', url + '/input/audio')
        self.assertEqual((status, content), (200, b'audio'))
        status, content = await call(self.app, 'GET', url + '/artifacts/textgrid')
        self.assertEqual((status, content), (200, b'textgrid'))
        status, content = await call(self.app, 'GET', url + '/input/text')
        self.assertEqual((status, content), (200, b'one\ntwo'))
        status, content = await call(self.app, 'DELETE', url)
        self.assertEqual(status, 200)
        status, _ = await call(self.app, 'GET', url)
        self.assertEqual(status, 404)

    async def test_ui_and_text_upload(self):
        status, html = await call(self.app, 'GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('长音频文本对齐', html.decode())
        status, languages = await call(self.app, 'GET', '/v1/languages')
        self.assertEqual(status, 200)
        self.assertIn('en_us', [item['code'] for item in json.loads(languages)['languages']])
        body, headers = form({'language': 'en'}, [('audio', 'a.wav', b'audio'), ('text_file', 'sentences.txt', b'one\ntwo')])
        status, data = await call(self.app, 'POST', '/v1/jobs', body, headers)
        self.assertEqual(status, 202)
        self.assertEqual((await self.finished(json.loads(data)['job_id']))['status'], 'completed')
        body, headers = form({'language': 'eng'}, [('audio', 'a.wav', b'audio'), ('text_file', 'bad.txt', b'\xff')])
        self.assertEqual((await call(self.app, 'POST', '/v1/jobs', body, headers))[0], 400)

    async def test_failure_and_validation(self):
        status, response = await self.submit(language='fra')
        job = await self.finished(response['job_id'])
        self.assertEqual(job['status'], 'failed')
        self.assertIn('backend failure', job['error'])
        self.assertEqual((await self.submit(audio=b'123456789'))[0], 413)
        self.assertEqual((await self.submit(language='../bad'))[0], 400)
        self.assertEqual((await self.submit(text=''))[0], 400)
        status, _ = await call(self.app, 'POST', '/v1/jobs', b'', [(b'content-length', b'99999999')])
        self.assertEqual(status, 413)
        body, headers = form({'language': 'eng', 'text': 'hello'}, [('audio', 'a.wav', b'x' * (4 * 1024 * 1024))])
        status, _ = await call(self.app, 'POST', '/v1/jobs', body, headers)
        self.assertEqual(status, 413)

    async def test_restart_marks_running_as_interrupted(self):
        store = self.app.state.store
        job_id = 'f' * 32
        with store.connect() as db:
            db.execute("INSERT INTO jobs (id, language, audio_name, status) VALUES (?, 'eng', 'a.wav', 'running')", (job_id,))
        store.recover()
        job = store.get(job_id)
        self.assertEqual(job['status'], 'failed')
        self.assertIn('重启', job['error'])

    async def test_management_filters_review_download_and_retry(self):
        _, completed = await self.submit()
        _, failed = await self.submit(language='fra')
        await self.finished(completed['job_id'])
        await self.finished(failed['job_id'])
        status, content = await call(self.app, 'GET', '/v1/jobs?status=completed&language=eng&q=file')
        self.assertEqual(status, 200)
        self.assertEqual([job['id'] for job in json.loads(content)['jobs']], [completed['job_id']])
        status, content = await call(self.app, 'GET', '/v1/jobs/' + completed['job_id'] + '/sentences')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)[0], {'id': '1', 'start': .123, 'end': .456, 'text': 'one'})
        status, content = await call(self.app, 'GET', '/v1/jobs/bulk-artifacts.zip?job_ids=' + completed['job_id'] + '&formats=csv,txt')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(set(archive.namelist()), {completed['job_id'] + '/result.csv', completed['job_id'] + '/result.txt'})
        status, _ = await call(self.app, 'POST', '/v1/jobs/' + completed['job_id'] + '/retry')
        self.assertEqual(status, 409)
        status, _ = await call(self.app, 'POST', '/v1/jobs/' + failed['job_id'] + '/retry')
        self.assertEqual(status, 200)
        self.assertEqual((await self.finished(failed['job_id']))['status'], 'failed')

    async def test_jobs_are_private_and_admin_can_view_legacy(self):
        _, created = await self.submit()
        job_id = created['job_id']
        await self.finished(job_id)
        legacy_id = 'e' * 32
        with self.app.state.store.connect() as db:
            db.execute("INSERT INTO jobs (id, language, audio_name, status) VALUES (?, 'eng', 'old.wav', 'failed')", (legacy_id,))
        self.user = {'id': 'another-user', 'is_admin': False}
        for suffix in ('', '/input/audio', '/input/text', '/artifacts/csv', '/sentences'):
            self.assertEqual((await call(self.app, 'GET', '/v1/jobs/' + job_id + suffix))[0], 404)
        self.assertEqual((await call(self.app, 'GET', '/v1/jobs/bulk-artifacts.zip?job_ids=' + job_id))[0], 404)
        for method, suffix in (('POST', '/retry'), ('DELETE', '')):
            self.assertEqual((await call(self.app, method, '/v1/jobs/' + job_id + suffix))[0], 404)
        _, listed = await call(self.app, 'GET', '/v1/jobs')
        self.assertEqual(json.loads(listed)['total'], 0)
        self.user = {'id': 'admin', 'is_admin': True}
        _, listed = await call(self.app, 'GET', '/v1/jobs')
        self.assertEqual({job['id'] for job in json.loads(listed)['jobs']}, {job_id, legacy_id})

    async def test_authentication_required(self):
        self.app.dependency_overrides.clear()
        self.assertEqual((await call(self.app, 'GET', '/v1/jobs'))[0], 503)
