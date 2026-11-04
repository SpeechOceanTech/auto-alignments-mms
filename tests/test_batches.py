import asyncio
import io
import json
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alignment_web.app import create_app
from alignment_web.auth import require_account
from test_web import call, form


class BatchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        def runner(audio, text, language, output):
            result = {}
            for kind in ('csv', 'textgrid', 'txt'):
                path = output / ('result.' + kind)
                path.write_text('id,start,end,text\n1,0,1,hello\n' if kind == 'csv' else kind)
                result[kind] = path
            return result
        self.app = create_app(data_dir=self.temp.name, runner=runner, max_audio_bytes=1024,
                              converter=lambda source, target: target.write_bytes(source.read_bytes()))
        self.user = {'id': 'owner', 'is_admin': False}
        self.app.dependency_overrides[require_account] = lambda: self.user
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()

    async def asyncTearDown(self):
        await self.lifespan.__aexit__(None, None, None)
        self.temp.cleanup()

    async def request_json(self, path, data):
        return await call(self.app, 'POST', path, json.dumps(data).encode(), [(b'content-type', b'application/json')])

    async def upload(self, batch_id, audio='A.wav', text='a.txt', language='en_us'):
        body, headers = form({'language': language, 'batch_id': batch_id},
                             [('audio', audio, b'audio'), ('text_file', text, b'hello')])
        status, data = await call(self.app, 'POST', '/v1/jobs', body, headers)
        return status, json.loads(data)

    async def test_pair_upload_and_download_permissions(self):
        manifest = {'audio_names': ['A.wav', 'unused.wav', 'dupe.wav', 'dupe.mp3'],
                    'text_names': ['a.txt', 'orphan.txt', 'dupe.txt'], 'language': 'en_us'}
        status, data = await self.request_json('/v1/batches/check', manifest)
        self.assertEqual(status, 200)
        result = json.loads(data)
        self.assertEqual(result['pairs'], [{'audio': 'A.wav', 'text': 'a.txt'}])
        self.assertEqual(result['unmatched_audio'], ['unused.wav'])
        self.assertEqual(result['unmatched_text'], ['orphan.txt'])
        self.assertEqual(result['duplicates'][0]['stem'], 'dupe')
        status, data = await self.request_json('/v1/batches', {**manifest, 'language': ''})
        self.assertEqual(status, 400)
        status, data = await self.request_json('/v1/batches', manifest)
        self.assertEqual(status, 201)
        batch_id = json.loads(data)['batch_id']
        self.assertEqual((await self.upload(batch_id, text='orphan.txt'))[0], 400)
        self.assertEqual((await self.upload(batch_id, language='zh_cn'))[0], 400)
        status, first = await self.upload(batch_id)
        self.assertEqual(status, 202)
        status, second = await self.upload(batch_id)
        self.assertEqual((status, second['job_id']), (202, first['job_id']))
        for _ in range(200):
            _, data = await call(self.app, 'GET', '/v1/jobs/' + first['job_id'])
            if json.loads(data)['status'] == 'completed':
                break
            await asyncio.sleep(.01)
        self.assertEqual(json.loads(data)['status'], 'completed')
        status, data = await call(self.app, 'GET', '/v1/jobs?batch_id=' + batch_id)
        self.assertEqual((status, json.loads(data)['total']), (200, 1))
        status, data = await call(self.app, 'GET', '/v1/batches/' + batch_id + '/artifacts.zip')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.namelist(), ['A.csv'])
            self.assertIn(b'Name\tStart\tDuration', archive.read('A.csv'))
        self.user = {'id': 'other', 'is_admin': False}
        self.assertEqual((await call(self.app, 'GET', '/v1/jobs?batch_id=' + batch_id))[0], 404)
        self.assertEqual((await call(self.app, 'GET', '/v1/batches/' + batch_id + '/artifacts.zip'))[0], 404)
        self.assertEqual((await self.upload(batch_id))[0], 404)
        self.assertEqual(json.loads((await call(self.app, 'GET', '/v1/batches'))[1])['batches'], [])
        self.user = {'id': 'admin', 'is_admin': True}
        self.assertEqual((await call(self.app, 'GET', '/v1/batches/' + batch_id + '/artifacts.zip'))[0], 200)

    async def test_duplicate_http_uploads_keep_one_directory(self):
        manifest = {'audio_names': ['A.wav'], 'text_names': ['a.txt'], 'language': 'en_us'}
        _, data = await self.request_json('/v1/batches', manifest)
        batch_id = json.loads(data)['batch_id']
        results = await asyncio.gather(self.upload(batch_id), self.upload(batch_id))
        self.assertTrue(all(status == 202 for status, _ in results))
        self.assertEqual(results[0][1]['job_id'], results[1][1]['job_id'])
        jobs = self.app.state.store.batch_jobs(batch_id)
        self.assertEqual(len(jobs), 1)
        self.assertEqual([path.name for path in (Path(self.temp.name) / 'jobs').iterdir()], [jobs[0]['id']])
        self.assertTrue((Path(self.temp.name) / 'jobs' / jobs[0]['id'] / 'normalized.wav').exists())

    async def test_standard_arabic_batch_and_filter(self):
        manifest = {'audio_names': ['A.wav'], 'text_names': ['a.txt'], 'language': 'ar_msa'}
        status, data = await self.request_json('/v1/batches', {**manifest, 'language': 'ar_001'})
        self.assertEqual(status, 400)
        status, data = await self.request_json('/v1/batches', manifest)
        self.assertEqual(status, 201)
        batch_id = json.loads(data)['batch_id']
        self.assertEqual((await self.upload(batch_id, language='ar_001'))[0], 400)
        self.assertEqual((await self.upload(batch_id, language='ar_msa'))[0], 202)
        status, data = await call(self.app, 'GET', '/v1/jobs?language=ar_msa')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)['total'], 1)
        self.assertEqual((await call(self.app, 'GET', '/v1/jobs?language=ar_001'))[0], 400)

    async def test_same_pair_atomic_duplicate_submission(self):
        manifest = {'audio_names': ['A.wav'], 'text_names': ['a.txt'], 'language': 'en_us'}
        status, data = await self.request_json('/v1/batches', manifest)
        batch_id = json.loads(data)['batch_id']
        store = self.app.state.store
        def insert(i):
            return store.create(f'{i:032x}', 'en_us', 'A.wav', 'owner', batch_id, 'A.wav', 'a.txt')
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(insert, range(1, 9)))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len(store.batch_jobs(batch_id)), 1)
