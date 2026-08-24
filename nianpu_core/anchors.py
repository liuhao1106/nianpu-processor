# -*- coding: utf-8 -*-
"""標題錨點解析、出生年共識與三錨點一致性驗證。"""



import re

from .constants import (
    REIGNS, AGE_DIGITS, AGE_SUFFIXES,
    REIGN_START_YEARS, REIGN_END_YEARS, STEM_BRANCH,
)
from .base import (
    _build_year_pattern, extract_reign,
    _compute_ad_year, _chinese_year_to_int, _chinese_digits_to_int,
    _ganzhi_index_of_pair, _ganzhi_pair_of_ad,
)


# ======== L2：三錨點一致性檢查 ========
def _parse_heading_anchors(heading):
    """從 ###/#### 標題行解析錨點：年號年→公元、干支、年齡、顯式公元年。回傳 dict。"""
    if heading.startswith('#### '):
        h = heading[5:].strip()
    elif heading.startswith('### '):
        h = heading[4:].strip()
    else:
        h = heading.strip()
    info = {'raw': h, 'reign_ad': None, 'ganzhi': None, 'ganzhi_idx': None,
            'age': None, 'age_int': None, 'ad_anchor': None, 'ad_anchor_int': None}
    # ① 年號+年序 → 公元
    m = re.search(r'(' + '|'.join(REIGNS) + r')(' + _build_year_pattern() + r')年', h)
    if m:
        info['reign_ad'] = _compute_ad_year(m.group(1), m.group(2))
    # ② 干支（取第一個）
    gm = re.search(STEM_BRANCH, h)
    if gm:
        info['ganzhi'] = gm.group(0)
        info['ganzhi_idx'] = _ganzhi_index_of_pair(gm.group(0))
    # ③ 年齡（N嵗/歲，取第一個）
    am = re.search(AGE_DIGITS + r'[' + AGE_SUFFIXES + r']', h)
    if am:
        age_s = re.sub(r'[' + AGE_SUFFIXES + r']$', '', am.group(0))
        info['age'] = age_s
        info['age_int'] = _chinese_year_to_int(age_s)
    # ④ 顯式公元年（現代學者年譜：干支後接 1813年／一九二三年；排除（1806年）括號註記）
    # (?<!\d) 避免部分匹配長數字（（1867年）中的「867」），(?<![（(]) 排除括號內的公元註記
    adm = re.search(r'(?<!\d)(?<![（(])(?:公元)?(?P<aad>[0-9]{3,4}|[一二三四五六七八九零〇]{3,4})\s*年', h)
    if adm:
        a = adm.group('aad')
        info['ad_anchor'] = a
        info['ad_anchor_int'] = int(a) if a.isdigit() else _chinese_digits_to_int(a)
    return info


def _consensus_birth_year(parsed, min_rate=0.6, min_sample=5):
    """推定出生年（CBDB 缺席時的回退訊號）。

    年譜錨點錯誤的主流是「年號年序」誤刻（許敬菴尾部整體錯一年、尙友堂掉
    「十/二十/三十」），干支與年齡通常可信，故以 (干支, 年齡) 對推定出生年：
      birth ≡ (ganzhi_idx − age_int + 5) (mod 60)
    多數決一致率 ≥ min_rate 且樣本 ≥ min_sample 才算共識（對個別條目錯誤魯棒）。
    若年號年序多數決（reign_ad − age + 1，含顯式公元）落在該餘類內且落在文本
    年號 span 內，兩訊號互相佐證，直接採用；否則以文本年號 span 將餘類解為唯一
    絕對年（最早條目年份 ≥ era_min−5、最晚條目年份 ≤ era_max）。無法判定回傳
    None（不自動修，回歸人工）。
    """
    from collections import Counter
    # ① (干支, 年齡) 餘類共識
    gz_res = [((p['ganzhi_idx'] - p['age_int'] + 5) % 60)
              for p in parsed if p['ganzhi_idx'] is not None and p['age_int'] is not None]
    gz_residue = None
    if len(gz_res) >= min_sample:
        top, cnt = Counter(gz_res).most_common(1)[0]
        if cnt / len(gz_res) >= min_rate:
            gz_residue = top
    # ② 年號年序多數決（含顯式公元，現代學者年譜）
    rc = ([p['reign_ad'] - p['age_int'] + 1
           for p in parsed if p['reign_ad'] is not None and p['age_int'] is not None]
          + [p['ad_anchor_int'] - p['age_int'] + 1
             for p in parsed if p['ad_anchor_int'] is not None and p['age_int'] is not None])
    reign_major = None
    if len(rc) >= min_sample:
        top, cnt = Counter(rc).most_common(1)[0]
        if cnt / len(rc) >= min_rate:
            reign_major = top
    if gz_residue is None:
        return reign_major
    # ③ 文本年號 span（唯一絕對年收斂用）
    era_min = era_max = None
    for p in parsed:
        r, _ = extract_reign(p['raw'])
        if r and r in REIGN_START_YEARS:
            s = REIGN_START_YEARS[r]
            e = REIGN_END_YEARS.get(r, s + 60)
            era_min = s if era_min is None else min(era_min, s)
            era_max = e if era_max is None else max(era_max, e)
    ages = [p['age_int'] for p in parsed if p['age_int'] is not None]
    lo, hi = (min(ages), max(ages)) if ages else (None, None)

    def in_span(b):
        return (era_min is not None and lo is not None
                and b >= era_min - 5 and b + hi - 1 <= era_max)

    if reign_major is not None and reign_major % 60 == gz_residue and in_span(reign_major):
        return reign_major  # 兩訊號互相佐證
    if era_min is None or lo is None:
        return None
    valid = [b for b in range(era_min - 5, era_max + 1)
             if b % 60 == gz_residue and in_span(b)]
    return valid[0] if len(valid) == 1 else None


