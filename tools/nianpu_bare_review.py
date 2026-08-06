#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""歧義 bare pattern 複核工具（風險最小版）— nianpu_bare_review.py
=====================================================================
只讀診斷：不改任何檔案、不呼叫 LLM API。LLM 判定由人工照既有慣例執行
（與 slot_model.arbitrate_prompt 同模式：工具生成 prompt → 人跑 LLM → 取回判定）。

背景：entry_bare / entry_bare_gz / entry_bare_ls / entry_bare_se_yuan
這四條「無年齡」通用 pattern 是歷史上誤切最多的一類：
  - v3.16 桐城吳「公年N歲」被 entry_bare 搶先匹配（年齡竊取）
  - v3.21 鄭端簡「永樂十九年辛丑／二十六年甲申」散文干支被誤切
本工具對源文本重跑這些 pattern，列出「會被切成 ### 標題」的候選、前後文，
並生成一則自足的 LLM 複核 prompt：判定每條是「合法年份標題」還是「散文誤切」。

── 只報告，不改檔；LLM 判定亦不自動套用 ──

用法：
    python tools/nianpu_bare_review.py <源檔> [選項]

選項：
    --loose     額外納入「通用 entry_bare」的匹配（bare_gz 格式下現正則刻意
                排除的散文干支邊界，如 永樂十九年辛丑）——看 LLM 能否判「不切」。
    --all       fmt=None：套用全部 pattern 子集（近似舊版寬鬆行為，
                可重現 v3.21 前誤切，驗證 LLM 能標出）。
    --limit N   最多取前 N 個候選。
    --no-llm    只印候選表（純規則報告），不生成 LLM prompt。
    --prompt F  把 LLM prompt 寫到 F（不寫則只印）。
