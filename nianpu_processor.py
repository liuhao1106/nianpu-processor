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

# 語義槽位模型（--slots 配置）：slot_model.slots_to_fmt 把 LLM 推得的槽位
# 映射為本工具的格式族 dict，使新格式不需改正則、只需填槽位表
try:
    from slot_model import slots_to_fmt
except ImportError:
    slots_to_fmt = None


# ======== 配置區 ========
# 年號：包含宋代、元代、明代（含南明）、清代
# 注意：清與南明年號在前（沿用既有行為），其後為明/元/宋；無重疊前綴，順序不影響匹配
REIGNS = [
    # 明代
    '洪武', '建文', '永樂', '洪熙', '宣德', '正統', '景泰', '天順', '成化',
    '弘治', '正德', '嘉靖', '隆慶', '萬厯', '萬曆', '萬厤', '泰昌', '天啟', '崇禎',
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
    '順治', '康熙', '雍正', '乾隆', '嘉慶', '道光', '咸豐', '同治', '光緖', '光緒', '光绪',
    # 清代簡體（現代學者年譜／簡體書刊）
    '顺治', '乾隆', '嘉庆', '咸丰',
    # 清末宣統、民國（近現代年譜；含簡/繁體）
    '宣統', '宣统', '民國', '民国',
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
    # 宋代皇帝前綴（朱熹年譜：宋高宗建炎、孝宗隆興、光宗紹熙、寧宗慶元）
    ('宋高宗','建炎'),('孝宗','隆興'),('光宗','紹熙'),('寧宗','慶元'),
]

PERSON_PREFIXES = ['先生','公','府君']
AGE_SUFFIXES = '嵗歲歳𡻕岁'   # 含簡體「岁」（近現代/民國年譜用）
AGE_SUFFIX_REQUIRED = '[' + AGE_SUFFIXES + ']'   # 年齡後綴必備（無稱謂格式用，避免誤配「六月」等月份/日期字）
AGE_DIGITS = r'[十有和一二三四五六七八九十百零〇廿卅\d]+'   # 含 廿/卅（廿一歲=21歲、卅二歲=32歲）

# 各年號元年對應的公元年份（含異體字）。用於在標題上標註公元年，如 嘉慶十一年 → 1806年
REIGN_START_YEARS = {
    # 明代
    '洪武': 1368, '建文': 1399, '永樂': 1403, '洪熙': 1425, '宣德': 1426,
    '正統': 1436, '景泰': 1450, '天順': 1457, '成化': 1465, '弘治': 1488,
    '正德': 1506, '嘉靖': 1522, '隆慶': 1567,
    '萬厯': 1573, '萬曆': 1573, '萬厤': 1573,
    '泰昌': 1620, '天啟': 1621, '崇禎': 1628,
    # 南明
    '隆武': 1645, '永厯': 1647, '永曆': 1647,
    '宏光': 1645, '弘光': 1645, '紹武': 1646,
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
    '道光': 1821, '咸豐': 1851, '同治': 1862, '光緖': 1875, '光緒': 1875, '光绪': 1875,
    # 清代簡體（現代學者年譜／簡體書刊）
    '顺治': 1644, '乾隆': 1736, '嘉庆': 1796, '咸丰': 1851,
    # 清末宣統、民國（近現代年譜；含簡/繁體）
    '宣統': 1909, '宣统': 1909, '民國': 1912, '民国': 1912,
}

# 中文數字→整數
_CN_NUM = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '百': 100,
}


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

# 天干地支（精確匹配，避免誤配「正月」「八月」）
# 包含常見OCR變體：已（U+5DF2）代替己（U+5DF1）和巳（U+5DF3）、戍（U+620D）代替戌（U+620C）、
# 戊（U+620A，本為天干，古籍偶誤刻為地支「戌」）亦收作戌之變體
_TG = '甲乙丙丁戊己已庚辛壬癸巳'
_DZ = '子丑寅卯辰巳已午未申酉戌戍戊亥'
STEM_BRANCH = r'[' + _TG + r'][' + _DZ + r']'

