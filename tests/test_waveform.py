"""Waveform envelopes preserve audio extremes and respect job permissions."""
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from alignment_web.app import create_app
from alignment_web.auth import require_account
from alignment_web.waveform import _read_pcm


def write_wav(path, samples, rate=4):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(struct.pack('<' + 'h' * len(samples), *samples))


class WaveformTest(unittest.TestCase):
    def test_envelope_and_bounded_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'normalized.wav'
            # A bucket larger than the internal read limit still has correct extrema.
            samples = [0] * 262145 + [-32768, 32767, 16384]
            write_wav(path, samples, 16000)
            data = _read_pcm(path, 1)
            self.assertEqual(data['duration'], len(samples) / 16000)
            self.assertEqual(data['peaks'], [[-1.0, 32767 / 32768]])
            self.assertEqual(len(_read_pcm(path, 3)['peaks']), 3)

    def test_api_owner_admin_and_legacy(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_app(data_dir=temp)
            user = {'id': 'alice', 'is_admin': False}
            app.dependency_overrides[require_account] = lambda: user
            job_id = 'f' * 32
            folder = Path(temp) / 'jobs' / job_id
            folder.mkdir()
            write_wav(folder / 'normalized.wav', [-32768, -16384] * 4000 + [0, 32767] * 4000, 16000)
            app.state.store.create(job_id, 'en_us', 'audio.wav', 'alice')
            with app.state.store.connect() as db:
                db.execute("UPDATE jobs SET status = 'failed' WHERE id = ?", (job_id,))
            with TestClient(app) as client:
                url = '/v1/jobs/' + job_id + '/waveform'
                data = client.get(url, params={'points': 2})
                self.assertEqual(data.status_code, 200)
                self.assertEqual(data.json(), {'duration': 1.0,
                                              'peaks': [[-1.0, -.5], [0.0, 32767 / 32768]]})
                self.assertEqual(client.get(url, params={'points': 48001}).status_code, 422)
                user = {'id': 'bob', 'is_admin': False}
                self.assertEqual(client.get(url).status_code, 404)
                user = {'id': 'admin', 'is_admin': True}
                self.assertEqual(client.get(url).status_code, 200)
                # Pre-migration tasks keep original audio under their old name.
                (folder / 'normalized.wav').rename(folder / 'audio.wav')
                response = client.get(url, params={'points': 2})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertAlmostEqual(response.json()['duration'], 1.0)
                self.assertEqual(len(response.json()['peaks']), 2)
                self.assertEqual({p.name for p in folder.iterdir()}, {'audio.wav'})
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(folder / 'audio.wav'),
                                '-y', str(folder / 'audio.mp3')], check=True)
                (folder / 'audio.wav').unlink()
                with app.state.store.connect() as db:
                    db.execute("UPDATE jobs SET audio_name = 'audio.mp3' WHERE id = ?", (job_id,))
                compressed = client.get(url, params={'points': 2})
                self.assertEqual(compressed.status_code, 200, compressed.text)
                self.assertAlmostEqual(compressed.json()['duration'], 1.0, places=2)
                self.assertEqual(len(compressed.json()['peaks']), 2)
                self.assertEqual({p.name for p in folder.iterdir()}, {'audio.mp3'})


if __name__ == '__main__':
    unittest.main()