"""
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
import nianpu_processor as np

# Windows 主控台預設 cp936 會亂碼中文輸出；強制 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ── 與 nianpu_processor._build_full_pattern 同步的「歧義無年齡」pattern 建構 ──
# 注意：主 pattern 變更時需同步此處；工具另有 --selfcheck 對照真實輸出校正。
def _build_bare_patterns(fmt):
    y = np._build_year_pattern()
    sb = np.STEM_BRANCH
    an = np.AGE_DIGITS
    ap = '|'.join(re.escape(p) for p, _ in np.EMPEROR_PREFIXES)
    ar = '|'.join(np.REIGNS)
    extra_person = (fmt or {}).get('_person_extra') or []
    person = '(?:' + '|'.join(np.PERSON_PREFIXES + extra_person) + r')'
    age_lookahead = (r'(?!(?:[，,、。]?\s*)?(?:(?:' + person + r')?(?:年)?\s*)?'
                     + an + r'[' + np.AGE_SUFFIXES + r'])')
    return {
        'entry_bare': re.compile(
            r'(?:^|(?<=[。！？；〕\n]))\s*'
            + r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')?'
            + y + r'年' + sb + age_lookahead
            + r'[，,、。]?'),
        'entry_bare_gz': re.compile(
            r'(?:^|(?<=\n))\s*'
            + r'[○〇]?'
            + r'(?<!年)'
            + r'(?P<gz>[' + np._TG + r'][' + np._DZ + r'])'
            + r'(?![甲乙丙丁戊己已庚辛壬癸巳])'
            + r'[，,、。]?'),
        'entry_bare_ls': re.compile(
            r'(?:^|(?<=\n))\s*'
            + r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')?'
            + y + r'年' + sb + age_lookahead
            + r'[，,、。]?'),
        'entry_bare_se_yuan': re.compile(
            r'(?<=[。！？；〕])\s*'
            + r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')?'
            + r'元年' + sb + age_lookahead
            + r'[，,、。]?'),
    }


def _active_bare_names(fmt, loose=False):
    """依格式族決定哪些歧義 pattern 啟用（與 _build_full_pattern 子集一致）。"""
    active = []
    if fmt is None or (fmt.get('bare') and not fmt.get('bare_gz')):
        active.append('entry_bare')
    if fmt is None or fmt.get('bare_gz'):
        active.extend(['entry_bare_ls', 'entry_bare_se_yuan', 'entry_bare_gz'])
    if loose and 'entry_bare' not in active:
        active.append('entry_bare')   # loose：納入被格式刻意排除的通用 pattern
    return active


def _predict_heading(raw, fmt, reign_state):
    """複製 process_nianpu insert() 的標題預測（filter＋_make_heading＋reign 追蹤＋bare_gz 擴展）。

    同步 insert() 的順序：先 filter（長度/句號），過了才 extract_reign 更新
    reign_state，再決定 bare_gz 擴展或補年號。回傳 (heading|None, is_skipped)；
    None 表示 insert() 會跳過該匹配（且不更新 reign_state）。
    """
    raw = raw.strip()
    if not raw:
        return None, True
    person_p = '(?:' + '|'.join(np.PERSON_PREFIXES + (fmt or {}).get('_person_extra', [])) + r')'
    is_birth = (bool(re.search(r'(?<!先)生於', raw))
                or re.search(person_p + r'生(?:於)?', raw) is not None)
    if is_birth and '。' in raw:
        raw = raw.split('。')[0]
    heading = np._make_heading(raw)
    if is_birth:
        heading = re.sub(person_p + r'生(?:於)?$', '', heading).rstrip('，, ')
    if (not is_birth and len(heading) > 40) or (is_birth and len(heading) > 30):
        return None, True
    if '。' in heading and not is_birth:
        return None, True
    # 與 insert() 相同的 reign 追蹤：先更新，再擴展
    r, _ = np.extract_reign(heading)
    if r and r not in ('', None):
        reign_state[0] = r
    elif (reign_state[0]
          and not any(heading.startswith(rr) for rr in np.REIGNS)
          and not heading.startswith('公元')):
        if (fmt or {}).get('bare_gz'):
            expanded = np._expand_bare_gz_heading(heading, reign_state[0])
            if expanded is not None:
                heading = expanded
            else:
                heading = reign_state[0] + heading
        else:
            heading = reign_state[0] + heading
    return heading, False


def _line_context(text, pos, radius=1):
    """取包含 pos 的行，以及其前後 radius 行，去空白後回傳。"""
    start = text.rfind('\n', 0, pos) + 1
    end = text.find('\n', pos)
    if end == -1:
        end = len(text)
    cur = text[start:end].strip()
    prevs, nexts = [], []
    s = start
    for _ in range(radius):
        s2 = text.rfind('\n', 0, s - 1)
        if s2 == -1:
            break
        prevs.append(text[s2 + 1:s].strip())
        s = s2
    e = end
    for _ in range(radius):
        e2 = text.find('\n', e + 1)
        if e2 == -1:
            break
        nexts.append(text[e + 1:e2].strip())
        e = e2
    return prevs[::-1], cur, nexts


def collect_candidates(text, fmt, loose=False, limit=None):
    """重跑歧義 pattern，收集候選（含預測標題、前後文、是否實際已切）。"""
    pats = _build_bare_patterns(fmt)
    active = _active_bare_names(fmt, loose=loose)
    # loose 模式額外納入的 entry_bare 只是「邊界測試」候選：生產上它不啟用，
    # 其年號由完整軌跡提供（見下方 _reign_at），不會污染年號推算

    # 實際輸出標題集合（--selfcheck 對照；np.process_nianpu 不寫 learnings）
    try:
        real_out, _ = np.process_nianpu(text)
        real_heads = set()
        for m in re.finditer(r'^### (.+)$', real_out, re.M):
            h = m.group(1).strip()
            h = re.sub(r'（\d{3,4}年）$', '', h)   # 去掉公元年註記再比對
            real_heads.add(h)
    except Exception:
        real_heads = None   # 對照失敗不阻斷工具

    matches = []
    for name in active:
        p = pats[name]
        for m in p.finditer(text):
            raw = m.group(0).strip()
            if not raw:
                continue
            matches.append((name, m.start(), m.end(), raw))
    # 依位置去重（同 span 只留先匹配到的 pattern）
    seen, uniq = set(), []
    for name, s, e, raw in sorted(matches, key=lambda t: (t[1], t[2])):
        if (s, e) in seen:
            continue
        seen.add((s, e))
        uniq.append((name, s, e, raw))

    # 年號軌跡：用「完整 pattern」模擬 insert()（含 entry_sb 等有稱謂標題的年號，
    # 混合格式如 桐城吳 person+bare_gz 的年份主要由 公年N歲 提供，不能只靠 bare 候選）
    reign_traj = []
    full_reign = [None]
    try:
        for m in np._build_full_pattern(fmt).finditer(text):
            _predict_heading(m.group(0), fmt, full_reign)
            reign_traj.append((m.start(), full_reign[0]))
    except Exception:
        reign_traj = []

    def _reign_at(pos):
        rv = None
        for s, r in reign_traj:
            if s <= pos:
                rv = r
            else:
                break
        return rv

    cands = []
    for name, s, e, raw in uniq:
        # 每個候選依其位置從完整軌跡取當前年號；loose-only pattern 只讀不寫回
        state = [_reign_at(s)]
        heading, skipped = _predict_heading(raw, fmt, state)
        if skipped:
            continue   # insert() 不會切
        prevs, cur, nexts = _line_context(text, s)
        status = '?'
        if real_heads is not None:
            cmp_h = re.sub(r'（\d{3,4}年）$', '', heading)
            status = '已切' if cmp_h in real_heads else '未切'
        cands.append({
            'n': len(cands) + 1,
            'pattern': name, 'raw': raw, 'heading': heading,
            'prev': prevs, 'cur': cur, 'next': nexts, 'status': status,
        })
    if limit:
        cands = cands[:limit]
    return cands


REVIEW_PROMPT = """你是年譜校勘者。以下是從年譜源文重跑「無年齡通用 pattern」
（entry_bare／entry_bare_gz／entry_bare_ls／entry_bare_se_yuan）得到的候選年份標題。
這些 pattern 歷史誤切最多（把散文中的干支日期誤當年份標題）。請逐條判定：
  ① 合法年份標題（年譜按此紀年，切標題正確）
  ② 散文誤切（正文敘述的干支日期，不該切成標題）

