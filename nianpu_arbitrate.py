#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年譜 L2 三錨點衝突仲裁助手 — nianpu_arbitrate.py
=================================================
當 --check 標出「年號年 vs 干支 vs 年齡」打架的標題時，本腳本把衝突收集成一份
仲裁請求（含上下文窗口）交給 LLM 判定，再把判定結果套用並復驗。

工作流（仲裁由 LLM 執行，本腳本只負責收集／套用／保全校驗，與 nianpu_biaodian
的 chunk→LLM→merge→verify 同一模式）：
  1. python nianpu_arbitrate.py --request <已整理.md>      # → <名>_仲裁請求.md
  2. LLM 讀請求逐條判定，寫出 <名>_仲裁結果.md（每行一條）：
        {衝突標題} → {修正後標題}      只動年號年序
        {衝突標題} → 不改              無法判定
  3. python nianpu_arbitrate.py --apply <已整理.md> <仲裁結果.md>
       # 套用合法修正 → 寫入 <名>_已仲裁.md → 復驗三錨點

保守原則：只准改「年號年序」（含公元註記），干支/年齡/正文一律保留；修正後
「年號年→公元」須與該條干支自洽（(ad−4)%60 == 干支索引），不滿足的判定直接拒絕。
"""
from pathlib import Path
import re, sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import nianpu_processor as np


def read_text(path):
    data = Path(path).read_bytes()
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'big5'):
        try:
            return data.decode(enc).replace('\r\n', '\n').replace('\r', '\n')
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')


def _strip_pref(l):
    if l.startswith('#### '):
        return l[5:]
    if l.startswith('### '):
        return l[4:]
    return l


def neighbor_context(result, heading, before=2, after=1):
    hs = [l for l in result.split('\n') if l.startswith('### ') or l.startswith('#### ')]
    raw = _strip_pref(heading)
    idx = [i for i, l in enumerate(hs) if _strip_pref(l) == raw]
    if not idx:
        return []
    i = idx[0]
    return hs[max(0, i - before):i] + hs[i + 1:i + 1 + after]


def build_request(result):
    """收集 L2 三錨點衝突 + 上下文 → 仲裁請求文字。回傳 (請求, 衝突數)。"""
    suspects, seq_bad, birth, total = np.verify_anchors(result)
    if not suspects:
        return None, 0
    hs = [l for l in result.split('\n') if l.startswith('### ') or l.startswith('#### ')]
    raw2full = {_strip_pref(l): l for l in hs}
    out = [
        '你是年譜校勘者。以下條目在「年號年→公元」「干支→公元」「年齡→公元」三個錨點間打架。',
        '請結合上下文逐條定奪哪個錨點有誤、正確年號年序應是什麼。',
        f'推定出生年：{birth if birth else "（無法推定，只能靠干支週期）"}',
        '',
        '── 輸出格式（嚴格，每行一條，勿加說明）──',
        '  {衝突標題原樣} → {修正後標題}',
        '  或  {衝突標題原樣} → 不改',
        '規則：只動「年號年序」＋（公元註記）；干支/年齡/正文一律保留；',
        '修正後年號年推得的公元年須與該條干支自洽；無法判定填「不改」。',
        '',
        '衝突條目：',
    ]
    for raw, reasons in suspects:
        full = raw2full.get(raw, raw)
        out.append(f'  {full}')
        for r in reasons:
            out.append(f'      └ {r}')
        nbr = neighbor_context(result, full)
        if nbr:
            out.append('      上下文：' + ' ／ '.join(nbr))
    if seq_bad:
        out.append('')
        out.append('（另有序列問題需人工處理，不在仲裁範圍：）')
        for s in seq_bad[:8]:
            out.append(f'  ⚠ {s}')
    return '\n'.join(out), len(suspects)


def parse_verdicts(text):
    """解析仲裁結果檔：每行 {原標題} → {修正}。回傳 [(orig, prop)]。"""
    out = []
    for line in text.split('\n'):
        line = line.strip()
        if '→' not in line:
            continue
        left, right = line.split('→', 1)
        left, right = left.strip(), right.strip()
        if left.startswith(('### ', '#### ')) and right:
            out.append((left, right))
    return out


def validate_proposal(orig, prop):
    """保守驗證：只准改年號年序；干支/年齡/正文/前綴一律保留；年號年與干支自洽。"""
    if not prop or prop.strip() == '不改' or prop.strip() == orig:
        return None
    o = np._parse_heading_anchors(orig)
    p = np._parse_heading_anchors(prop)
    if p['ganzhi'] != o['ganzhi']:
        return None  # 不許改干支
    if p['age'] != o['age']:
        return None  # 不許改年齡
    if p['reign_ad'] is None:
        return None  # 修正後必須有年號年
    if p['ganzhi_idx'] is not None and (p['reign_ad'] - 4) % 60 != p['ganzhi_idx']:
        return None  # 修正後年號年與干支不自洽
    # 前綴一致
    op = orig[:5] if orig.startswith(('### ', '#### ')) else ''
    pp = prop[:5] if prop.startswith(('### ', '#### ')) else ''
    if op != pp:
        return None
    return prop.strip()


def apply_arbitration(result, verdicts):
    """套用仲裁判定：合法修正→fixes；非法→rejected。回傳 (new_result, fixes, rejected)。"""
    fixes, rejected = [], []
    for orig, prop in verdicts:
        if prop == '不改':
            continue
        valid = validate_proposal(orig, prop)
        if valid and valid != orig:
            fixes.append((orig, valid))
        else:
            rejected.append((orig, prop))
    new = np.apply_fixes(result, fixes)
    return new, fixes, rejected


def cmd_request(inp):
    result = read_text(inp)
    req, n = build_request(result)
    if n == 0:
        print(f"✓ {Path(inp).name}：無 L2 三錨點衝突，不需仲裁。")
        return
    out = inp.with_stem(inp.stem.replace('_已整理', '') + '_仲裁請求')
    out.write_text(req + '\n', encoding='utf-8')
    print(f"仲裁請求：{n} 條衝突 → {out}")
    print("下一步：LLM 讀此檔逐條判定，寫出〈結果檔〉（每行 {標題} → {修正後標題} 或 → 不改）。")


def cmd_apply(inp, verdict_path):
    result = read_text(inp)
    verdicts = parse_verdicts(read_text(verdict_path))
    if not verdicts:
        print(f"錯誤：{Path(verdict_path).name} 沒有可解析的「標題 → 修正」行。")
        sys.exit(1)
    new, fixes, rejected = apply_arbitration(result, verdicts)
    out = inp.with_stem(inp.stem.replace('_已整理', '') + '_已仲裁')
    out.write_text(new, encoding='utf-8')
    print(f"已套用 {len(fixes)} 條、拒絕 {len(rejected)} 條 → {out}")
    for orig, prop in rejected:
        print(f"  ✗ 拒絕：{orig} → {prop}")
    # 復驗
    sus, seq_bad, birth, total = np.verify_anchors(new)
    print(f"復驗：推定出生年 {birth if birth else '（無法推定）'}；剩餘衝突 {len(sus)} 條，序列問題 {len(seq_bad)} 條")
    for h, reasons in sus[:8]:
        print(f"  ⚠ {h}")
        for r in reasons:
            print(f"      └ {r}")
    if seq_bad:
        for s in seq_bad[:5]:
            print(f"  ⚠ {s}")
    print(f"（仍剩 {len(sus)} 條衝突需人工處理）" if sus else "（三錨點已清 ✓）")


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(1)
    mode, argv = argv[0], argv[1:]
    if mode == '--request':
        if not argv:
            print("用法：nianpu_arbitrate.py --request <已整理.md>"); sys.exit(1)
        cmd_request(Path(argv[0]))
    elif mode == '--apply':
        if len(argv) < 2:
            print("用法：nianpu_arbitrate.py --apply <已整理.md> <仲裁結果.md>"); sys.exit(1)
        cmd_apply(Path(argv[0]), Path(argv[1]))
    else:
        print(f"未知模式：{mode}")
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
