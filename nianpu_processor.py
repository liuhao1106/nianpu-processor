#!/usr/bin/env python3
"""
年譜整理工具 — Nianpu Processor
=================================
一鍵處理中國年譜，支援多種年份格式：

格式A：X年干支，先生年N嵗       (方柏堂風格)
格式B：X年干支N嵗              (萬清軒風格，年齡直接接在干支後)
格式C：X年干支[，]年N嵗        (方柏堂變體)
格式D：X年干支，公年N[歲]       (張清恪風格)
格式E：X年 公N歲（跨行年份+年齡）(沈端恪風格)
格式F：出生：X年干支...先生生/公生

功能：年份標題化、年號補全、段落整理、月份/季節分段、自我進化（置信度評分、從修正中學習、審查清理）

用法：
  python nianpu_processor.py <輸入檔案路徑> [輸出檔案路徑]
  python nianpu_processor.py --status        # 查看學習狀態
  python nianpu_processor.py --prune          # 清理無效學習
"""

import re, sys, json, os
from pathlib import Path

SKILL_DIR = Path(__file__).parent.resolve()
LEARNINGS_FILE = SKILL_DIR / 'learnings.json'


# ======== 配置區 ========
# 年號：包含宋代、元代、明代（含南明）、清代
# 注意：清與南明年號在前（沿用既有行為），其後為明/元/宋；無重疊前綴，順序不影響匹配
REIGNS = [
    # 明代
    '洪武', '建文', '永樂', '洪熙', '宣德', '正統', '景泰', '天順', '成化',
    '弘治', '正德', '嘉靖', '隆慶', '萬厯', '萬曆', '泰昌', '天啟', '崇禎',
    # 南明
    '隆武', '永厯', '永曆', '宏光', '弘光', '紹武',
    # 元代
    '中統', '至元', '元貞', '大德', '至大', '皇慶', '延祐', '至治', '泰定',
    '致和', '天曆', '至順', '元統', '至正',
    # 宋代（北宋+南宋）
    '建隆', '乾德', '開寶', '太平興國', '雍熙', '端拱', '淳化', '至道',
    '咸平', '景德', '大中祥符', '天禧', '乾興', '天聖', '明道', '景祐',
    '寶元', '康定', '慶曆', '皇祐', '至和', '嘉祐', '治平', '熙寧', '元豐',
    '元祐', '紹聖', '元符', '建中靖國', '崇寧', '大觀', '政和', '重和',
    '宣和', '靖康', '建炎', '紹興', '隆興', '乾道', '淳熙', '紹熙', '慶元',
    '嘉泰', '開禧', '嘉定', '寶慶', '紹定', '端平', '嘉熙', '淳祐', '寶祐',
    '開慶', '景定', '咸淳', '德祐', '景炎', '祥興',
    # 清代
    '順治', '康熙', '雍正', '乾隆', '嘉慶', '道光', '咸豐', '同治', '光緖', '光緒',
]

EMPEROR_PREFIXES = [
    ('世祖章皇帝','順治'),('世祖章','順治'),
    ('聖祖仁皇帝','康熙'),('聖祖仁','康熙'),
    ('世宗憲皇帝','雍正'),('世宗憲','雍正'),
    ('高宗純皇帝','乾隆'),('高宗純','乾隆'),
    ('仁宗睿皇帝','嘉慶'),('仁宗睿','嘉慶'),
    ('宣宗成皇帝','道光'),('宣宗成','道光'),
    ('文宗顯皇帝','咸豐'),('文宗顯','咸豐'),
    ('穆宗毅皇帝','同治'),('穆宗毅','同治'),
    ('德宗景皇帝','光緖'),('德宗景','光緖'),
    ('今上','光緖'),
    ('大淸',''),('大清',''),   # 大清是年號前綴，實際年號跟在其後
    ('明',''),                  # 明是年號前綴，實際年號跟在其後
]

PERSON_PREFIXES = ['先生','公','府君']
AGE_SUFFIXES = '嵗歲歳𡻕'
AGE_SUFFIX_REQUIRED = '[' + AGE_SUFFIXES + ']'   # 年齡後綴必備（無稱謂格式用，避免誤配「六月」等月份/日期字）
AGE_DIGITS = r'[十有和一二三四五六七八九十百零〇\d]+'

# 各年號元年對應的公元年份（含異體字）。用於在標題上標註公元年，如 嘉慶十一年 → 1806年
REIGN_START_YEARS = {
    # 明代
    '洪武': 1368, '建文': 1399, '永樂': 1403, '洪熙': 1425, '宣德': 1426,
    '正統': 1436, '景泰': 1450, '天順': 1457, '成化': 1465, '弘治': 1488,
    '正德': 1506, '嘉靖': 1522, '隆慶': 1567,
    '萬厯': 1573, '萬曆': 1573,
    '泰昌': 1620, '天啟': 1621, '崇禎': 1628,
    # 南明
    '隆武': 1645, '永厯': 1647, '永曆': 1647,
    '宏光': 1644, '弘光': 1644, '紹武': 1646,
    # 元代
    '中統': 1260, '至元': 1264, '元貞': 1295, '大德': 1297, '至大': 1308,
    '皇慶': 1312, '延祐': 1314, '至治': 1321, '泰定': 1324, '致和': 1328,
    '天曆': 1328, '至順': 1330, '元統': 1333, '至正': 1341,
    # 宋代（北宋+南宋）
    '建隆': 960, '乾德': 963, '開寶': 968, '太平興國': 976, '雍熙': 984,
    '端拱': 988, '淳化': 990, '至道': 995, '咸平': 998, '景德': 1004,
    '大中祥符': 1008, '天禧': 1017, '乾興': 1022, '天聖': 1023, '明道': 1032,
    '景祐': 1034, '寶元': 1038, '康定': 1040, '慶曆': 1041, '皇祐': 1049,
    '至和': 1054, '嘉祐': 1056, '治平': 1064, '熙寧': 1068, '元豐': 1078,
    '元祐': 1086, '紹聖': 1094, '元符': 1098, '建中靖國': 1101, '崇寧': 1102,
    '大觀': 1107, '政和': 1111, '重和': 1118, '宣和': 1119, '靖康': 1126,
    '建炎': 1127, '紹興': 1131, '隆興': 1163, '乾道': 1165, '淳熙': 1174,
    '紹熙': 1190, '慶元': 1195, '嘉泰': 1201, '開禧': 1205, '嘉定': 1208,
    '寶慶': 1225, '紹定': 1228, '端平': 1234, '嘉熙': 1237, '淳祐': 1241,
    '寶祐': 1253, '開慶': 1259, '景定': 1260, '咸淳': 1265, '德祐': 1275,
    '景炎': 1276, '祥興': 1278,
    # 清代
    '順治': 1644, '康熙': 1662, '雍正': 1723, '乾隆': 1736, '嘉慶': 1796,
    '道光': 1821, '咸豐': 1851, '同治': 1862, '光緖': 1875, '光緒': 1875,
}

