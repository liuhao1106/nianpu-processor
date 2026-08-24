# -*- coding: utf-8 -*-
"""自我進化系統：新年號／前綴／字形發現、修正記錄、學習管理。"""



import re
import json

from .constants import (
    REIGNS, EMPEROR_PREFIXES, PERSON_PREFIXES, AGE_SUFFIXES, AGE_DIGITS,
    STEM_BRANCH, LEARNINGS_FILE,
)
from .base import _build_year_pattern, _ganzhi_index_of_pair


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
        'corrections': [],            # [{type: 'reign'|'prefix'|'suffix'|'year_seq'|'ocr_ganzhi'|'manual', wrong: '', correct: '',
                                      #   source: 檔名, date: ISO}]
        'ocr_candidates': {},         # {pair_key: {pair: ['乙亥','己亥'], context: '順治', count: N, sources: [...]}}
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
            # 質檢閘門（v3.38）：可應用條目（年號/前綴）須有 status 欄位；
            # 舊數據一律遷移為 pending——未經回歸驗證的條目不再自動應用
            for section in ['discovered_reigns', 'discovered_prefixes']:
                for k, v in data.get(section, {}).items():
                    if isinstance(v, dict) and 'status' not in v:
                        v['status'] = 'pending'
            _LEARNINGS_CACHE = data
            return data
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    _LEARNINGS_CACHE = dict(template)
    return _LEARNINGS_CACHE


def _save_learnings(data):
    """保存學習檔案（覆寫前自動備份至 learnings.json.bak，--revert 可回滾）。"""
    global _LEARNINGS_CACHE
    _LEARNINGS_CACHE = data
    p = _learnings_path()
    if p.exists():
        bak = p.parent / (p.name + '.bak')
        try:
            bak.write_text(p.read_text(encoding='utf-8'), encoding='utf-8')
        except OSError:
            pass  # 備份失敗不阻斷保存
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
                'invalidated': False,
                'status': 'pending'
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
                'invalidated': False,
                'status': 'pending'
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
    """記錄一個修正（用於從修正中學習）。

    type：
      'reign'/'prefix'/'suffix' — 既有：標記對應發現為無效
      'ocr_ganzhi' — 干支形近字修正（如 順治乙亥→己亥）：累積候選規則
      'year_seq'/'manual' — 年序誤標或一般人工修正，僅記帳（校勘，非 OCR）
    """
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
    elif corr_type == 'ocr_ganzhi':
        _accumulate_ocr_candidate(learnings, wrong_value, correct_value, source)


def _accumulate_ocr_candidate(learnings, wrong, correct, source):
    """干支形近字修正 → 累積 OCR 候選規則（上下文約束 + 多來源置信度）。

    只收「干支雙字中恰有一個字不同」的替換（己/乙、内/丙 形近字）；年序推論
    錯誤（四年→二十四年）屬校勘非 OCR，不生成規則。規則附上下文約束（如所在
    年號），避免打壞正確文本；不自動晉升 _OCR_FIXES——由 --status 列出高置信
    候選，人工複核後手動升級。
    """
    wg = re.search(STEM_BRANCH, wrong)
    cg = re.search(STEM_BRANCH, correct)
    if not (wg and cg):
        return
    w, c = wg.group(0), cg.group(0)
    if len(w) != 2 or len(c) != 2 or w == c:
        return
    if (w[0] != c[0]) == (w[1] != c[1]):
        return  # 兩字皆變（非形近）或皆不變
    if _ganzhi_index_of_pair(w) is None or _ganzhi_index_of_pair(c) is None:
        return
    ctx = ''
    m = re.search(r'([一-鿿]{0,4})' + re.escape(w), wrong)
    if m:
        ctx = m.group(1)
    key = f'{w}→{c}'
    cand = learnings.setdefault('ocr_candidates', {}).setdefault(key, {
        'pair': [w, c], 'context': ctx, 'count': 0, 'sources': []})
    cand['count'] += 1
    if ctx and not cand['context']:
        cand['context'] = ctx
    if source and source not in cand['sources']:
        cand['sources'].append(source)
    cand['date'] = __import__('datetime').datetime.now().isoformat()[:10]


