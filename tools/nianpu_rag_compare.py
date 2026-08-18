#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年譜 RAG 檢索效果對比工具 — nianpu_rag_compare.py
==================================================
比較「整理前（原始 OCR）」vs「整理後（nianpu-processor 已整理）」年譜的
RAG 檢索效果：用相同 BM25 檢索回答「某人在 25/35/45/55 歲做什麼」，
對比答案塊品質（命中／噪音／長度）與召回率（Recall@K、受限預算召回率）。

用法：
  python nianpu_rag_compare.py <年譜資料目錄> [年齡清單...]
  例：
    python nianpu_rag_compare.py "E:/2022/个人研究资料/年谱项目"
  python nianpu_rag_compare.py "E:/2022/个人研究资料/年谱项目" 25 35 45 55
  python nianpu_rag_compare.py "E:/2022/个人研究资料/年谱项目" --json   # 輸出 JSON

自動偵測：
  * 整理後檔：目錄下「*_已整理.md」
  * 整理前檔：同 stem 的「*_完整.md」；無則取去掉「_已整理」的原始檔
  * 年份標題層級（### / ####）與出生年：從已整理檔標題反推

指標：
  hit@1 / 噪音（混入其它年份干支數）/ 塊長（答案塊品質）
  Recall@1 / Recall@3（塊層級）
  受限預算召回率（500/1000/2000 字，模擬 RAG 上下文有限）
"""
import re, sys, io, math, json, argparse
from pathlib import Path
from collections import Counter

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

STEMS = '甲乙丙丁戊己庚辛壬癸'
BRANCHES = '子丑寅卯辰巳午未申酉戌亥'
CN = '零一二三四五六七八九'
BUDGETS = [500, 1000, 2000]
DEFAULT_AGES = [25, 35, 45, 55]


# ---------- 中文數字 ----------
def _cn_to_int(s):
    s = s.replace('廿', '二十').replace('卅', '三十')
    if s == '元' or s == '一':
        return 1
    if '十' in s:
        a, b = s.split('十', 1)
        n = (CN.index(a) if a and a in CN else 1) * 10
        if b and b in CN:
            n += CN.index(b)
        return n
    if s in CN:
        return CN.index(s)
    return None


def _int_to_cn(n):
    if n == 1:
        return '一'
    if n < 10:
        return CN[n]
    if n == 10:
        return '十'
    if n < 20:
        return '十' + CN[n % 10]
    return CN[n // 10] + '十' + (CN[n % 10] if n % 10 else '')


def _ganzhi_of_ad(ad):
    i = (ad - 4) % 60
    return STEMS[i % 10] + BRANCHES[i % 12]


# ---------- 檔案配對 ----------
def find_pairs(dirpath):
    """在目錄（含子目錄）下找 (name, before_path, after_path) 清單。

    整理後檔（*_已整理.md）可能與整理前檔分屬不同分類：
    先找同資料夾的「*_完整」/同名原始檔；找不到時再到整棵樹搜同名「*_完整」
    或同名原始檔（例如 年譜整理稿 的 _已整理 對應 年譜原始PDF/識典數據 的原始檔）。
    """
    d = Path(dirpath)
    pairs = []
    for after in sorted(d.rglob('*_已整理.md')):
        raw_stem = after.stem.replace('_已整理', '')
        before = None
        for c in (after.parent / (raw_stem + '_完整.md'), after.parent / (raw_stem + '.md')):
            if c.exists() and c != after:
                before = c; break
        if before is None:
            cands = sorted([c for c in d.rglob(raw_stem + '_完整.*')
                            if c.suffix in ('.md', '.txt') and c != after])
            if cands:
                before = cands[0]
        if before is None:
            cands = sorted([c for c in d.rglob(raw_stem + '.*')
                            if c != after and c.suffix in ('.md', '.txt')
                            and '_已整理' not in c.stem])
            if cands:
                before = cands[0]
        if before is not None:
            pairs.append((after.stem, str(before), str(after)))
    return pairs


def detect_hdr(text):
    """偵測年份標題層級：統計含干支的 ###/#### 行，取多數。"""
    pat = r'[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]'
    n3 = len(re.findall(r'^### [^\n]*' + pat, text, re.M))
    n4 = len(re.findall(r'^#### [^\n]*' + pat, text, re.M))
    return r'^#### ' if n4 > n3 else r'^### '


