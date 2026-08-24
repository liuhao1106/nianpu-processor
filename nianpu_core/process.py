# -*- coding: utf-8 -*-
"""主管線：年份切分與標題化（process_nianpu）、公元年標註（annotate_ad_years）。"""



import re

from .constants import (
    REIGNS, EMPEROR_PREFIXES, PERSON_PREFIXES,
    AGE_SUFFIXES, AGE_DIGITS, STEM_BRANCH,
)
from .base import (
    _build_year_pattern, extract_reign,
    _chinese_digits_to_int, _compute_ad_year,
)
from .expand import (
    _find_gz_age_birth_ref, _reign_dynasty, _inject_birth_ganzhi,
    _expand_gz_age_heading, _expand_bare_gz_heading, _expand_pure_age_heading,
)
from .preprocess import (
    _normalize_reign_variants, _apply_ocr_fixes, _merge_multi_line_years,
    _make_heading, _merge_broken_lines, _split_embedded_years,
    _dedupe_repeated_year_headings, _fill_missing_bare_year_title,
)
from .patterns import classify_format, _build_full_pattern
from .segment import split_by_month
from .modern import process_modern_nianpu

# 語義槽位模型（--slots 配置）：slot_model.slots_to_fmt 把 LLM 推得的槽位
# 映射為本工具的格式族 dict，使新格式不需改正則、只需填槽位表
try:
    from slot_model import slots_to_fmt
except ImportError:
    slots_to_fmt = None


def annotate_ad_years(text):
    """在 ### 標題的干支後標註公元年：嘉慶十一年丙寅 → 嘉慶十一年丙寅（1806年）。

    對所有含年號+年序的標題行計算公元年並插入「（YYYY年）」。
    年號不在 REIGN_START_YEARS 表、或無年序的標題（如純干支「丙申，公四十一嵗」）保持原樣。
    """
    y = _build_year_pattern()
    # 標題開頭：(### ) + [廟號前綴?] + [年號?] + N年 + [干支?]
    head_pat = re.compile(
        r'^(?:中華)?'
        + r'(?:' + '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES) + r')?'
        + r'(?:' + '|'.join(re.escape(r) for r in REIGNS) + r')?'
    )
    yr_pat = re.compile(r'(' + y + r'年)(?:' + STEM_BRANCH + r')?')

    lines = []
    for line in text.split('\n'):
        if line.startswith('### '):
            head = line[4:]
            # 公元年格式標題：公元一八七三年，同治十二年，岁次癸酉，一岁
            # → 公元一八七三年（1873年），同治十二年，岁次癸酉，一岁
            if head.startswith('公元'):
                ad_m = re.match(r'公元([一二三四五六七八九零〇]+)年', head)
                if ad_m:
                    ad = _chinese_digits_to_int(ad_m.group(1))
                    if ad:
                        insert_at = 4 + len('公元' + ad_m.group(1) + '年')
                        line = line[:insert_at] + f'（{ad}年）' + line[insert_at:]
                lines.append(line)
                continue
            hm = head_pat.match(head)
            reign = None
            rest = head
            cn_off = 2 if head.startswith('中華') else 0
            if hm:
                base = head[cn_off:]
                rest = head[hm.end():]
                # 從標題開頭往後找年號（優先完整匹配，含廟號前綴）
                for r in REIGNS:
                    if base.startswith(r):
                        reign = r
                        rest = base[len(r):]
                        break
                else:
                    for p, r in EMPEROR_PREFIXES:
                        if p and base.startswith(p) and base[len(p):].startswith(r):
                            reign = r
                            rest = base[len(p) + len(r):]
                            break
            ym = yr_pat.match(rest)
            if reign and ym:
                ad = _compute_ad_year(reign, ym.group(1)[:-1])  # 去掉「年」字
                if ad:
                    insert_at = 4 + len(head) - len(rest) + len(ym.group(0))
                    line = line[:insert_at] + f'（{ad}年）' + line[insert_at:]
        lines.append(line)
    return '\n'.join(lines)


