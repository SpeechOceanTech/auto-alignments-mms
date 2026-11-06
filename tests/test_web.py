"""HTTP service tests with an in-process fake aligner, no model or GPU needed."""
import asyncio
import csv
import json
import io
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

from alignment_web.app import _download_stem, create_app
from alignment_web.auth import require_account


async def call(app, method, path, body=b'', headers=(), include_headers=False):
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
    if include_headers:
        return start['status'], content, dict(start['headers'])
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

    async def submit(self, language='en_us', audio=b'audio', text='one\ntwo', filename='file.wav'):
        body, headers = form({'language': language, 'text': text}, [('audio', filename, audio)])
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
        status, content, headers = await call(self.app, 'GET', url + '/artifacts/textgrid', include_headers=True)
        self.assertEqual((status, content), (200, b'textgrid'))
        self.assertEqual(headers[b'content-disposition'], b'attachment; filename="file.TextGrid"')
        status, content = await call(self.app, 'GET', url + '/input/text')
        self.assertEqual((status, content), (200, b'one\ntwo'))
        status, content = await call(self.app, 'DELETE', url)
        self.assertEqual(status, 403)
        self.user = {'id': 'admin', 'is_admin': True}
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
        self.assertEqual(job['error_code'], 'unknown')
        self.assertEqual(job['error_display'], job['error'])
        self.assertEqual((await self.submit(audio=b'123456789'))[0], 413)
        self.assertEqual((await self.submit(language='../bad'))[0], 400)
        self.assertEqual((await self.submit(text=''))[0], 400)
        status, _ = await call(self.app, 'POST', '/v1/jobs', b'', [(b'content-length', b'99999999')])
        self.assertEqual(status, 413)
        body, headers = form({'language': 'eng', 'text': 'hello'}, [('audio', 'a.wav', b'x' * (4 * 1024 * 1024))])
        status, _ = await call(self.app, 'POST', '/v1/jobs', body, headers)
        self.assertEqual(status, 413)

    async def test_known_error_is_explained_for_existing_jobs(self):
        job_id = 'e' * 32
        raw = 'Traceback (most recent call last):\nValueError: Sentence 2 has no alignable characters after normalization'
        directory = Path(self.temp.name) / 'jobs' / job_id
        directory.mkdir()
        (directory / 'input.txt').write_text('first\n\nsegment-2\t-\n', encoding='utf-8')
        with self.app.state.store.connect() as db:
            db.execute("INSERT INTO jobs (id, language, audio_name, status, error, owner_id) VALUES (?, 'zh_cn', 'sample.wav', 'failed', ?, ?)",
                       (job_id, raw, self.user['id']))
        status, content = await call(self.app, 'GET', '/v1/jobs/' + job_id)
        self.assertEqual(status, 200)
        detail = json.loads(content)
        self.assertEqual(detail['error'], raw)
        self.assertNotEqual(detail['error_code'], 'unknown')
        self.assertIn('segment-2', detail['error_display'])
        self.assertIn('3', detail['error_display'])
        status, content = await call(self.app, 'GET', '/v1/jobs?status=failed')
        listed = next(job for job in json.loads(content)['jobs'] if job['id'] == job_id)
        self.assertEqual(listed['error_display'], detail['error_display'])

    async def test_job_duration_is_available_before_completion(self):
        job_id = 'd' * 32
        directory = Path(self.temp.name) / 'jobs' / job_id
        directory.mkdir()
        with wave.open(str(directory / 'normalized.wav'), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b'\0\0' * (16000 * 3))
        with self.app.state.store.connect() as db:
            db.execute("INSERT INTO jobs (id, language, audio_name, status, owner_id) VALUES (?, 'zh_cn', 'sample.wav', 'failed', ?)", (job_id, self.user['id']))
        status, content = await call(self.app, 'GET', '/v1/jobs/' + job_id)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)['audio_duration_seconds'], 3)
        status, content = await call(self.app, 'GET', '/v1/jobs?status=failed')
        listed = next(job for job in json.loads(content)['jobs'] if job['id'] == job_id)
        self.assertEqual(listed['audio_duration_seconds'], 3)

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
            self.assertEqual(set(archive.namelist()), {'file.csv', 'file.txt'})
        status, content = await call(self.app, 'GET', '/v1/jobs/bulk-artifacts.zip?job_ids=' + completed['job_id'])
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(archive.namelist(), ['file.csv'])
        status, content = await call(self.app, 'GET', '/v1/jobs/bulk-artifacts.zip?job_ids=' + completed['job_id'] + '&formats=textgrid')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(archive.namelist(), ['file.TextGrid'])
        self.assertEqual((await call(self.app, 'GET', '/v1/jobs/bulk-artifacts.zip?job_ids=' + completed['job_id'] + '&formats=csv,invalid'))[0], 400)
        self.assertEqual((await call(self.app, 'GET', '/v1/jobs/bulk-artifacts.zip?job_ids=' + failed['job_id']))[0], 409)
        status, _ = await call(self.app, 'POST', '/v1/jobs/' + completed['job_id'] + '/retry')
        self.assertEqual(status, 409)
        status, _ = await call(self.app, 'POST', '/v1/jobs/' + failed['job_id'] + '/retry')
        self.assertEqual(status, 200)
        self.assertEqual((await self.finished(failed['job_id']))['status'], 'failed')

    async def test_download_names_original_audio_and_deduplicates_flat_archives(self):
        self.assertEqual(_download_stem(r'..\目录\名称.v1.wav'), '名称.v1')
        self.assertEqual(_download_stem('../folder/../../unsafe.wav'), 'unsafe')
        self.assertEqual(_download_stem('bad:name?.wav'), 'bad_name_')
        ids = []
        for name in ('语音.片段.wav', '语音.片段.wav', '语音.片段_2.wav', 'recording.v1.wav'):
            _, created = await self.submit(filename=name)
            ids.append(created['job_id'])
            await self.finished(ids[-1])
        status, content, headers = await call(self.app, 'GET', f'/v1/jobs/{ids[0]}/artifacts/csv', include_headers=True)
        self.assertEqual(status, 200)
        self.assertIn(b"filename*=utf-8''%E8%AF%AD%E9%9F%B3.%E7%89%87%E6%AE%B5.csv", headers[b'content-disposition'])
        status, content = await call(self.app, 'GET', '/v1/jobs/bulk-artifacts.zip?job_ids=' + ','.join(ids) + '&formats=csv,txt')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(set(archive.namelist()), {
                '语音.片段.csv', '语音.片段.txt', '语音.片段_2.csv', '语音.片段_2.txt',
                '语音.片段_2_2.csv', '语音.片段_2_2.txt', 'recording.v1.csv', 'recording.v1.txt'})
            self.assertEqual(len(archive.namelist()), 8)

    async def test_audition_downloads_and_sentence_review_for_new_and_old_results(self):
        ids = []
        for filename in ('old.wav', 'new.wav'):
            _, created = await self.submit(filename=filename)
            ids.append(created['job_id'])
            await self.finished(ids[-1])

        old = ('\ufeffid,start,end,text\n'
               'old-id,0.125,1.625,"你好, ""world"""\n').encode('utf-8')
        new = ('Name\tStart\tDuration\tTime Format\tType\tDescription\n'
               'new-id\t00:00:02.000000\t00:00:01.500000\tdecimal\tCue\t第二句\n').encode('utf-8')
        output = Path(self.temp.name) / 'jobs'
        for job_id, original in zip(ids, (old, new)):
            (output / job_id / 'output' / 'result.csv').write_bytes(original)

        expected = [
            {'id': 'old-id', 'start': .125, 'end': 1.625, 'text': '你好, "world"'},
            {'id': 'new-id', 'start': 2.0, 'end': 3.5, 'text': '第二句'},
        ]
        expected_rows = [
            ['old-id', '00:00:00.125000', '00:00:01.500000', 'decimal', 'Cue', '你好, "world"'],
            ['new-id', '00:00:02.000000', '00:00:01.500000', 'decimal', 'Cue', '第二句'],
        ]
        header = ['Name', 'Start', 'Duration', 'Time Format', 'Type', 'Description']

        def check_csv(data, expected_row):
            self.assertFalse(data.startswith(b'\xef\xbb\xbf'))
            rows = list(csv.reader(io.StringIO(data.decode('utf-8'), newline=''), delimiter='\t'))
            self.assertEqual(rows, [header, expected_row])

        for job_id, sentence, row in zip(ids, expected, expected_rows):
            status, content = await call(self.app, 'GET', f'/v1/jobs/{job_id}/sentences')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(content), [sentence])
            status, content, headers = await call(self.app, 'GET', f'/v1/jobs/{job_id}/artifacts/csv?format_version=audition-v2', include_headers=True)
            self.assertEqual(status, 200)
            self.assertEqual(headers[b'cache-control'], b'no-store')
            check_csv(content, row)

        status, content, headers = await call(self.app, 'GET', '/v1/jobs/bulk-artifacts.zip?job_ids=' + ','.join(ids) + '&format_version=audition-v2', include_headers=True)
        self.assertEqual(status, 200)
        self.assertEqual(headers[b'cache-control'], b'no-store')
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            check_csv(archive.read('old.csv'), expected_rows[0])
            check_csv(archive.read('new.csv'), expected_rows[1])
        for job_id, original in zip(ids, (old, new)):
            self.assertEqual((output / job_id / 'output' / 'result.csv').read_bytes(), original)

    async def test_jobs_are_private_and_admin_can_view_legacy(self):
        _, created = await self.submit()
        job_id = created['job_id']
        await self.finished(job_id)
        legacy_id = 'e' * 32
        with self.app.state.store.connect() as db:
            db.execute("INSERT INTO jobs (id, language, audio_name, status) VALUES (?, 'eng', 'old.wav', 'failed')", (legacy_id,))
        self.user = {'id': 'another-user', 'is_admin': False}
        for suffix in ('', '/input/audio', '/input/text', '/artifacts/csv', '/sentences', '/waveform'):
            self.assertEqual((await call(self.app, 'GET', '/v1/jobs/' + job_id + suffix))[0], 404)
        self.assertEqual((await call(self.app, 'GET', '/v1/jobs/bulk-artifacts.zip?job_ids=' + job_id))[0], 404)
        for method, suffix in (('POST', '/retry'), ('DELETE', '')):
            self.assertEqual((await call(self.app, method, '/v1/jobs/' + job_id + suffix))[0], 404)
        _, listed = await call(self.app, 'GET', '/v1/jobs')
        self.assertEqual(json.loads(listed)['total'], 0)
        self.user = {'id': 'admin', 'is_admin': True}
        _, listed = await call(self.app, 'GET', '/v1/jobs')
        jobs = {job['id']: job for job in json.loads(listed)['jobs']}
        self.assertEqual(set(jobs), {job_id, legacy_id})
        self.assertEqual(jobs[legacy_id]['owner_username'], '历史任务')
        self.assertEqual(jobs[job_id]['owner_username'], '未知用户')

    async def test_authentication_required(self):
        self.app.dependency_overrides.clear()
        self.assertEqual((await call(self.app, 'GET', '/v1/jobs'))[0], 503)

    async def test_admin_owner_filter_paginates_and_protects_private_jobs(self):
        store = self.app.state.store
        for job_id, owner, language in [('a' * 32, 'alice', 'en_us'),
                                         ('b' * 32, 'alice', 'en_us'),
                                         ('c' * 32, 'bob', 'en_us'),
                                         ('d' * 32, None, 'en_us'),
                                         ('e' * 32, 'alice', 'fr_fr')]:
            store.create(job_id, language, 'recording.wav', owner)
        self.user = {'id': 'bob', 'is_admin': False}
        for owner in ('alice', '__legacy__'):
            status, _ = await call(self.app, 'GET', '/v1/jobs?owner_id=' + owner)
            self.assertEqual(status, 403)
        _, content = await call(self.app, 'GET', '/v1/jobs')
        self.assertEqual([job['id'] for job in json.loads(content)['jobs']], ['c' * 32])

        self.user = {'id': 'admin', 'is_admin': True}
        _, content = await call(self.app, 'GET', '/v1/jobs?owner_id=alice&language=en_us&limit=1&offset=1')
        result = json.loads(content)
        self.assertEqual(result['total'], 2)
        self.assertEqual([job['id'] for job in result['jobs']], ['a' * 32])
        _, content = await call(self.app, 'GET', '/v1/jobs?owner_id=__legacy__')
        self.assertEqual([job['id'] for job in json.loads(content)['jobs']], ['d' * 32])
        _, content = await call(self.app, 'GET', '/v1/jobs?owner_id=missing')
        self.assertEqual(json.loads(content)['total'], 0)
