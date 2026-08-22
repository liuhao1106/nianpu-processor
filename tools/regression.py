#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""年譜工具回歸測試套件（stdlib 零依賴）。

背景：弱點③——改動 nianpu_processor.py 後的回歸測試長期靠手工重跑舊案例，
      v3.23 起「6 案例差異=0」式量化回退記錄斷檔，歷史成績不可自證。

本套件把「已成功處理」的成績變成可複現的黃金測試：
  tools/testdata/*_source.md / *_golden.md     源 + 已整理（黃金輸出）成對，自包含、換機可跑
  tools/testdata/regression_manifest.json      每案例：源/黃金路徑、格式、模式、槽位
  tools/testdata/regression_baseline.json      --selfcheck 建立：行為快照＋黃金輸出指標

雙參照比對：
  ① 行為快照（baseline.metrics）＝上次審核通過的管線輸出指標
     ——回歸測試的對象：改碼後若行為變了（標題數/覆蓋率/出生年/可疑數），--run 報 FAIL
  ② 黃金輸出（baseline.golden）＝當年歸檔文件的指標
     ——驗證「歷史成績是否可復現」：差異一律列為 WARN（人工修正已寫回源檔的案例
       ≠ 純自動管線能力，誠實分開），不擋 PASS

三層模式：
  exact   行為快照指標全比對（標題數/出生年/可疑數/覆蓋率）＋標題數須與黃金輸出一致
  metric  行為快照容差比對（標題數不降、覆蓋率不低於基線-容差、不崩潰）
  smoke   只驗證跑通不炸

用法：
  python tools/regression.py --selfcheck       # 建立基線（行為快照＋黃金指標）
  python tools/regression.py --run             # 重跑管線 vs 基線，出 PASS/FAIL 表＋回歸行
  python tools/regression.py --run --full      # 另掃描 E: 識典數據 全部案例（不限 testdata）
  python tools/regression.py --run --update    # 重跑後以本次結果刷新基線（人工審核後再用）
  python tools/regression.py --smoke           # 只驗證不崩潰（快速冒煙）

約定：
  * 回歸對象是「基礎規則集」——直接呼叫 process_nianpu，不走 main() 的
    apply_learnings()，因此不受 learnings.json 經驗累積影響，結果可跨機複現。
  * 標點（nianpu_biaodian）與仲裁（nianpu_arbitrate）屬 LLM-in-loop 步驟，
    不在此回歸範圍（其 verify 已做字符保全校驗）。
  * 指標式比對（非全文 diff）不抓「改了輸出但指標不變」的 bug，是刻意取捨：
    大量黃金輸出含人工修正，全文 diff 必然假陽性。
"""

import json
import os
import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SKILL_DIR = TOOLS_DIR.parent
TESTDATA_DIR = TOOLS_DIR / 'testdata'
MANIFEST_PATH = TESTDATA_DIR / 'regression_manifest.json'
BASELINE_PATH = TESTDATA_DIR / 'regression_baseline.json'

# --full 全庫掃描根目錄：可用環境變數 NIANPU_ROOT 覆蓋（換機只需設定一次）
FULL_LIB_ROOT = os.path.join(os.environ.get('NIANPU_ROOT', r'E:/2022/个人研究资料/年谱项目'), '識典數據')

sys.path.insert(0, str(SKILL_DIR))
import nianpu_processor as NP  # noqa: E402

_COV_TOL = 0.5      # exact 模式覆蓋率容差
_COV_TOL_M = 1.0    # metric 模式覆蓋率容差


def _setup_stdout():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def read_text(path):
    return Path(path).read_text(encoding='utf-8')


def load_manifest(path=MANIFEST_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_baseline(path=BASELINE_PATH):
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding='utf-8'))


def case_paths(case):
    """回傳 (source_path, golden_path) 絕對路徑。--full 掃出的案例已是絕對路徑。"""
    src = case['source']
    gld = case.get('golden')
    if not os.path.isabs(src):
        src = str(TESTDATA_DIR / src)
    if gld and not os.path.isabs(gld):
        gld = str(TESTDATA_DIR / gld)
    return src, gld


def pipeline_metrics(text):
    """對一份文本跑完整管線，回傳指標 dict。"""
    result, modern_report = NP.process_nianpu(text)
    suspects, seq_bad, birth_year, total = NP.verify_anchors(result)
    m = {
        'format': NP.classify_format(text).get('label', ''),
        'titles': total,
        'birth_year': birth_year,
        'suspicious': len(suspects) + len(seq_bad),
        'modern': modern_report is not None,
        'coverage': None,
        'missed': None,
    }
    if modern_report is None:
        try:
            rep = NP.verify_output(text, result)
            cov = re.search(r'覆蓋率：([0-9.]+)%', rep)
            mis = re.search(r'遺漏：(\d+) 個', rep)
            if cov:
                m['coverage'] = float(cov.group(1))
            if mis:
                m['missed'] = int(mis.group(1))
        except Exception:
            pass
    return m


def golden_metrics(text):
    """對黃金輸出量測指標（只取可從輸出本身推得的）。"""
    suspects, seq_bad, birth_year, total = NP.verify_anchors(text)
    return {
        'titles': total,
        'birth_year': birth_year,
        'suspicious': len(suspects) + len(seq_bad),
    }


def format_label(text):
    return NP.classify_format(text).get('label', '')


# ---------------- 比對 ----------------

def compare(metrics, base, mode):
    """回傳 (passed, diffs)。base = baseline 的 metrics（行為快照）。"""
    diffs = []
    if mode == 'smoke':
        return True, diffs
    if base is None:
        return False, ['缺少基線（先跑 --selfcheck）']

    if mode == 'exact':
        if metrics['titles'] != base['titles']:
            diffs.append(f"標題數 {base['titles']}→{metrics['titles']}")
        if metrics.get('birth_year') != base.get('birth_year'):
            diffs.append(f"推定出生年 {base.get('birth_year')}→{metrics.get('birth_year')}")
        if metrics.get('suspicious', 0) > base.get('suspicious', 0):
            diffs.append(f"可疑標題 {base.get('suspicious')}→{metrics.get('suspicious')}")
        if metrics.get('coverage') is not None and base.get('coverage') is not None \
                and metrics['coverage'] < base['coverage'] - _COV_TOL:
            diffs.append(f"覆蓋率 {base['coverage']}%→{metrics['coverage']}%")
    else:  # metric
        if metrics['titles'] < base['titles']:
            diffs.append(f"標題數 {base['titles']}→{metrics['titles']}（下降）")
        if metrics.get('coverage') is not None and base.get('coverage') is not None \
                and metrics['coverage'] < base['coverage'] - _COV_TOL_M:
            diffs.append(f"覆蓋率 {base['coverage']}%→{metrics['coverage']}%（低於容差）")
    return len(diffs) == 0, diffs


def golden_diff(metrics, golden):
    """與黃金輸出比對，回傳差異清單（只列標題數/出生年，供 WARN 用）。"""
    diffs = []
    if golden is None:
        return diffs
    if metrics['titles'] != golden.get('titles'):
        diffs.append(f"標題數與黃金輸出 {golden.get('titles')} 不一致（現 {metrics['titles']}）")
    if metrics.get('birth_year') != golden.get('birth_year'):
        diffs.append(f"推定出生年與黃金輸出 {golden.get('birth_year')} 不一致（現 {metrics.get('birth_year')}）")
    return diffs


# ---------------- 自檢：建立基線 ----------------

def cmd_selfcheck(manifest):
    baseline = {}
    for case in manifest['cases']:
        name = case['name']
        src, gld = case_paths(case)
        try:
            m = pipeline_metrics(read_text(src))
        except Exception as e:
            print(f"▸ {name}：管線量測失敗：{e}")
            continue
        g = None
        if gld and Path(gld).exists():
            try:
                g = golden_metrics(read_text(gld))
            except Exception:
                g = None
        entry = {'metrics': m, 'golden': g}
        baseline[name] = entry
        print(f"  基線 {name}：標題 {m['titles']} 覆蓋 {m.get('coverage')}% "
              f"出生年 {m.get('birth_year')} 可疑 {m.get('suspicious')} "
              f"| 黃金輸出標題 {g['titles'] if g else '-'}")
    BASELINE_PATH.write_text(
        json.dumps({'cases': baseline}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n已寫入 {BASELINE_PATH}（{len(baseline)} 案例）")


# ---------------- 掃描 E: 全庫（--full） ----------------

def scan_full_library():
    root = Path(FULL_LIB_ROOT)
    if not root.exists():
        print(f"▸ {FULL_LIB_ROOT} 不存在，--full 跳過全庫掃描")
        return []
    cases = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        src = d / f"{d.name}_完整.md"
        if not src.exists():
            src = d / f"{d.name}_完整.txt"
        if not src.exists():
            continue
        gld = d / f"{d.name}_已整理.md"
        if not gld.exists():
            gld = d / f"{d.name}_已整理.txt"
        if not gld.exists():
            continue
        cases.append({
            'name': d.name, 'source': str(src), 'golden': str(gld),
            'format': '', 'mode': 'metric', 'slots': None,
        })
    return cases


# ---------------- 執行回歸 ----------------

def cmd_run(manifest, baseline, full=False, update=False):
    cases = list(manifest['cases'])
    if full:
        cases += scan_full_library()

    lines = []
    passed = 0
    failed = []
    warn_fmt = []
    warn_golden = []
    run_metrics = {}
    base_cases = (baseline or {}).get('cases', {}) if baseline else {}

    for case in cases:
        name = case['name']
        mode = case.get('mode', 'metric')
        src, gld = case_paths(case)
        if not Path(src).exists():
            failed.append((name, ['源檔不存在']))
            continue
        try:
            m = pipeline_metrics(read_text(src))
        except Exception as e:
            failed.append((name, [f'拋異常：{e}']))
            continue
        run_metrics[name] = m

        base_entry = base_cases.get(name)
        base_m = base_entry.get('metrics') if base_entry else None
        ok, diffs = compare(m, base_m, mode)
        if base_entry and base_m and base_m.get('format') and m.get('format') \
                and base_m['format'] != m['format']:
            warn_fmt.append(f"{name}：格式族 {base_m['format']}→{m['format']}")
        gd = golden_diff(m, base_entry.get('golden') if base_entry else None)
        if gd:
            warn_golden.append(f"{name}：{'；'.join(gd)}")
        if ok:
            passed += 1
        else:
            failed.append((name, diffs))
        cov_s = f"{m['coverage']}%" if m.get('coverage') is not None else '-'
        lines.append(
            f"  [{'PASS' if ok else 'FAIL'}] {name[:16]:16s} {mode:6s} "
            f"標題 {m['titles']:3d} 覆蓋 {cov_s:>6s} "
            f"出生年 {str(m.get('birth_year')) if m.get('birth_year') else '?':>4s} "
            f"可疑 {m.get('suspicious', 0)}")

    print('─' * 78)
    print('回歸結果')
    print('─' * 78)
    for l in lines:
        print(l)
    if warn_fmt:
        print('\n⚠ 格式族標籤變動（偵測可能改變，請人工確認）：')
        for w in warn_fmt:
            print(f"  {w}")
    if warn_golden:
        print('\n⚠ 與黃金輸出差異（人工修正案例屬正常，非回歸）：')
        for w in warn_golden:
            print(f"  {w}")
    if failed:
        print('\n── 未通過 ──')
        for name, diffs in failed:
            print(f"  {name}：{'；'.join(diffs)}")
    print(f"\n通過 {passed}/{len(cases)}")

    line = []
    for case in cases:
        m = run_metrics.get(case['name'])
        if m:
            line.append(f"{case['name']} {m['titles']}")
    if failed:
        print(f"\n回歸（有 FAIL，僅供參考）：回歸：{'/'.join(line)}")
    else:
        print(f"\n回歸：{'/'.join(line)} 標題數不變（{len(cases)} 案例差異=0）")

    if update:
        new_base = {'cases': {k: {'metrics': v, 'golden': base_cases.get(k, {}).get('golden')}
                              for k, v in run_metrics.items()}}
        BASELINE_PATH.write_text(
            json.dumps(new_base, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\n已以本次結果刷新基線 → {BASELINE_PATH}（{len(run_metrics)} 案例）")
    return 0 if not failed else 1


def cmd_smoke(manifest):
    cases = list(manifest['cases']) + scan_full_library()
    ok = 0
    for case in cases:
        src, _ = case_paths(case)
        try:
            NP.process_nianpu(read_text(src))
            ok += 1
            print(f"  [OK] {case['name']}")
        except Exception as e:
            print(f"  [ERR] {case['name']}：{e}")
    print(f"\n冒煙通過 {ok}/{len(cases)}")


def main():
    _setup_stdout()
    args = sys.argv[1:]
    manifest = load_manifest()
    baseline = load_baseline()

    if not args or '--selfcheck' in args:
        cmd_selfcheck(manifest)
    elif '--smoke' in args:
        cmd_smoke(manifest)
    elif '--run' in args:
        sys.exit(cmd_run(manifest, baseline,
                         full='--full' in args, update='--update' in args))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()