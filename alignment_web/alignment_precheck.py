"""Conservative transcript density warning for the upload screen.

The caller supplies the full recording duration, not speech-only duration.
This is therefore a one-sided heuristic, never proof that audio and text match.
"""
import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from alignment_languages import normalize_language
from .auth import require_account
from .language_check import _script, _transcript

router = APIRouter()
TEXT_LIMIT = 2 * 1024 * 1024
MANDARIN_CHARACTERS_PER_SECOND = 6.0


class AlignmentPrecheckRequest(BaseModel):
    language: str
    text: str
    duration_seconds: float | None = None


def _remove_header(text):
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        fields = line.lstrip('\ufeff').split('\t', 1)
        if len(fields) == 2:
            key, value = (part.strip().casefold() for part in fields)
            if key.endswith(('id', '编号')) and value.endswith(('内容', '文本', 'text', 'sentence')):
                del lines[index]
        break
    return '\n'.join(lines)


def check_alignment_density(language, text, duration_seconds):
    """Return a warning for an unusually high Mandarin character density."""
    iso = normalize_language(language)
    duration = duration_seconds if duration_seconds is not None and math.isfinite(duration_seconds) and duration_seconds > 0 else None
    result = {'status': 'unknown', 'message': '', 'duration_seconds': duration,
              'character_count': None, 'characters_per_second': None}
    if duration is None:
        result['message'] = '无法读取音频时长，未进行文本长度检查；仍可继续提交。'
        return result
    if iso != 'cmn':
        result['message'] = '该语种暂不支持文本长度风险检查；仍可继续提交。'
        return result
    cleaned = _transcript(_remove_header(text))
    scripts = [_script(char) for char in cleaned]
    chars = scripts.count('HAN')
    letters = sum(script is not None for script in scripts)
    result['character_count'] = chars
    # A Chinese selection with mostly another script cannot be evaluated with
    # a Mandarin-character threshold; the language check handles mismatches.
    if not chars or chars < letters * 0.75:
        result['message'] = '文本并非以汉字为主，无法可靠检查长度；仍可继续提交。'
        return result
    rate = chars / duration
    result['characters_per_second'] = round(rate, 2)
    if rate > MANDARIN_CHARACTERS_PER_SECOND:
        result['status'] = 'warning'
        result['message'] = (f'文本约 {chars} 个汉字，音频总时长 {duration / 60:.1f} 分钟，'
                             f'平均每秒 {rate:.1f} 字。文本可能比实际朗读内容多，'
                             '对齐结果可能不准确，请核对后决定是否继续。')
    else:
        result['status'] = 'ok'
        result['message'] = '未发现明显文本过长风险；这不代表音频和文本内容一致。'
    return result


@router.post('/v1/alignment-precheck')
def alignment_precheck(payload: AlignmentPrecheckRequest, user: dict = Depends(require_account)):
    if len(payload.text.encode('utf-8')) > TEXT_LIMIT:
        raise HTTPException(413, '文本文件过大')
    if not payload.text.strip() or '\x00' in payload.text:
        raise HTTPException(400, '文本不能为空或包含 NUL 字符')
    try:
        return check_alignment_density(payload.language, payload.text, payload.duration_seconds)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
