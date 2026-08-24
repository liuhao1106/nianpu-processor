# -*- coding: utf-8 -*-
"""年號誤配自動修正（--fix）與 CBDB 生卒年核驗。"""



import re

from .constants import (
    REIGNS, AGE_DIGITS,
    REIGN_START_YEARS, REIGN_END_YEARS, _QING_REIGNS,
)
from .base import (
    _build_year_pattern, extract_reign,
    _chinese_year_to_int, _int_to_chinese_year,
)
from .anchors import _parse_heading_anchors, verify_anchors


# ======== CBDB 生卒年核驗與年號誤配自動修正 ========
try:
    from cbdb import get_person, extract_person_name as _cbdb_extract_name
except Exception:
    get_person = None
    _cbdb_extract_name = None


def _reign_span(reign):
    start = REIGN_START_YEARS.get(reign)
    if start is None:
        return None
    return start, REIGN_END_YEARS.get(reign, start + 60)


def reign_for_year(ad, current_reign=None):
    """公元年 → 正確年號+年序。

    優先沿用標題現年號（同一年號只改年序，如 道光十六→二十六年）——但僅在現年號
    實際涵蓋 ad 時（崇禎止於 1644，故 1645 不再沿用崇禎而切換為順治）；
    現年號不涵蓋時，取涵蓋 ad 的年號，清系列優先（顧亭林 1645 → 順治二年）。
    回傳 (年號, 年序) 或 (None, None)。
    """
    if current_reign and current_reign in REIGN_START_YEARS:
        s, e = _reign_span(current_reign)
        if s <= ad <= e:
            return current_reign, ad - s + 1
    cands = []
    for reign, start in REIGN_START_YEARS.items():
        s, e = _reign_span(reign)
        if s <= ad <= e:
            cands.append((reign, ad - s + 1))
    if not cands:
        return None, None
    for q in _QING_REIGNS:
        for reign, n in cands:
            if reign == q:
                return reign, n
    cands.sort(key=lambda x: REIGN_START_YEARS[x[0]], reverse=True)
    return cands[0]


def suggest_fix(heading, birth, death):
    """對單一標題行，依 CBDB 生卒年 + 干支/年齡 推定正確公元年並修正年號年序。

    回傳修正後的標題行；無需修正或無法判定回傳 None。只動年號+年序+（公元註記），
    干支/年齡/正文一律保留。
    """
    prefix = ''
    h = heading
    if h.startswith('### '):
        prefix = '### '
        h = h[4:].strip()
    info = _parse_heading_anchors(h)
    if info['reign_ad'] is None:
        return None
    age = info['age_int']
    if age is None:
        # 無「嵗」後綴的年齡（如張清恪「公年六十五」）：有稱謂（公/先生/府君）或「年N嵗」變體
        for apat in (r'(?:公|先生|府君)(?:年)?(' + AGE_DIGITS + r')(?:[嵗歲歳𡻕岁]|[，,、。；;\n]|$)',
                     r'(?:年)(' + AGE_DIGITS + r')[嵗歲歳𡻕岁]'):
            m2 = re.search(apat, h)
            if m2:
                try:
                    age = _chinese_year_to_int(m2.group(1))
                    break
                except Exception:
                    age = None
    # 保守原則：無年齡錨點不自動修（出生/干支誤刻類留人工）；
    # 有年齡時以「虛歲→公元」為準，並以干支候選集佐證（避免跟錯干支、或 OCR 髒字誤讀年齡）。
    if age is None or not birth:
        return None
    ad = birth + age - 1
    if ad == info['reign_ad']:
        return None  # 年號年本身正確（即便干支誤刻，也不動）
    if info['ganzhi_idx'] is not None:
        lo = (birth - 1) if birth else 1
        hi = (death + 1) if death else (birth + 100)
        cands = [y for y in range(lo, hi + 1) if (y - 4) % 60 == info['ganzhi_idx']]
        if not cands or ad not in cands:
            return None  # 干支無法佐證年齡（歧義/矛盾/OCR），不自動修
    # 現行年號名（extract_reign 回傳 (年號, 其後文字)，不認「### 」前綴，故先剝離）
    current_reign, rest = extract_reign(h)
    reign, n = reign_for_year(ad, current_reign=current_reign)
    if not reign:
        return None
    new_yr = _int_to_chinese_year(n)
    m = re.match(_build_year_pattern() + r'年', rest)
    if not m:
        return None
    old_part = (current_reign or '') + m.group(0)
    new_part = reign + new_yr + '年'
    if not current_reign or old_part not in h:
        return None
    fixed = h.replace(old_part, new_part, 1)
    # 修（公元註記）
    fixed = re.sub(r'（\d+年）', f'（{ad}年）', fixed, count=1)
    return prefix + fixed if fixed != h else None