# 中文數字→整數
_CN_NUM = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '百': 100,
}


def _chinese_year_to_int(s):
    """中文數字年份（元/一~九/十/十一~十九/二十~九十九/十有一）轉為整數。"""
    if s == '元':
        return 1
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


def _compute_ad_year(reign, year_str):
    """由年號與年序計算公元年：公元年 = 年號元年公元 + 年序 - 1。"""
    start = REIGN_START_YEARS.get(reign)
    if start is None:
        return None
    n = _chinese_year_to_int(year_str)
    if n is None:
        return None
    return start + n - 1

# 天干地支（精確匹配，避免誤配「正月」「八月」）
# 包含常見OCR變體：已（U+5DF2）代替己（U+5DF1）和巳（U+5DF3）
_TG = '甲乙丙丁戊己已庚辛壬癸巳'
_DZ = '子丑寅卯辰巳已午未申酉戌亥'
STEM_BRANCH = r'[' + _TG + r'][' + _DZ + r']'

SEASON_MARKERS = [
    '春正月','春二月','春三月','夏四月','夏五月','夏六月',
    '秋七月','秋八月','秋九月','冬十月','冬十一月','冬十二月',
    '是年','先是',
]
# 月份/季節分段用
_SEASONS = ['春', '夏', '秋', '冬']
_SEASON_MONTHS = {
    '春': ['正月', '二月', '三月'],
    '夏': ['四月', '五月', '六月'],
    '秋': ['七月', '八月', '九月'],
    '冬': ['十月', '十一月', '十二月'],
}

EVENT_MARKERS = ['書至','將南歸']  # 非季節的事件標記，用於段落合併邊界

# ======== OCR 容錯修正 ========

_OCR_FIXES = [
    # 先生年 → 先元年（常見 OCR 錯誤：生→元）
    (r'先元年', '先生年'),
    # 十年九歲 → 十九歲（OCR 斷字錯誤）
    (r'十年九', '十九'),
    # 廿 → 二十
    (r'廿(\s*年)', r'二十\1'),
    # 卅 → 三十
    (r'卅(\s*年)', r'三十\1'),
]

def _apply_ocr_fixes(text):
    """對文本應用常見 OCR 錯誤修正。"""
    for pattern, replacement in _OCR_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


# ======== 年號字形正規化 ========

_REIGN_NORMALIZATIONS = {
    '光緖': '光緒',
    '萬厯': '萬曆',
    '永厯': '永曆',
}

def _normalize_reign_variants(text):
    """將年號異體字正規化為統一寫法。"""
    for old, new in _REIGN_NORMALIZATIONS.items():
        text = text.replace(old, new)
    return text


# ======== 嵌入式年份拆分 ========