SEASON_MARKERS = [
    '春正月','春二月','春三月','夏四月','夏五月','夏六月',
    '秋七月','秋八月','秋九月','冬十月','冬十一月','冬十二月',
    '是年','先是',
]
# 季節複合詞排除：裸季節字後緊跟這些字時不切分（秋闈=鄉試、冬至=節氣、春秋=經書、春仲=仲春、春日/春闈…）
_SEASON_EXCLUDE_CONTINUATION = {
    '春': '秋日仲闈試',
    '夏': '至',
    '秋': '闈日試',
    '冬': '至日',
}
# 月份/季節分段用
_SEASONS = ['春', '夏', '秋', '冬']
_SEASON_MONTHS = {
    '春': ['正月', '二月', '三月'],
    '夏': ['四月', '五月', '六月'],
    '秋': ['七月', '八月', '九月'],
    '冬': ['十月', '十一月', '十二月'],
}

EVENT_MARKERS = ['書至','將南歸']  # 非季節的事件標記，用於段落合併邊界

# ======== 干支→60週期索引（三錨點一致性檢查用） ========
# 甲子=0、乙丑=1、…、癸亥=59。已(U+5DF2)同時是 己/巳 的OCR變體，一律視為索引5（己、巳皆為5）
_STEMS_CANON = '甲乙丙丁戊己庚辛壬癸'
_BRANCHES_CANON = '子丑寅卯辰巳午未申酉戌亥'
_STEM_IDX = {'甲':0,'乙':1,'丙':2,'丁':3,'戊':4,'己':5,'已':5,'庚':6,'辛':7,'壬':8,'癸':9}
_BRANCH_IDX = {'子':0,'丑':1,'寅':2,'卯':3,'辰':4,'巳':5,'已':5,'午':6,'未':7,'申':8,'酉':9,'戌':10,'戍':10,'戊':10,'亥':11}
_GANZHI_INDEX = {}   # '甲子'→0 … '癸亥'→59
for _i in range(60):
    _GANZHI_INDEX[_STEMS_CANON[_i % 10] + _BRANCHES_CANON[_i % 12]] = _i


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
    # 十不年 → 十八年（OCR 誤刻：不/八形近，唐一庵先生年譜「嘉靖十不年己亥四十三歲」）
    (r'十不年', '十八年'),
]

def _apply_ocr_fixes(text):
    """對文本應用常見 OCR 錯誤修正。"""
    for pattern, replacement in _OCR_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


# ======== 年號字形正規化 ========
# 異體字依據《規範字與繁异体字不對等用法表》（文津學志，鮑國強）取「辨識相關」子集：
#   0095 历：歷(异:歴厯)／曆(异:厤) → 萬曆/永曆 的 OCR 異體 厤厯歴暦 一律歸一為 曆
#   0023 干：干支用「干」（規範），不處理
#   0436 岁：歲(异:嵗) 已由 AGE_SUFFIXES 涵蓋
#   其餘（煕/熙、啓/啟、佑/祐）為史籍/OCR 常見異體，屬同類問題，一併歸一
# 注意：此處只正規化「辨識依賴」的年號字形；正文一律保留原樣，不做出版性繁简轉換
_REIGN_NORMALIZATIONS = {
    # 弘治系（弘/宏）：宏治為 OCR/刻工常見誤刻（唐一庵先生年譜 全譜「宏治」）
    '宏治': '弘治',
    # 光緒系（緒/緖）
    '光緖': '光緒',
    # 萬曆系（曆/厤/厯/歴/暦）
    '萬厤': '萬曆',
    '萬厯': '萬曆',
    '萬歴': '萬曆',
    '萬暦': '萬曆',
    # 永曆系（同曆族）
    '永厤': '永曆',
    '永厯': '永曆',
    '永歴': '永曆',
    # 康熙（熙/煕）
    '康煕': '康熙',
    # 天啟（啟/啓）
    '天啓': '天啟',
    # 嘉祐、元祐（祐/佑）
    '嘉佑': '嘉祐',
    '元佑': '元祐',
}

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
    # 不能以中文數字結尾（「人十」「以五十」「至一八九」等數字碎片；「有」屬「十有一」文言數字構造）
    if candidate[-1] in '一二三四五六七八九十百千零〇廿卅有':
        return False
    # 不能含標點/引號/空白
    if re.search(r'[。，、！？；：〔〕「」『』（）\[\]《》〈〉\s]', candidate):
        return False
    if '"' in candidate or "'" in candidate:
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
        # 出現 <2 次證據不足，不收錄（杜絕「人十」「以五十」等單次碎片進學習庫）
        if count < 2:
            continue
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

    # 4. 統計處理結果（現代學者年譜標題為 ####，一併統計）
    hs = [l for l in result.split('\n') if l.startswith('### ') or l.startswith('#### ')]
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


