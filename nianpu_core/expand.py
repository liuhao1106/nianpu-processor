# -*- coding: utf-8 -*-
"""標題擴展：裸干支／干支+年齡／純年齡 標題 → 年號年序＋公元年。"""



import re

from .constants import (
    REIGNS, EMPEROR_PREFIXES, AGE_DIGITS, AGE_SUFFIXES,
    REIGN_START_YEARS, REIGN_END_YEARS, _REIGN_SERIES,
    _TG, _DZ, STEM_BRANCH,
)
from .base import (
    _build_year_pattern, _gz_age_connector,
    _ganzhi_index_of_pair, _ganzhi_pair_of_ad, _int_to_chinese_year,
    _chinese_year_to_int,
)


def _expand_bare_gz_heading(heading, reign):
    """純干支標題（丁卯，公九歲／己亥）→ 依「當前年號 + 干支週期」推得年序與公元年。

    公式：offset =（目標干支索引 − 年號元年干支索引）mod 60；AD = 年號元年 + offset；
          年序 = offset + 1。年號歷時皆 <60 年，故 mod-60 落在年號內唯一。
    合理性：推算出的 AD 年干支須與目標一致（防 60 年週期在長年號下的歧義）；
           年序 ≤80 才算數，否則回傳 None（維持原標題）。
    回傳「年號N年干支」+原標題殘餘（如「，公九歲」）；失敗回傳 None。
    """
    m = re.match(r'^(?P<gz>[' + _TG + r'][' + _DZ + r'])(?P<rest>.*)$', heading)
    if not m:
        return None
    gz, rest = m.group('gz'), m.group('rest')
    rstart = REIGN_START_YEARS.get(reign)
    gi = _ganzhi_index_of_pair(gz)
    if rstart is None or gi is None:
        return None
    sgi = _ganzhi_index_of_pair(_ganzhi_pair_of_ad(rstart))
    if sgi is None:
        return None
    offset = (gi - sgi) % 60
    ad = rstart + offset
    if _ganzhi_index_of_pair(_ganzhi_pair_of_ad(ad)) != gi:
        return None
    n = offset + 1
    # 年號年序長度檢驗：推算年的公元年必須落在該年號實際起訖內（隆慶祗 6 年，
    # 故附录散文干支不可能推出「隆慶十年」；朱熹「紹熙五十二年」等亦被攔下）。
    # 年序超過年號跨度 → 絕非該年號下的年份條目，回傳 None 交由呼叫端不切分。
    _s0 = REIGN_START_YEARS.get(reign, rstart)
    _e0 = REIGN_END_YEARS.get(reign, _s0 + 60)
    if not (_s0 <= ad <= _e0):
        return None
    if n > 80:
        return None
    year_str = _int_to_chinese_year(n)
    if year_str is None:
        return None
    return f'{reign}{year_str}年{gz}{rest}'


# ======== 干支+直接年齡格式（gz_age）支援 ========
# 李恕谷先生年譜等：逐年條目為「庚子二歲／丙戌，年四十八歲／壬寅，康熙元年四歲」——
# 裸干支緊接年齡、無年號前綴（年號僅出生條目與更替處出現）。依「出生干支 + 干支週期」
# 推得公元年，再映射到朝代年號序列（含順治→康熙→雍正…年號更替）。


def _reign_dynasty(reign):
    """年號 → 所屬朝代（明/南明/清/民國/宋/元）；未知回傳 None。"""
    for dyn, series in _REIGN_SERIES.items():
        if reign in series:
            return dyn
    return None


def _ad_to_reign(ad, dynasty):
    """公元年 → 朝代序列內的（年號, 年序）：1686 → (康熙, 25)。"""
    series = _REIGN_SERIES.get(dynasty)
    if not series:
        return None
    for i, r in enumerate(series):
        start = REIGN_START_YEARS.get(r)
        if start is None:
            continue
        nxt = REIGN_START_YEARS.get(series[i + 1]) if i + 1 < len(series) else None
        if start <= ad and (nxt is None or ad < nxt):
            return r, ad - start + 1
    return None


def _find_gz_age_birth_ref(text):
    """從出生條目找（出生干支, 公元年, 年號）參照。

    兩種順序：干支在前「己亥順治十六年閏三月…先生生」、
    年號在前「順治十六年己亥…先生生」。回傳 (gz, ad, reign) 或 None。
    """
    sb = STEM_BRANCH
    ar = '|'.join(REIGNS)
    ap = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)
    y = _build_year_pattern()
    pats = [
        # 干支在前：己亥順治十六年閏三月二十四曰卯時，先生生
        re.compile(r'(?P<gz>' + sb + r')(?:(?:中華)?(?:' + ap + r')?(?P<reign>' + ar + r'))(?P<yr>' + y + r')年'),
        # 年號在前：順治十六年己亥閏三月二十四日，先生生
        re.compile(r'(?:(?:中華)?(?:' + ap + r')?(?P<reign>' + ar + r'))(?P<yr>' + y + r')年(?P<gz>' + sb + r')'),
    ]
    for pat in pats:
        for m in pat.finditer(text):
            gz = m.group('gz')
            reign = m.group('reign')
            n = _chinese_year_to_int(m.group('yr'))
            start = REIGN_START_YEARS.get(reign)
            if start and n and gz and _ganzhi_index_of_pair(gz) is not None:
                return gz, start + n - 1, reign
    return None