def _split_embedded_years(text):
    """在已合併的段落中二次掃描嵌入式年份模式。

    處理如「八年戊子五歲。九年己丑六歲」等連續密集的年份條目，
    以及行首獨立出現的「十七年壬申二十二歲」等條目。
    在 `_merge_broken_lines` 之後調用，將隱藏的年份拆出為獨立標題，
    並自動補全年號（沿用前一個標題的年號）。
    """
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_required = AGE_SUFFIX_REQUIRED  # 後綴必備（無稱謂直接年齡格式）
    ap = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)
    ar = '|'.join(REIGNS)

    # 嵌入式模式：行首、或〔註文〕/句末標點後 接「(前綴)(年號)N年干支[標點][年]N歲」
    # 年齡後綴必備，避免把「同治十一年壬申六月」中的「六」誤切為年份標題
    embedded = re.compile(
        r'(?:^|(?<=[〕。」）！？\n]))'
        + r'(?:' + ap + r')?(?:' + ar + r')?'
        + y + r'年' + sb
        + r'[，,、。]?\s*'
        + r'(?:年)?'
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


# ======== 自我進化系統 ========

_LEARNINGS_CACHE = None  # 記憶體緩存，避免重複讀檔


def _learnings_path():
    return LEARNINGS_FILE


def _load_learnings():
    """載入學習檔案，若不存在則返回空模板。"""
    global _LEARNINGS_CACHE
    if _LEARNINGS_CACHE is not None:
        return _LEARNINGS_CACHE
    template = {
        'discovered_reigns': {},      # {年號: {source: 檔名, count: N, confidence: 0.0~1.0, invalidated: false}}
        'discovered_prefixes': {},    # {前綴: {source: 檔名, reign: 年號, invalidated: false}}
        'age_suffix_variants': {},    # {字形: {source: 檔名, invalidated: false}}
        'person_prefix_variants': {}, # {稱謂: {source: 檔名, invalidated: false}}
        'corrections': [],            # [{type: 'reign'|'prefix'|'suffix', wrong: '', correct: '',
                                      #   source: 檔名, date: ISO}]
        'processed_files': [],        # [{file: 檔名, year_count: N, coverage: %,
                                      #   missed: N, format: 格式描述}]
    }
    p = _learnings_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            for key in template:
                if key not in data:
                    data[key] = template[key]
            # 確保舊數據有 invalidated 字段
            for section in ['discovered_reigns', 'discovered_prefixes',
                            'age_suffix_variants', 'person_prefix_variants']:
                for k, v in data.get(section, {}).items():
                    if isinstance(v, dict) and 'invalidated' not in v:
                        v['invalidated'] = False
            _LEARNINGS_CACHE = data
            return data
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    _LEARNINGS_CACHE = dict(template)
    return _LEARNINGS_CACHE


def _save_learnings(data):
    """保存學習檔案。"""
    global _LEARNINGS_CACHE
    _LEARNINGS_CACHE = data
    p = _learnings_path()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _is_valid_reign_candidate(candidate):
    """驗證年號候選是否合理。

    排除：純數字、太短、含標點、含年歲字、已知年號的子集。
    """
    # 必須是 2-6 個 CJK 字元
    if len(candidate) < 2 or len(candidate) > 6:
        return False
    # 不能是純數字或數字相關
    if all(c in '一二三四五六七八九十百千萬零' for c in candidate):
        return False
    # 不能含標點
    if re.search(r'[。，、！？；：〔〕「」『』（）\[\]《》〈〉""''，、\s]', candidate):
        return False
    # 不能含年歲嵗等表示時間的字
    if any(c in candidate for c in '年歲嵗'):
        return False
    # 不能是已知年號的片段
    for known in REIGNS:
        if candidate in known or known in candidate:
            return False
    # 不能是皇帝前綴的片段
    for prefix, _ in EMPEROR_PREFIXES:
        if prefix and candidate in prefix:
            return False
    # 必須至少包含一個 CJK 統一表意文字
    cjk_count = sum(1 for c in candidate if '\u4e00' <= c <= '\u9fff')
    if cjk_count < 1:
        return False
    return True


def _compute_reign_confidence(candidate, text, matches_in_text):
    """計算年號候選的置信度 (0.0~1.0)。"""
    score = 0.0

    # 1. 出現次數 (最多 0.3)
    if matches_in_text <= 1:
        score += 0.05
    elif matches_in_text == 2:
        score += 0.15
    else:
        score += 0.3

    # 2. 候選品質 (最多 0.4)
    if 2 <= len(candidate) <= 4:
        score += 0.2  # 正常年號長度
    # 結尾不含「皇皇帝帝」
    if not candidate.endswith(('皇', '帝')):
        score += 0.1
    # 看起來像年號的常見結尾模式
    if candidate[-1] in ('治', '熙', '慶', '光', '豐', '緒', '禎', '曆', '武', '統'):
        score += 0.1
    # 是否和已知年號共享部首/偏旁（形近字探測）
    for known in REIGNS:
        shared = sum(1 for a, b in zip(candidate, known) if a == b)
        if shared >= 2 and len(candidate) >= 2:
            score += 0.1
            break

    # 3. 上下文品質 (最多 0.3)
    # 出現位置前後是否和年份相關
    for m in re.finditer(re.escape(candidate) + r'\d+年' + STEM_BRANCH, text):
        score += 0.2
        break
    # 不和其他雜訊關鍵字相鄰
    noise_pattern = r'[。，、！？]' + re.escape(candidate)
    if re.search(noise_pattern, text):
        score -= 0.1

    return max(0.0, min(1.0, score))


def _discover_reigns(text):
    """掃描文本，發現不在 REIGNS 列表中的年號。

    策略：查找「N年干支」模式，提取 N 之前的文字作為潛在年號。
    加入驗證和置信度評分，過濾假陽性。
    """
    y = _build_year_pattern()
    sb = STEM_BRANCH
    pattern = re.compile(r'([^\d\s\n]{1,6})' + y + r'年' + sb)
    found = {}
    for m in pattern.finditer(text):
        candidate = m.group(1).strip()
        if candidate in REIGNS:
            continue
        if any(candidate.startswith(r) for r in REIGNS):
            continue
        if any(candidate.endswith(p) for p in ['先生', '公', '府君']):
            continue
        if not _is_valid_reign_candidate(candidate):
            continue
        if candidate not in found:
            found[candidate] = 0
        found[candidate] += 1

    # 計算置信度並過濾低置信度候選
    result = {}
    for candidate, count in found.items():
        confidence = _compute_reign_confidence(candidate, text, count)
        # 置信度 < 0.2 的跳過
        if confidence < 0.2:
            continue
        result[candidate] = {
            'count': count,
            'confidence': round(confidence, 2)
        }
    return result


def _is_valid_prefix_candidate(prefix):
    """驗證皇帝前綴候選是否合理。"""
    # 不能含標點
    if re.search(r'[。，、！？；：]', prefix):
        return False
    # 長度合理 (2-12)
    if len(prefix) < 2 or len(prefix) > 12:
        return False
    # 必須以皇帝/皇/帝結尾
    if not prefix.endswith(('皇帝', '皇', '帝')):
        return False
    return True


def _discover_prefixes(text):
    """掃描文本，發現新的皇帝廟號前綴。"""
    known_prefixes = [p for p, _ in EMPEROR_PREFIXES if p]
    pat = re.compile(r'([^\s\n]{2,12}(?:皇帝|皇|帝))(' + '|'.join(REIGNS) + r')')
    found = {}
    for m in pat.finditer(text):
        prefix = m.group(1)
        reign = m.group(2)
        if prefix not in known_prefixes and _is_valid_prefix_candidate(prefix):
            found[prefix] = reign
    return found


def _is_valid_suffix_candidate(suffix):
    """驗證年齡後綴候選是否合理。

    合理的年齡後綴：單個字，且和「歲」字形相近（含止/山/夕等部件）。
    """
    if len(suffix) != 1:
        return False
    if suffix in AGE_SUFFIXES:
        return False
    if suffix in '歲歳嵗𡻕年歲':
        return False
    # 檢查是否包含「歲」的部件
    sui_parts = set('歲歳嵗𡻕')
    if any(p in suffix for p in sui_parts):
        return True
    # 檢查常見 OCR 變體：足→𧾷、山部首等
    ocr_variants = set('𡻕𡻑𡺼𡵌𡶫')
    if any(v in suffix for v in ocr_variants):
        return True
    return False


def _discover_age_suffixes(text):
    """掃描文本，發現新的年齡後綴字形。"""
    an = AGE_DIGITS
    pat = re.compile(r'(?:' + an + r')([^，。、\s\n]{1,2})')
    found = set()
    for m in pat.finditer(text):
        s = m.group(1)
        if _is_valid_suffix_candidate(s):
            found.add(s)
    return found


def self_learn(original_text, result, source_file='', report_lines=None):
    """分析處理結果，發現新知並存入學習檔案。

    Args:
        original_text: 原始文本
        result: 處理後的文本
        source_file: 來源檔案名
        report_lines: verification report lines (list)
    """
    learnings = _load_learnings()

    # 1. 發現新年號（含置信度）
    new_reigns = _discover_reigns(original_text)
    for r, info in new_reigns.items():
        if r not in learnings['discovered_reigns']:
            learnings['discovered_reigns'][r] = {
                'source': source_file,
                'count': info['count'],
                'confidence': info['confidence'],
                'invalidated': False
            }
        else:
            existing = learnings['discovered_reigns'][r]
            existing['count'] = existing.get('count', 0) + info['count']
            # 保留更高的置信度
            existing['confidence'] = max(
                existing.get('confidence', 0), info['confidence']
            )

    # 2. 發現新前綴
    new_prefixes = _discover_prefixes(original_text)
    for prefix, reign in new_prefixes.items():
        if prefix not in learnings['discovered_prefixes']:
            learnings['discovered_prefixes'][prefix] = {
                'source': source_file,
                'reign': reign,
                'invalidated': False
            }

    # 3. 發現新字形
    new_suffixes = _discover_age_suffixes(original_text)
    for s in new_suffixes:
        if s not in learnings['age_suffix_variants']:
            learnings['age_suffix_variants'][s] = {
                'source': source_file,
                'invalidated': False
            }

    # 4. 統計處理結果
    hs = [l for l in result.split('\n') if l.startswith('### ')]
    year_count = len(hs)

    # 從 report_lines 提取覆蓋率
    coverage = 0.0
    missed = 0
    if report_lines:
        for line in report_lines:
            m = re.search(r'覆蓋率：([\d.]+)%', line)
            if m:
                coverage = float(m.group(1))
            m = re.search(r'遺漏：(\d+)', line)
            if m:
                missed = int(m.group(1))

    # 去重：避免同一檔案重複記錄
    existing_indices = [
        i for i, f in enumerate(learnings['processed_files'])
        if f['file'] == source_file
    ]
    if existing_indices:
        # 更新最後一次記錄
        idx = existing_indices[-1]
        learnings['processed_files'][idx] = {
            'file': source_file,
            'year_count': year_count,
            'coverage': coverage,
            'missed': missed,
            'reigns_found': list(new_reigns.keys()) if new_reigns else [],
        }
    else:
        learnings['processed_files'].append({
            'file': source_file,
            'year_count': year_count,
            'coverage': coverage,
            'missed': missed,
            'reigns_found': list(new_reigns.keys()) if new_reigns else [],
        })

    # 只保留最近 50 條記錄
    if len(learnings['processed_files']) > 50:
        learnings['processed_files'] = learnings['processed_files'][-50:]

    _save_learnings(learnings)
    return learnings


def _record_correction(learnings, corr_type, wrong_value, correct_value, source):
    """記錄一個手動修正（用於從修正中學習）。"""
    learnings.setdefault('corrections', [])
    learnings['corrections'].append({
        'type': corr_type,
        'wrong': wrong_value,
        'correct': correct_value,
        'source': source,
        'date': __import__('datetime').datetime.now().isoformat()[:10]
    })

    # 同時標記對應的發現為無效
    if corr_type == 'reign' and wrong_value in learnings.get('discovered_reigns', {}):
        learnings['discovered_reigns'][wrong_value]['invalidated'] = True
    elif corr_type == 'prefix' and wrong_value in learnings.get('discovered_prefixes', {}):
        learnings['discovered_prefixes'][wrong_value]['invalidated'] = True
    elif corr_type == 'suffix' and wrong_value in learnings.get('age_suffix_variants', {}):
        learnings['age_suffix_variants'][wrong_value]['invalidated'] = True


def prune_invalidated_learnings(learnings=None):
    """移除所有被標記為無效的學習，並整理數據。

    可在命令列調用：python nianpu_processor.py --prune
    """
    if learnings is None:
        learnings = _load_learnings()

    removed = {'reigns': [], 'prefixes': [], 'suffixes': []}

    # 清理無效年號
    for r in list(learnings.get('discovered_reigns', {}).keys()):
        info = learnings['discovered_reigns'][r]
        if info.get('invalidated'):
            removed['reigns'].append(r)
            del learnings['discovered_reigns'][r]

    # 清理無效前綴
    for p in list(learnings.get('discovered_prefixes', {}).keys()):
        info = learnings['discovered_prefixes'][p]
        if info.get('invalidated'):
            removed['prefixes'].append(p)
            del learnings['discovered_prefixes'][p]

    # 清理無效字形
    for s in list(learnings.get('age_suffix_variants', {}).keys()):
        info = learnings['age_suffix_variants'][s]
        if info.get('invalidated'):
            removed['suffixes'].append(s)
            del learnings['age_suffix_variants'][s]

    _save_learnings(learnings)
    return removed


_DEFAULT_CONFIDENCE_THRESHOLD = 0.4  # 年號自動應用的置信度閾值


def apply_learnings():
    """從學習檔案加載已知知識，動態擴展配置。

    使用置信度閾值過濾低質量年號，排除已無效的學習。
    返回學習摘要（新增了什麼）。
    """
    learnings = _load_learnings()
    changes = []

    # 動態擴展 REIGNS（僅置信度 >= 閾值的，且未被無效化的）
    new_ri = []
    for r, info in sorted(learnings['discovered_reigns'].items()):
        if r not in REIGNS:
            conf = info.get('confidence', 0)
            count = info.get('count', 0)
            invalidated = info.get('invalidated', False)
            if not invalidated and count >= 2 and conf >= _DEFAULT_CONFIDENCE_THRESHOLD:
                new_ri.append(r)
    if new_ri:
        REIGNS.extend(new_ri)
        changes.append(f"年號 +{len(new_ri)}：{'、'.join(new_ri)}")

    # 動態擴展 EMPEROR_PREFIXES（排除已無效的）
    existing_prefixes = {p for p, _ in EMPEROR_PREFIXES}
    new_ep = []
    for p, info in learnings['discovered_prefixes'].items():
        if p not in existing_prefixes and not info.get('invalidated', False):
            new_ep.append((p, info['reign']))
    if new_ep:
        for prefix, reign in new_ep:
            EMPEROR_PREFIXES.insert(0, (prefix, reign))
        changes.append(f"前綴 +{len(new_ep)}：{'、'.join(p for p, _ in new_ep)}")

    return changes


def print_learnings_summary():
    """輸出學習摘要。"""
    learnings = _load_learnings()
    lines = []
    lines.append("=" * 60)
    lines.append("年譜工具 — 自我進化報告")
    lines.append("=" * 60)

    d_r = learnings['discovered_reigns']
    d_p = learnings['discovered_prefixes']
    d_s = learnings['age_suffix_variants']
    corrections = learnings.get('corrections', [])
    files = learnings['processed_files']

    # === 新年號 ===
    # 分為有效和無效
    valid_reigns = {k: v for k, v in d_r.items() if not v.get('invalidated', False)}
    invalid_reigns = {k: v for k, v in d_r.items() if v.get('invalidated', False)}

    if valid_reigns:
        lines.append(f"\n▸ 已發現 {len(valid_reigns)} 個新年號（有效）：")
        for r, info in sorted(valid_reigns.items()):
            conf = info.get('confidence', 0)
            bar = '█' * int(conf * 10) + '░' * (10 - int(conf * 10))
            lines.append(f"  「{r}」發現 {info['count']} 次 [置信度 {conf:.0%} {bar}]")

    if invalid_reigns:
        lines.append(f"\n▸ 已作廢 {len(invalid_reigns)} 個年號（無效）：")
        for r, info in sorted(invalid_reigns.items()):
            lines.append(f"  「{r}」（來源：{info['source']}）")

    # === 新前綴 ===
    valid_prefixes = {k: v for k, v in d_p.items() if not v.get('invalidated', False)}
    invalid_prefixes = {k: v for k, v in d_p.items() if v.get('invalidated', False)}

    if valid_prefixes:
        lines.append(f"\n▸ 已發現 {len(valid_prefixes)} 個新前綴（有效）：")
        for p, info in valid_prefixes.items():
            lines.append(f"  「{p}」→ {info['reign']}")
    if invalid_prefixes:
        lines.append(f"\n▸ 已作廢 {len(invalid_prefixes)} 個前綴（無效）：")
        for p, info in invalid_prefixes.items():
            lines.append(f"  「{p}」→ {info['reign']}")

    # === 字形變體 ===
    valid_suffixes = {k: v for k, v in d_s.items() if not v.get('invalidated', False)}
    invalid_suffixes = {k: v for k, v in d_s.items() if v.get('invalidated', False)}

    if valid_suffixes:
        lines.append(f"\n▸ 已發現 {len(valid_suffixes)} 個字形變體（有效）：")
        for s, info in valid_suffixes.items():
            code = f"U+{ord(s[0]):04X}" if len(s) == 1 else f"U+{ord(s[0]):04X}…"
            lines.append(f"  {code}「{s}」")
    if invalid_suffixes:
        lines.append(f"\n▸ 已作廢 {len(invalid_suffixes)} 個字形（無效）：")
        for s, info in invalid_suffixes.items():
            code = f"U+{ord(s[0]):04X}" if len(s) == 1 else f"U+{ord(s[0]):04X}…"
            lines.append(f"  {code}「{s}」")

    # === 修正記錄 ===
    if corrections:
        lines.append(f"\n▸ 修正記錄：{len(corrections)} 條")
        for c in corrections[-5:]:  # 只顯示最近5條
            lines.append(f"  {c['type']}：「{c['wrong']}」→「{c['correct']}」（{c.get('date', '?')}）")

    # === 處理統計 ===
    if files:
        total = len(files)
        avg_cov = sum(f['coverage'] for f in files) / total if total > 0 else 0
        total_years = sum(f['year_count'] for f in files)
        lines.append(f"\n▸ 處理統計：{total} 個年譜，{total_years} 個年份，平均覆蓋率 {avg_cov:.1f}%")
        lines.append(f"  最近處理：{files[-1]['file']}（{files[-1]['year_count']} 年，覆蓋率 {files[-1]['coverage']}%）")

    lines.append("=" * 60)
    return '\n'.join(lines)


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
    ]
    return '(?:' + '|'.join(nums) + ')'