def process_nianpu(text, slots=None):
    """按年份切分年譜文本。

    使用正則表達式全文查找年份+年齡組合，替換為 ### 標題行。
    標題中的〔〕註文會自動清理。

    現代學者年譜（已有年份標題）另走 process_modern_nianpu：不做傳統匹配，
    只統一格式並檢查標題是否全。回傳 (result, modern_report)，非現代格式時
    modern_report 為 None。

    slots：--slots 槽位配置（slot_model.slots_to_fmt 產生的格式族 dict），
    由 LLM 依新年譜開頭推得，使新格式不需改正則。
    """
    fmt = classify_format(text)
    if slots:
        fmt = slots_to_fmt(slots)
    if fmt.get('modern'):
        return process_modern_nianpu(text)
    person_extra = fmt.get('_person_extra', [])
    # 剝離 HTML 註解（如分頁標記 <!-- 第X頁 -->），避免干擾年份識別
    text = re.sub(r'<!--.*?-->', '', text)
    # 年號字形正規化
    text = _normalize_reign_variants(text)
    # OCR 錯誤修正
    text = _apply_ocr_fixes(text)
    # --slots 的 ocr_variants：套用槽位指定的額外字形修正（如 内午→丙午、壬戍→壬戌）
    if slots and slots.get('ocr_variants'):
        for _old, _new in slots['ocr_variants'].items():
            if _old and _old != _new:
                text = text.replace(_old, _new)
    text = _merge_multi_line_years(text, person_extra=person_extra)
    reign_state = [None]
    # 干支+直接年齡（gz_age）格式：由出生條目取（出生干支, 公元年, 年號）參照，
    # 依「出生年 + 年齡」推算各條目年號年序＋公元年（_expand_gz_age_heading）
    gz_age_ref = None
    gz_age_dyn = None
    if fmt.get('gz_age'):
        gz_age_ref = _find_gz_age_birth_ref(text)
        if gz_age_ref:
            gz_age_dyn = _reign_dynasty(gz_age_ref[2])
    # 純年齡格式（曹月川先生年譜等）：出生條目為唯一紀年錨點，
    # 依出生年＋年齡 推算各條目年號年序＋公元年（_expand_pure_age_heading）
    pure_age_ref = None
    pure_age_dyn = None
    if fmt.get('pure_age'):
        pure_age_ref = _find_gz_age_birth_ref(text)
        if pure_age_ref:
            pure_age_dyn = _reign_dynasty(pure_age_ref[2])

    def insert(m):
        raw = m.group(0).strip()
        if not raw:
            return ''
        # 〔〕注文排除：僅行首裸干支（bare_gz）格式適用——其卷前/述畧常以「干支、
        # 〔年號N年，公N歲。〕」重複彙總全文年份（另以「干支、〔」跨括號開頭）。
        # person 等格式的〔〕內年份可能是合法條目（警石「〔…。道光六年丙戌旣裝潢」），
        # 故不在此排除之列。
        if fmt.get('bare_gz') and any(s <= m.end() and m.start() <= e
                                      for s, e in bracket_spans):
            return raw

        # 出生條目：在第一個句號處截斷（僅保留干支+年號+年）
        # 「先生於」中的「生於」不是出生標記（(?<!先)排除）
        person_p = '(?:' + '|'.join(PERSON_PREFIXES + fmt.get('_person_extra', [])) + r')'
        is_birth = (bool(re.search(r'(?<!先)生於', raw))
                    or re.search(person_p + r'生(?:於)?', raw) is not None)
        if is_birth and '。' in raw:
            raw = raw.split('。')[0]

        # 清理標題（移除〔〕註文）
        heading = _make_heading(raw)

        # 出生條目：移除結尾的「先生生(於)」「公生(於)」「希濤生」等，保持標題乾淨
        if is_birth:
            heading = re.sub(person_p + r'生(?:於)?$', '', heading)
            heading = heading.rstrip('，, ')
            # 干支+直接年齡（gz_age）出生條目：順治十六年閏三月… → 順治十六年己亥閏三月…（補回干支）
            if fmt.get('gz_age') and gz_age_ref:
                heading = _inject_birth_ganzhi(heading, gz_age_ref[0])

        # 純年齡格式：依出生年＋年齡 推年號年序＋干支（出生標題原樣、標題自含年號）
        if fmt.get('pure_age') and pure_age_ref:
            exp = _expand_pure_age_heading(heading, pure_age_ref, pure_age_dyn)
            if exp is not None:
                heading = exp

        # 如果清理後標題過長（>40字，出生條目 >30字），跳過
        if (not is_birth and len(heading) > 40) or (is_birth and len(heading) > 30):
            return raw
        if '。' in heading and not is_birth:
            return raw

        r, _ = extract_reign(heading)
        if r and r not in ('', None):
            reign_state[0] = r
        elif (reign_state[0] and not any(
            heading.startswith(rr) for rr in REIGNS
        ) and not heading.startswith('公元')):
            # 公元年格式標題（如 公元一九五零年）本身即為完整年份，不補上年號
            # 行首裸干支年標（bare_gz 格式）：由干支週期 + 當前年號 推得年序＋公元年
            # （丁卯，公九歲 → 正德二年丁卯，公九歲；己亥 → 嘉靖十八年己亥）
            if fmt.get('gz_age') and gz_age_ref:
                # 干支+直接年齡（gz_age）：庚子二歲 → 順治十七年庚子二歲（出生年 + 年齡推算）
                expanded = _expand_gz_age_heading(heading, gz_age_ref, gz_age_dyn)
                if expanded is not None:
                    heading = expanded
            elif fmt.get('bare_gz'):
                expanded = _expand_bare_gz_heading(heading, reign_state[0])
                if expanded is not None:
                    heading = expanded
                else:
                    # 推算失敗（含年號年序超長等不可能年份，如附録導出的「隆慶十年」）：
                    # 該行首干支屬散文/記日而無真年號，不成標題，保留原文
                    return raw
            else:
                heading = reign_state[0] + heading

        return '\n### ' + heading + '\n'

    # 格式預分類：只套用與本譜相關的 pattern 子集，降低誤配（L1）
    pat = _build_full_pattern(fmt)
    # 〔〕註文跨度（供 insert 排除註文內的重複年份條目，如鄭端簡述畧）。
    # 於 OCR 修正後的 text 上計算，與 pat.sub 使用的 text 一致。
    bracket_spans = [(mo.start(), mo.end()) for mo in re.finditer(r'〔[^〕]*〕', text)]
    result = pat.sub(insert, text)
    result = _merge_broken_lines(result)
    result = _split_embedded_years(result, person_extra=person_extra)
    # 干支+直接年齡（gz_age）年譜為逐年短敘散文，季節字（春夏秋冬）多為正文用語
    # （如討論《春秋》「春正月無氷」），按月/季節分段會誤切，跳過
    if not fmt.get('gz_age') and not fmt.get('pure_age'):
        result = split_by_month(result)
    # 在標題上標註公元年：嘉慶十一年丙寅 → 嘉慶十一年丙寅（1806年）
    result = annotate_ad_years(result)
    # 述畧/卷前重複年份去重（bare_gz 格式：保留含干支主內容、述畧無干支重複降回正文）
    if fmt.get('bare_gz'):
        result = _dedupe_repeated_year_headings(result)
        # 補缺行内嵌入式年份（bare_gz）：行首干支被 OCR 併入前句致缺年標題者（鄭端簡 1546）
        result = _fill_missing_bare_year_title(result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip() + '\n', None
