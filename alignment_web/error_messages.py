"""User-facing descriptions of known job failures.

The original traceback remains in the job record. Add narrowly scoped rules
here as new failure modes are diagnosed; unknown failures stay unchanged.
"""
from pathlib import Path
import re


_EMPTY_SENTENCE = re.compile(
    r"ValueError: Sentence ([1-9][0-9]{0,8}) has no alignable characters after normalization"
)
_TEXT_TOO_LONG = re.compile(
    r"ValueError: Transcript is too long for the supplied audio(?:[.: ].*)?"
)


def _sentence_location(text_path, sentence_number):
    """Find the non-empty sentence as numbered by read_sentences()."""
    if text_path is None:
        return None
    try:
        with Path(text_path).open(encoding="utf-8-sig") as source:
            count = 0
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                count += 1
                if count != sentence_number:
                    continue
                if "\t" in line:
                    sentence_id, text = line.split("\t", 1)
                    sentence_id = sentence_id.strip()
                else:
                    sentence_id, text = str(count), line
                return line_number, sentence_id, text.strip()
    except (OSError, UnicodeError):
        pass
    return None


def _preview(value, limit=120):
    return value if len(value) <= limit else value[:limit] + "…"


def explain_error(error, text_path=None):
    """Return a code and display message, or None when there is no error."""
    if not error:
        return None
    # A traceback can contain earlier exceptions and quoted source code. Only
    # its final exception line describes the failure that reached the worker.
    lines = error.rstrip().splitlines()
    final_line = lines[-1] if lines else ""
    match = _EMPTY_SENTENCE.fullmatch(final_line)
    if match:
        number = int(match.group(1))
        location = _sentence_location(text_path, number)
        message = f"第 {number} 句没有可用于对齐的文字。"
        if location:
            line, sentence_id, text = location
            message += f"\n文本文件第 {line} 行，ID：{_preview(sentence_id)}\n原文：{_preview(text)}"
        message += "\n请检查该句是否只有标点、符号或【】中的说明，并填写实际朗读的文字。"
        return {"code": "empty_sentence", "message": message}
    if _TEXT_TOO_LONG.fullmatch(final_line):
        return {"code": "transcript_too_long", "message": (
            "文本相对于音频过长，无法完成对齐。请检查是否选择了对应的文本和音频，"
            "或将过长的文本与音频拆分后重新提交。"
        )}
    return {"code": "unknown", "message": error}