def extract_reign(heading):
    """從標題行中提取年號。"""
    h = heading.strip()
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


def _merge_multi_line_years(text):
    """
    合併跨行年份+年齡（沈端恪）和跨行出生（萬清軒出生條目）：
      康熙十六年\n公七歲  →  康熙十六年公七歲
      ...戊辰八月二十四日\n先生生於...  →  ...戊辰八月二十四日先生生於...
    """
    year_pat = _build_year_pattern()
    person = '(?:' + '|'.join(PERSON_PREFIXES) + r')'
    all_reigns = '|'.join(REIGNS)
    lines = text.split('\n')
    merged = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()

        # 跨行年份+年齡：純年份行後接年齡/出生
        is_year_line = re.match(
            r'^(?:' + all_reigns + r')?' + year_pat + r'年$', s
        )
        if is_year_line and i + 1 < len(lines):
            ns = lines[i+1].strip()
            if (re.match(person + r'(?:年)?\s*' + AGE_DIGITS + r'[' + AGE_SUFFIXES + r']?', ns)
                or re.match(r'^年' + AGE_DIGITS + r'[' + AGE_SUFFIXES + r']?', ns)
                or re.match(r'^' + person + r'生(?:於)?', ns)):
                merged.append(s + ns)
                i += 2
                continue

        # 跨行出生/續文：行末"日"後接續文（不限於先生生/公生）
        if s.endswith('日') and i + 1 < len(lines):
            ns = lines[i+1].strip()
            # 只要下一行不是獨立的年分行就合併
            if not re.match(
                r'^(?:' + all_reigns + r')?' + year_pat + r'年$'
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
    cleaned = cleaned.strip().rstrip('。，, ')
    cleaned = re.sub(r'\s+', '', cleaned)
    # 句號用作干支與稱謂分隔符時（如「丙申。公四十一嵗」）改為逗號
    cleaned = cleaned.replace('。', '，')
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
        if line.startswith('#') or line.startswith('=') or not line.strip():
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


def split_by_month(text):
    """按月份/季節分段，將年份內的內容按 春/夏/秋/冬 拆分。

    識別模式：
      - 春正月/二月/三月，夏四月/五月/六月，秋七月/八月/九月，冬十月/十一月/十二月
      - 僅季節（春、夏、秋、冬）
      - 「是春」「是夏」「是秋」「是冬」
      - 是歲、是年（歸入前段）

    輸出格式：**春正月**內容...\n\n**夏四月**內容...
    """
    all_labels = _build_all_labels()

    pattern = re.compile(
        r'(?:(?<=[。？！\n○\s])|^)((?:是)?(?:'
        + '|'.join(
            f'{s}(?:' + '|'.join(_SEASON_MONTHS[s]) + ')?'
            for s in _SEASONS
        )
        + r')|是歲|是年)'
    )

    lines = text.split('\n')
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('### '):
            result_lines.append(line)
            i += 1
            year_content = []
            while i < len(lines):
                if not lines[i].strip():
                    year_content.append(lines[i])
                    i += 1
                    continue
                if lines[i].startswith('### ') or lines[i].startswith('---') or lines[i].startswith('## '):
                    break
                year_content.append(lines[i])
                i += 1

            content_text = '\n'.join(year_content)
            if content_text.strip():
                processed = _process_year_content(content_text, all_labels, pattern)
            else:
                processed = content_text
            result_lines.append(processed)
        else:
            result_lines.append(line)
            i += 1
    return '\n'.join(result_lines)


def _build_all_labels():
    """生成所有月份/季節標籤，用於匹配和清理。"""
    all_labels = []
    for s in _SEASONS:
        all_labels.append(f'是{s}')
        all_labels.append(s)
        for m in _SEASON_MONTHS[s]:
            all_labels.append(f'{s}{m}')
    all_labels.append('是歲')
    all_labels.append('是年')
    all_labels.sort(key=len, reverse=True)
    return all_labels


def _process_year_content(content, all_labels, pattern):
    """處理一年內的內容，按季節分段並以 **標籤** 標記。"""
    matches = list(pattern.finditer(content))
    if not matches:
        return content

    # 按匹配位置分割成段
    segments = []
    for j, m in enumerate(matches):
        label = m.group(1)
        start = m.start()
        end = matches[j + 1].start() if j < len(matches) - 1 else len(content)

        if j == 0 and start > 0:
            segments.append(('', content[0:start].strip()))

        segments.append((label, content[start:end].strip()))

    # 合併 是歲/是年 到前段
    filtered = []
    for label, text in segments:
        cleaned = text.strip()
        if not cleaned:
            continue
        if label in ('是歲', '是年'):
            if filtered:
                pl, pt = filtered[-1]
                filtered[-1] = (pl, pt + '\n\n' + cleaned)
            else:
                filtered.append(('', cleaned))
        else:
            filtered.append((label, cleaned))

    if not filtered:
        return content

    # 若僅有是歲/是年且無季節標籤，返回原內容
    has_season = any(l not in ('', ) for l, _ in filtered)
    if not has_season and len(filtered) <= 1:
        return content

    # 輸出格式：**季節**內容
    output = []
    for label, text in filtered:
        if not label:
            output.append(text)
        else:
            cleaned = text
            for l in all_labels:
                if cleaned.startswith(l):
                    cleaned = cleaned[len(l):].lstrip('，、 ')
                    break
            output.append(f'**{label}**{cleaned}')

    return '\n\n'.join(output)


def _build_full_pattern():
    """構建用於全文替換的正則表達式（匹配年份+年齡，替換為###標題）。"""
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_ = r'[' + AGE_SUFFIXES + r']?'
    as_required = AGE_SUFFIX_REQUIRED  # 後綴必備（無稱謂直接年齡格式）

    ap = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)
    ar = '|'.join(REIGNS)
    person = '(?:' + '|'.join(PERSON_PREFIXES) + r')'
    pp = r'(?:' + ap + r')?(?:' + ar + r')?'

    # 出生條目：X年干支...先生生/公生/府君生
    # 中間文字不跨句號，避免誤把「爲公生朝」等生日慶祝當成出生，並防止吞噬其後的真實年份條目
    birth = pp + y + r'年(?:' + sb + r')?' + r'[^。\n]*?' + person + r'生(?:於)?' + r'[，。、]?'

    # 年份條目（有干支）
    # 匹配：可能前綴 + N年干支 + [最多120字，不含換行與句號] + 先生[年]N嵗
    # 中間文字限制不跨句號，防止一個條目吞噬其後的真實年份（如「道光元年辛巳三十一歲。府君…二年壬午三十二歲」）
    entry_sb = (
        pp + y + r'年' + sb
        + r'[^。\n]{0,120}?'             # 中間最多120字，不跨句號（原為60字）
        + person + r'(?:年)?\s*' + an + as_ # 先生[年]N嵗
        + r'[，。、]?'                    # 消耗年齡後綴後的標點
    )

    # 年份條目（無干支，但有年號前綴，如「順治元年，先生二十六歲」）
    entry_no_sb = (
        r'(?:' + ap + r')?(?:' + ar + r')'  # 年號前綴是必需的
        + y + r'年'
        + r'(?!' + sb + r')'        # 後面不是干支
        + r'[^。\n]*?'
        + person + r'(?:年)?\s*' + an + as_
        + r'[，。、]?'                    # 消耗年齡後綴後的標點
    )

    # 出生條目（無直接年齡）：干支，年號年。公...生於
    birth_direct = (
        r'(?:^|(?<=[。！？；\n]))\s*'    # 行首或句末
        + sb + r'[，,]\s*'               # 干支+逗號
        + r'(?:' + ap + r')?(?:' + ar + r')?' + y + r'年'  # 前綴+年號+年
        + r'[^。]{0,100}?。\s*公[^。]{0,200}?' + r'生(?:於)?'
        + r'[，。、]?'                    # 消耗生於後的標點
    )

    # 直接干支+公N嵗（無年號前綴）
    # 匹配：行首/句末的干支 + 必需標點 + 内容 + 稱謂+年齡
    # 標點為必需，避免把「乙丑春，與…先生一」中的「乙丑+季節」誤判為年份條目
    entry_sb_direct = (
        r'(?:^|(?<=[。！？；\n]))\s*'   # 行首或句末
        + r'(?<!年)'                     # 干支前不能有「年」
        + sb                             # 干支
        + r'[，,、。]\s*'               # 必需標點（逗號/句號）
        + r'[^。\n]{0,30}?'              # 中間内容（最多30字，不跨句號）
        + person + r'(?:年)?\s*' + an + as_  # 稱謂+年齡
        + r'[，。、]?'                    # 消耗年齡後綴後的標點
    )

    # 出生條目（直接生於，無先生/公前綴，澄懷主人/自定年譜風格）
    # 匹配：康熙十一年壬子，是年...生於京師。 ／ 嘉慶十一年丙寅十月一日戌時。兆鏞生於...
    # (?<!先) 防止把「先生於」中的「生於」誤判為出生（先生於≠生於）
    # 第二分支容許跨一個句號（「…戌時。{人名}生於」），解決自定年譜「{年}干支{月日時}。{名}生於」出生條目
    birth_no_person = (
        r'(?:' + ap + r')?(?:' + ar + r')?'  # 前綴（含年號）
        + y + r'年(?:' + sb + r')?'           # N年 + 可選干支
        + r'(?:'                                # 兩分支：
        + r'[^。\n]{0,120}?'                    #  ① 直接生於（不跨句號，原為60）
        + r'|[^。\n]{0,60}?。[^。\n]{0,60}?'     #  ② 跨一句號（…戌時。兆鏞生於）
        + r')'
        + r'(?<!先)生於'                        # 生於
    )

    # 年份條目（有干支，無先生/公前綴，澄懷主人/殷譜經風格）
    # 匹配：十二年癸丑二歲 ／ 雍正元年癸卯五十二歲 ／ 光緖元年乙亥，年七十歳
    # 也支援年與干支間有逗號：十年，壬子六十一歲 ／ 五年。丙寅六十一歲
    # 年齡後綴必備 + 可選「年」前綴，避免把「嘉慶十一年丙寅十月」中的「十」誤判為年齡
    entry_sb_no_person = (
        r'(?:' + ap + r')?(?:' + ar + r')?'  # 可選前綴（皇帝廟號+年號）
        + y + r'年[，,、。]?' + sb              # N年 + 可選標點 + 干支
        + r'[，,、。]?\s*'                      # 可選標點
        + r'(?:年)?'                            # 可選「年」前綴（光緖元年乙亥，年七十歳）
        + an + as_required                      # 年齡數字 + 嵗/歲（後綴必備）
        + r'[，。、]?'                           # 消耗年齡後綴後的標點
    )

    return re.compile(
        r'(?:' + birth + r'|' + entry_sb + r'|' + entry_no_sb
        + r'|' + birth_direct + r'|' + entry_sb_direct
        + r'|' + birth_no_person + r'|' + entry_sb_no_person + r')'
    )