def detect_birth(text, hdr):
    """從第一個含公元年與年齡的年份標題反推出生年。

    支援：公元年在（）內外、阿拉伯（1813）或中文（一九〇一）寫法；
    年齡後綴 嵗/歲/歳/岁。
    """
    ad_pat = r'（?(\d{4}|[一二三四五六七八九零〇]{3,4})\s*年）?'
    for line in text.split('\n'):
        if not re.match(hdr, line):
            continue
        m = re.search(ad_pat, line)
        a = re.search(r'([一二三四五六七八九十廿卅]{1,4})[嵗歲歳岁]', line)
        if m and a:
            ad_s = m.group(1)
            ad = int(ad_s) if ad_s.isdigit() else _cn_ad_to_int(ad_s)
            age = _cn_to_int(a.group(1))
            if ad and age:
                return ad - age + 1
    return None


def _cn_ad_to_int(s):
    """中文數字逐位轉整數（一八一三=1813、一九〇一=1901）。"""
    mp = {'零': 0, '〇': 0, '一': 1, '二': 2, '三': 3, '四': 4,
          '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    n = 0
    for ch in s:
        if ch in mp:
            n = n * 10 + mp[ch]
    return n


# ---------- 分塊 ----------
def chunk_paragraphs(text):
    """整理前：按空行分段落（原始 OCR 只有這種粒度）。"""
    return [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]


def chunk_by_header(text, hdr):
    """整理後：按年份標題分塊（每一年自成一個檢索單元）。"""
    blocks, cur = [], None
    for line in text.split('\n'):
        if re.match(hdr, line):
            if cur is not None:
                blocks.append('\n'.join(cur).strip())
            cur = [line]
        else:
            cur = [line] if cur is None else cur + [line]
    if cur is not None:
        blocks.append('\n'.join(cur).strip())
    return [b for b in blocks if b.strip()]


# ---------- 分詞 / BM25 ----------
def _tokenize(text):
    toks = [m.group(0) for m in re.finditer(r'\d+', text)]
    t = re.sub(r'\d+', ' ', text)
    chars = re.findall(r'[\u4e00-\u9fff]', t)
    return toks + chars + [a + b for a, b in zip(chars, chars[1:])]


def build_bm25(chunks):
    N = len(chunks)
    df, doc_len, tfs = {}, [], []
    for c in chunks:
        t = _tokenize(c)
        doc_len.append(len(t))
        for tk in set(t):
            df[tk] = df.get(tk, 0) + 1
    avgdl = (sum(doc_len) / N) if N else 1
    for c in chunks:
        tf = {}
        for tk in _tokenize(c):
            tf[tk] = tf.get(tk, 0) + 1
        tfs.append(tf)
    k1, b = 1.5, 0.75

    def score(q):
        qs = set(_tokenize(q))
        out = []
        for i, tf in enumerate(tfs):
            s = 0.0
            for tk in qs:
                f = tf.get(tk, 0)
                if not f:
                    continue
                idf = math.log((N - df.get(tk, 0) + 0.5) / (df.get(tk, 0) + 0.5) + 1)
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * doc_len[i] / avgdl))
            out.append(s)
        return out
    return score


# ---------- 指標 ----------
GANZHI_RE = re.compile(r'[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]')


def _char_overlap_recall(usable, gt):
    """usable 文本對 ground-truth 的字符覆蓋召回率（去空白，字符 bag）。"""
    u = re.sub(r'\s', '', usable)
    g = re.sub(r'\s', '', gt)
    if not g:
        return 0.0
    cu, cg = Counter(u), Counter(g)
    return sum((cu & cg).values()) / len(g)


def get_gt(text, hdr, ganzhi):
    """整理後檔中該干支年份段（作標準答案）。"""
    m = re.search(r'^' + hdr + r'[^\n]*' + re.escape(ganzhi)
                  + r'[^\n]*\n.*?(?=\n' + hdr + r'|\Z)', text, re.M | re.S)
    return m.group(0).strip() if m else ''


