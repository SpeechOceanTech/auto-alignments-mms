"""Bounded-memory waveform envelopes for normalized and legacy audio."""
import tempfile
import wave
from pathlib import Path

import numpy as np

from alignment_core import convert_audio


def waveform(path: Path, points: int):
    """Read a mono PCM recording in bounded chunks and return evenly spaced extrema."""
    path = Path(path)
    if path.name != 'normalized.wav':
        # Older jobs may retain any of the supported upload formats. Decode them
        # temporarily; new jobs already have the exact normalized input on disk.
        with tempfile.TemporaryDirectory(prefix='alignment-waveform-') as directory:
            normalized = Path(directory) / 'normalized.wav'
            convert_audio(path, normalized)
            return _read_pcm(normalized, points)
    return _read_pcm(path, points)


def _read_pcm(path: Path, points: int):
    with wave.open(str(path), 'rb') as audio:
        total = audio.getnframes()
        if (not total or audio.getnchannels() != 1 or audio.getsampwidth() != 2
                or audio.getframerate() <= 0 or audio.getcomptype() != 'NONE'):
            raise ValueError('音频格式无效')
        duration = total / audio.getframerate()
        count = min(points, total)
        peaks = []
        # Limit each read even when a very long file is requested at low resolution.
        chunk_size = 262144
        for index in range(count):
            remaining = (index + 1) * total // count - index * total // count
            low, high = 32767, -32768
            while remaining:
                n = min(chunk_size, remaining)
                data = audio.readframes(n)
                if len(data) != n * 2:
                    raise ValueError('音频文件不完整')
                samples = np.frombuffer(data, dtype='<i2')
                low = min(low, int(samples.min()))
                high = max(high, int(samples.max()))
                remaining -= n
            peaks.append([low / 32768, high / 32768])
        return {'duration': duration, 'peaks': peaks}