def annotate_ad_years(text):
    """在 ### 標題的干支後標註公元年：嘉慶十一年丙寅 → 嘉慶十一年丙寅（1806年）。

    對所有含年號+年序的標題行計算公元年並插入「（YYYY年）」。
    年號不在 REIGN_START_YEARS 表、或無年序的標題（如純干支「丙申，公四十一嵗」）保持原樣。
    """
    y = _build_year_pattern()
    # 標題開頭：(### ) + [廟號前綴?] + [年號?] + N年 + [干支?]
    head_pat = re.compile(
        r'^(?:' + '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES) + r')?'
        + r'(?:' + '|'.join(re.escape(r) for r in REIGNS) + r')?'
    )
    yr_pat = re.compile(r'(' + y + r'年)(?:' + STEM_BRANCH + r')?')

    lines = []
    for line in text.split('\n'):
        if line.startswith('### '):
            head = line[4:]
            hm = head_pat.match(head)
            reign = None
            rest = head
            if hm:
                rest = head[hm.end():]
                # 從標題開頭往後找年號（優先完整匹配，含廟號前綴）
                for r in REIGNS:
                    if head.startswith(r):
                        reign = r
                        rest = head[len(r):]
                        break
                else:
                    for p, r in EMPEROR_PREFIXES:
                        if p and head.startswith(p) and head[len(p):].startswith(r):
                            reign = r
                            rest = head[len(p) + len(r):]
                            break
            ym = yr_pat.match(rest)
            if reign and ym:
                ad = _compute_ad_year(reign, ym.group(1)[:-1])  # 去掉「年」字
                if ad:
                    insert_at = 4 + len(head) - len(rest) + len(ym.group(0))
                    line = line[:insert_at] + f'（{ad}年）' + line[insert_at:]
        lines.append(line)
    return '\n'.join(lines)