def record_manual_correction(wrong, correct, source=''):
    """手動修正錄入：--record「錯」「對」[來源]。

    干支形近字修正（單字替換，如 順治乙亥→己亥）→ ocr_ganzhi 候選規則；
    其餘（年序/正文）→ 一般修正記帳（校勘，非 OCR）。
    """
    learnings = _load_learnings()
    wg = re.search(STEM_BRANCH, wrong)
    cg = re.search(STEM_BRANCH, correct)
    is_gz = False
    if wg and cg:
        w, c = wg.group(0), cg.group(0)
        is_gz = (w != c and len(w) == 2 and len(c) == 2
                 and (w[0] != c[0]) != (w[1] != c[1])
                 and _ganzhi_index_of_pair(w) is not None
                 and _ganzhi_index_of_pair(c) is not None)
    _record_correction(learnings, 'ocr_ganzhi' if is_gz else 'manual',
                       wrong, correct, source)
    _save_learnings(learnings)
    return learnings, is_gz


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
    """從學習檔案加載已知知識，動態擴展配置（僅應用已通過回歸驗證的條目）。

    質檢閘門（P0，v3.38）：只有 status='verified' 的年號/前綴才會被套用；
    pending 條目須先跑 python tools/regression.py --verify-learnings
    （逐條臨時套用→跑回歸→PASS 轉正）。返回變更清單（含 pending 提示行，
    供 CLI 在 apply 當下顯示 diff）。
    """
    learnings = _load_learnings()
    changes = []
    pending_hint = 0

    # 動態擴展 REIGNS（已驗證＋置信度/次數閾值＋未無效化）
    new_ri = []
    for r, info in sorted(learnings['discovered_reigns'].items()):
        if r in REIGNS or info.get('invalidated', False):
            continue
        meets = (info.get('count', 0) >= 2
                 and info.get('confidence', 0) >= _DEFAULT_CONFIDENCE_THRESHOLD)
        if info.get('status', 'pending') != 'verified':
            if meets:
                pending_hint += 1
            continue
        if meets:
            new_ri.append(r)
    if new_ri:
        REIGNS.extend(new_ri)
        changes.append(f"年號 +{len(new_ri)}：{'、'.join(new_ri)}（已驗證）")

    # 動態擴展 EMPEROR_PREFIXES（已驗證＋未無效化）
    existing_prefixes = {p for p, _ in EMPEROR_PREFIXES}
    new_ep = []
    for p, info in learnings['discovered_prefixes'].items():
        if p in existing_prefixes or info.get('invalidated', False):
            continue
        if info.get('status', 'pending') != 'verified':
            pending_hint += 1
            continue
        new_ep.append((p, info['reign']))
    if new_ep:
        for prefix, reign in new_ep:
            EMPEROR_PREFIXES.insert(0, (prefix, reign))
        changes.append(f"前綴 +{len(new_ep)}：{'、'.join(p for p, _ in new_ep)}（已驗證）")

    if pending_hint:
        changes.append(
            f"⏳ {pending_hint} 條待驗證學習未應用"
            f"（驗證：python tools/regression.py --verify-learnings）")

    return changes


def pending_learnings():
    """待驗證（pending）且未被無效化的可應用條目。

    回傳 {'reigns': {年號: info}, 'prefixes': {前綴: info}}，
    供質檢閘門（tools/regression.py --verify-learnings）逐條驗證。
    """
    learnings = _load_learnings()
    reigns = {r: info for r, info in learnings.get('discovered_reigns', {}).items()
              if not info.get('invalidated', False)
              and info.get('status', 'pending') == 'pending'}
    prefixes = {p: info for p, info in learnings.get('discovered_prefixes', {}).items()
                if not info.get('invalidated', False)
                and info.get('status', 'pending') == 'pending'}
    return {'reigns': reigns, 'prefixes': prefixes}


