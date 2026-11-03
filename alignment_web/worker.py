"""Execute one alignment in a fresh process and report its output paths."""
import json
from pathlib import Path
import sys


def main():
    if len(sys.argv) != 6:
        raise SystemExit('Expected audio, transcript, language, output directory and result path')
    audio_path, text_path, language, output_dir, result_path = sys.argv[1:]
    audio_path = Path(audio_path)
    from alignment_core import align
    result = align(audio_path, Path(text_path), language, Path(output_dir),
                   already_converted=audio_path.name == 'normalized.wav')
    Path(result_path).write_text(json.dumps({key: str(path) for key, path in result.items()}),
                                 encoding='utf-8')


if __name__ == '__main__':
    main()
