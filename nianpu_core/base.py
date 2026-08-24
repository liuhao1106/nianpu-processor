# -*- coding: utf-8 -*-
"""底層轉換與模式工具：中文數字↔整數、干支↔公元、年份模式、年號提取、稱謂偵測。"""



import re

from .constants import (
    REIGNS, EMPEROR_PREFIXES, PERSON_PREFIXES,
    AGE_SUFFIXES, AGE_DIGITS,
    REIGN_START_YEARS, _CN_NUM,
    _TG, _DZ, STEM_BRANCH,
    _STEM_IDX, _BRANCH_IDX, _STEMS_CANON, _BRANCHES_CANON,
)


def _chinese_year_to_int(s):
    """中文數字年份（元/一~九/十/十一~十九/二十~九十九/十有一/廿/卅）轉為整數。"""
    if s == '元':
        return 1
    if s.startswith('廿'):      # 廿=20、廿一=21…
        rest = s[1:]
        return 20 + (_chinese_year_to_int(rest) if rest else 0)
    if s.startswith('卅'):      # 卅=30、卅二=32…
        rest = s[1:]
        return 30 + (_chinese_year_to_int(rest) if rest else 0)
    total = 0
    cur = 0
    for ch in s:
        if ch in '一二三四五六七八九':
            cur = _CN_NUM[ch]
        elif ch == '十':
            cur = cur if cur else 1          # 「十一」→10+1；「十」→10
            cur *= 10
            total += cur
            cur = 0
        elif ch == '百':
            total += (cur if cur else 1) * 100
            cur = 0
        # 「有」「和」等連接詞直接略過
    total += cur
    return total if total > 0 else None