def verify_anchors(result):
    """三錨點一致性檢查：每個標題交叉驗證 年號年→公元、干支→公元、年齡→公元。

    ① 年號年→公元 vs 年齡→公元（出生年+歲-1）不符 → 年號誤配（如順治誤標崇禎）
    ② 干支 vs 年齡→公元 不符 → 干支或年齡有誤
    ③ 干支 vs 年號年→公元 不符（無年齡可用時）
    ④ 相鄰標題年齡序列未逐年遞增 → 可能漏年/錯序

    回傳 (suspects, seq_bad, birth_year, total)。
    """
    headings = [l for l in result.split('\n') if l.startswith('### ') or l.startswith('#### ')]
    parsed_all = [_parse_heading_anchors(l) for l in headings]
    parsed = [p for p in parsed_all if p['reign_ad'] is not None or p['age_int'] is not None]

    # 出生年共識：以 (干支, 年齡) 餘類多數決為主、年號年序多數決佐證
    # （_consensus_birth_year），對「年號年序系統性誤刻」魯棒；無法判定回傳 None。
    birth_year = _consensus_birth_year(parsed_all)

    suspects = []
    for p in parsed:
        reasons = []
        ad_age = (birth_year + p['age_int'] - 1
                  if birth_year and p['age_int'] is not None else None)
        # ① 年號年 vs 年齡
        if p['reign_ad'] is not None and ad_age is not None and p['reign_ad'] != ad_age:
            reasons.append(f"年號年→公元 {p['reign_ad']} ≠ 年齡→公元 {ad_age}")
        # ①' 顯式公元年 vs 年號年
        if p['reign_ad'] is not None and p['ad_anchor_int'] is not None and p['reign_ad'] != p['ad_anchor_int']:
            reasons.append(f"顯式公元 {p['ad_anchor_int']} ≠ 年號年→公元 {p['reign_ad']}")
        # ② 干支 vs 年齡（出生年推定後）
        if p['ganzhi_idx'] is not None and ad_age is not None:
            exp = (ad_age - 4) % 60
            if p['ganzhi_idx'] != exp:
                reasons.append(
                    f"干支{p['ganzhi']}(idx {p['ganzhi_idx']}) ≠ 年齡應為 {_ganzhi_pair_of_ad(ad_age)}(idx {exp})")
        # ③ 干支 vs 年號年（無年齡可用時）
        elif p['ganzhi_idx'] is not None and p['reign_ad'] is not None:
            exp = (p['reign_ad'] - 4) % 60
            if p['ganzhi_idx'] != exp:
                reasons.append(
                    f"干支{p['ganzhi']} ≠ 年號年應為 {_ganzhi_pair_of_ad(p['reign_ad'])}")
        # ③' 干支 vs 顯式公元年（無年號年可用時）
        elif p['ganzhi_idx'] is not None and p['ad_anchor_int'] is not None:
            exp = (p['ad_anchor_int'] - 4) % 60
            if p['ganzhi_idx'] != exp:
                reasons.append(
                    f"干支{p['ganzhi']} ≠ 顯式公元{p['ad_anchor_int']}應為 {_ganzhi_pair_of_ad(p['ad_anchor_int'])}")
        if reasons:
            suspects.append((p['raw'], reasons))

    # ④ 年齡序列連續性
    seq_bad = []
    prev = None
    for p in parsed:
        if p['age_int'] is None:
            prev = None
            continue
        if prev is not None and prev['age_int'] is not None:
            gap = p['age_int'] - prev['age_int']
            if p['reign_ad'] is not None and prev['reign_ad'] is not None:
                ygap = p['reign_ad'] - prev['reign_ad']
                if gap != ygap and gap > 0:
                    seq_bad.append(
                        f"{prev['raw']} → {p['raw']}：年齡差 {gap} ≠ 年差 {ygap}")
            elif gap <= 0:
                seq_bad.append(f"{prev['raw']} → {p['raw']}：年齡未遞增（差 {gap}）")
        prev = p

    return suspects, seq_bad, birth_year, len(headings)