def _inject_birth_ganzhi(heading, birth_gz):
    """出生標題補/調干支：
    「順治十六年閏三月…」→「順治十六年己亥閏三月…」（補）、
    「己亥順治十六年…」→「順治十六年己亥…」（干支提前者移至年號年後）。"""
    # 干支在前（己亥順治十六年…先生生）：移至年號年後
    m = re.match(r'^(?P<gz>[' + _TG + r'][' + _DZ + r'])((?:' + '|'.join(REIGNS) + r')' + _build_year_pattern() + r'年)(?P<rest>.*)$', heading)
    if m and m.group('gz') == birth_gz:
        return m.group(2) + m.group('gz') + m.group('rest')
    # 年號在前但缺干支（順治十六年閏三月…）：補上
    m = re.match(r'^((?:' + '|'.join(REIGNS) + r')?' + _build_year_pattern() + r'年)(?P<rest>.*)$', heading)
    if m and not m.group('rest').startswith(birth_gz):
        return m.group(1) + birth_gz + m.group('rest')
    return heading


def _expand_gz_age_heading(heading, birth_ref, dynasty):
    """純干支+年齡標題（庚子二歲／丙戌，年四十八歲／壬寅，康熙元年四歲）→
    依「出生年 + 年齡」推得公元年（干支交叉驗證），再映射到朝代年號年序。
    回傳「年號N年干支+殘餘」（如 順治十七年庚子二歲）；失敗回傳 None。
    """
    m = re.match(
        r'^(?P<gz>[' + _TG + r'][' + _DZ + r'])'
        + _gz_age_connector()
        + r'(?P<age>[一二三四五六七八九十百廿卅]{1,4})?'
        + r'(?P<rest>.*)$',
        heading)
    if not m:
        return None
    gz = m.group('gz')
    age_str = m.group('age')
    rest = m.group('rest')
    birth_gz, birth_ad, _ = birth_ref
    gz_idx = _ganzhi_index_of_pair(gz)
    b_idx = _ganzhi_index_of_pair(birth_gz)
    if gz_idx is None or b_idx is None:
        return None
    # AD 由年齡推得（出生年 + 年齡 - 1），干支作交叉驗證（防 60 年週期歧義）
    if age_str:
        age = _chinese_year_to_int(age_str)
        if age and 0 < age < 120:
            ad = birth_ad + age - 1
            if _ganzhi_index_of_pair(_ganzhi_pair_of_ad(ad)) == gz_idx:
                rr = _ad_to_reign(ad, dynasty)
                if rr:
                    reign, n = rr
                    year_str = _int_to_chinese_year(n)
                    if year_str:
                        return f'{reign}{year_str}年{gz}{age_str}{rest}'
    # 無年齡或年齡與干支不符：由干支週期推（出生後最近一次匹配）
    ad = birth_ad + (gz_idx - b_idx) % 60
    if _ganzhi_index_of_pair(_ganzhi_pair_of_ad(ad)) == gz_idx:
        rr = _ad_to_reign(ad, dynasty)
        if rr:
            reign, n = rr
            year_str = _int_to_chinese_year(n)
            if year_str:
                return f'{reign}{year_str}年{gz}{age_str or ""}{rest}'
    return None


def _expand_pure_age_heading(heading, birth_ref, dynasty):
    """純年齡標題（曹月川先生年譜等）：
    「N歲」 → 「年號N年干支+選歲」依出生年＋年齡−1 推算（_ad_to_reign＋干支週期）；
    「年號N年干支」（出生條目）→ 原樣保留（annotate_ad_years 補公元年）。失敗回傳 None。"""
    m = re.match(r'^(?P<digits>' + AGE_DIGITS + r')(?P<suf>[' + AGE_SUFFIXES + r'])$', heading)
    if m:
        age = _chinese_year_to_int(m.group('digits'))
        if not age or not (0 < age < 150):
            return None
        _, birth_ad, _reign = birth_ref
        ad = birth_ad + age - 1
        rr = _ad_to_reign(ad, dynasty)
        if not rr:
            return None
        reign, seq = rr
        year_cn = _int_to_chinese_year(seq)
        gz = _ganzhi_pair_of_ad(ad)
        return f'{reign}{year_cn}年{gz}{m.group(0)}'
    # 出生條目（年號N年干支）：「洪武九年丙辰」原樣保留（annotate_ad_years 補公元年）
    if re.match(r'(?:' + '|'.join(REIGNS) + r')' + _build_year_pattern() + r'年'
                + STEM_BRANCH + r'$', heading):
        return heading
    return None


def _reign_label_of_ad(ad):
    """公元年 → 「年號N年」標籤（如 1546→嘉靖二十五年）；跨年號自動接續。"""
    for reign in sorted(REIGN_START_YEARS, key=REIGN_START_YEARS.get):
        s = REIGN_START_YEARS[reign]
        e = REIGN_END_YEARS.get(reign, s + 60)
        if s <= ad <= e:
            n = _int_to_chinese_year(ad - s + 1)
            if n:
                return f'{reign}{n}年'
    return None