def _is_season_compound(content, m):
    """裸季節字（春/夏/秋/冬）後緊跟複合詞續字（如 秋闈、冬至、春秋、春仲）時，不當季節分段。"""
    label = m.group(1)
    if label not in _SEASONS:
        return False
    nxt = content[m.end():m.end() + 1]
    return nxt in _SEASON_EXCLUDE_CONTINUATION.get(label, '')


def _process_year_content(content, all_labels, pattern):
    """處理一年內的內容，按季節分段並以 **標籤** 標記。"""
    matches = [m for m in pattern.finditer(content) if not _is_season_compound(content, m)]
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


def classify_format(text):
    """偵測年譜格式族，決定套用哪些年份 pattern 子集，降低誤配率。

    二元特徵：
      person    — 有「先生/公/府君〔年〕N嵗」（方柏堂/張清恪/府君風格）
      no_person — 有「N年干支…N嵗」無稱謂直接年齡（萬清軒/澄懷主人/顧亭林風格）
      ad        — 含「公元N年」（近現代/民國年譜）
    回傳 dict；兩個 count 皆 >0 表示混合格式（套用全部 pattern）。
    """
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_req = AGE_SUFFIX_REQUIRED
    extra_person = detect_person_prefixes(text)
    person = '(?:' + '|'.join(PERSON_PREFIXES + extra_person) + r')'
    reign_alt = '|'.join(REIGNS)
    emp_alt = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)

    # 有稱謂：先生/公/府君/傳主名 [年] N嵗
    person_age = re.compile(person + r'(?:年)?\s*' + an + as_req)
    n_person = len(person_age.findall(text))

    # 無稱謂：N年[標點]干支[標點][年]N嵗（年齡緊接干支，避免誤配「，先生年N嵗」）
    no_person_age = re.compile(
        r'(?:' + emp_alt + r')?(?:' + reign_alt + r')?' + y + r'年[，,、。]?' + sb
        + r'[，,、。]?\s*(?:年)?' + an + as_req
    )
    n_no_person = len(no_person_age.findall(text))

    n_ad = len(re.findall(r'公元[一二三四五六七八九零〇]{3,4}年', text))

    # 無年齡純年份（朱熹年譜風格）：(前綴)?(年號)?N年干支 於行首/句末
    # 干支必備，避免誤配正文年份引用（如「淳熙元年，始拜命」無干支）
    # 注意：此處不加「排除緊接/間隔年齡」的 lookahead —— 顧亭林出生/卒年條目
    # （萬厯四十一年癸丑五月二十八日生一歲／康熙二十一年壬戌正月初九日卒）也是
    # 「N年干支＋日期＋生/卒」的 bare 形態；加了會讓 n_bare 掉到閾值(5)以下，
    # bare 模式被關閉，顧亭林童年條目丟失萬曆年號與公元年（回歸）。年齡竊取
    # 已由 entry_bare 自身的強化 lookahead 解決（見 _build_full_pattern）。
    bare_pat = re.compile(
        r'(?:^|(?<=[。！？；〕\n]))\s*'
        + r'(?:' + emp_alt + r')?(?:' + reign_alt + r')?'
        + y + r'年' + sb
    )
    n_bare = len(bare_pat.findall(text))

    # 現代學者年譜：已有年份標題（年號N年 干支 公元年 年齡），非待切分。
    # 判定：≥2 行能被 try_parse_modern_heading(allow_plain=True) 解析——
    # 含帶 # 前綴標題與無 # 前綴的純文字獨立年份行（四錨點覆蓋整行）。
    # 傳統年譜原始文本無公元年，不會誤觸發；已整理傳統檔的「（1806年）」在括號內，
    # 因「公元年在干支後緊接」的要求而不被視為現代格式。
    n_modern = sum(1 for line in text.split('\n')
                   if try_parse_modern_heading(line, allow_plain=True) is not None)

    return {
        'person': n_person > 0 or bool(extra_person),
        'no_person': n_no_person > 0,
        'ad': n_ad > 0,
        'bare': n_bare >= 5,
        'modern': n_modern >= 2,
        '_person_extra': extra_person,
        '_counts': (n_person, n_no_person, n_ad, n_bare, n_modern),
    }


