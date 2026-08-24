# -*- coding: utf-8 -*-
"""現代學者年譜（已有年份標題）支援：解析、格式統一、完整性檢查。"""



import re

from .constants import REIGNS, AGE_DIGITS, AGE_SUFFIXES, STEM_BRANCH
from .base import (
    _build_year_pattern,
    _chinese_year_to_int, _chinese_digits_to_int, _compute_ad_year,
    _ganzhi_index_of_pair, _ganzhi_pair_of_ad, _int_to_chinese_year,
)
from .preprocess import _normalize_reign_variants, _apply_ocr_fixes
from .fixes import reign_for_year


# ======== 現代學者年譜（已有年份標題）支援 ========
# 格式家族：現代學者編年譜通常已有人工標好的年份標題，本工具「檢查年份標題是否全」
# 而非重新匹配。兩種變體：
#   A（年號在前）：#### 嘉慶十八年 癸酉 1813年 一岁
#   B（公元在前）：#### 一九二三年（民國十二年癸亥）二十三歲


def _parse_modern_components(body):
    """從標題內容提取 年號年/干支/公元年/年齡 四錨點。回傳 dict（含 _spans）或 None。"""
    # 公元年（阿拉伯 3-4 位 或 中文 4 位；不含「十」以免誤配年號年序「十二年」）
    ad_m = re.search(r'(?:公元)?(?P<ad>[0-9]{3,4}|[一二三四五六七八九零〇]{3,4})\s*年', body)
    # 年號 + 年序（嘉慶十八 / 民國十二 / 光緒三十）
    r_m = re.search(r'(?P<reign>' + '|'.join(REIGNS) + r')(?P<ry>' + _build_year_pattern() + r')年', body)
    # 干支
    g_m = re.search(STEM_BRANCH, body)
    # 年齡（N嵗/歲…，後綴必備）
    a_m = re.search(r'(?P<age>' + AGE_DIGITS + r')(?P<suf>[' + AGE_SUFFIXES + r'])', body)
    if not ad_m:
        return None
    if not (r_m or g_m or a_m):
        return None
    ad = ad_m.group('ad')
    info = {
        'reign': r_m.group('reign') if r_m else None,
        'reign_year': r_m.group('ry') if r_m else None,
        'ganzhi': g_m.group(0) if g_m else None,
        'ad': ad,
        'age': a_m.group('age') if a_m else None,
        'age_suf': a_m.group('suf') if a_m else '',
    }
    info['ad_int'] = int(ad) if ad.isdigit() else _chinese_digits_to_int(ad)
    info['reign_ad'] = (_compute_ad_year(info['reign'], info['reign_year'])
                        if info['reign'] and info['reign_year'] else None)
    info['ganzhi_idx'] = (_ganzhi_index_of_pair(info['ganzhi']) if info['ganzhi'] else None)
    info['age_int'] = (_chinese_year_to_int(info['age']) if info['age'] else None)
    # 變體：公元年在左（B）或年號年在左（A）
    ad_pos = body.index(ad_m.group(0))
    r_pos = body.index(r_m.group(0)) if r_m else len(body)
    info['variant'] = 'B' if ad_pos < r_pos else 'A'
    info['_spans'] = [m.span() for m in (ad_m, r_m, g_m, a_m) if m]
    return info


def try_parse_modern_heading(line, allow_plain=False):
    """解析現代學者年譜標題行（已有標題，非待切分）。

    同時支援 A（年號在前）與 B（公元在前）兩種變體；回傳 dict 或 None。
    必須含公元年（阿拉伯 3-4 位 或 中文 4 位），且至少有年號年/干支/年齡之一，
    以免把普通「公元N年」敘述或頁碼標題誤認成年份標題。

    allow_plain=True 時亦接受無 # 前綴的純文字獨立年份行（如
    「一九三六年（民國二十五年丙子）三十六歲」）——須「四錨點覆蓋整行」
    （錨點之外餘留僅括號/空白）且行短，確保是獨立年份標題而非正文敘述。
    """
    m = re.match(r'^(?P<marker>#{2,4})\s*(?P<body>.*)$', line)
    if m:
        info = _parse_modern_components(m.group('body').strip())
        if info is None:
            return None
        info['marker'] = m.group('marker')
        info['raw'] = line
        info['body'] = m.group('body').strip()
        return info
    if not allow_plain or line.startswith('#'):
        return None
    # 純文字獨立年份行：行短 + 四錨點覆蓋整行（餘留僅括號/空白）
    if len(line) > 45:
        return None
    info = _parse_modern_components(line)
    if info is None:
        return None
    covered = [False] * len(line)
    for s, e in info['_spans']:
        for i in range(max(0, s), min(e, len(line))):
            covered[i] = True
    for i, ch in enumerate(line):
        if not covered[i] and ch not in '（）【】〔〕 　':
            return None
    info['marker'] = ''
    info['raw'] = line
    info['body'] = line
    return info