def evaluate_book(before_path, after_path, hdr, birth, ages):
    bt = open(before_path, encoding='utf-8').read()
    at = open(after_path, encoding='utf-8').read()
    bc = chunk_paragraphs(bt)              # 整理前：段落分塊
    ac = chunk_by_header(at, hdr)          # 整理後：年份標題分塊
    bs, as_ = build_bm25(bc), build_bm25(ac)

    rows = []
    for age in ages:
        ad = birth + age - 1
        gz = _ganzhi_of_ad(ad)
        query = f'{ad} {gz} {_int_to_cn(age)}歲'
        gt = get_gt(at, hdr, gz)
        bsc, asc = bs(query), as_(query)
        b_top = sorted(range(len(bc)), key=lambda i: bsc[i], reverse=True)[:5]
        a_top = sorted(range(len(ac)), key=lambda i: asc[i], reverse=True)[:5]

        def top(chunks, top_idx, sc, k):
            return [chunks[i] for i in top_idx[:k] if sc[i] > 0]

        b1 = top(bc, b_top, bsc, 1); a1 = top(ac, a_top, asc, 1)
        b3 = top(bc, b_top, bsc, 3); a3 = top(ac, a_top, asc, 3)
        b_hit = bool(b1) and gz in b1[0]
        a_hit = bool(a1) and gz in a1[0]
        b_cover3 = any(gz in c for c in b3)
        a_cover3 = any(gz in c for c in a3)

        b_noise = len(set(GANZHI_RE.findall(b1[0])) - {gz}) if b1 else None
        a_noise = len(set(GANZHI_RE.findall(a1[0])) - {gz}) if a1 else None
        b_len = len(b1[0]) if b1 else 0
        a_len = len(a1[0]) if a1 else 0

        # 受限預算召回率
        b_usable = ''.join(b3)
        a_usable = ''.join(a3)
        rec_b = {B: _char_overlap_recall(b_usable[:B], gt) for B in BUDGETS} if gt else None
        rec_a = {B: _char_overlap_recall(a_usable[:B], gt) for B in BUDGETS} if gt else None

        rows.append({
            'age': age, 'query': query, 'gt': gt,
            'before': {'hit': b_hit, 'cover3': b_cover3, 'noise': b_noise, 'len': b_len,
                       'recall': rec_b, 'top1': b1[0][:60] if b1 else ''},
            'after': {'hit': a_hit, 'cover3': a_cover3, 'noise': a_noise, 'len': a_len,
                      'recall': rec_a, 'top1': a1[0][:60] if a1 else ''},
        })
    return {'before_n': len(bc), 'after_n': len(ac), 'rows': rows}


def print_report(name, person, birth, res, ages):
    print(f"===== {name}（{person}，生於 {birth}）=====")
    print(f"塊數：整理前(段落) {res['before_n']} / 整理後(按年) {res['after_n']}")
    for r in res['rows']:
        b, a = r['before'], r['after']
        line = (f"  {r['age']}歲 {r['query']}\n"
                f"    整理前 hit={b['hit']} 噪音={b['noise']} 塊長={b['len']}\n"
                f"    整理後 hit={a['hit']} 噪音={a['noise']} 塊長={a['len']}")
        if b['recall']:
            line += (f"\n    受限召回(500/1000/2000)：前 {b['recall'][500]*100:.0f}%/{b['recall'][1000]*100:.0f}%/{b['recall'][2000]*100:.0f}%"
                     f"   后 {a['recall'][500]*100:.0f}%/{a['recall'][1000]*100:.0f}%/{a['recall'][2000]*100:.0f}%")
        print(line)
    print()


def summarize(results):
    print("\n===== 匯總（預算 1000 字受限召回率）=====")
    print("書\t整理前(均)\t整理後(均)\t改善")
    for name, birth, res in results:
        b = [r['before']['recall'][1000] for r in res['rows'] if r['before']['recall']]
        a = [r['after']['recall'][1000] for r in res['rows'] if r['after']['recall']]
        if b and a:
            mb, ma = sum(b) / len(b) * 100, sum(a) / len(a) * 100
            print(f"{name}\t{mb:.0f}%\t{ma:.0f}%\t+{ma - mb:.0f} 個百分點")


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('dir', help='年譜資料目錄')
    ap.add_argument('ages', nargs='*', type=int, help='要查詢的年齡（預設 25 35 45 55）')
    ap.add_argument('--json', action='store_true', help='輸出 JSON')
    args = ap.parse_args()

    ages = args.ages or DEFAULT_AGES
    pairs = find_pairs(args.dir)
    if not pairs:
        print(f"錯誤：在 {args.dir} 找不到「*_已整理.md」配對。"); sys.exit(1)

    results = []
    for name, before, after in pairs:
        at = open(after, encoding='utf-8').read()
        hdr = detect_hdr(at)
        birth = detect_birth(at, hdr)
        if not birth:
            print(f"跳過 {name}：無法從標題推出生年。"); continue
        res = evaluate_book(before, after, hdr, birth, ages)
        results.append((name, birth, res))
        print_report(name, '？', birth, res, ages)

    if args.json:
        out = []
        for name, birth, res in results:
            out.append({'name': name, 'birth': birth, 'before_n': res['before_n'],
                        'after_n': res['after_n'], 'rows': res['rows']})
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        summarize(results)


if __name__ == '__main__':
    main()
