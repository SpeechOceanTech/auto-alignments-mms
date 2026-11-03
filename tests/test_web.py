"""HTTP service tests with an in-process fake aligner, no model or GPU needed."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from alignment_web.app import create_app


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
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
             'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
             'query_string': b'', 'root_path': '', 'headers': list(headers),
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
            if language == 'fra':
                raise RuntimeError('backend failure')
            self.assertEqual(language, 'eng')
            self.assertEqual(audio.read_bytes(), b'audio')
            self.assertEqual(text.read_text(), 'one\ntwo')
            result = {}
            for name in ('csv', 'textgrid', 'txt'):
                result[name] = output / ('actual.' + name)
                result[name].write_text(name)
            return result
        self.app = create_app(data_dir=self.temp.name, runner=runner, max_audio_bytes=8)
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
        self.assertIn('eng', [item['code'] for item in json.loads(languages)['languages']])
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