def _normalize_modern_heading(info):
    """統一現代學者年譜標題格式（依變體重組為固定結構）。"""
    reign_part = ''
    if info['reign'] and info['reign_year']:
        reign_part = info['reign'] + info['reign_year'] + '年'
    gan = info['ganzhi'] or ''
    ad_raw = info['ad'] + '年'
    # 無年齡標題（如卒年/後事）不加後綴；有年齡才補嵗/歲
    age_raw = ((info['age'] or '') + (info['age_suf'] or '歲')) if info['age'] else ''
    if info['variant'] == 'A':
        parts = [reign_part, gan, ad_raw, age_raw]
        return info['marker'] + ' ' + ' '.join(p for p in parts if p)
    # B：公元年（中文）+（年號年干支）+ 年齡
    inner = reign_part + gan
    return info['marker'] + ' ' + ad_raw + (f'（{inner}）' if inner else '') + age_raw


def check_modern_headers(headers):
    """現代學者年譜完整性檢查：推定出生年、三錨點交叉驗證、缺年清單。

    「缺年」指公元年序列的空隙——現代學者年譜常因該年無事可記而略過，
    故列出供人工確認，不自動補標題。
    """
    lines = []
    birth_cands = [p['ad_int'] - p['age_int'] + 1
                   for p in headers
                   if p['ad_int'] is not None and p['age_int'] is not None]
    birth = None
    if birth_cands:
        from collections import Counter
        birth = Counter(birth_cands).most_common(1)[0][0]

    lines.append('── 現代學者年譜（已有年份標題）完整性檢查 ──')
    lines.append(f'  年份標題數：{len(headers)}')
    if birth:
        lines.append(f'  推定出生年：{birth}（公元年 − 年齡 + 1 多數決）')

    no_age = [p for p in headers if p['age_int'] is None]
    if no_age:
        lines.append('  無年齡標題：' + '、'.join(p['raw'] for p in no_age))

    # 三錨點（＋顯式公元年）交叉驗證
    suspects = []
    for p in headers:
        reasons = []
        if p['ad_int'] is not None and p['reign_ad'] is not None and p['ad_int'] != p['reign_ad']:
            reasons.append(f'顯式公元 {p["ad_int"]} ≠ 年號年→公元 {p["reign_ad"]}')
        if p['ad_int'] is not None and p['ganzhi_idx'] is not None:
            exp = (p['ad_int'] - 4) % 60
            if p['ganzhi_idx'] != exp:
                reasons.append(f'干支{p["ganzhi"]} ≠ {p["ad_int"]}年應為 {_ganzhi_pair_of_ad(p["ad_int"])}')
        if birth and p['age_int'] is not None and p['ad_int'] is not None:
            exp_age = p['ad_int'] - birth + 1
            if p['age_int'] != exp_age:
                reasons.append(f'年齡 {p["age"]} ≠ 公元{p["ad_int"]}應為 {exp_age}歲')
        if reasons:
            suspects.append((p['raw'], reasons))
    if suspects:
        lines.append('  ⚠ 可疑標題（錨點不一致）：')
        for raw, reasons in suspects:
            lines.append(f'    {raw}')
            for r in reasons:
                lines.append(f'      └ {r}')
    else:
        lines.append('  ⚠ 可疑標題：無 ✓')

    # 缺年清單（公元序列空隙）
    ads = sorted({p['ad_int'] for p in headers if p['ad_int'] is not None})
    if ads:
        start, end = ads[0], ads[-1]
        span = end - start + 1
        lines.append(f'  覆蓋：{start}–{end}（有標題 {len(ads)} 年）')
        lines.append(f'  覆蓋率：{round(len(ads) / span * 100, 1)}%（區間 {span} 年）')
        missing = [y for y in range(start, end + 1) if y not in set(ads)]
        if missing:
            lines.append('  ── 缺年（無標題；可能該年無事可記，請人工確認）──')
            for y in missing:
                age = (y - birth + 1) if birth else None
                if age:
                    age_s = ('一' if age == 1 else _int_to_chinese_year(age)) + '歲'
                else:
                    age_s = ''
                reign, rn = reign_for_year(y)
                ry_s = (reign + _int_to_chinese_year(rn) + '年') if reign else ''
                lines.append(f'    {y}年　{age_s}{"　" if age_s else ""}{ry_s}')
        else:
            lines.append('  ── 缺年：無 ✓')

    return '\n'.join(lines)


def process_modern_nianpu(text):
    """現代學者年譜：不套用傳統年份匹配，只解析已有標題、統一格式、檢查完整性。

    allow_plain=True：亦把無 # 前綴的純文字獨立年份行（如
    「一九三六年（民國二十五年丙子）三十六歲」）提升為 #### 標題。
    """
    text = _normalize_reign_variants(text)
    text = _apply_ocr_fixes(text)
    headers = []
    for ln, line in enumerate(text.split('\n'), 1):
        info = try_parse_modern_heading(line, allow_plain=True)
        if info is not None:
            info['line'] = ln
            headers.append(info)
    # 標題層級統一：取多數決（劉熙載全為 ####；王欣夫以 #### 為主，##/### 參差者、
    # 純文字行皆歸一；無 # 前綴時預設 ####）
    canon = '####'
    if headers:
        from collections import Counter
        marked = [h for h in headers if h['marker']]
        if marked:
            canon = Counter(h['marker'] for h in marked).most_common(1)[0][0]
    out = []
    idx = 0
    for ln, line in enumerate(text.split('\n'), 1):
        if idx < len(headers) and headers[idx]['line'] == ln:
            info = headers[idx]
            info['marker'] = canon
            out.append(_normalize_modern_heading(info))
            idx += 1
        else:
            out.append(line)
    result = '\n'.join(out).strip() + '\n'
    report = check_modern_headers(headers)
    return result, report