判定時看「原文所在行的上下文」：年譜的年份標題通常是行首、簡短、無句意依存；
散文中的干支日期通常嵌在句意中、前後文字有具體事件/時間連貫。

格式族：{fmt_desc}

候選清單：
{items}

── 請逐條輸出：條目號 / 判定（合法 or 誤切）/ 理由（一句話）／若誤切，建議處理 ──
"""


def _fmt_desc(fmt):
    if fmt is None:
        return '全部 pattern（--all 寬鬆模式）'
    flags = [k for k, v in fmt.items() if v and k in (
        'person', 'no_person', 'ad', 'bare', 'bare_gz', 'modern')]
    return ('+' + '/'.join(flags)) if flags else 'auto'


def build_review_prompt(cands, fmt, src_name=''):
    lines = []
    for c in cands:
        ctx = ' ｜ '.join([c['cur']] + c['prev'] + c['next'])
        lines.append(
            f"[{c['n']}] pattern={c['pattern']} [{c['status']}]\n"
            f"    預測標題：### {c['heading']}\n"
            f"    原文：{c['raw']}\n"
            f"    上下文：{ctx}"
        )
    return REVIEW_PROMPT.format(
        fmt_desc=_fmt_desc(fmt),
        items='\n'.join(lines),
    )


def print_table(cands):
    print("═" * 60)
    print(f"歧義 bare pattern 候選複核表（共 {len(cands)} 條）")
    print("═" * 60)
    for c in cands:
        print(f"[{c['n']:>3}] {c['pattern']:<16} [{c['status']}]")
        print(f"      標題  ### {c['heading']}")
        print(f"      原文  {c['raw']}")
        print(f"      上文  {' / '.join(c['prev']) or '—'}")
        print(f"      下行  {' / '.join(c['next']) or '—'}")
        print("-" * 60)


def main(argv):
    args = [a for a in argv if not a.startswith('--')]
    if not args:
        print(__doc__)
        return 1
    src = args[0]
    loose = '--loose' in argv
    all_fmt = '--all' in argv
    limit = None
    if '--limit' in argv:
        i = argv.index('--limit')
        limit = int(argv[i + 1])
    prompt_path = None
    if '--prompt' in argv:
        i = argv.index('--prompt')
        prompt_path = argv[i + 1]

    text = open(src, encoding='utf-8').read()
    text = re.sub(r'<!--.*?-->', '', text)
    text = np._normalize_reign_variants(text)
    text = np._apply_ocr_fixes(text)
    text = np._merge_multi_line_years(text)

    fmt = None if all_fmt else np.classify_format(text)
    cands = collect_candidates(text, fmt, loose=loose, limit=limit)
    print_table(cands)

    if '--no-llm' in argv:
        return 0
    prompt = build_review_prompt(cands, fmt, src)
    if prompt_path:
        open(prompt_path, 'w', encoding='utf-8').write(prompt)
        print(f"\n▸ LLM 複核 prompt 已寫入：{prompt_path}")
    else:
        print("\n" + "═" * 60)
        print("LLM 複核 prompt（照 arbitrate 慣例：拿去跑 LLM，取回判定）")
        print("═" * 60)
        print(prompt)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
