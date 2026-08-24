# -*- coding: utf-8 -*-
"""文本預處理：OCR 修正、年號字形歸一、跨行合併、嵌入式年份、去重補缺。"""



import re

from .constants import (
    REIGNS, EMPEROR_PREFIXES, PERSON_PREFIXES,
    AGE_SUFFIXES, AGE_DIGITS, AGE_SUFFIX_REQUIRED,
    SEASON_MARKERS, _OCR_FIXES, _REIGN_NORMALIZATIONS,
    _TG, _DZ, STEM_BRANCH,
)
from .base import (
    _build_year_pattern, extract_reign, detect_person_prefixes,
    _ganzhi_pair_of_ad,
)
from .expand import _reign_label_of_ad


# ======== OCR 容錯修正 ========


def _apply_ocr_fixes(text):
    """對文本應用常見 OCR 錯誤修正。"""
    for pattern, replacement in _OCR_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


def _normalize_reign_variants(text):
    """將年號異體字正規化為統一寫法。"""
    for old, new in _REIGN_NORMALIZATIONS.items():
        text = text.replace(old, new)
    return text


# ======== 嵌入式年份拆分 ========

def _split_embedded_years(text, person_extra=None):
    """在已合併的段落中二次掃描嵌入式年份模式。

    處理如「八年戊子五歲。九年己丑六歲」等連續密集的年份條目，
    以及行首獨立出現的「十七年壬申二十二歲」等條目。
    在 `_merge_broken_lines` 之後調用，將隱藏的年份拆出為獨立標題，
    並自動補全年號（沿用前一個標題的年號）。
    person_extra：--slots 槽位指定之傳主名前綴；None 時自動偵測。
    """
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_required = AGE_SUFFIX_REQUIRED  # 後綴必備（無稱謂直接年齡格式）
    ap = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)
    ar = '|'.join(REIGNS)
    extra_person = detect_person_prefixes(text) if person_extra is None else list(person_extra)
    person = '(?:' + '|'.join(PERSON_PREFIXES + extra_person) + r')'

    # 嵌入式模式：行首、或〔註文〕/句末標點後 接「(前綴)(年號)N年干支[標點][年]N歲」
    # 年齡後綴必備，避免把「同治十一年壬申六月」中的「六」誤切為年份標題
    embedded = re.compile(
        r'(?:^|(?<=[〕。」）！？\n]))'
        + r'(?:' + ap + r')?(?:' + ar + r')?'
        + y + r'年' + sb
        + r'[，,、。]?\s*'
        + r'(?:' + person + r')?(?:年)?'
        + an + as_required
        + r'[，。、]?'
    )

    current_reign = [None]
    lines = text.split('\n')
    result = []
    for line in lines:
        if line.startswith('### '):
            # 更新當前年號
            r, _ = extract_reign(line[4:].strip())
            if r:
                current_reign[0] = r
            result.append(line)
            continue
        if line.startswith('## ') or line.startswith('---') or not line.strip():
            result.append(line)
            continue
        # 在非標題行中查找所有嵌入式年份（不止第一處）
        parts = []
        pos = 0
        matched_any = False
        for m in embedded.finditer(line):
            if m.start() != pos:
                parts.append(line[pos:m.start()])
            heading = m.group(0).strip()
            # 補全年號
            h_reign, _ = extract_reign(heading)
            if not h_reign and current_reign[0]:
                heading = current_reign[0] + heading
            # 過長或含句號則跳過（避免誤拆）
            if len(heading) > 40 or '。' in heading:
                parts.append(line[pos:m.end()])
                pos = m.end()
                continue
            parts.append('\n### ' + heading + '\n')
            pos = m.end()
            matched_any = True
        if matched_any:
            parts.append(line[pos:])
            line = ''.join(parts)
        result.append(line)
    return '\n'.join(result)


def _dedupe_repeated_year_headings(text):
    """去述畧/卷前重複：bare_gz 格式譜的卷前摘要常以「干支，〔年號N年，公N歲〕」
    無干支形式重複彙總主內容的逐年標題。主內容行首裸干支展開後必含干支
    （年N年干支），述畧則無——故對「同一公元年」同時含干支與無干支標題者，
    保留含干支者（主內容），把述畧無干支重複條目降回正文（去 ### 前綴）。
    含干支的多緼條（如嘉靖三十三/三十六年各多緼）不受影響。僅 bare_gz 用。
    """
    lines = text.split('\n')
    blocks, cur = [], None
    for l in lines:
        if l.startswith('### '):
            if cur:
                blocks.append(cur)
            cur = [l]
        elif cur is not None:
            cur.append(l)
    if cur:
        blocks.append(cur)

    def ad_of(h):
        m = re.search(r'（(\d{4})年）', h)
        return int(m.group(1)) if m else None

    def has_gz(h):
        h2 = re.sub(r'（\d{4}年）', '', h)
        return bool(re.search(
            r'(' + '|'.join(REIGNS) + r')?[一二三四五六七八九十]{1,3}年'
            r'[甲乙丙丁戊己已庚辛壬癸巳][子丑寅卯辰巳已午未申酉戌戍戊亥]', h2))

    from collections import defaultdict
    groups = defaultdict(list)
    for i, b in enumerate(blocks):
        ad = ad_of(b[0])
        if ad is not None:
            groups[ad].append(i)
    drop = set()
    for ad, idxs in groups.items():
        if len(idxs) < 2:
            continue
        any_gz = any(has_gz(blocks[i][0]) for i in idxs)
        if not any_gz:
            continue
        drop.update(i for i in idxs if not has_gz(blocks[i][0]))
    if not drop:
        return text
    out = []
    for i, b in enumerate(blocks):
        if i in drop:
            out.append(b[0][4:])     # 降回正文（去 ### 前綴）
            out.extend(b[1:])
        else:
            out.extend(b)
    return '\n'.join(out)