def verified_learnings():
    """已驗證（status='verified'）且未被無效化的年號/前綴（供 --run 帳本報告）。

    回傳 {'reigns': [年號...], 'prefixes': {前綴: reign}}。
    與 apply_learnings 的實際套用集略有出入——套用另受「已在基座 REIGNS/
    EMPEROR_PREFIXES」「置信度/次數閾值」約束；本函式只反映「已轉正」的全量。
    """
    learnings = _load_learnings()
    reigns = sorted(
        r for r, info in learnings.get('discovered_reigns', {}).items()
        if not info.get('invalidated', False)
        and info.get('status') == 'verified')
    prefixes = {
        p: info['reign']
        for p, info in learnings.get('discovered_prefixes', {}).items()
        if not info.get('invalidated', False)
        and info.get('status') == 'verified'}
    return {'reigns': reigns, 'prefixes': prefixes}


def mark_learnings_verified(reign_names, prefix_names):
    """質檢閘門回報：把通過回歸驗證的條目轉正（status='verified'）並保存。

    保存前自動備份（learnings.json.bak），--revert 可回滾本次轉正。
    回傳轉正條目數。
    """
    import datetime
    learnings = _load_learnings()
    today = datetime.date.today().isoformat()
    n = 0
    for r in reign_names:
        info = learnings['discovered_reigns'].get(r)
        if info is not None:
            info['status'] = 'verified'
            info['verified_date'] = today
            n += 1
    for p in prefix_names:
        info = learnings['discovered_prefixes'].get(p)
        if info is not None:
            info['status'] = 'verified'
            info['verified_date'] = today
            n += 1
    if n:
        _save_learnings(learnings)
    return n


def revert_learnings():
    """回滾 learnings.json 至最近一次保存前的狀態（.bak 單槽備份）。

    每次 _save_learnings 覆寫前都會備份；--revert 回滾最近一次寫入
    （驗證轉正、修正錄入或處理統計更新皆可回滾）。回傳 (ok, message)。
    """
    global _LEARNINGS_CACHE
    p = _learnings_path()
    bak = p.parent / (p.name + '.bak')
    if not bak.exists():
        return False, '無備份可回滾（learnings.json.bak 不存在）'
    if not p.exists():
        return False, 'learnings.json 不存在（無需回滾）'
    p.write_text(bak.read_text(encoding='utf-8'), encoding='utf-8')
    _LEARNINGS_CACHE = None
    return True, '已回滾 learnings.json 至最近一次保存前的狀態'


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
            status = '已驗證' if info.get('status') == 'verified' else '待驗證'
            lines.append(f"  「{r}」發現 {info['count']} 次 [置信度 {conf:.0%} {bar}]（{status}）")

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
            status = '已驗證' if info.get('status') == 'verified' else '待驗證'
            lines.append(f"  「{p}」→ {info['reign']}（{status}）")
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

    # === 干支 OCR 候選規則 ===
    ocr = learnings.get('ocr_candidates', {})
    ready = {k: v for k, v in ocr.items() if v.get('count', 0) >= 2}
    if ready:
        lines.append("\n▸ 干支 OCR 候選（出現 ≥2 次，可考慮手動升級 _OCR_FIXES）：")
        for k, v in ready.items():
            lines.append(f"  {v['pair'][0]}→{v['pair'][1]}"
                         f"（上下文「{v.get('context', '')}」，"
                         f"{len(v.get('sources', []))} 來源，{v['count']} 次）")

    # === 處理統計 ===
    if files:
        total = len(files)
        avg_cov = sum(f['coverage'] for f in files) / total if total > 0 else 0
        total_years = sum(f['year_count'] for f in files)
        lines.append(f"\n▸ 處理統計：{total} 個年譜，{total_years} 個年份，平均覆蓋率 {avg_cov:.1f}%")
        lines.append(f"  最近處理：{files[-1]['file']}（{files[-1]['year_count']} 年，覆蓋率 {files[-1]['coverage']}%）")

    n_pending = sum(1 for v in d_r.values()
                    if not v.get('invalidated') and v.get('status', 'pending') == 'pending') \
        + sum(1 for v in d_p.values()
              if not v.get('invalidated') and v.get('status', 'pending') == 'pending')
    if n_pending:
        lines.append(f"\n▸ 質檢閘門：{n_pending} 條待驗證（未被應用）——"
                     f"python tools/regression.py --verify-learnings")

    lines.append("=" * 60)
    return '\n'.join(lines)
