"""Read compact usage metadata from completed tasks without loading audio into memory."""
import math
import subprocess
import wave
from pathlib import Path

from alignment_csv import read_alignment_csv


def audio_duration(path):
    try:
        with wave.open(str(path), 'rb') as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            if frames > 0 and rate > 0:
                return frames / rate
    except (OSError, EOFError, wave.Error):
        pass
    # Legacy jobs can contain MP3/FLAC/etc. ffprobe only reads metadata and
    # avoids decoding hours of audio. New normalized files use the WAV header.
    if not path.exists() or path.name == 'normalized.wav':
        return None
    try:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                               capture_output=True, text=True, timeout=10, check=True)
        seconds = float(probe.stdout.strip())
        return seconds if math.isfinite(seconds) and seconds > 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def output_sentences(path):
    try:
        return len(read_alignment_csv(path)) or None
    except (OSError, UnicodeError, ValueError):
        return None