def process_nianpu(text):
    """按年份切分年譜文本。

    使用正則表達式全文查找年份+年齡組合，替換為 ### 標題行。
    標題中的〔〕註文會自動清理。
    """
    # 年號字形正規化
    text = _normalize_reign_variants(text)
    # OCR 錯誤修正
    text = _apply_ocr_fixes(text)
    text = _merge_multi_line_years(text)
    reign_state = [None]

    def insert(m):
        raw = m.group(0).strip()
        if not raw:
            return ''

        # 出生條目：在第一個句號處截斷（僅保留干支+年號+年）
        # 「先生於」中的「生於」不是出生標記（(?<!先)排除）
        is_birth = bool(re.search(r'(?<!先)生於', raw)) or '公生' in raw
        if is_birth and '。' in raw:
            raw = raw.split('。')[0]

        # 清理標題（移除〔〕註文）
        heading = _make_heading(raw)

        # 出生條目：移除結尾的「先生生(於)」「公生(於)」等，保持標題乾淨
        if is_birth:
            heading = re.sub(r'(?:先生|公)生(?:於)?$', '', heading)
            heading = heading.rstrip('，, ')

        # 如果清理後標題過長（>40字，出生條目 >30字），跳過
        if (not is_birth and len(heading) > 40) or (is_birth and len(heading) > 30):
            return raw
        if '。' in heading and not is_birth:
            return raw

        r, _ = extract_reign(heading)
        if r and r not in ('', None):
            reign_state[0] = r
        elif reign_state[0] and not any(
            heading.startswith(rr) for rr in REIGNS
        ):
            heading = reign_state[0] + heading

        return '\n### ' + heading + '\n'

    pat = _build_full_pattern()
    result = pat.sub(insert, text)
    result = _merge_broken_lines(result)
    result = _split_embedded_years(result)
    result = split_by_month(result)
    # 在標題上標註公元年：嘉慶十一年丙寅 → 嘉慶十一年丙寅（1806年）
    result = annotate_ad_years(result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip() + '\n'


def verify_output(original_text, result):
    """檢查年譜整理結果，報告遺漏和異常。

    比對原始文本中所有「N年干支 + 先生N歲」組合與輸出 ### 標題，
    列出遺漏的年份條目及異常情況。
    """
    # 年號字形先正規化（光緖→光緒），避免比對時因字形變體誤報遺漏
    original_text = _normalize_reign_variants(original_text)
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_ = r'[' + AGE_SUFFIXES + r']?'

    ap = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)
    ar = '|'.join(REIGNS)
    person = '(?:' + '|'.join(PERSON_PREFIXES) + r')'

    def head_starts_with_reign(h):
        for r_ in REIGNS:
            if h.startswith(r_):
                return True
        return False

    # === 1. 在原始文本中找出所有年份+年齡（含無稱謂前綴格式） ===
    raw_entry_pat = re.compile(
        r'((?:' + ap + r')?(?:' + ar + r')?' + y + r'年[，,、。]?(?:' + sb + r')?)'
        + r'[^\n]{0,200}?'
        + r'(?:' + person + r'(?:年)?\s*)?' + an + as_
    )
    raw_matches = {}
    for m in raw_entry_pat.finditer(original_text):
        heading_raw = _make_heading(m.group(0))
        if len(heading_raw) > 40 or '。' in heading_raw:
            continue
        # 提取年齡數字（有或無稱謂前綴）
        age_m = re.search(r'(?:' + person + r'(?:年)?\s*)?(' + an + r')[' + AGE_SUFFIXES + r']', m.group(0))
        age = age_m.group(1) if age_m else '?'
        # 提取年份部分
        marker = m.group(1)
        raw_matches[marker] = {'age': age, 'heading': heading_raw}

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
        for oh in output_headings:
            # 如果輸出的標題包含原始年份標記（去掉前綴），則認為已處理
            if marker in oh or oh in marker:
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
        elif not head_starts_with_reign(h) and prev_reign:
            reign_issues.append(f"缺年號：{h[:20]}...，應爲{prev_reign}")

    # === 6. 輸出報告 ===
    report = []
    report.append("=" * 60)
    report.append("年譜整理檢查報告")
    report.append("=" * 60)

    # 覆蓋率
    total_raw = len(raw_matches)
    total_out = len(output_headings)
    coverage = round(total_out / total_raw * 100, 1) if total_raw > 0 else 0
    report.append(f"\n原始年份+年齡組合：{total_raw} 個")
    report.append(f"輸出 ### 標題：{total_out} 個")
    report.append(f"覆蓋率：{coverage}%")
    report.append(f"遺漏：{len(missed)} 個")

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


