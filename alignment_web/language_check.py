"""Conservative, offline transcript language warnings.

Only obvious discrepancies are reported. Language identification is probabilistic;
unsupported, short, ambiguous and mixed-language inputs return ``uncertain``.
"""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import re
import math
from threading import Lock
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from alignment_languages import ARABIC_ISOS, COMMON_LANGUAGES, canonical_locale, normalize_language
from .auth import require_account
from . import fasttext_client
from vendor.langdetect import DetectorFactory, LangDetectException

router = APIRouter()
_TEXT_LIMIT = 2 * 1024 * 1024
_MODEL_LOCK = Lock()
_factory = None

# Alternatives are accepted for languages routinely written in multiple scripts.
_SCRIPT_OVERRIDES = {
    'cmn': {'HAN'}, 'yue': {'HAN'}, 'nan': {'HAN'},
    'jpn': {'HAN', 'HIRAGANA', 'KATAKANA'}, 'kor': {'HANGUL', 'HAN'},
    'rus': {'CYRILLIC'}, 'ukr': {'CYRILLIC'}, 'bel': {'CYRILLIC'},
    'bul': {'CYRILLIC'}, 'mkd': {'CYRILLIC'}, 'kir': {'CYRILLIC'},
    'tgk': {'CYRILLIC'}, 'kaz': {'CYRILLIC', 'LATIN', 'ARABIC'},
    'mon': {'CYRILLIC', 'MONGOLIAN'}, 'srp': {'CYRILLIC', 'LATIN'},
    'uzb': {'CYRILLIC', 'LATIN', 'ARABIC'}, 'aze': {'CYRILLIC', 'LATIN', 'ARABIC'},
    **{iso: {'ARABIC'} for iso in ARABIC_ISOS},
    'fas': {'ARABIC'}, 'urd': {'ARABIC'}, 'pus': {'ARABIC'},
    'ckb': {'ARABIC'}, 'uig': {'ARABIC', 'CYRILLIC', 'LATIN'},
    'snd': {'ARABIC', 'DEVANAGARI'}, 'pan': {'GURMUKHI', 'ARABIC'},
    'zsm': {'LATIN', 'ARABIC'}, 'hau': {'LATIN', 'ARABIC'},
    'jav': {'LATIN', 'JAVANESE'}, 'sun': {'LATIN', 'SUNDANESE'},
    'heb': {'HEBREW'}, 'ell': {'GREEK'}, 'hin': {'DEVANAGARI'},
    'mar': {'DEVANAGARI'}, 'npi': {'DEVANAGARI'}, 'mai': {'DEVANAGARI'},
    'awa': {'DEVANAGARI'}, 'hne': {'DEVANAGARI'}, 'mag': {'DEVANAGARI'},
    'ben': {'BENGALI'}, 'asm': {'BENGALI'}, 'guj': {'GUJARATI'},
    'tam': {'TAMIL'}, 'tel': {'TELUGU'}, 'kan': {'KANNADA'}, 'mal': {'MALAYALAM'},
    'tha': {'THAI'}, 'lao': {'LAO'}, 'khm': {'KHMER'}, 'mya': {'MYANMAR'},
    'kat': {'GEORGIAN'}, 'hye': {'ARMENIAN'}, 'bod': {'TIBETAN'},
    'amh': {'ETHIOPIC'}, 'tir': {'ETHIOPIC'}, 'sin': {'SINHALA'}, 'ory': {'ORIYA'},
}
_LATIN_ISOS = set('''eng fra deu spa por ita vie ind tgl tur pol ces slk hrv hun ron
 nld swe dan nob nno fin est swh som afr sqi cat eus glg isl gle lav lit slv cym
 ibo yor zul xho orm kin nya ceb ilo war bcl pam pag ace ban mad min mlg lin lug
 sna tso tuk kmr nso bre fry oci'''.split())
_SCRIPT_NAMES = ('LATIN', 'CYRILLIC', 'ARABIC', 'HEBREW', 'GREEK', 'DEVANAGARI',
                 'BENGALI', 'GUJARATI', 'GURMUKHI', 'TAMIL', 'TELUGU', 'KANNADA',
                 'MALAYALAM', 'THAI', 'LAO', 'KHMER', 'MYANMAR', 'GEORGIAN',
                 'ARMENIAN', 'TIBETAN', 'ETHIOPIC', 'SINHALA', 'ORIYA', 'HANGUL',
                 'HIRAGANA', 'KATAKANA', 'MONGOLIAN', 'JAVANESE', 'SUNDANESE')