def _build_full_pattern(fmt=None):
    """構建用於全文替換的正則表達式（匹配年份+年齡，替換為###標題）。

    fmt: classify_format() 的結果。為 None 時套用全部 8 種 pattern（相容舊行為）；
    指定後只套用該格式族相關的子集（如 純無稱謂年譜 排除 有稱謂 pattern，
    避免把正文「崇禎九年，巡按御史王公一…」中的「公一」誤當「公一歲」）。
    若分類產生空集合，退回全部 pattern 以免漏切。
    """
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_ = r'[' + AGE_SUFFIXES + r']?'
    as_required = AGE_SUFFIX_REQUIRED  # 後綴必備（無稱謂直接年齡格式）

    ap = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)
    ar = '|'.join(REIGNS)
    extra_person = (fmt or {}).get('_person_extra') or []
    person = '(?:' + '|'.join(PERSON_PREFIXES + extra_person) + r')'
    pp = r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')?'

    # 出生條目：X年干支...先生生/公生/府君生
    # 中間文字不跨句號，避免誤把「爲公生朝」等生日慶祝當成出生，並防止吞噬其後的真實年份條目
    birth = pp + y + r'年(?:' + sb + r')?' + r'[^。\n]*?' + person + r'生(?:於)?' + r'[，。、]?'

    # 年份條目（有干支）
    # 匹配：可能前綴 + N年干支 + [最多120字，不含換行與句號] + 先生[年]N嵗
    # 中間文字限制不跨句號，防止一個條目吞噬其後的真實年份（如「道光元年辛巳三十一歲。府君…二年壬午三十二歲」）
    # [，,、。]?\s* 容許干支後直接接句號的斷裂格式（如「四十五年丁巳。公八嵗」），與 entry_sb_no_person 一致
    entry_sb = (
        pp + y + r'年' + sb
        + r'[，,、。]?\s*' + r'[^。\n]{0,120}?'  # 中間最多120字，不跨句號（原為60字）
        + person + r'(?:年)?\s*' + an + as_ # 先生[年]N嵗
        + r'[，。、]?'                    # 消耗年齡後綴後的標點
    )

    # 年份條目（無干支，但有年號前綴，如「順治元年，先生二十六歲」）
    entry_no_sb = (
        r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')'  # 年號前綴是必需的
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

    # 公元年格式（近現代/民國年譜）：公元一八七三年，同治十二年，岁次癸酉，一岁。
    # 公元N年（3-4位中文數字）+ 可選年號年（同治十二年/民國元年/宣統三年）+ 可選岁次干支 + N岁（後綴必備）
    # 必須有年齡，避免誤切世系簡述等「公元N年」無年齡的敘述
    ad_years = r'[一二三四五六七八九零〇]{3,4}'
    ad_entry = (
        r'公元' + ad_years + r'年'
        + r'(?:，?' + r'(?:' + ar + r')' + y + r'年)?'   # 可選：年號年
        + r'(?:，?岁次' + sb + r')?'                      # 可選：岁次干支
        + r'，?' + an + as_required                       # 年齡（後綴必備）
        + r'[。，]?'                                       # 消耗結尾標點
    )

    # 無年齡純年份（朱熹年譜風格）：(前綴)?(年號)?N年干支，無年齡
    # 匹配：紹興元年辛亥 ／ 四年甲寅 ／ 孝宗隆興元年癸未 ／ 光宗紹熙元年庚戍
    # 限行首或句末/註文後，且干支必備（區分正文年份引用「淳熙元年，始拜命」）
    # 放在 alternation 末尾：有年齡的條目（entry_sb_no_person 等）先匹配，避免此 pattern 搶走「N年干支」部分
    entry_bare = (
        r'(?:^|(?<=[。！？；〕\n]))\s*'      # 行首或句末/註文後
        + r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')?'  # 可選前綴（皇帝廟號）+年號
        + y + r'年' + sb                         # N年干支（干支必備）
        + r'(?!(?:[，,、。]?\s*)?(?:(?:' + person + r')?(?:年)?\s*)?' + an + r'[' + AGE_SUFFIXES + r'])'  # 排除緊接或間隔標點後接「[稱謂][年]N嵗/歲」的（避免搶走「N年干支，公年N歲」等有稱謂年齡條目）
        + r'[，,、。]?'                          # 消耗干支後標點（「二十六年丙子，七月」）
    )

    # 依格式族選擇 pattern 子集（fmt=None 時全部套用）
    # 出生 pattern（birth/birth_direct/birth_no_person）一律啟用：
    #   1) 兩種格式（先生生 / 公生於 / 生於）的出生條目都會種下年號，若排除則後續條目
    #      失去年號前綴（如羅忠節公「先生生」出生後，各條目丟失嘉慶年號與公元年註記）
    #   2) 出生 pattern 均需「先生生/公生/生於」等特定動詞，誤配風險低
    # 分類只決定「年份條目」pattern（有稱謂 entry_*  vs  無稱謂 entry_sb_no_person  vs  無年齡 entry_bare）
    alts = []
    if fmt is None or fmt.get('ad'):
        alts.append(ad_entry)
    alts.extend([birth, birth_direct, birth_no_person])
    if fmt is None or fmt.get('person'):
        alts.extend([entry_sb, entry_no_sb, entry_sb_direct])
    if fmt is None or fmt.get('no_person'):
        alts.append(entry_sb_no_person)
    if fmt is None or fmt.get('bare'):
        alts.append(entry_bare)   # 放末尾：有年齡條目優先
    if not alts:   # 保險：分類異常導致空集合時退回全部，避免漏切
        alts = [ad_entry, birth, entry_sb, entry_no_sb, birth_direct,
                entry_sb_direct, birth_no_person, entry_sb_no_person, entry_bare]
    return re.compile('(?:' + '|'.join(alts) + ')')


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
    text = _merge_multi_line_years(text, person_extra=person_extra)
    reign_state = [None]

    def insert(m):
        raw = m.group(0).strip()
        if not raw:
            return ''

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
            heading = reign_state[0] + heading

        return '\n### ' + heading + '\n'

    # 格式預分類：只套用與本譜相關的 pattern 子集，降低誤配（L1）
    pat = _build_full_pattern(fmt)
    result = pat.sub(insert, text)
    result = _merge_broken_lines(result)
    result = _split_embedded_years(result, person_extra=person_extra)
    result = split_by_month(result)
    # 在標題上標註公元年：嘉慶十一年丙寅 → 嘉慶十一年丙寅（1806年）
    result = annotate_ad_years(result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip() + '\n', None


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

    # 排除「無干支 且 無年齡錨點」的正文年份引用（如卷末附錄/追述「三十八年，學使…」「同治二年，清釐戸管」）。
    # 真實年份條目必有其一：干支（含出生條目，如 明萬曆三十八年庚戌…）或 年齡+後綴（如 先生N嵗/公二嵗）。
    # 依「結構特徵」而非「卒年之後的位置」判斷，故年譜若把身後事作為正當條目（帶干支/年齡）編入，照常計入。
    prose_year_refs = []
    for marker, info in list(raw_matches.items()):
        if info['age'] == '?' and not re.search(sb, marker):
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


def verify_anchors(result):
    """三錨點一致性檢查：每個標題交叉驗證 年號年→公元、干支→公元、年齡→公元。

    ① 年號年→公元 vs 年齡→公元（出生年+歲-1）不符 → 年號誤配（如順治誤標崇禎）
    ② 干支 vs 年齡→公元 不符 → 干支或年齡有誤
    ③ 干支 vs 年號年→公元 不符（無年齡可用時）
    ④ 相鄰標題年齡序列未逐年遞增 → 可能漏年/錯序

    回傳 (suspects, seq_bad, birth_year, total)。
    """
    headings = [l for l in result.split('\n') if l.startswith('### ') or l.startswith('#### ')]
    parsed = [_parse_heading_anchors(l) for l in headings]
    parsed = [p for p in parsed if p['reign_ad'] is not None or p['age_int'] is not None]

    # 出生年共識：由「年號年→公元 − 年齡 + 1」多數決（1613、1662…）；現代學者年譜
    # 亦可用「顯式公元 − 年齡 + 1」
    birth_cands = [p['reign_ad'] - p['age_int'] + 1
                   for p in parsed
                   if p['reign_ad'] is not None and p['age_int'] is not None]
    birth_cands += [p['ad_anchor_int'] - p['age_int'] + 1
                    for p in parsed
                    if p['ad_anchor_int'] is not None and p['age_int'] is not None]
    birth_year = None
    if birth_cands:
        from collections import Counter
        birth_year = Counter(birth_cands).most_common(1)[0][0]

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


# ======== CBDB 生卒年核驗與年號誤配自動修正 ========
try:
    from cbdb import get_person, extract_person_name as _cbdb_extract_name
except Exception:
    get_person = None
    _cbdb_extract_name = None

# 清系列年號：多個年號涵蓋同一公元年（明清之際）時，優先依清正朔標註
_QING_REIGNS = ['順治', '康熙', '雍正', '乾隆', '嘉慶', '道光', '咸豐', '同治', '光緒', '宣統', '光绪', '宣统']

# 年號終年（含）；未列者以元年+60 計。供年號誤配修正判斷「該年號是否真的涵蓋某公元年」
REIGN_END_YEARS = {
    '建炎': 1130, '紹興': 1162, '隆興': 1164, '乾道': 1173, '淳熙': 1189,
    '紹熙': 1194, '慶元': 1200, '嘉泰': 1204, '開禧': 1207, '嘉定': 1224,
    '寶慶': 1227, '紹定': 1233, '端平': 1236, '嘉熙': 1240, '淳祐': 1252,
    '寶祐': 1258, '開慶': 1259, '景定': 1264, '咸淳': 1274, '德祐': 1276,
    '景炎': 1278, '祥興': 1279,
    '中統': 1264, '至元': 1294, '元貞': 1297, '大德': 1307, '至大': 1311,
    '皇慶': 1313, '延祐': 1320, '至治': 1323, '泰定': 1328, '致和': 1328,
    '天曆': 1330, '至順': 1333, '元統': 1335, '至正': 1368,
    '洪武': 1398, '建文': 1402, '永樂': 1424, '洪熙': 1425, '宣德': 1435,
    '正統': 1449, '景泰': 1456, '天順': 1464, '成化': 1487, '弘治': 1505,
    '正德': 1521, '嘉靖': 1566, '隆慶': 1572, '萬厯': 1620, '萬曆': 1620,
    '泰昌': 1620, '天啟': 1627, '崇禎': 1644,
    '弘光': 1645, '隆武': 1646, '紹武': 1646, '永厤': 1662, '永曆': 1662,
    '順治': 1661, '康熙': 1722, '雍正': 1735, '乾隆': 1795, '嘉慶': 1820,
    '道光': 1850, '咸豐': 1861, '同治': 1874, '光緖': 1908, '光緒': 1908, '光绪': 1908,
    '顺治': 1661, '乾隆': 1795, '嘉庆': 1820, '咸丰': 1861,
    '宣統': 1911, '宣统': 1911,
    '民國': 1949, '民国': 1949,
}


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


# ======== 命令列 ========
def main():
    # Windows 控制台編碼修正：統一以 UTF-8 輸出，避免中文亂碼/空輸出
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    # --- 選項解析（--cbdb <傳主名>、--fix） ---
    argv = sys.argv[1:]
    fix_mode = '--fix' in argv
    argv = [a for a in argv if a != '--fix']
    cbdb_name = None
    cbdb_requested = '--cbdb' in argv
    if cbdb_requested:
        i = argv.index('--cbdb')
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if nxt and not nxt.startswith('-') and not nxt.lower().endswith(('.md', '.txt')):
            cbdb_name = nxt
            del argv[i:i + 2]
        else:
            del argv[i]  # 空 --cbdb：自動從卷首提取傳主名

    # --slots <json>：LLM 依新年譜開頭推得的語義槽位配置，覆蓋格式分類
    slots = None
    if '--slots' in argv:
        i = argv.index('--slots')
        sp = argv[i + 1] if i + 1 < len(argv) else None
        if sp:
            slots = json.loads(Path(sp).read_text(encoding='utf-8'))
            del argv[i:i + 2]
        else:
            del argv[i]

    if not argv:
        print(__doc__); sys.exit(1)

    # --status 查看學習狀態
    if argv[0] == '--status':
        try: print(print_learnings_summary())
        except UnicodeEncodeError: pass
        return

    # --prune 清理無效學習
    if argv[0] == '--prune':
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

    # --check 對既有整理檔跑三錨點一致性檢查（不需重新處理；可加 --cbdb 附核驗/修正建議）
    if argv[0] == '--check':
        if len(argv) < 2:
            print("用法：nianpu_processor.py --check <已整理.md> [--cbdb <傳主名>]"); sys.exit(1)
        cp = Path(argv[1])
        if not cp.exists():
            print(f"錯誤：找不到檔案 {cp}"); sys.exit(1)
        res = cp.read_text(encoding='utf-8')
        try: print(_format_anchor_report(res))
        except UnicodeEncodeError: pass
        if cbdb_requested and get_person:
            name = cbdb_name or (_cbdb_extract_name(res) if _cbdb_extract_name else None)
            if name:
                person = get_person(name)
                if person and person.get('birth'):
                    _cbdb_check(res, person)
                elif person:
                    print(f"▸ CBDB 有「{name}」但無生卒日期，跳過 CBDB 核驗")
                else:
                    print(f"▸ CBDB 查無「{name}」，跳過 CBDB 核驗")
        return

    # 載入歷史學習
    learn_changes = apply_learnings()
    if learn_changes:
        print("▸ 自我進化：應用歷史學習成果")
        for c in learn_changes:
            print(f"  {c}")

    inp = Path(argv[0])
    if not inp.exists():
        print(f"錯誤：找不到檔案 {inp}"); sys.exit(1)
    out = Path(argv[1]) if len(argv) >= 2 else inp.with_stem(
        inp.stem.replace('_完整','').replace('_全本','').replace('完整','').replace('全本','') + '_已整理'
    )
    print(f"讀取：{inp}")
    original = inp.read_text(encoding='utf-8')
    slot_extra = None
    if slots and slots_to_fmt:
        slot_extra = slots_to_fmt(slots).get('_person_extra') or None
    result, modern_report = process_nianpu(original, slots=slots)

    # CBDB 生卒年核驗 + 年號誤配自動修正（現代學者年譜已有標題，不適用 --fix 改寫）
    if cbdb_requested and get_person and modern_report is None:
        name = cbdb_name or (_cbdb_extract_name(original) if _cbdb_extract_name else None)
        if name:
            person = get_person(name)
            if person and person.get('birth'):
                fixes = _cbdb_check(result, person)
                if fix_mode and fixes:
                    result = apply_fixes(result, fixes)
                    print(f"▸ 已自動修正 {len(fixes)} 條年號年序誤標（干支/年齡保留）")
            elif person:
                print(f"▸ CBDB 有「{name}」但無生卒日期，跳過 CBDB 核驗")
            else:
                print(f"▸ CBDB 查無「{name}」，跳過 CBDB 核驗")
        else:
            print("▸ 無法自動判定傳主名，跳過 CBDB 核驗（可用 --cbdb <傳主名> 指定）")

    out.write_text(result, encoding='utf-8')
    print(f"寫入：{out}")

    if modern_report is not None:
        # 現代學者年譜：已有標題，輸出統一格式後的標題 + 完整性檢查 + 三錨點檢查
        hs = [l for l in result.split('\n') if try_parse_modern_heading(l, allow_plain=True) is not None]
        print(f"\n共找到 {len(hs)} 個年份標題（現代學者年譜，已有標題）：")
        for h in hs[:60]:
            try: print(f"  {h}")
            except UnicodeEncodeError: print(f"  [包含罕用字: {len(h)} chars]")
        if len(hs) > 60: print(f"  ... 尚有 {len(hs)-60} 個")
        print()
        for line in modern_report.split('\n'):
            try: print(line)
            except UnicodeEncodeError: print(f"  [包含罕用字]")
        print()
        for line in _format_anchor_report(result).split('\n'):
            try: print(line)
            except UnicodeEncodeError: print(f"  [包含罕用字]")
        source_name = inp.name
        self_learn(original, result, source_file=source_name, report_lines=modern_report.split('\n'))
        print()
        try: print(print_learnings_summary())
        except UnicodeEncodeError: pass
        return

    hs = [l for l in result.split('\n') if l.startswith('### ')]
    print(f"\n共找到 {len(hs)} 個年份標題：")
    for h in hs[:50]:
        try: print(f"  {h}")
        except UnicodeEncodeError: print(f"  [包含罕用字: {len(h)} chars]")
    if len(hs) > 50: print(f"  ... 尚有 {len(hs)-50} 個")
    print()
    report_lines = verify_output(original, result, person_extra=slot_extra).split('\n')
    for line in report_lines:
        try: print(line)
        except UnicodeEncodeError: print(f"  [包含罕用字]")

    # L2：三錨點一致性檢查（年號年/干支/年齡 交叉驗證，輸出可疑標題）
    print()
    for line in _format_anchor_report(result).split('\n'):
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
