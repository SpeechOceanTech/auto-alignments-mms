import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from alignment_web.fasttext_client import FastTextClient
from alignment_web import fasttext_client
from alignment_web.language_check import check_language

ENGLISH = ('Everyone should work together to improve the community and help '
           'our friends with the important tasks that we need to finish. ') * 5
MALAY = ('Pada hari ini kami akan membincangkan bagaimana kita dapat meningkatkan '
         'kerjasama antara semua anggota masyarakat untuk menjadikan kehidupan '
         'lebih baik dan lebih selamat. ') * 5


def response(code, scores=(.98, .98, .98), labels=('en', 'ms', 'id', 'fr', 'zh')):
    return {'labels': list(labels), 'predictions': [[code, n] for n in scores]}


class LanguagePredictionTest(unittest.TestCase):
    @patch('alignment_web.language_check.fasttext_client.predict')
    def test_malay_chinese_mismatch_and_english(self, predict):
        predict.return_value = response('ms')
        result = check_language('zh_cn', MALAY)
        self.assertEqual(result['status'], 'mismatch')
        self.assertIn('与所选语种不符', result['message'])
        self.assertIsNone(result['detected_language'])
        self.assertEqual(result['detected_name'], '马来语或印度尼西亚语')
        self.assertEqual(check_language('ms_my', MALAY)['status'], 'match')
        # Close Indonesian/Malay must not be asserted as a mismatch.
        self.assertEqual(check_language('id_id', MALAY)['status'], 'uncertain')
        predict.return_value = response('en')
        self.assertEqual(check_language('en_us', ENGLISH)['status'], 'match')
        self.assertEqual(check_language('fr_fr', ENGLISH)['status'], 'mismatch')

    @patch('alignment_web.language_check.fasttext_client.predict')
    def test_ambiguous_mixed_and_unsupported(self, predict):
        predict.return_value = response('ms', scores=(.98, .2, .98))
        self.assertEqual(check_language('ms_my', MALAY)['status'], 'uncertain')
        predict.return_value = response('en')
        predict.return_value['predictions'][1][0] = 'fr'
        self.assertEqual(check_language('fr_fr', ENGLISH)['status'], 'uncertain')
        predict.return_value = response('en', labels=('en',))
        self.assertEqual(check_language('fr_fr', ENGLISH)['status'], 'uncertain')
        predict.return_value = response('ms', scores=(float('nan'), .99, .99))
        self.assertEqual(check_language('ms_my', MALAY)['status'], 'uncertain')
        # Arbitrary ISO-639-3 strings are accepted as input by the aligner but
        # cannot be inferred as supported language names from the model alone.
        predict.return_value = response('als', labels=('en', 'als'))
        self.assertEqual(check_language('en_us', ENGLISH)['status'], 'uncertain')
        predict.return_value = response('no', labels=('no', 'sv'))
        self.assertEqual(check_language('sv_se', ENGLISH)['status'], 'uncertain')

    @patch('alignment_web.language_check.fasttext_client.predict', return_value=None)
    def test_backend_failure_uses_original_detector(self, predict):
        self.assertEqual(check_language('en_us', ENGLISH)['status'], 'match')
        self.assertEqual(check_language('fr_fr', ENGLISH)['status'], 'mismatch')

    @patch('alignment_web.language_check.fasttext_client.predict', return_value=None)
    @patch('alignment_web.language_check._identify', return_value=('id_id', 'ind'))
    def test_original_detector_cannot_distinguish_malay_from_indonesian(self, identify, predict):
        result = check_language('zh_cn', MALAY)
        self.assertEqual(result['status'], 'mismatch')
        self.assertIsNone(result['detected_language'])
        self.assertEqual(result['detected_name'], '马来语或印度尼西亚语')
        self.assertEqual(check_language('id_id', MALAY)['status'], 'uncertain')
        self.assertEqual(check_language('en_us', MALAY)['detected_name'], '马来语或印度尼西亚语')

    @patch('alignment_web.language_check._identify', return_value=('id_id', 'ind'))
    @patch('alignment_web.language_check.fasttext_client.predict')
    def test_low_confidence_pair_is_ambiguous_and_selection_is_not_flagged(self, predict, identify):
        predict.return_value = response('id', scores=(.58, .73, .63))
        result = check_language('zh_cn', MALAY)
        self.assertEqual((result['status'], result['detected_name']), ('mismatch', '马来语或印度尼西亚语'))
        self.assertIn('疑似', result['message'])
        self.assertEqual(check_language('ms_my', MALAY)['status'], 'uncertain')
        self.assertEqual(check_language('id_id', MALAY)['status'], 'uncertain')

        # Disagreement within the closely related pair remains a pair-level
        # guess, while a third language or an uncorroborated guess stays vague.
        predict.return_value['predictions'][1][0] = 'ms'
        self.assertEqual(check_language('zh_cn', MALAY)['detected_name'], '马来语或印度尼西亚语')
        predict.return_value['predictions'][1][0] = 'en'
        self.assertEqual(check_language('zh_cn', MALAY)['detected_name'], '拉丁字母')
        predict.return_value['predictions'][1][0] = 'ms'
        identify.return_value = ('fr_fr', 'fra')
        self.assertEqual(check_language('zh_cn', MALAY)['detected_name'], '拉丁字母')

    @unittest.skipUnless(os.environ.get('ALIGN_TEST_FASTTEXT_MODEL'), 'requires an explicitly provided local model')
    def test_real_local_model_on_synthetic_text(self):
        config = {'ALIGN_LANGUAGE_FASTTEXT_PYTHON': os.environ.get('ALIGN_TEST_FASTTEXT_PYTHON', sys.executable),
                  'ALIGN_LANGUAGE_FASTTEXT_MODEL': os.environ['ALIGN_TEST_FASTTEXT_MODEL']}
        with patch.dict(os.environ, config):
            try:
                result = check_language('zh_cn', MALAY)
                self.assertEqual((result['status'], result['detected_name']), ('mismatch', '马来语或印度尼西亚语'))
                self.assertNotEqual(check_language('ms_my', MALAY)['status'], 'mismatch')
                self.assertEqual(check_language('zh_cn', ENGLISH)['detected_name'], '英语')
            finally:
                fasttext_client.close()


