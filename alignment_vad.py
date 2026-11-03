"""Silero speech detection and the original silence_enrich boundary adjustment."""
from pathlib import Path
import os
import subprocess

SAMPLE_RATE = 16000


def speech_timestamps(wav):
    """Return speech intervals in seconds, using the original Silero ONNX model."""
    try:
        import torchaudio
        from alignment_support.silero import OnnxWrapper, get_speech_timestamps
    except (ImportError, OSError) as exc:
        raise RuntimeError("Silero VAD requires PyTorch, torchaudio and onnxruntime") from exc
    model_path = Path(os.environ.get("SILERO_VAD_MODEL", Path(__file__).parent / "alignment_support/silero/silero_vad.onnx"))
    if not model_path.is_file():
        raise FileNotFoundError(f"Silero VAD model not found: {model_path}")
    waveform, rate = torchaudio.load(str(wav))
    if rate != SAMPLE_RATE or waveform.shape[0] != 1 or waveform.shape[1] == 0:
        raise ValueError("Converted audio must be nonempty, mono and 16 kHz")
    model = OnnxWrapper(str(model_path), force_onnx_cpu=True)
    timestamps = get_speech_timestamps(waveform[0], model, sampling_rate=SAMPLE_RATE)
    if timestamps:
        return [(item['start'] / SAMPLE_RATE, item['end'] / SAMPLE_RATE) for item in timestamps]
    # Match demo.py: if Silero finds no speech, run the existing vad_tts fallback.
    try:
        subprocess.run(["vad_tts", "-p", str(wav)], check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("Silero detected no speech and the original vad_tts fallback is unavailable") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"vad_tts failed: {exc.stderr.strip()}") from exc
    path = Path(str(wav) + ".vad.2")
    if not path.is_file():
        raise RuntimeError("vad_tts did not produce its .vad.2 output")
    return [tuple(map(float, line.split())) for line in path.read_text().splitlines() if line.strip()]


def refine_times(times, speech, duration):
    """Apply silence_enrich.py's 0.8 s nearest-silence and overlap rules."""
    if not times:
        return []
    if not speech:
        raise ValueError("VAD returned no speech intervals")
    silences = []
    previous = 0.0
    for start, end in speech:
        if not 0 <= previous <= start <= end <= duration:
            raise ValueError("Invalid VAD speech intervals")
        silences.append((previous, start))
        previous = end
    silences.append((previous, duration))
    refined = []
    for index, (start, end) in enumerate(times):
        # The original JSON reader rounds MMS timestamps before refining.
        start, end = round(start, 3), round(end, 3)
        starts = [(abs(start - b), (a + b) / 2) for a, b in silences if abs(start - b) < 0.8]
        ends = [(abs(end - a), (a + b) / 2) for a, b in silences if abs(end - a) < 0.8]
        new_start = min(starts, key=lambda item: item[0])[1] if starts else start
        new_end = min(ends, key=lambda item: item[0])[1] if ends else end
        if not new_start:
            new_start = start
        if index == len(times) - 1:
            new_end = sum(silences[-1]) / 2
        if not new_end:
            new_end = end
        refined.append([new_start, new_end])
    final = [refined[0]]
    prev_end = refined[0][1]
    for start, end in refined[1:]:
        if start < prev_end:
            middle = max((start + prev_end) / 2, final[-1][0])
            final[-1][1] = middle
            start, end = middle, max(end, middle)
        final.append([start, end])
        prev_end = end
    return [tuple(item) for item in final]