def _fill_missing_bare_year_title(text):
    """補缺行内嵌入式年份（bare_gz 主叙事）：某年的行首裸干支標記被 OCR 併進前句
    （内午→丙午，如鄭端簡「…撫卷長嘆也已。丙午三月，再疏乞致仕…」），致該年缺標題。

    僅當「塊標題年 Y 的正文在句界後出現 『干支X月』，且該干支恰為 Y 的次年、
    而次年確無標題」時，才在該處拆出次年新標題──否則不動，杜絕誤切祭文/記日
    中的「干支+月」（其干支非次年，或次年已有標題）。須在 annotate_ad_years 之後
    調用，故新標題直接帶（AD年）。
    """
    lines = text.split('\n')
    blocks, cur = [], None
    for l in lines:
        if l.startswith('### '):
            if cur:
                blocks.append(cur)
            cur = [l]
        elif cur is not None:
            cur.append(l)
    if cur:
        blocks.append(cur)

    year_pat = re.compile(r'（(\d{4})年）')
    existing = set()
    for b in blocks:
        m = year_pat.search(b[0])
        if m:
            existing.add(int(m.group(1)))

    # 句界後「干支X月」：行首、或句末標點（。！？；」』）】）之後
    _sb = '|'.join(re.escape(c) for c in '。！？；」』）】')
    inline_pat = re.compile(
        r'(?:(?<=\n)|(?<=[' + _sb + r']))\s*'
        r'([' + _TG + r'][' + _DZ + r'])(?:[' + '正二三四五六七八九十' + r']{1,2}月)')

    out = []
    for b in blocks:
        m = year_pat.search(b[0])
        if not m:
            out.extend(b)
            continue
        Y = int(m.group(1))
        target = Y + 1
        if target in existing:
            out.extend(b)
            continue
        gz = _ganzhi_pair_of_ad(target)
        if not gz:
            out.extend(b)
            continue
        label = _reign_label_of_ad(target)
        if not label:
            out.extend(b)
            continue
        # 搜正文第一個匹配的句界「干支X月」
        cut = None
        for i in range(1, len(b)):
            for mm in inline_pat.finditer(b[i]):
                if mm.group(1) == gz:
                    # 记录「干支」起點：截點之前的内容（如同行「…撫卷長嘆也已。」）
                    # 仍归当年块，只把干支去掉後（保留「三月」等月名）作为次年块正文
                    cut = (i, mm.start(), mm.start() + 2)
                    break
            if cut:
                break
        if not cut:
            out.extend(b)
            continue
        i, gz_start, after_gz = cut
        new_head = f'### {label}{gz}（{target}年）'
        head_keep = b[i][:gz_start]
        tail = b[i][after_gz:]
        out.extend(b[:i])                                  # 块的前些行
        if head_keep.strip():
            out.append(head_keep)                          # 截点前行尾内容（…也已。）
        out.append(new_head)                               # 次年新標題
        if tail.strip():
            out.append(tail)                               # 次年正文（干支月之後）
        out.extend(b[i + 1:])                              # 塊內剩餘行
    return '\n'.join(out)


def _next_nonempty(lines, start):
    """回傳 (index, 內容) of 下一非空行；無則 None。"""
    for j in range(start, len(lines)):
        if lines[j].strip():
            return j, lines[j].strip()
    return None


