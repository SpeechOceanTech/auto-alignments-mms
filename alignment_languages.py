"""Locale choices for the service and ISO 639-3 codes for the MMS engine.

Language ISO codes follow the local MMS ISO information table. Locale spellings
also include the codes used by the legacy batch pipeline. Regions identify input
choices, not separate MMS models. Three-letter ISO input remains supported.
"""
import re


# ISO 639-3, Chinese name, English name, locale:region pairs, extra aliases.
# The first locale is the default when an ISO code or language name is supplied.
_LANGUAGES = (
    ('cmn', '中文（普通话）', 'Mandarin Chinese', 'zh_cn:中国大陆 zh_tw:中国台湾 zh_sg:新加坡', 'zh 中文 普通话 chinese mandarin'),
    ('yue', '粤语', 'Cantonese', 'ct_hk:中国香港 yue_hk:中国香港 zh_hk:中国香港', 'cantonese 广东话'),
    ('nan', '闽南语', 'Min Nan Chinese', 'min_cn:中国大陆 nan_tw:中国台湾', '闽南话'),
    ('eng', '英语', 'English', 'en_us:美国 en_gb:英国 en_in:印度 en_za:南非 en_au:澳大利亚 en_ca:加拿大 en_nz:新西兰 en_ie:爱尔兰 en_sg:新加坡 en_ph:菲律宾 en_es:西班牙', 'en english'),
    ('jpn', '日语', 'Japanese', 'ja_jp:日本', 'ja japanese'),
    ('kor', '韩语', 'Korean', 'ko_kr:韩国', 'ko korean'),
    ('fra', '法语', 'French', 'fr_fr:法国 fr_ca:加拿大 fr_be:比利时 fr_ch:瑞士', 'fr french'),
    ('deu', '德语', 'German', 'de_de:德国 de_at:奥地利 de_ch:瑞士', 'de german'),
    ('spa', '西班牙语', 'Spanish', 'es_es:西班牙 es_mx:墨西哥 es_ar:阿根廷 es_co:哥伦比亚 es_cl:智利 es_pe:秘鲁 es_us:美国', 'es spanish'),
    ('por', '葡萄牙语', 'Portuguese', 'pt_br:巴西 pt_pt:葡萄牙', 'pt portuguese'),
    ('ita', '意大利语', 'Italian', 'it_it:意大利 it_ch:瑞士', 'it italian'),
    ('rus', '俄语', 'Russian', 'ru_ru:俄罗斯', 'ru russian'),
    ('ara', '阿拉伯语', 'Arabic', 'ar_sa:沙特阿拉伯 ar_eg:埃及 ar_iq:伊拉克 ar_ae:阿联酋 ar_ma:摩洛哥 ar_dz:阿尔及利亚 ar_jo:约旦', 'ar arabic'),
    ('hin', '印地语', 'Hindi', 'hi_in:印度', 'hi hindi'),
    ('ben', '孟加拉语', 'Bengali', 'bn_bd:孟加拉国 bn_in:印度', 'bn bengali'),
    ('urd', '乌尔都语', 'Urdu', 'ur_pk:巴基斯坦 ur_in:印度', 'ur urdu'),
    ('tam', '泰米尔语', 'Tamil', 'ta_in:印度 ta_lk:斯里兰卡 ta_sg:新加坡', 'ta tamil'),
    ('tel', '泰卢固语', 'Telugu', 'te_in:印度', 'te telugu'),
    ('kan', '卡纳达语', 'Kannada', 'kn_in:印度', 'kn kannada'),
    ('mar', '马拉地语', 'Marathi', 'mr_in:印度', 'mr marathi'),
    ('guj', '古吉拉特语', 'Gujarati', 'gu_in:印度', 'gu gujarati'),
    ('pan', '旁遮普语', 'Punjabi', 'pa_in:印度', 'pa punjabi'),
    ('mal', '马拉雅拉姆语', 'Malayalam', 'ml_in:印度', 'ml malayalam'),
    ('npi', '尼泊尔语', 'Nepali', 'ne_np:尼泊尔 ne_in:印度', 'ne nepali'),
    ('mai', '迈蒂利语', 'Maithili', 'mai_in:印度', 'maithili'),
    ('tha', '泰语', 'Thai', 'th_th:泰国', 'th thai'),
    ('vie', '越南语', 'Vietnamese', 'vi_vn:越南 vi_in:印度', 'vi vietnamese'),
    ('ind', '印度尼西亚语', 'Indonesian', 'id_id:印度尼西亚', 'id indonesian 印尼语'),
    ('zsm', '马来语', 'Malay', 'ms_my:马来西亚 my_my:马来西亚 ms_sg:新加坡', 'ms malay'),
    ('mya', '缅甸语', 'Burmese', 'my_mm:缅甸', 'my burmese'),
    ('khm', '高棉语', 'Khmer', 'km_kh:柬埔寨', 'km khmer 柬埔寨语'),
    ('lao', '老挝语', 'Lao', 'lo_la:老挝', 'lo lao'),
    ('tgl', '他加禄语 / 菲律宾语', 'Tagalog / Filipino', 'fil_ph:菲律宾 tl_ph:菲律宾', 'tl fil tagalog filipino 菲律宾语 他加禄语'),
    ('tur', '土耳其语', 'Turkish', 'tr_tr:土耳其', 'tr turkish'),
    ('fas', '波斯语', 'Persian', 'fa_ir:伊朗', 'fa persian farsi'),
    ('heb', '希伯来语', 'Hebrew', 'he_il:以色列', 'he hebrew'),
    ('ukr', '乌克兰语', 'Ukrainian', 'uk_ua:乌克兰', 'uk ukrainian'),
    ('pol', '波兰语', 'Polish', 'pl_pl:波兰', 'pl polish'),
    ('ces', '捷克语', 'Czech', 'cs_cz:捷克 cs_cs:捷克', 'cs czech'),
    ('slk', '斯洛伐克语', 'Slovak', 'sk_sk:斯洛伐克', 'sk slovak'),
    ('hrv', '克罗地亚语', 'Croatian', 'hr_hr:克罗地亚', 'hr croatian'),
    ('srp', '塞尔维亚语', 'Serbian', 'sr_rs:塞尔维亚', 'sr serbian'),
    ('hun', '匈牙利语', 'Hungarian', 'hu_hu:匈牙利', 'hu hungarian'),
    ('ron', '罗马尼亚语', 'Romanian', 'ro_ro:罗马尼亚', 'ro romanian'),
    ('bul', '保加利亚语', 'Bulgarian', 'bg_bg:保加利亚', 'bg bulgarian'),
    ('ell', '希腊语', 'Greek', 'el_gr:希腊', 'el greek'),
    ('nld', '荷兰语', 'Dutch', 'nl_nl:荷兰 nl_be:比利时', 'nl dutch'),
    ('swe', '瑞典语', 'Swedish', 'sv_se:瑞典 sv_fi:芬兰', 'sv swedish'),
    ('dan', '丹麦语', 'Danish', 'da_dk:丹麦', 'da danish'),
    ('nob', '挪威语（书面语）', 'Norwegian Bokmal', 'nb_no:挪威', 'nb bokmal'),
    ('nno', '挪威语（新挪威语）', 'Norwegian Nynorsk', 'nn_no:挪威', 'nn nynorsk'),
    ('fin', '芬兰语', 'Finnish', 'fi_fi:芬兰', 'fi finnish'),
    ('est', '爱沙尼亚语', 'Estonian', 'et_ee:爱沙尼亚', 'et estonian'),
    ('kat', '格鲁吉亚语', 'Georgian', 'ka_ge:格鲁吉亚', 'ka georgian'),
    ('kaz', '哈萨克语', 'Kazakh', 'kk_kz:哈萨克斯坦', 'kk kazakh'),
    ('uzb', '乌兹别克语', 'Uzbek', 'uz_uz:乌兹别克斯坦', 'uz uzbek'),
    ('uig', '维吾尔语', 'Uyghur', 'ug_cn:中国', 'ug uyghur uighur'),
    ('tgk', '塔吉克语', 'Tajik', 'tg_tj:塔吉克斯坦', 'tg tajik'),
    ('mon', '蒙古语', 'Mongolian', 'mn_mn:蒙古', 'mn mongolian'),
    ('bod', '藏语', 'Tibetan', 'bo_lhasa:中国拉萨', 'bo tibetan'),
    ('swh', '斯瓦希里语', 'Swahili', 'sw_ke:肯尼亚 sw_tz:坦桑尼亚', 'sw swahili'),
    ('amh', '阿姆哈拉语', 'Amharic', 'am_et:埃塞俄比亚', 'am amharic'),
    ('som', '索马里语', 'Somali', 'so_so:索马里', 'so somali'),
    ('hat', '海地克里奥尔语', 'Haitian Creole', 'ht_ht:海地', 'ht haitian creole'),
    ('afr', '南非荷兰语', 'Afrikaans', 'af_za:南非', 'af afrikaans'),
    ('sqi', '阿尔巴尼亚语', 'Albanian', 'sq_al:阿尔巴尼亚', 'sq albanian'),
    ('hye', '亚美尼亚语', 'Armenian', 'hy_am:亚美尼亚', 'hy armenian'),
    ('aze', '阿塞拜疆语', 'Azerbaijani', 'az_az:阿塞拜疆', 'az azerbaijani'),
    ('bel', '白俄罗斯语', 'Belarusian', 'be_by:白俄罗斯', 'be belarusian'),
    ('bos', '波斯尼亚语', 'Bosnian', 'bs_ba:波斯尼亚和黑塞哥维那', 'bs bosnian'),
    ('cat', '加泰罗尼亚语', 'Catalan', 'ca_es:西班牙', 'ca catalan'),
    ('eus', '巴斯克语', 'Basque', 'eu_es:西班牙', 'eu basque'),
    ('glg', '加利西亚语', 'Galician', 'gl_es:西班牙', 'gl galician'),
    ('isl', '冰岛语', 'Icelandic', 'is_is:冰岛', 'is icelandic'),
    ('gle', '爱尔兰语', 'Irish', 'ga_ie:爱尔兰', 'ga irish'),
    ('lav', '拉脱维亚语', 'Latvian', 'lv_lv:拉脱维亚', 'lv latvian'),
    ('lit', '立陶宛语', 'Lithuanian', 'lt_lt:立陶宛', 'lt lithuanian'),
    ('mkd', '马其顿语', 'Macedonian', 'mk_mk:北马其顿', 'mk macedonian'),
    ('mlt', '马耳他语', 'Maltese', 'mt_mt:马耳他', 'mt maltese'),
    ('slv', '斯洛文尼亚语', 'Slovenian', 'sl_si:斯洛文尼亚', 'sl slovenian'),
    ('cym', '威尔士语', 'Welsh', 'cy_gb:英国', 'cy welsh'),
    ('kir', '吉尔吉斯语', 'Kyrgyz', 'ky_kg:吉尔吉斯斯坦', 'ky kyrgyz'),
    ('pus', '普什图语', 'Pashto', 'ps_af:阿富汗 ps_pk:巴基斯坦', 'ps pashto'),
    ('sin', '僧伽罗语', 'Sinhala', 'si_lk:斯里兰卡', 'si sinhala sinhalese'),
    ('asm', '阿萨姆语', 'Assamese', 'as_in:印度', 'as assamese'),
    ('ory', '奥里亚语', 'Odia', 'or_in:印度', 'or ori odia oriya'),
    ('snd', '信德语', 'Sindhi', 'sd_pk:巴基斯坦', 'sd sindhi'),
    ('hau', '豪萨语', 'Hausa', 'ha_ng:尼日利亚', 'ha hausa'),
    ('ibo', '伊博语', 'Igbo', 'ig_ng:尼日利亚', 'ig igbo'),
    ('yor', '约鲁巴语', 'Yoruba', 'yo_ng:尼日利亚', 'yo yoruba'),
    ('zul', '祖鲁语', 'Zulu', 'zu_za:南非', 'zu zulu'),
    ('xho', '科萨语', 'Xhosa', 'xh_za:南非', 'xh xhosa'),
    ('orm', '奥罗莫语', 'Oromo', 'om_et:埃塞俄比亚', 'om oromo'),
    ('kin', '卢旺达语', 'Kinyarwanda', 'rw_rw:卢旺达', 'rw kinyarwanda'),
    ('nya', '齐切瓦语', 'Chichewa', 'ny_mw:马拉维', 'ny chichewa'),
    ('jav', '爪哇语', 'Javanese', 'jv_id:印度尼西亚', 'jv javanese'),
    ('sun', '巽他语', 'Sundanese', 'su_id:印度尼西亚', 'su sundanese'),
)