def apply_fixes(result, fixes):
    """把修正套用到整理結果文本（逐標題行替換）。"""
    if not fixes:
        return result
    lines = result.split('\n')
    out = []
    for line in lines:
        replaced = False
        for old, new in fixes:
            if line.startswith(old):
                out.append(new)
                replaced = True
                break
        if not replaced:
            out.append(line)
    return '\n'.join(out)


def _anchor_fix_check(result, birth, source_desc):
    """以內部共識出生年跑 suggest_fix（CBDB 缺席回退），印報告並回傳修正清單。

    只動年號年序（suggest_fix 保守原則），干支/年齡/正文一律保留。
    """
    fixes = []
    if not birth:
        return fixes
    lines_out = [f'── 錨點共識修正（{source_desc}）──']
    for h in [l for l in result.split('\n') if l.startswith('### ')]:
        try:
            fixed = suggest_fix(h, birth, None)
        except Exception:
            continue
        if fixed:
            fixes.append((h, fixed))
    if fixes:
        lines_out.append(f'  ⚠ 建議修正 {len(fixes)} 條（年號年序誤標，干支/年齡已自洽）：')
        for old, new in fixes[:8]:
            lines_out.append(f'    {old[4:]} → {new[4:]}')
        if len(fixes) > 8:
            lines_out.append(f'    … 尚有 {len(fixes) - 8} 條')
    else:
        lines_out.append('  無需修正 ✓')
    print('\n'.join(lines_out))
    return fixes


def _cbdb_check(result, person):
    """CBDB 核驗：輸出報告並回傳 (舊標題→新標題) 修正清單。"""
    fixes = []
    birth = person.get('birth') if person else None
    death = person.get('death') if person else None
    if not birth:
        return fixes
    lines_out = ['── CBDB 生卒年核驗 ──']
    pname = person.get('name', '')
    pid = person.get('id', '')
    span = f'{birth}–{death}' if death else str(birth)
    lines_out.append(f'  傳主：{pname}（{span}，CBDB#{pid}）')
    # ① 出生年 vs 三錨點多數決
    _, _, anchor_birth, _ = verify_anchors(result)
    if anchor_birth:
        diff = anchor_birth - birth
        if diff == 0:
            lines_out.append(f'  推定出生年 {anchor_birth}：與 CBDB 一致')
        elif abs(diff) <= 1:
            lines_out.append(f'  推定出生年 {anchor_birth} ≠ CBDB {birth}（差 {diff} 年，虛歲/源文本之別，以 CBDB 為準）')
        else:
            lines_out.append(f'  推定出生年 {anchor_birth} ≠ CBDB {birth}（差 {diff} 年，請複核）')
    # ② 年譜是否止於卒前
    if death:
        max_ad = None
        for h in [l for l in result.split('\n') if l.startswith('### ')]:
            ad = _parse_heading_anchors(h)['reign_ad']
            if ad and (max_ad is None or ad > max_ad):
                max_ad = ad
        if max_ad and max_ad < death - 2:
            lines_out.append(f'  年譜止於 {max_ad}，CBDB 卒 {death}——自訂/自編年譜止於卒前 {death - max_ad} 年')
    # ③ 逐條可疑標題建議修正
    for h in [l for l in result.split('\n') if l.startswith('### ')]:
        try:
            fixed = suggest_fix(h, birth, death)
        except Exception:
            continue
        if fixed:
            fixes.append((h, fixed))
    if fixes:
        lines_out.append(f'  ⚠ 建議修正 {len(fixes)} 條（年號年序誤標，干支/年齡已自洽）：')
        for old, new in fixes[:8]:
            lines_out.append(f'    {old[4:]} → {new[4:]}')
        if len(fixes) > 8:
            lines_out.append(f'    … 尚有 {len(fixes) - 8} 條')
    else:
        lines_out.append('  無需修正 ✓')
    print('\n'.join(lines_out))
    return fixes
