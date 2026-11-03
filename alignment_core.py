"""Sentence-level alignment using the multilingual MMS CTC model.

The model architecture, text normalization and star-token approach are adapted
from MMS/fairseq and MXuer/mms-alignment-tools. Model files are never fetched
implicitly. Set MMS_MODEL_PATH to a local model.pt and UROMAN_PATH to uroman's
bin directory if the bundled copy should not be used.
"""
from __future__ import annotations

import csv
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave

from alignment_languages import normalize_language
from alignment_csv import write_audition_csv
from alignment_support.text_normalization import text_normalize
from alignment_vad import refine_times, speech_timestamps

ROOT = Path(__file__).resolve().parent
SAMPLE_RATE = 16000
SPECIAL_ISOS = set("ara bel bul deu ell eng fas grc heb kaz kir lav lit mkd mkd2 oss pnt pus rus srp srp2 tur uig ukr yid".split())


def read_sentences(path):
    """Read UTF-8 text, one sentence per line; optional ID<TAB>sentence."""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    sentences = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        if "\t" in line:
            name, text = line.split("\t", 1)
            if not name.strip() or not text.strip():
                raise ValueError(f"Line {number}: ID and sentence must both be nonempty")
            name, text = name.strip(), text.strip()
        else:
            name, text = str(len(sentences) + 1), line.strip()
        sentences.append((name, text))
    if not sentences:
        raise ValueError("Transcript must contain at least one nonempty sentence")
    return sentences


def romanize(sentences, language):
    # Bracketed annotations are metadata, not spoken words. Keep `sentences`
    # untouched so result files and the review page retain the original text.
    normal = [text_normalize(re.sub(r"【[^】]*】", " ", text), language)
              for _, text in sentences]
    for i, line in enumerate(normal):
        if not line.strip():
            raise ValueError(f"Sentence {i + 1} has no alignable characters after normalization")
    root = Path(os.environ.get("UROMAN_PATH", ROOT / "vendor/uroman/bin"))
    script = root / "uroman.pl"
    if not script.is_file():
        raise FileNotFoundError(f"uroman.pl not found at {script}; set UROMAN_PATH")
    command = ["perl", str(script)]
    if language in SPECIAL_ISOS:
        command += ["-l", language]
    try:
        proc = subprocess.run(command, input="\n".join(normal) + "\n", text=True,
                              encoding="utf-8", capture_output=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("Perl is required to run uroman") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"uroman failed: {exc.stderr.strip()}") from exc
    rows = proc.stdout.splitlines()
    if len(rows) != len(sentences):
        raise ValueError("uroman returned an unexpected number of transcript lines")
    result = []
    for i, row in enumerate(rows):
        cleaned = re.sub(r"[^a-z' ]", " ", row.lower())
        tokens = list(re.sub(r"\s+", " ", cleaned).replace(" ", ""))
        if not tokens:
            raise ValueError(f"Sentence {i + 1} has no alignable characters after normalization")
        result.append(tokens)
    return result