_SCRIPT_LABELS = {'HAN': '汉字', 'LATIN': '拉丁字母', 'CYRILLIC': '西里尔字母',
                  'ARABIC': '阿拉伯文字', 'HANGUL': '韩文', 'HIRAGANA': '日文假名',
                  'KATAKANA': '日文假名', 'DEVANAGARI': '天城文', 'HEBREW': '希伯来文',
                  'GREEK': '希腊字母', 'BENGALI': '孟加拉文', 'GUJARATI': '古吉拉特文',
                  'GURMUKHI': '古木基文', 'TAMIL': '泰米尔文', 'TELUGU': '泰卢固文',
                  'KANNADA': '卡纳达文', 'MALAYALAM': '马拉雅拉姆文', 'THAI': '泰文',
                  'LAO': '老挝文', 'KHMER': '高棉文', 'MYANMAR': '缅甸文',
                  'GEORGIAN': '格鲁吉亚文', 'ARMENIAN': '亚美尼亚文', 'TIBETAN': '藏文',
                  'ETHIOPIC': '埃塞俄比亚文', 'SINHALA': '僧伽罗文', 'ORIYA': '奥里亚文',
                  'MONGOLIAN': '蒙古文', 'JAVANESE': '爪哇文', 'SUNDANESE': '巽他文'}
# Disambiguating close languages/dialects and mutually intelligible scripts from
# text alone is unreliable. Never issue an identifier-based warning within these.
_RELATED = [
    {'cmn', 'yue', 'nan', 'jpn'}, {'ind', 'zsm'}, {'srp', 'hrv', 'bos'},
    {'nob', 'nno', 'swe', 'dan'}, {'rus', 'ukr', 'bel'}, {'hin', 'mar', 'npi', 'mai', 'awa', 'hne', 'mag'},
    {'ben', 'asm'}, {'por', 'spa', 'glg', 'cat'}, ARABIC_ISOS,
]
_DETECT_ALIASES = {'no': 'nb_no', 'zh-cn': 'zh_cn', 'zh-tw': 'zh_tw', 'tl': 'tl_ph'}
_NAMES = {item['iso']: item['language_name'] for item in COMMON_LANGUAGES}
# Detectors identify generic Arabic, not a specific country or dialect.
_NAMES['ara'] = '阿拉伯语'
_KNOWN_ISOS = set(_NAMES)
# Malay has no separate model profile. Common function words are used only to
# suppress an English warning, never to positively identify a language.
_MALAY_MARKERS = set('''yang dan untuk dengan tidak dalam kepada daripada kerana
    mempunyai setiap bukan juga boleh tetapi bahawa telah mereka kami saya anda
    adalah akan pada ini itu kita tersebut sebuah beberapa dengan sebagai oleh
    serta ia selepas sebelum seperti'''.split())


@lru_cache(maxsize=10000)
def _script(char):
    if not unicodedata.category(char).startswith('L'):
        return None
    name = unicodedata.name(char, '')
    if name.startswith(('CJK ', 'IDEOGRAPHIC ')):
        return 'HAN'
    return next((value for value in _SCRIPT_NAMES if name.startswith(value)), 'OTHER')


def _transcript(text):
    # The aligner accepts ID<TAB>sentence; IDs and 【unspoken notes】 must not
    # determine the language. Avoid holding unbounded additional copies.
    lines = (line.split('\t', 1)[-1] for line in text.splitlines())
    return re.sub(r'【[^】]*】', ' ', '\n'.join(lines))


def _model():
    global _factory
    if _factory is None:
        with _MODEL_LOCK:
            if _factory is None:
                factory = DetectorFactory()
                factory.seed = 0
                factory.load_profile(str(Path(__file__).resolve().parent.parent / 'vendor/langdetect/profiles'))
                _factory = factory
    return _factory


def _detect(text):
    detector = _model().create()
    detector.append(text)
    try:
        results = detector.get_probabilities()
    except LangDetectException:
        return None, 0.0
    return (results[0].lang, results[0].prob) if results else (None, 0.0)


def _same_or_related(a, b):
    return a == b or any(a in group and b in group for group in _RELATED)


def _identify(cleaned, counts, letter_count):
    words = re.findall(r'[^\W\d_]+', cleaned, re.UNICODE)
    if letter_count < 120 or (counts['LATIN'] / letter_count > 0.5 and len(words) < 24):
        return None
    if len(cleaned) <= 12000:
        midpoint = len(cleaned) // 2
        pieces = (cleaned[:midpoint], cleaned[midpoint:])
    else:
        # Sample both ends so the first few sentences cannot determine the
        # language of an otherwise mixed or different-language recording.
        pieces = (cleaned[:6000], cleaned[-6000:])
    detected = [_detect(piece) for piece in pieces]
    if any(not code or score < 0.995 for code, score in detected) or detected[0][0] != detected[1][0]:
        return None
    try:
        observed = canonical_locale(_DETECT_ALIASES.get(detected[0][0], detected[0][0]))
        return observed, normalize_language(observed)
    except ValueError:
        return None