class FakeClient(FastTextClient):
    def __init__(self, script, timeout=1):
        super().__init__(sys.executable, 'unused', timeout=timeout)
        self.script = script
        self.starts = 0

    def _start(self):
        self.starts += 1
        self.process = subprocess.Popen([sys.executable, '-u', '-c', self.script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)


class WorkerClientTest(unittest.TestCase):
    def test_worker_is_reused_and_cleanup(self):
        script = "import sys,json\nfor line in sys.stdin: print(json.dumps({'labels':['en'],'predictions':[['en',.99]]*len(json.loads(line)['pieces'])}),flush=True)"
        client = FakeClient(script)
        try:
            self.assertEqual(client.predict(['hello'])['labels'], ['en'])
            self.assertEqual(client.predict(['second'])['labels'], ['en'])
            self.assertEqual(client.starts, 1)
            process = client.process
        finally:
            client.close()
        self.assertIsNotNone(process.poll())

    def test_crash_and_timeout_fall_back_and_kill(self):
        for script in ('raise SystemExit(1)', 'import time; time.sleep(10)'):
            with self.subTest(script=script):
                client = FakeClient(script, timeout=.15)
                started = time.monotonic()
                try:
                    self.assertIsNone(client.predict(['x' * 100000]))
                    self.assertLess(time.monotonic() - started, 2)
                    self.assertIsNone(client.process)
                    # Failure cooldown avoids repeatedly spawning broken workers.
                    self.assertIsNone(client.predict(['hello']))
                    self.assertEqual(client.starts, 1)
                finally:
                    client.close()

    def test_concurrent_requests_are_serialized(self):
        script = ("import sys,json\nfor line in sys.stdin:\n"
                  " x=json.loads(line)['pieces'][0]; "
                  "print(json.dumps({'labels':[x],'predictions':[[x,.99]]}),flush=True)")
        client = FakeClient(script)
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda text: client.predict([text]), ['a', 'b', 'c', 'd']))
            self.assertEqual([r['labels'][0] for r in results], ['a', 'b', 'c', 'd'])
            self.assertEqual(client.starts, 1)
        finally:
            client.close()

    def test_failure_recovers_with_new_worker(self):
        client = FakeClient('raise SystemExit(1)')
        try:
            self.assertIsNone(client.predict(['hello']))
            client.failed_until = 0
            client.script = ("import sys,json\nfor line in sys.stdin: "
                             "print(json.dumps({'labels':['en'],'predictions':[['en',.99]]}),flush=True)")
            self.assertEqual(client.predict(['hello'])['labels'], ['en'])
            self.assertEqual(client.starts, 2)
        finally:
            client.close()

    def test_real_worker_protocol_with_fake_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'fasttext.py').write_text(
                "class Model:\n"
                " def get_labels(self): return ['__label__en']\n"
                " def predict(self, text, k): return (['__label__en'], [.99])\n"
                "def load_model(path): return Model()\n", encoding='utf-8')
            with patch.dict(os.environ, {'PYTHONPATH': tmp}):
                client = FastTextClient(sys.executable, 'unused', timeout=2)
                try:
                    result = client.predict(['Hello there'])
                    self.assertEqual(result, {'labels': ['en'], 'predictions': [['en', .99]]})
                finally:
                    client.close()

    def test_malformed_output_does_not_escape(self):
        client = FakeClient("import sys; sys.stdin.readline(); print('not json',flush=True)")
        try:
            self.assertIsNone(client.predict(['hello']))
            self.assertIsNone(client.process)
        finally:
            client.close()


if __name__ == '__main__':
    unittest.main()
