import csv
import tempfile
import time
import unittest
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from alignment_web.app import create_app
from alignment_web.auth import AuthStore
from alignment_web.statistics import audio_duration, output_sentences
from alignment_web.store import JobStore


def write_wav(path, seconds=2):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0\0' * (8000 * seconds))


def write_csv(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['id', 'start', 'end', 'text'])
        writer.writerow([1, 0, 1, '多行\n文本'])
        writer.writerow([2, 1, 2, '第二句'])


class StatisticsTests(unittest.TestCase):
    def test_metadata_reading_and_empty_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_wav(root / 'normalized.wav')
            write_csv(root / 'result.csv')
            self.assertEqual(audio_duration(root / 'normalized.wav'), 2)
            self.assertEqual(output_sentences(root / 'result.csv'), 2)
            (root / 'result.csv').write_text('id,start,end,text\n', encoding='utf-8')
            self.assertIsNone(output_sentences(root / 'result.csv'))
            self.assertIsNone(audio_duration(root / 'missing.wav'))

    def test_atomic_finish_retry_and_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / 'db.sqlite3')
            store.create('job', 'zh_cn', 'a.wav', 'alice')
            self.assertEqual(store.claim(), 'job')
            store.finish('job', error='failed')
            self.assertEqual(store.usage()['totals']['jobs'], 0)
            self.assertTrue(store.retry('job'))
            self.assertEqual(store.claim(), 'job')
            store.finish('job', audio_seconds=2, sentence_count=3)
            store.finish('job', audio_seconds=99, sentence_count=99)
            stats = store.usage()
            self.assertEqual(stats['totals']['jobs'], 1)
            self.assertEqual(stats['totals']['audio_seconds'], 2)
            self.assertEqual(stats['totals']['sentence_count'], 3)
            self.assertTrue(store.delete('job'))
            self.assertEqual(store.usage()['totals']['jobs'], 1)
            self.assertEqual(store.usage()['current']['completed'], 0)

    def test_legacy_backfill_and_admin_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JobStore(root / 'jobs.sqlite3')
            job_id = 'a' * 32
            store.create(job_id, 'zh_cn', 'old.wav')
            with store.connect() as db:
                db.execute("UPDATE jobs SET status='completed' WHERE id=?", (job_id,))
            folder = root / 'jobs' / job_id
            folder.mkdir(parents=True)
            write_wav(folder / 'normalized.wav')
            write_csv(folder / 'output' / 'result.csv')
            sent = {}
            auth = AuthStore(root / 'accounts.sqlite3', b'x' * 32,
                             lambda email, code: sent.update({email: code}))
            app = create_app(data_dir=root, auth_store=auth)
            with TestClient(app) as admin:
                app.state.stats_worker.join(timeout=5)
                self.assertFalse(app.state.stats_worker.is_alive())
                self.assertEqual(admin.get('/api/admin/usage').status_code, 401)
                def login(client, email):
                    self.assertEqual(client.post('/api/auth/request-code', json={'email': email}).status_code, 200)
                    result = client.post('/api/auth/verify-code', json={'email': email, 'code': sent[email]})
                    self.assertEqual(result.status_code, 200)
                    return {'x-csrf-token': result.json()['csrf_token']}
                alice = TestClient(app)
                login(alice, 'alice@dataoceanai.com')
                self.assertEqual(alice.get('/api/admin/usage').status_code, 403)
                headers = login(admin, 'duhu@dataoceanai.com')
                stats = admin.get('/api/admin/usage').json()
                self.assertEqual(stats['totals']['jobs'], 1)
                self.assertEqual(stats['totals']['audio_seconds'], 2)
                self.assertEqual(stats['totals']['sentence_count'], 2)
                self.assertEqual(stats['totals']['language_count'], 1)
                self.assertEqual(stats['users'][0]['username'], '历史任务')
                self.assertEqual(admin.delete('/v1/jobs/' + job_id, headers=headers).status_code, 200)
                self.assertEqual(admin.get('/api/admin/usage').json()['totals']['jobs'], 1)
                store.fill_statistics(job_id, 8, 8)
                self.assertEqual(admin.get('/api/admin/usage').json()['totals']['audio_seconds'], 2)