def _chinese_digits_to_int(s):
    """中文數字逐位轉整數（公元年格式，如 一八七三=1873、一九五零=1950）。"""
    mapping = {'零': 0, '〇': 0, '一': 1, '二': 2, '三': 3, '四': 4,
               '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    result = 0
    for ch in s:
        if ch in mapping:
            result = result * 10 + mapping[ch]
    return result if s else None


def _compute_ad_year(reign, year_str):
    """由年號與年序計算公元年：公元年 = 年號元年公元 + 年序 - 1。"""
    start = REIGN_START_YEARS.get(reign)
    if start is None:
        return None
    n = _chinese_year_to_int(year_str)
    if n is None:
        return None
    return start + n - 1


def _ganzhi_index_of_pair(pair):
    """解析 2 字干支（含已/己/巳 變體）→ 60 週期索引；無法解析回傳 None。"""
    if len(pair) != 2:
        return None
    si = _STEM_IDX.get(pair[0])
    bi = _BRANCH_IDX.get(pair[1])
    if si is None or bi is None:
        return None
    for i in range(60):
        if i % 10 == si and i % 12 == bi:
            return i
    return None


def _ganzhi_pair_of_ad(ad_year):
    """公元年 → 該年干支（甲子=公元4年，週期60）。"""
    i = (ad_year - 4) % 60
    return _STEMS_CANON[i % 10] + _BRANCHES_CANON[i % 12]


def _gz_age_connector():
    """干支+直接年齡格式的「干支→年齡」連接段。

    容許：無（庚子二歲）、「年」（乙酉年四十七歲）、「，年」（丙戌，年四十八歲）、
    逗號+年號+年序（壬寅，康熙元年四歲）。分支顯式、逗號後可選「年號年序」或「年」，
    避免把「丙戌，年四十八歲」的逗號單獨消耗後殘留「，年」無法銜接（此前被回溯丟失）。
    """
    ar = '|'.join(REIGNS)
    return (r'(?:[，,、]\s*(?:(?:' + ar + r')?[一-十百廿卅元]{1,3}年?[，,、]?\s*|(?:年)?)?'
            + r'|(?:年)?)')


def _build_year_pattern():
    nums = [
        '元','一','二','三','四','五','六','七','八','九','十',
        '十一','十二','十三','十四','十五','十六','十七','十八','十九',
        '二十','二十一','二十二','二十三','二十四','二十五','二十六',
        '二十七','二十八','二十九',
        '三十','三十一','三十二','三十三','三十四','三十五','三十六',
        '三十七','三十八','三十九',
        '四十','四十一','四十二','四十三','四十四','四十五','四十六',
        '四十七','四十八','四十九',
        '五十','五十一','五十二','五十三','五十四','五十五','五十六',
        '五十七','五十八','五十九',
        '六十','六十一','六十二','六十三','六十四','六十五','六十六',
        '六十七','六十八','六十九','七十',
        '十有一','十有二','十有三','十有四','十有五','十有六','十有七','十有八','十有九',
        # 廿/卅（近現代年譜：民國廿二年、光緒卅四年、廿一歲）
        '廿','廿一','廿二','廿三','廿四','廿五','廿六','廿七','廿八','廿九',
        '卅','卅一','卅二','卅三','卅四','卅五','卅六','卅七','卅八','卅九',
    ]
    # 前一位不能是數字：防止把「一八七三年」中的「三」誤當年份（4位公元年內部數字）
    return '(?<![一二三四五六七八九零〇])' + '(?:' + '|'.join(nums) + ')'


def extract_reign(heading):
    """從標題行中提取年號。"""
    h = heading.strip()
    # 民國國名「中華」前綴：不影響年號識別，先剝離（中華民國N年→民國N年）
    if h.startswith('中華'):
        h = h[2:]
    # 公元年格式（近現代年譜）：公元一八七三年，同治十二年，岁次癸酉，一歲
    # 年號在標題中段（同治/光绪/宣統/民國…），返回該年號，避免被當成無年號而錯誤補上前一年號
    if h.startswith('公元'):
        m = re.search(r'(' + '|'.join(REIGNS) + r')' + _build_year_pattern() + r'年', h)
        if m:
            return m.group(1), h[m.end():]
        return None, h
    for prefix, reign in EMPEROR_PREFIXES:
        if h.startswith(prefix):
            r = h[len(prefix):]
            for re_ in REIGNS:
                if r.startswith(re_):
                    return re_, r[len(re_):]
            return reign, r
    for r in REIGNS:
        if h.startswith(r):
            return r, h[len(r):]
    return None, h


# ======== 傳主名前綴自動偵測 ========
# 傳統年譜稱謂前綴固定（先生/公/府君）；近代年譜常直接以傳主名為年齡前綴
# （如袁觀瀾年譜「希濤年五十八歲」「希濤三歲」）。偵測反覆出現的「XX[年]N嵗」
# 前綴並自動納入該譜稱謂集合，使有稱謂 pattern 得以套用、民國無干支條目得以切分。

def detect_person_prefixes(text):
    """偵測以傳主名為前綴的「XX年N嵗／XXN嵗」年齡格式，回傳額外前綴清單。

    只統計「緊接 (年號)N年干支 之後」的 2 漢字前綴（非 先生/公/府君），
    出現 ≥3 次即視為傳主名。例：袁觀瀾年譜「光緒元年乙亥希濤年十歲」
    反覆出現 → ['希濤']。限定緊接干支之後，可排除正文中「卒年N歲」「夫人年N歲」
    等非名字前綴（殷譜經等無稱謂格式不會誤觸發）。
    """
    y = _build_year_pattern()
    sb = STEM_BRANCH
    ar = '|'.join(REIGNS)
    an = AGE_DIGITS
    as_suffix = r'[' + AGE_SUFFIXES + r']'
    age_digit_chars = frozenset('十有和一二三四五六七八九十百零〇廿卅0123456789')
    pat = re.compile(
        r'(?:' + ar + r')?' + y + r'年' + sb
        + r'([一-鿿]{2})(?:年)?(' + an + r')' + as_suffix
    )
    counts = {}
    for m in pat.finditer(text):
        pre = m.group(1)
        # 排除已知稱謂與「全由年齡數字構成」的前綴（無稱謂格式「N年干支N歲」的
        # 前兩位即年齡數字，如 二十/三十，非傳主名）
        if pre in PERSON_PREFIXES or all(c in age_digit_chars for c in pre):
            continue
        counts[pre] = counts.get(pre, 0) + 1
    return [p for p, c in counts.items() if c >= 3]


def _int_to_chinese_year(n):
    """年序整數 → 中文（1→元、10→十、26→二十六）。"""
    _D = '零一二三四五六七八九'
    if n == 1:
        return '元'
    if n < 10:
        return _D[n]
    if n == 10:
        return '十'
    if n < 20:
        return '十' + _D[n % 10]
    t, o = n // 10, n % 10
    return _D[t] + '十' + (_D[o] if o else '')