def _load_model():
    try:
        import torch
        import torchaudio
    except (ImportError, OSError) as exc:
        raise RuntimeError("Compatible PyTorch and torchaudio installations are required") from exc
    default = ROOT / "models/model.pt"
    model_path = Path(os.environ.get("MMS_MODEL_PATH", default)).expanduser()
    if not model_path.is_file():
        raise FileNotFoundError(f"MMS model not found: {model_path}. Set MMS_MODEL_PATH to an existing model.pt")
    dictionary_path = Path(os.environ.get("MMS_DICTIONARY_PATH", model_path.parent / "ctc_alignment_mling_uroman_model.dict"))
    if not dictionary_path.is_file():
        alternative = model_path.parent / "dictionary.txt"
        if alternative.is_file() and "MMS_DICTIONARY_PATH" not in os.environ:
            dictionary_path = alternative
        else:
            raise FileNotFoundError(f"MMS dictionary not found: {dictionary_path}")
    dictionary = {line.strip(): i for i, line in enumerate(dictionary_path.read_text(encoding="utf-8").splitlines())}
    if "<blank>" not in dictionary:
        raise ValueError("MMS dictionary does not contain <blank>")
    device = os.environ.get("ALIGN_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    model = torchaudio.models.wav2vec2_model(
        extractor_mode="layer_norm", extractor_conv_layer_config=[(512, 10, 5), (512, 3, 2), (512, 3, 2), (512, 3, 2), (512, 3, 2), (512, 2, 2), (512, 2, 2)],
        extractor_conv_bias=True, encoder_embed_dim=1024, encoder_projection_dropout=0.0,
        encoder_pos_conv_kernel=128, encoder_pos_conv_groups=16, encoder_num_layers=24,
        encoder_num_heads=16, encoder_attention_dropout=0.0, encoder_ff_interm_features=4096,
        encoder_ff_interm_dropout=0.1, encoder_dropout=0.0, encoder_layer_norm_first=True,
        encoder_layer_drop=0.1, aux_num_out=31)
    try:
        state = torch.load(model_path, map_location="cpu", weights_only=True)
    except TypeError:  # older supported PyTorch versions
        state = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state)
    model.to(device).eval()
    return torch, torchaudio, model, dictionary, device


def _alignment(wav, tokens):
    torch, torchaudio, model, dictionary, device = _load_model()
    waveform, rate = torchaudio.load(str(wav))
    if rate != SAMPLE_RATE or waveform.shape[0] != 1 or waveform.shape[1] == 0:
        raise ValueError("Converted audio must be nonempty, mono and 16 kHz")
    duration = waveform.shape[1] / SAMPLE_RATE
    emissions = []
    with torch.inference_mode():
        for start in range(0, math.ceil(duration), 30):
            left, right = max(start - 3, 0), min(start + 33, duration)
            chunk = waveform[:, int(left * rate):int(right * rate)].to(device)
            output, _ = model(chunk)
            frames = output[0]
            begin = int(start * 50) - int(left * 50)
            end = int((start + 30) * 50) - int(left * 50)
            emissions.append(frames[begin:end])
        emission = torch.log_softmax(torch.cat(emissions, dim=0), dim=-1)
        stride = duration / emission.shape[0]
        # A zero-score star between sentences allows untranscribed speech to be skipped.
        star = emission.shape[1]
        emission = torch.cat([emission, torch.zeros((emission.shape[0], 1), device=emission.device)], dim=1)
        target = [star]
        spans = []
        for line in tokens:
            missing = sorted(set(line) - dictionary.keys())
            if missing:
                raise ValueError(f"Model dictionary cannot represent characters: {''.join(missing)}")
            begin = len(target)
            target.extend(dictionary[c] for c in line)
            spans.append((begin, len(target)))
            target.append(star)
        # CTC needs an intervening blank for adjacent identical targets.
        required = len(target) + sum(a == b for a, b in zip(target, target[1:]))
        if required > emission.shape[0]:
            raise ValueError("Transcript is too long for the supplied audio")
        target_tensor = torch.tensor([target], dtype=torch.int32, device=device)
        try:
            path, _ = torchaudio.functional.forced_align(emission.unsqueeze(0), target_tensor, blank=dictionary["<blank>"])
        except (AttributeError, RuntimeError) as exc:
            raise RuntimeError(f"MMS forced alignment failed: {exc}") from exc
    return _times_from_path(path[0].cpu().tolist(), target, spans,
                            dictionary["<blank>"], stride), duration


def _times_from_path(values, target, spans, blank, stride):
    """Reproduce align_utils.merge_repeats/get_spans, including blank padding."""
    segments = []
    pos = 0
    while pos < len(values):
        end = pos + 1
        while end < len(values) and values[end] == values[pos]:
            end += 1
        # Original merge_repeats stores an inclusive final frame.
        segments.append((values[pos], pos, end - 1))
        pos = end
    token_indices = [i for i, seg in enumerate(segments) if seg[0] != blank]
    if [segments[i][0] for i in token_indices] != target:
        raise RuntimeError("MMS output did not match all transcript tokens")
    result = []
    for a, b in spans:
        first, last = token_indices[a], token_indices[b - 1]
        start, end = segments[first][1], segments[last][2]
        # Sentence tokens are surrounded by star tokens, so they are never the
        # first or last span; original get_spans uses blank midpoints here.
        if first > 0 and segments[first - 1][0] == blank:
            prev = segments[first - 1]
            start = (prev[1] + prev[2]) // 2
        if last + 1 < len(segments) and segments[last + 1][0] == blank:
            following = segments[last + 1]
            end = (following[1] + following[2]) // 2
        result.append((start * stride, end * stride))
    return result