# ======== 命令列 ========
def main():
    # Windows 控制台編碼修正：統一以 UTF-8 輸出，避免中文亂碼/空輸出
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)

    # --status 查看學習狀態
    if sys.argv[1] == '--status':
        try: print(print_learnings_summary())
        except UnicodeEncodeError: pass
        return

    # --prune 清理無效學習
    if sys.argv[1] == '--prune':
        removed = prune_invalidated_learnings()
        total = sum(len(v) for v in removed.values())
        if total > 0:
            print(f"▸ 已清理 {total} 項無效學習：")
            if removed['reigns']:
                print(f"  年號：{'、'.join(removed['reigns'])}")
            if removed['prefixes']:
                print(f"  前綴：{'、'.join(removed['prefixes'])}")
            if removed['suffixes']:
                print(f"  字形：{'、'.join(removed['suffixes'])}")
        else:
            print("▸ 無需清理，所有學習均有效。")
        print()
        try: print(print_learnings_summary())
        except UnicodeEncodeError: pass
        return

    # 載入歷史學習
    learn_changes = apply_learnings()
    if learn_changes:
        print("▸ 自我進化：應用歷史學習成果")
        for c in learn_changes:
            print(f"  {c}")

    inp = Path(sys.argv[1])
    if not inp.exists():
        print(f"錯誤：找不到檔案 {inp}"); sys.exit(1)
    out = Path(sys.argv[2]) if len(sys.argv) >= 3 else inp.with_stem(
        inp.stem.replace('_完整','').replace('_全本','').replace('完整','').replace('全本','') + '_已整理'
    )
    print(f"讀取：{inp}")
    original = inp.read_text(encoding='utf-8')
    result = process_nianpu(original)
    out.write_text(result, encoding='utf-8')
    print(f"寫入：{out}")
    hs = [l for l in result.split('\n') if l.startswith('### ')]
    print(f"\n共找到 {len(hs)} 個年份標題：")
    for h in hs[:50]:
        try: print(f"  {h}")
        except UnicodeEncodeError: print(f"  [包含罕用字: {len(h)} chars]")
    if len(hs) > 50: print(f"  ... 尚有 {len(hs)-50} 個")
    print()
    report_lines = verify_output(original, result).split('\n')
    for line in report_lines:
        try: print(line)
        except UnicodeEncodeError: print(f"  [包含罕用字]")

    # 自我進化：分析本次處理，學習新知
    source_name = inp.name
    self_learn(original, result, source_file=source_name, report_lines=report_lines)
    print()
    try: print(print_learnings_summary())
    except UnicodeEncodeError: pass

if __name__ == '__main__':
    main()