def _merge_multi_line_years(text, person_extra=None):
    """
    合併跨行年份+年齡（沈端恪）和跨行出生（萬清軒出生條目）：
      康熙十六年\n公七歲  →  康熙十六年公七歲
      ...戊辰八月二十四日\n先生生於...  →  ...戊辰八月二十四日先生生於...
    person_extra：--slots 槽位指定之傳主名前綴；None 時自動偵測。
    """
    year_pat = _build_year_pattern()
    extra_person = detect_person_prefixes(text) if person_extra is None else list(person_extra)
    person = '(?:' + '|'.join(PERSON_PREFIXES + extra_person) + r')'
    all_reigns = '|'.join(REIGNS)
    lines = text.split('\n')
    merged = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()

        # 跨行年份+年齡：純年份行後接年齡/出生
        is_year_line = re.match(
            r'^(?:中華)?(?:' + all_reigns + r')?' + year_pat + r'年$', s
        )
        if is_year_line:
            # 跳過空行找下一非空行（民國年譜常以「中華民國N年\n\n希濤N歲」跨行相隔）
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                ns = lines[j].strip()
                if (re.match(person + r'(?:年)?\s*' + AGE_DIGITS + r'[' + AGE_SUFFIXES + r']?', ns)
                    or re.match(r'^年' + AGE_DIGITS + r'[' + AGE_SUFFIXES + r']?', ns)
                    or re.match(r'^' + person + r'生(?:於)?', ns)):
                    merged.append(s + ns)
                    i = j + 1
                    continue

        # 跨行拆分年份（影印本 OCR 把豎排標題拆成 年號/N年/干支 三行）：
        #   康熙\n五年\n丙午  →  康熙五年丙午；乾隆\n元年\n丙辰 → 乾隆元年丙辰
        if i + 1 < len(lines):
            nxt = _next_nonempty(lines, i + 1)
            nxt2 = _next_nonempty(lines, nxt[0] + 1) if nxt else None
            if (nxt and nxt2
                    and re.match(r'^(?:大淸|大清|明|中華)?(?:' + all_reigns + r')$', s)
                    and re.match(r'^' + year_pat + r'年$', nxt[1])
                    and re.match(r'^' + STEM_BRANCH + r'$', nxt2[1])):
                merged.append(s + nxt[1] + nxt2[1])
                i = nxt2[0] + 1
                continue

        # 跨行出生/續文：行末"日"後接續文（不限於先生生/公生）
        if s.endswith('日') and i + 1 < len(lines):
            ns = lines[i+1].strip()
            # 只要下一行不是獨立的年分行就合併
            if not re.match(
                r'^(?:中華)?(?:' + all_reigns + r')?' + year_pat + r'年$'
                + r'|^' + STEM_BRANCH + r'.*' + person + AGE_DIGITS,
                ns
            ):
                merged.append(s + ns)
                i += 2
                continue

        # 跨行年齡後綴：行末為年齡數字，下一行為嵗/𡻕/歳
        if i + 1 < len(lines):
            ns = lines[i+1].strip()
            if (re.search(r'年' + STEM_BRANCH + r'.*' + AGE_DIGITS + r'$', s)
                and re.match(r'^[' + AGE_SUFFIXES + r']', ns)):
                merged.append(s + ns[0] + ns[1:])
                i += 2
                continue

        # 跨行今上：OCR導致「今\n上光緒」斷行
        if s == '今' and i + 1 < len(lines):
            ns = lines[i+1].strip()
            if ns.startswith('上光緒'):
                merged.append('今上光緒' + ns[3:])
                i += 2
                continue

        merged.append(lines[i])
        i += 1
    return '\n'.join(merged)


def _make_heading(raw):
    """清理標題：移除方括註文〔〕，去除多餘空白標點。"""
    cleaned = re.sub(r'〔[^〕]*〕', '', raw)
    # 殘留未閉合〔：註文只匹配到前半時（如「〔先生二十八歲」），無對應〕 的〔 一律清除
    cleaned = re.sub(r'〔(?!.*〕)', '', cleaned)
    cleaned = cleaned.strip().rstrip('。，、, ')
    cleaned = re.sub(r'\s+', '', cleaned)
    # 句號用作干支與稱謂分隔符時（如「丙申。公四十一嵗」）改為逗號
    cleaned = cleaned.replace('。', '，')
    # 「十有二年/十有七嵗」→「十二年/十七嵗」（文言計數正規化，僅影響標題）
    cleaned = cleaned.replace('十有', '十')
    return cleaned


def _merge_broken_lines(text):
    lines = text.split('\n')
    merged, i = [], 0
    # 年份模式：用於邊界檢測
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_ = r'[' + AGE_SUFFIXES + r']?'
    ap = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)
    ar = '|'.join(REIGNS)
    year_boundary = re.compile(
        r'^(?:' + ap + r')?(?:' + ar + r')?' + y + r'年' + sb
        + r'(?:[，,、。]?\s*' + an + as_ + r')?'
    )
    while i < len(lines):
        line = lines[i]
        # 標記列表項（- x）不與前行合併（卷首 metadata 清單，如 中華古籍智慧平台 匯出格式）
        if line.startswith('#') or line.startswith('=') or not line.strip() or line.lstrip().startswith('- '):
            merged.append(line); i += 1; continue
        c = line
        while i + 1 < len(lines):
            nl = lines[i+1]
            if nl.startswith('#') or nl.startswith('=') or not nl.strip(): break
            if c.rstrip().endswith(('。','）','」','！','？')): break
            if re.match(r'^(?:' + '|'.join(SEASON_MARKERS) + r')', nl.strip()): break
            if c.rstrip().endswith(('曰','：',':','。')): break
            # 年份邊界檢測：若下一行是獨立年份條目則停止合併
            if year_boundary.match(nl.strip()):
                break
            c += nl.strip(); i += 1
        merged.append(c); i += 1
    return '\n'.join(merged)