def write_outputs(sentences, times, duration, output_dir):
    if len(sentences) != len(times):
        raise ValueError("Number of sentence timings does not match transcript")
    previous = 0.0
    for start, end in times:
        if not all(math.isfinite(t) for t in (start, end)) or not 0 <= previous <= start <= end <= duration + 1e-6:
            raise ValueError("Invalid or overlapping sentence timings")
        previous = end
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {"csv": output / "alignment.csv", "txt": output / "alignment.txt", "textgrid": output / "alignment.TextGrid"}
    write_audition_csv(paths["csv"], [
        # Match the original converter, which rounded both boundaries before
        # calculating the marker duration.
        {'id': name, 'start': round(start, 3), 'end': round(end, 3), 'text': text}
        for (name, text), (start, end) in zip(sentences, times)
    ])
    with paths["txt"].open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "start", "end", "text"])
        for (name, text), (start, end) in zip(sentences, times):
            writer.writerow([name, f"{start:.3f}", f"{end:.3f}", text])
    intervals = []
    prev = 0.0
    for (_, text), (start, end) in zip(sentences, times):
        if start > prev:
            intervals.append((prev, start, ""))
        intervals.append((start, end, text))
        prev = end
    if prev < duration:
        intervals.append((prev, duration, ""))
    with paths["textgrid"].open("w", encoding="utf-8") as f:
        f.write('File type = "ooTextFile"\nObject class = "TextGrid"\n\n')
        f.write(f'xmin = 0\nxmax = {duration:.6f}\ntiers? <exists>\nsize = 1\nitem []:\n    item [1]:\n        class = "IntervalTier"\n        name = "sentences"\n        xmin = 0\n        xmax = {duration:.6f}\n        intervals: size = {len(intervals)}\n')
        for i, (start, end, text) in enumerate(intervals, 1):
            escaped = text.replace('"', '""')
            f.write(f'        intervals [{i}]:\n            xmin = {start:.6f}\n            xmax = {end:.6f}\n            text = "{escaped}"\n')
    return paths


def convert_audio(audio_path, destination):
    """Decode audio into a validated, nonempty 16 kHz mono PCM WAV."""
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(audio_path),
                        "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le",
                        "-y", str(destination)], capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required to decode audio") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"Unable to decode audio: {exc.stderr.strip()}") from exc
    try:
        with wave.open(str(destination), 'rb') as wav:
            if (wav.getframerate() != SAMPLE_RATE or wav.getnchannels() != 1
                    or wav.getsampwidth() != 2 or wav.getnframes() == 0
                    or len(wav.readframes(1)) != 2):
                raise ValueError("Converted audio must be nonempty 16 kHz mono PCM")
    except (wave.Error, EOFError) as exc:
        raise ValueError("Converted audio is not a valid WAV file") from exc


def align(audio_path, text_path, language, output_dir, *, already_converted=False):
    """Align a recording and UTF-8 transcript. Return output paths by format.

    `language` may be an MMS ISO code or a supported locale alias.
    """
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    language = normalize_language(language)
    sentences = read_sentences(text_path)
    tokens = romanize(sentences, language)
    with tempfile.TemporaryDirectory(prefix="mms-align-") as temp:
        wav = Path(temp) / "audio.wav"
        if already_converted:
            wav = audio_path
        else:
            convert_audio(audio_path, wav)
        speech = speech_timestamps(wav)
        times, duration = _alignment(wav, tokens)
        times = refine_times(times, speech, duration)
    return write_outputs(sentences, times, duration, output_dir)
