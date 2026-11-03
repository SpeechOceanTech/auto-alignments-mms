"""Language choices and input normalization shared by the UI and API.

The engine uses ISO 639-3 codes.  The legacy batch system used locale-like
codes, so those remain usable as aliases.  An arbitrary three-letter code is
accepted for less common languages; syntactic acceptance does not guarantee
that its text can be romanized or aligned successfully.

Reference: https://github.com/MXuer/mms-alignment-tools/blob/main/MMS_ISO_Information.md
"""

import re


# ISO 639-3, Chinese display name, and common ISO 639-1/legacy aliases.
_LANGUAGES = (
    ("cmn", "中文（普通话）", "zh zh_cn zh_tw zh_sg"),
    ("yue", "粤语", "ct_hk yue_hk zh_hk"),
    ("nan", "闽南语", "min_cn"),
    ("eng", "英语", "en en_us en_gb en_in en_za en_es"),
    ("jpn", "日语", "ja ja_jp"),
    ("kor", "韩语", "ko ko_kr"),
    ("fra", "法语", "fr fr_fr"),
    ("deu", "德语", "de de_de"),
    ("spa", "西班牙语", "es es_es es_mx"),
    ("por", "葡萄牙语", "pt pt_br pt_pt"),
    ("ita", "意大利语", "it it_it"),
    ("rus", "俄语", "ru ru_ru"),
    ("ara", "阿拉伯语", "ar ar_sa"),
    ("hin", "印地语", "hi hi_in"),
    ("ben", "孟加拉语", "bn bn_bd bn_in"),
    ("urd", "乌尔都语", "ur ur_pk ur_in"),
    ("tam", "泰米尔语", "ta ta_in"),
    ("tel", "泰卢固语", "te te_in"),
    ("kan", "卡纳达语", "kn kn_in"),
    ("mar", "马拉地语", "mr mr_in"),
    ("guj", "古吉拉特语", "gu gu_in"),
    ("pan", "旁遮普语", "pa pa_in"),
    ("mal", "马拉雅拉姆语", "ml ml_in"),
    ("npi", "尼泊尔语", "ne ne_np ne_in"),
    ("mai", "迈蒂利语", "mai_in"),
    ("tha", "泰语", "th th_th"),
    ("vie", "越南语", "vi vi_vn vi_in"),
    ("ind", "印度尼西亚语", "id id_id"),
    ("zsm", "马来语", "ms ms_my my_my"),
    ("mya", "缅甸语", "my my_mm"),
    ("khm", "高棉语", "km km_kh"),
    ("lao", "老挝语", "lo lo_la"),
    ("tgl", "他加禄语 / 菲律宾语", "tl tl_ph fil fil_ph"),
    ("tur", "土耳其语", "tr tr_tr"),
    ("fas", "波斯语", "fa fa_ir"),
    ("heb", "希伯来语", "he he_il"),
    ("ukr", "乌克兰语", "uk uk_ua"),
    ("pol", "波兰语", "pl pl_pl"),
    ("ces", "捷克语", "cs cs_cz"),
    ("slk", "斯洛伐克语", "sk sk_sk"),
    ("hrv", "克罗地亚语", "hr hr_hr"),
    ("srp", "塞尔维亚语", "sr sr_rs"),
    ("hun", "匈牙利语", "hu hu_hu"),
    ("ron", "罗马尼亚语", "ro ro_ro"),
    ("bul", "保加利亚语", "bg bg_bg"),
    ("ell", "希腊语", "el el_gr"),
    ("nld", "荷兰语", "nl nl_nl"),
    ("swe", "瑞典语", "sv sv_se"),
    ("dan", "丹麦语", "da da_dk"),
    ("nob", "挪威语（书面语）", "nb nb_no"),
    ("nno", "挪威语（新挪威语）", "nn nn_no"),
    ("fin", "芬兰语", "fi fi_fi"),
    ("est", "爱沙尼亚语", "et et_ee"),
    ("kat", "格鲁吉亚语", "ka ka_ge"),
    ("kaz", "哈萨克语", "kk kk_kz"),
    ("uzb", "乌兹别克语", "uz uz_uz"),
    ("uig", "维吾尔语", "ug ug_cn"),
    ("tgk", "塔吉克语", "tg tg_tj"),
    ("mon", "蒙古语", "mn mn_mn"),
    ("bod", "藏语", "bo bo_lhasa"),
    ("swh", "斯瓦希里语", "sw sw_ke"),
    ("amh", "阿姆哈拉语", "am am_et"),
    ("som", "索马里语", "so so_so"),
    ("hat", "海地克里奥尔语", "ht ht_ht"),
)

COMMON_LANGUAGES = [{"code": code, "name": name} for code, name, _ in _LANGUAGES]
_ALIASES = {alias: code for code, _, aliases in _LANGUAGES for alias in aliases.split()}


def normalize_language(value: str) -> str:
    """Return an ISO 639-3 code for a known alias or a three-letter input.

    This validates syntax, not membership in MMS's language catalog. Rejecting
    unknown two-letter or locale values prevents silently selecting a language.
    """
    if not isinstance(value, str):
        raise ValueError("语言代码必须是字符串")
    value = value.strip().lower().replace("-", "_")
    if value in _ALIASES:
        return _ALIASES[value]
    if re.fullmatch(r"[a-z]{3}", value, flags=re.ASCII):
        return value
    raise ValueError("请输入常用语种代码或三位 ISO 639-3 代码")