def _key(value):
    return value.strip().casefold().replace('-', '_')


COMMON_LANGUAGES = []
_ALIAS_LOCALES = {}
_LOCALE_ISOS = {}
for iso, name, english, locales, extra in _LANGUAGES:
    options = [item.split(':', 1) for item in locales.split()]
    preferred = options[0][0]
    aliases = list(dict.fromkeys([iso, name, english, *extra.split()]))
    for alias in aliases:
        _ALIAS_LOCALES.setdefault(_key(alias), preferred)
    for locale, region in options:
        duplicate_region = sum(option_region == region for _, option_region in options) > 1
        label = f'{name}（{region}，{locale}）' if duplicate_region else f'{name}（{region}）'
        COMMON_LANGUAGES.append({'code': locale, 'name': label, 'iso': iso,
                                 'english': english, 'aliases': aliases})
        _LOCALE_ISOS[locale] = iso
        _ALIAS_LOCALES[_key(locale)] = locale
        _ALIAS_LOCALES[_key(label)] = locale


def canonical_locale(value: str) -> str:
    """Resolve an input to a locale, retaining unlisted three-letter ISO codes."""
    if not isinstance(value, str):
        raise ValueError('语言代码必须是字符串')
    value = _key(value)
    if value in _ALIAS_LOCALES:
        return _ALIAS_LOCALES[value]
    match = re.fullmatch(r'([a-z]{2,3})_([a-z]{2})', value, flags=re.ASCII)
    if match and match.group(1) in _ALIAS_LOCALES:
        return value
    if re.fullmatch(r'[a-z]{3}', value, flags=re.ASCII):
        return value
    raise ValueError('请输入有效的语种名称、地区代码或三位 ISO 639-3 代码')


def normalize_language(value: str) -> str:
    """Resolve a locale, name, or ISO input to the ISO 639-3 engine code."""
    locale = canonical_locale(value)
    if locale in _LOCALE_ISOS:
        return _LOCALE_ISOS[locale]
    base = locale.split('_', 1)[0]
    return _LOCALE_ISOS.get(_ALIAS_LOCALES.get(base, ''), locale)
