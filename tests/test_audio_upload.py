"""Exercise real decoding, storage, playback and retry without the MMS model."""
import io
from pathlib import Path
import tempfile
import time
import unittest
import wave

from fastapi.testclient import TestClient

from alignment_web.app import create_app
from alignment_web.auth import require_account


def stereo_recording():
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b'\x00\x10\x00\xf0' * 4800)
    return audio.getvalue()


class AudioUploadTest(unittest.TestCase):
    def test_conversion_playback_retry_and_rejected_input(self):
        with tempfile.TemporaryDirectory() as temp:
            seen = []
            def runner(audio, text, language, output):
                with wave.open(str(audio), 'rb') as wav:
                    seen.append((audio.name, wav.getframerate(), wav.getnchannels(), wav.getnframes()))
                if len(seen) == 1:
                    raise RuntimeError('simulated failure')
                paths = {}
                for kind in ('csv', 'textgrid', 'txt'):
                    paths[kind] = output / kind
                    paths[kind].write_text(kind)
                return paths
            app = create_app(data_dir=temp, runner=runner)
            app.dependency_overrides[require_account] = lambda: {'id': 'alice', 'is_admin': False}
            with TestClient(app) as client:
                response = client.post('/v1/jobs', data={'language': 'en_us', 'text': 'hello'},
                                       files={'audio': ('original.wav', stereo_recording(), 'audio/wav')})
                self.assertEqual(response.status_code, 202, response.text)
                job_id = response.json()['job_id']
                directory = Path(temp) / 'jobs' / job_id
                self.assertEqual({p.name for p in directory.iterdir()} - {'output'}, {'normalized.wav', 'input.txt'})
                def wait_for(status):
                    for _ in range(200):
                        job = client.get('/v1/jobs/' + job_id).json()
                        if job['status'] == status:
                            return job
                        time.sleep(.01)
                    self.fail(f'job did not reach {status}: {job}')
                wait_for('failed')
                normalized = (directory / 'normalized.wav').read_bytes()
                preview = client.get('/v1/jobs/' + job_id + '/input/audio')
                self.assertEqual(preview.content, normalized)
                self.assertEqual(client.post('/v1/jobs/' + job_id + '/retry').status_code, 200)
                wait_for('completed')
                self.assertEqual(len(seen), 2)
                self.assertTrue(all(name == 'normalized.wav' and rate == 16000 and channels == 1 and frames > 0
                                    for name, rate, channels, frames in seen))
                invalid = client.post('/v1/jobs', data={'language': 'en_us', 'text': 'hello'},
                                      files={'audio': ('broken.mp3', b'not audio', 'audio/mpeg')})
                self.assertEqual(invalid.status_code, 400)
                self.assertEqual([p.name for p in (Path(temp) / 'jobs').iterdir()], [job_id])

    def test_legacy_audio_is_still_available(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_app(data_dir=temp)
            app.dependency_overrides[require_account] = lambda: {'id': 'alice', 'is_admin': False}
            job_id = 'f' * 32
            directory = Path(temp) / 'jobs' / job_id
            directory.mkdir()
            (directory / 'audio.mp3').write_bytes(b'legacy original')
            (directory / '.upload-interrupted.wav').write_bytes(b'partial upload')
            app.state.store.create(job_id, 'en_us', 'legacy.mp3', 'alice')
            with app.state.store.connect() as db:
                db.execute("UPDATE jobs SET status = 'failed' WHERE id = ?", (job_id,))
            with TestClient(app) as client:
                response = client.get('/v1/jobs/' + job_id + '/input/audio')
                self.assertEqual(response.content, b'legacy original')
                self.assertTrue((directory / 'audio.mp3').exists())
                self.assertFalse((directory / '.upload-interrupted.wav').exists())


if __name__ == '__main__':
    unittest.main()