def _fast_identify(cleaned, counts, letter_count):
    """Identify three transcript sections, or signal that the backend is absent.

    A successful but ambiguous prediction must remain uncertain; falling back
    to another detector in that case could conceal mixed-language input.
    """
    if letter_count < 120 or (counts['LATIN'] / letter_count > .5 and
                               len(re.findall(r'[^\W\d_]+', cleaned, re.UNICODE)) < 24):
        return None
    third = len(cleaned) // 3
    width = min(third, 4000)
    pieces = (cleaned[:width], cleaned[third:third + width], cleaned[-width:])
    if any(sum(1 for char in piece if _script(char)) < 30 for piece in pieces):
        return None
    response = fasttext_client.predict(pieces)
    if response is None:
        return None
    supported = set()
    for code in response['labels']:
        try:
            iso = normalize_language(_DETECT_ALIASES.get(code, code))
            if iso in _KNOWN_ISOS:
                supported.add(iso)
        except (ValueError, TypeError):
            continue
    observed = None
    malay_or_indonesian = False
    try:
        predictions = response['predictions']
        if len(predictions) == 3:
            normalized = []
            for code, confidence in predictions:
                confidence = float(confidence)
                if not math.isfinite(confidence) or not 0 <= confidence <= 1.0:
                    break
                locale = canonical_locale(_DETECT_ALIASES.get(code, code))
                iso = normalize_language(locale)
                if iso not in _KNOWN_ISOS or iso not in supported:
                    break
                normalized.append((locale, iso, confidence))
            if len(normalized) == 3:
                isos = {item[1] for item in normalized}
                if len(isos) == 1 and all(item[2] >= .85 for item in normalized):
                    observed = normalized[0][:2]
                    malay_or_indonesian = isos <= {'ind', 'zsm'}
                elif (isos <= {'ind', 'zsm'} and all(item[2] >= .55 for item in normalized)
                      and letter_count >= 200 and counts['LATIN'] / letter_count >= .9
                      and len(re.findall(r'[^\W\d_]+', cleaned, re.UNICODE)) >= 50):
                    # A compressed model often confuses these close languages.
                    # Require independent corroboration and identify the pair,
                    # never an individual language from low scores alone.
                    fallback = _identify(cleaned, counts, letter_count)
                    malay_or_indonesian = bool(fallback and fallback[1] == 'ind')
    except (TypeError, ValueError, KeyError):
        pass
    return supported, observed, malay_or_indonesian


def _clearly_english_for_malay(cleaned, counts):
    # The Indonesian profile is a close but imperfect proxy for Malay. Only an
    # especially strong, consistent English prediction can justify a warning.
    # Jawi or recognisable Malay function words make a mixed transcript unsure.
    if counts['ARABIC'] >= 5:
        return False
    words = re.findall(r'[^\W\d_]+', cleaned.casefold(), re.UNICODE)
    malay = [word for word in words if word in _MALAY_MARKERS]
    if len(set(malay)) >= 2 or len(malay) >= 3:
        return False
    if len(words) < 60:
        return False
    # Three independent samples also check the middle of long transcripts.
    third = len(cleaned) // 3
    pieces = (cleaned[:min(third, 4000)],
              cleaned[third:third + min(third, 4000)],
              cleaned[-min(third, 4000):])
    for piece in pieces:
        if sum(1 for char in piece if _script(char) == 'LATIN') < 60:
            return False
        code, confidence = _detect(piece)
        if code != 'en' or confidence < 0.995:
            return False
    return True


