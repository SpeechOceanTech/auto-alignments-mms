"""Read compact usage metadata from completed tasks without loading audio into memory."""
import csv
import math
import subprocess
import wave
from pathlib import Path


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
        with Path(path).open(encoding='utf-8-sig', newline='') as source:
            rows = csv.DictReader(source)
            if not rows.fieldnames or not {'id', 'start', 'end', 'text'} <= set(rows.fieldnames):
                return None
            count = 0
            for row in rows:
                if None in row or any(row.get(key) is None for key in ('id', 'start', 'end', 'text')):
                    return None
                count += 1
            return count if count else None
    except (OSError, UnicodeError, csv.Error):
        return None
