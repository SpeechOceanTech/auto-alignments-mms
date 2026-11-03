"""Run a single sentence-alignment job from the command line."""
import argparse
import sys

from alignment_core import align


def main():
    parser = argparse.ArgumentParser(description="Align a recording with a UTF-8 transcript")
    parser.add_argument("audio", help="input audio file")
    parser.add_argument("text", help="UTF-8 text, one sentence per line")
    parser.add_argument("language", help="ISO 639-3 language code or common locale")
    parser.add_argument("output_dir", help="directory for the three result files")
    args = parser.parse_args()
    try:
        outputs = align(args.audio, args.text, args.language, args.output_dir)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Alignment failed: {exc}", file=sys.stderr)
        return 1
    for kind, path in outputs.items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
