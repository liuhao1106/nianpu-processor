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
  python nianpu_processor.py --revert         # 回滾 learnings.json 最近一次保存
  python tools/regression.py --verify-learnings   # 質檢閘門：pending 學習→回歸驗證
"""

import re, sys, json
from pathlib import Path

from .constants import STEM_BRANCH
from .anchors import verify_anchors
from .fixes import (get_person, _cbdb_extract_name, _cbdb_check,
                    _anchor_fix_check, apply_fixes)
from .learnings import (apply_learnings, print_learnings_summary,
                        prune_invalidated_learnings, record_manual_correction,
                        self_learn, revert_learnings)
from .modern import try_parse_modern_heading
from .process import process_nianpu, slots_to_fmt
from .verify import verify_output, _format_anchor_report


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

    # --record「錯」「對」[來源]：錄入手動修正；干支形近字修正累積為 OCR 候選規則
    # （反饋閉環：--status 列出出現 ≥2 次的候選，人工複核後升級 _OCR_FIXES）
    if argv[0] == '--record':
        if len(argv) < 3:
            print("用法：nianpu_processor.py --record \"錯\" \"對\" [來源]"); sys.exit(1)
        source = argv[3] if len(argv) > 3 else ''
        learnings, is_gz = record_manual_correction(argv[1], argv[2], source)
        if is_gz:
            wg = re.search(STEM_BRANCH, argv[1]); cg = re.search(STEM_BRANCH, argv[2])
            key = f'{wg.group(0)}→{cg.group(0)}'
            cand = learnings.get('ocr_candidates', {}).get(key, {})
            print(f"▸ 已記錄干支 OCR 候選：{key}"
                  f"（上下文「{cand.get('context', '')}」，共 {cand.get('count', 0)} 次）")
        else:
            print("▸ 已記錄一般修正")
        return

    # --revert 回滾 learnings.json 至最近一次保存前（.bak 單槽備份；
    # 每次 _save_learnings 覆寫前自動備份：驗證轉正／修正錄入／統計更新皆可回滾）
    if argv[0] == '--revert':
        ok, msg = revert_learnings()
        print(f"▸ {msg}")
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
    # --fix 在 CBDB 缺席時回退到內部「干支+年齡」共識出生年（_consensus_birth_year），
    # 拔掉外部依賴——冷門傳主 / CBDB 無生卒日期者仍可自動修年號年序誤標。
    if modern_report is None:
        cbdb_birth = None
        if cbdb_requested and get_person:
            name = cbdb_name or (_cbdb_extract_name(original) if _cbdb_extract_name else None)
            if name:
                person = get_person(name)
                if person and person.get('birth'):
                    cbdb_birth = person['birth']
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
        if fix_mode and cbdb_birth is None:
            _, _, anchor_birth, _ = verify_anchors(result)
            if anchor_birth:
                print(f"▸ CBDB 無可用生年，以內部共識出生年 {anchor_birth} 執行錨點修正")
                fixes = _anchor_fix_check(result, anchor_birth,
                                          f'內部共識出生年 {anchor_birth}')
                if fixes:
                    result = apply_fixes(result, fixes)
                    print(f"▸ 已自動修正 {len(fixes)} 條年號年序誤標（干支/年齡保留）")
            else:
                print("▸ 無可用生年（CBDB 無＋內部共識不足），跳過錨點修正")

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