def check_language(language, text):
    """Return an advisory result; never treat uncertainty as evidence of a match."""
    selected = canonical_locale(language)
    iso = normalize_language(selected)
    cleaned = _transcript(text)
    letters = [char for char in cleaned if _script(char)]
    result = {'status': 'uncertain', 'selected_language': selected,
              'detected_language': None, 'detected_name': None,
              'message': '文本较短或语言特征不明显，无法可靠判断语种。'}
    if len(letters) < 40:
        return result
    counts = Counter(_script(char) for char in letters)
    scripts = _SCRIPT_OVERRIDES.get(iso, {'LATIN'} if iso in _LATIN_ISOS else set())
    # Han-only text cannot distinguish Chinese dialects, Japanese, or Korean.
    if iso in {'cmn', 'yue', 'nan', 'jpn', 'kor'} and counts['HAN'] / len(letters) >= 0.9:
        result['message'] = '仅凭汉字无法可靠区分中文方言或日文汉字。'
        return result
    fast = _fast_identify(cleaned, counts, len(letters))
    if scripts and sum(counts[s] for s in scripts) / len(letters) < 0.1:
        dominant, amount = counts.most_common(1)[0]
        if amount / len(letters) >= 0.8 and dominant != 'OTHER':
            label = _SCRIPT_LABELS.get(dominant, dominant.lower())
            observed = fast[1] if fast is not None else _identify(cleaned, counts, len(letters))
            if fast is not None and fast[2]:
                name = '马来语或印度尼西亚语'
                result.update(status='mismatch', detected_name=name,
                              message=f'选择的是{_NAMES.get(iso, selected)}，文本主要使用{label}，与所选语种不符；疑似为{name}，请核对。')
            elif observed:
                observed_code, observed_iso = observed
                # langdetect has no Malay profile and often labels Malay as
                # Indonesian. Do not present that guess as a specific language.
                ambiguous_malay = fast is None and observed_iso == 'ind'
                name = '马来语或印度尼西亚语' if ambiguous_malay else _NAMES.get(observed_iso, observed_code)
                if ambiguous_malay:
                    observed_code = None
                result.update(status='mismatch', detected_language=observed_code, detected_name=name,
                              message=f'选择的是{_NAMES.get(iso, selected)}，文本主要使用{label}，与所选语种不符；疑似为{name}，请核对。')
            else:
                result.update(status='mismatch', detected_name=label,
                              message=f'选择的是{_NAMES.get(iso, selected)}，文本主要使用{label}，与所选语种不符，请核对。')
            return result
    # Profiles cover 55 languages; never infer a mismatch when the selected
    # language is unsupported, because it can be mistaken for a supported one.
    if fast is not None:
        supported = iso in fast[0]
    else:
        model_codes = {item.replace('-', '_') for item in _model().langlist}
        supported = False
        for code in model_codes:
            try:
                model_iso = normalize_language(_DETECT_ALIASES.get(code.replace('_', '-'), code))
                supported |= model_iso == iso
            except ValueError:
                pass
        # Malay has no langdetect profile; the proxy is used conservatively.
        supported |= iso == 'zsm' and 'id' in model_codes
    if not supported or iso in {'yue', 'nan'}:
        result['message'] = '当前语种或文本特征无法可靠识别，请自行核对。'
        return result
    if fast is not None and fast[2] and (fast[1] is None or iso not in {'ind', 'zsm'}):
        if iso not in {'ind', 'zsm'}:
            result.update(status='mismatch', detected_name='马来语或印度尼西亚语',
                          message=f'选择的是{_NAMES.get(iso, selected)}，文本疑似为马来语或印度尼西亚语，请核对语种。')
        else:
            result['message'] = '文本可能是马来语或印度尼西亚语，无法可靠区分，请核对语种。'
        return result
    # Two independent pieces must agree with high confidence.
    observed = fast[1] if fast is not None else _identify(cleaned, counts, len(letters))
    if observed is None:
        result['message'] = '文本语言特征不够一致，无法可靠判断语种。'
        return result
    observed, observed_iso = observed
    if fast is None and observed_iso == 'ind':
        if iso not in {'ind', 'zsm'}:
            result.update(status='mismatch', detected_name='马来语或印度尼西亚语',
                          message=f'选择的是{_NAMES.get(iso, selected)}，文本疑似为马来语或印度尼西亚语，请核对语种。')
        else:
            result['message'] = '文本可能是马来语或印度尼西亚语，无法可靠区分，请核对语种。'
        return result
    # Do not claim a language match merely because a closely related language
    # was predicted; likewise, never warn about these common ambiguities.
    if iso == observed_iso:
        result.update(status='match', detected_language=observed, detected_name=_NAMES.get(observed_iso, observed),
                      message='文本与所选语种一致。')
    elif iso == 'zsm' and observed_iso == 'eng' and not _clearly_english_for_malay(cleaned, counts):
        return result
    elif fast is None and iso == 'zsm' and observed_iso != 'eng':
        return result
    elif not _same_or_related(iso, observed_iso):
        result.update(status='mismatch', detected_language=observed, detected_name=_NAMES.get(observed_iso, observed),
                      message=f'选择的是{_NAMES.get(iso, selected)}，文本疑似为{_NAMES.get(observed_iso, observed)}，请核对语种。')
    return result


class LanguageCheckRequest(BaseModel):
    language: str
    text: str


@router.post('/v1/language-check')
def language_check(payload: LanguageCheckRequest, user: dict = Depends(require_account)):
    if len(payload.text.encode('utf-8')) > _TEXT_LIMIT:
        raise HTTPException(413, '文本文件过大')
    if not payload.text.strip() or '\x00' in payload.text:
        raise HTTPException(400, '文本不能为空或包含 NUL 字符')
    try:
        return check_language(payload.language, payload.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
