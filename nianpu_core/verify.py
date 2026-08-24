# -*- coding: utf-8 -*-
"""輸出核對：遺漏條目、年齡連續性、年號切換、三錨點報告。"""



import re

from .constants import (
    REIGNS, EMPEROR_PREFIXES, PERSON_PREFIXES,
    AGE_SUFFIXES, AGE_DIGITS, STEM_BRANCH,
)
from .base import (
    _build_year_pattern, extract_reign, detect_person_prefixes,
    _gz_age_connector,
)
from .preprocess import _make_heading, _normalize_reign_variants
from .patterns import classify_format
from .anchors import verify_anchors


def verify_output(original_text, result, person_extra=None):
    """檢查年譜整理結果，報告遺漏和異常。

    比對原始文本中所有「N年干支 + 先生N歲」組合與輸出 ### 標題，
    列出遺漏的年份條目及異常情況。
    person_extra：--slots 槽位指定之傳主名前綴；None 時自動偵測。
    """
    # 年號字形先正規化（光緖→光緒），避免比對時因字形變體誤報遺漏
    original_text = _normalize_reign_variants(original_text)
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_ = r'[' + AGE_SUFFIXES + r']?'
    # bare_gz 格式（行首裸干支年標）：句末的 N年干支 若非「元年」，視為散文引用而非年份條目
    try:
        fmt_v = classify_format(original_text)
        bare_gz = fmt_v.get('bare_gz')
        gz_age = fmt_v.get('gz_age')
    except Exception:
        bare_gz = gz_age = False

    ap = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)
    ar = '|'.join(REIGNS)
    extra_person = detect_person_prefixes(original_text) if person_extra is None else list(person_extra)
    person = '(?:' + '|'.join(PERSON_PREFIXES + extra_person) + r')'

    def head_starts_with_reign(h):
        for r_ in REIGNS:
            if h.startswith(r_):
                return True
        return False

    # === 1. 在原始文本中找出所有年份+年齡（含無稱謂前綴格式與公元年格式） ===
    ad_marker = r'公元[一二三四五六七八九零〇]{3,4}年'   # 公元一八七三年…
    raw_entry_pat = re.compile(
        r'((?:' + ap + r')?(?:' + ar + r')?' + y + r'年[，,、。]?(?:' + sb + r')?'
        + r'|' + ad_marker + r')'
        + r'[^\n]{0,200}?'
        + r'(?:' + person + r'(?:年)?\s*)?' + an + as_
    )
    raw_matches = {}
    if gz_age:
        # 干支+直接年齡（李恕谷等）：庚子二歲／丙戌，年四十八歲／壬寅，康熙元年四歲。
        # 以「干支」為 marker（輸出標題含同干支），年齡另存；同干支跨 60 年重複者以 干支+年齡 為鍵。
        gz_age_pat = re.compile(
            r'(?:^|(?<=[。！？；〕，、\n' + AGE_SUFFIXES + r']))\s*'
            + r'(?<!年)' + sb
            + _gz_age_connector()
            + an + as_
        )
        for m in gz_age_pat.finditer(original_text):
            span = m.group(0).strip()
            gm = re.search(sb, span)
            age_m = re.search(an + r'[' + AGE_SUFFIXES + r']', span)
            if gm and age_m:
                gz = gm.group(0)
                key = gz + age_m.group(0)
                raw_matches.setdefault(key, {'age': age_m.group(0)[:-1], 'heading': gz,
                                             'pos': m.start(), 'gz': gz})
    else:
        for m in raw_entry_pat.finditer(original_text):
            heading_raw = _make_heading(m.group(0))
            if len(heading_raw) > 40 or '。' in heading_raw:
                continue
            # 提取年齡數字（有或無稱謂前綴）
            age_m = re.search(r'(?:' + person + r'(?:年)?\s*)?(' + an + r')[' + AGE_SUFFIXES + r']', m.group(0))
            age = age_m.group(1) if age_m else '?'
            # 提取年份部分
            marker = m.group(1)
            raw_matches[marker] = {'age': age, 'heading': heading_raw, 'pos': m.start()}

    # 排除「無干支 且 無年齡錨點」的正文年份引用（如卷末附錄/追述「三十八年，學使…」「同治二年，清釐戸管」）。
    # 真實年份條目必有其一：干支（含出生條目，如 明萬曆三十八年庚戌…）或 年齡+後綴（如 先生N嵗/公二嵗）。
    # 依「結構特徵」而非「卒年之後的位置」判斷，故年譜若把身後事作為正當條目（帶干支/年齡）編入，照常計入。
    prose_year_refs = []
    for marker, info in list(raw_matches.items()):
        if info['age'] == '?' and not re.search(sb, marker):
            prose_year_refs.append(marker)
            del raw_matches[marker]
            continue
        # bare_gz 格式：句末（非行首）的 N年干支 若非「元年」，視為散文引用
        # （重刻鄭端簡公年譜：卷末追述「二十六年甲申」「永樂十九年辛丑」皆正文追憶）
        if bare_gz:
            pos = info['pos']
            prev = original_text[pos - 1] if pos > 0 else ''
            is_linestart = (pos == 0 or prev == '\n')
            is_yuan = bool(re.search(r'元年' + sb, marker))
            if not is_linestart and not is_yuan:
                prose_year_refs.append(marker)
                del raw_matches[marker]

    # === 2. 從輸出中提取已處理的標題 ===
    output_headings = set()
    output_ages = {}
    for line in result.split('\n'):
        if line.startswith('### '):
            h = line[4:].strip()
            output_headings.add(h)
            # 提取年齡
            age_m = re.search(r'(?:' + person + r'(?:年)?\s*)?(' + an + r')[' + AGE_SUFFIXES + r']', h)
            if age_m:
                output_ages[h] = age_m.group(1)

    # === 3. 比對 ===
    findings = []
    missed = []
    captured = []

    # 提取所有原始 year marker 的簡化版本（去掉前綴）
    for marker, info in raw_matches.items():
        # 嘗試匹配輸出的 ### 標題
        found = False
        # 標題已把「十有二年」正規化為「十二年」，比對時同步正規化
        marker_n = marker.replace('十有', '十')
        for oh in output_headings:
            # 如果輸出的標題包含原始年份標記（去掉前綴），則認為已處理
            if marker_n in oh or oh in marker_n:
                found = True
                captured.append(marker)
                break
            # 或者年號補全後匹配
            if info['heading'] in oh:
                found = True
                captured.append(marker)
                break
        if not found:
            missed.append((marker, info['age']))

    # === 4. 年齡連續性 ===
    age_nums = {}
    for c in ['一二三四五六七八九十']:
        age_nums[c] = str('一二三四五六七八九十'.index(c) + 1)
    for c in ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']:
        age_nums[c] = str('零一二三四五六七八九'.index(c))

    def chinese_num_to_int(s):
        """將中文數字轉為整數（簡單版本）。"""
        if s.startswith('廿'):      # 廿=20、廿一=21…
            rest = s[1:]
            return 20 + (chinese_num_to_int(rest) if rest else 0)
        if s.startswith('卅'):      # 卅=30、卅二=32…
            rest = s[1:]
            return 30 + (chinese_num_to_int(rest) if rest else 0)
        total = 0
        if '十' in s:
            parts = s.split('十')
            if parts[0] and parts[0] in age_nums:
                total += int(age_nums[parts[0]]) * 10
            elif not parts[0]:
                total += 10
            if parts[1] and parts[1] in age_nums:
                total += int(age_nums[parts[1]])
        elif s in age_nums:
            total = int(age_nums[s])
        return total

    numeric_ages = []
    for oh, age_str in output_ages.items():
        n = chinese_num_to_int(age_str)
        if n > 0:
            numeric_ages.append(n)

    numeric_ages.sort()
    age_gaps = []
    if numeric_ages:
        expected = list(range(numeric_ages[0], numeric_ages[-1] + 1))
        missing_ages = sorted(set(expected) - set(numeric_ages))
        if missing_ages:
            age_gaps = missing_ages

    # === 5. 年號切換 ===
    reign_issues = []
    prev_reign = None
    for h in [l[4:].strip() for l in result.split('\n') if l.startswith('### ')]:
        r, _ = extract_reign(h)
        if r and r not in ('', None):
            if prev_reign and r != prev_reign:
                reign_issues.append(f"年號切換：{prev_reign} → {r}（{h[:20]}...）")
            prev_reign = r
        elif (not head_starts_with_reign(h) and prev_reign
              and not h.startswith('公元')):
            # 公元年標題（如 公元一九五零年）無年號屬正常，不報缺年號
            reign_issues.append(f"缺年號：{h[:20]}...，應爲{prev_reign}")

    # === 6. 輸出報告 ===
    report = []
    report.append("=" * 60)
    report.append("年譜整理檢查報告")
    report.append("=" * 60)

    # 覆蓋率（封頂 100%：原始偵測可能少於輸出，如魏貞庵靠嵌入式年份拆分補出標題）
    total_raw = len(raw_matches)
    total_out = len(output_headings)
    coverage = min(100.0, round(total_out / total_raw * 100, 1)) if total_raw > 0 else 0
    report.append(f"\n原始年份+年齡組合：{total_raw} 個")
    report.append(f"輸出 ### 標題：{total_out} 個")
    report.append(f"覆蓋率：{coverage}%")
    report.append(f"遺漏：{len(missed)} 個")
    if prose_year_refs:
        report.append(f"（已剔除無干支且無年齡錨點的正文年份引用 {len(prose_year_refs)} 個：{ '、'.join(prose_year_refs) }）")

    # 遺漏列表
    if missed:
        report.append(f"\n── 以下年份條目未被切分 ──")
        for marker, age in sorted(missed, key=lambda x: chinese_num_to_int(x[1]) if chinese_num_to_int(x[1]) > 0 else 999):
            age_int = chinese_num_to_int(age)
            if age_int > 0:
                report.append(f"  年齡 {age_int:2d}歲：{marker}")
            else:
                report.append(f"  年齡 {age}：{marker}")

    # 年齡空缺
    if age_gaps:
        report.append(f"\n── 年齡空缺（輸出中年齡序列不連續）──")
        # 分組顯示
        groups = []
        g_start = age_gaps[0]
        g_end = age_gaps[0]
        for a in age_gaps[1:]:
            if a == g_end + 1:
                g_end = a
            else:
                groups.append((g_start, g_end))
                g_start = g_end = a
        groups.append((g_start, g_end))
        for gs, ge in groups:
            if gs == ge:
                report.append(f"  缺 {gs} 歲")
            else:
                report.append(f"  缺 {gs}-{ge} 歲")

    # 年號問題
    if reign_issues:
        report.append(f"\n── 年號切換記錄 ──")
        for ri in reign_issues:
            report.append(f"  {ri}")

    # 可能誤匹配（不含年齡表達式的標題）
    age_pat = re.compile(r'(?:' + person + r'(?:年)?\s*)?' + an + as_)
    suspicious = [h for h in output_headings if not age_pat.search(h)]
    if suspicious:
        report.append(f"\n── 可疑標題（不含年齡）──")
        for s in suspicious:
            report.append(f"  {s}")

    report.append("=" * 60)
    return '\n'.join(report)


def _format_anchor_report(result):
    """格式化三錨點檢查報告文字。"""
    suspects, seq_bad, birth_year, total = verify_anchors(result)
    lines = ['── 三錨點一致性檢查 ──']
    lines.append(f'  標題數：{total}；推定出生年：{birth_year if birth_year else "（無法推定）"}')
    if not suspects and not seq_bad:
        lines.append('  無可疑標題 ✓')
    else:
        for raw, reasons in suspects:
            lines.append(f'  ⚠ {raw}')
            for r in reasons:
                lines.append(f'      └ {r}')
        for s in seq_bad:
            lines.append(f'  ⚠ {s}')
    return '\n'.join(lines)
