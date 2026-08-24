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
  full    指標全比對（標題數/出生年/可疑數/覆蓋率）＋全文內容鎖定：歸一化
          （剔標點/空白/標記、異體歸一）後正文逐字與黃金一致。零假陽性——
          黃金含人工修正的既有殘差存入基線，僅「新增殘差」才報 FAIL，抓到
          「輸出變了但標題數/覆蓋率不變」的 bug。路線圖 #4（黃金語料）半步交付。
  exact   行為快照指標全比對（標題數/出生年/可疑數/覆蓋率）＋標題數須與黃金輸出一致
  metric  行為快照容差比對（標題數不降、覆蓋率不低於基線-容差、不崩潰）
  smoke   只驗證跑通不炸

用法：
  python tools/regression.py --selfcheck       # 建立基線（行為快照＋黃金指標）
  python tools/regression.py --run             # 重跑管線 vs 基線，出 PASS/FAIL 表＋回歸行
  python tools/regression.py --run --full      # 另掃描 E: 識典數據 全部案例（不限 testdata）
  python tools/regression.py --run --update    # 重跑後以本次結果刷新基線（人工審核後再用）
  python tools/regression.py --smoke           # 只驗證不崩潰（快速冒煙）
  python tools/regression.py --verify-learnings  # 學習質檢閘門：pending 條目逐條臨時套用→
                                                 # 跑回歸→PASS 轉 verified（FAIL 維持 pending）

約定：
  * 回歸對象是「基礎規則集」——直接呼叫 process_nianpu，不走 main() 的
    apply_learnings()，因此不受 learnings.json 經驗累積影響，結果可跨機複現。
  * 標點（nianpu_biaodian）與仲裁（nianpu_arbitrate）屬 LLM-in-loop 步驟，
    不在此回歸範圍（其 verify 已做字符保全校驗）。
  * 指標式比對（非全文 diff）不抓「改了輸出但指標不變」的 bug，是刻意取捨：
    大量黃金輸出含人工修正，全文 diff 必然假陽性。
"""

import difflib
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


def pipeline_metrics(text, with_text=False):
    """對一份文本跑完整管線，回傳指標 dict（with_text=True 另回傳處理結果）。"""
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
    if with_text:
        return m, result
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


# ---------------- 全文內容鎖定（full 模式） ----------------

# 歸一化層：剔除全文比對中的「良性雜訊」——標點、空白、markdown 標記，
# 並把異體字（OCR 寫法的熈/戍等）歸一到規範形。目的：消除黃金輸出因
# biaodian 標點與異體字造成的假陽性，讓「正文內容」真正可比。
_FULL_PUNCT = re.compile(
    r'[\s。，、；：？！「」『』（）()〔〕【】<>《》〈〉—…·,.;:!?"\'`【】]+')
_FULL_MARK = re.compile(r'[*#]+')
_FULL_VAR = {'熈': '熙', '戍': '戌'}   # 異體 → 規範（兩側同歸一，故可對稱比對）


def normalize_content(t):
    for a, b in _FULL_VAR.items():
        t = t.replace(a, b)
    t = _FULL_MARK.sub('', t)
    return _FULL_PUNCT.sub('', t)


def content_residual(result_text, golden_text):
    """歸一化後「管線輸出 vs 黃金」的內容殘差（opcode 序列）。

    零殘差 = 全文內容鎖定（正文逐字一致）。非零 = 黃金含人工修正
    （如正德三→十三年、補「府君生」），屬既有、可容忍的殘差。
    """
    a = normalize_content(result_text)
    b = normalize_content(golden_text)
    if a == b:
        return []
    return [[t, a[i1:i2], b[j1:j2]]
            for t, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes()
            if t != 'equal']


def residual_brief(residual, limit=4):
    out = []
    for t, old, new in residual[:limit]:
        if t == 'insert':
            out.append(f'+{new!r}')
        elif t == 'delete':
            out.append(f'-{old!r}')
        else:
            out.append(f'{old!r}→{new!r}')
    if len(residual) > limit:
        out.append(f'…共{len(residual)}處')
    return '，'.join(out)


# ---------------- 比對 ----------------

def compare(metrics, base, mode):
    """回傳 (passed, diffs)。base = baseline 的 metrics（行為快照）。"""
    diffs = []
    if mode == 'smoke':
        return True, diffs
    if base is None:
        return False, ['缺少基線（先跑 --selfcheck）']

    if mode == 'exact' or mode == 'full':
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


def case_content_residual(case):
    """求某案例「管線輸出 vs 黃金」的歸一化內容殘差；無黃金或失敗回傳 None。"""
    src, gld = case_paths(case)
    if not Path(gld).exists():
        return None
    result, _ = NP.process_nianpu(read_text(src))
    return content_residual(result, read_text(gld))


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
        if case.get('mode') == 'full':
            entry['content_residual'] = case_content_residual(case)
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

def evaluate_case(case, base_entry):
    """單案例 vs 基線（--run 與 --verify-learnings 共用的比對核心）。

    回傳 dict：{ok, diffs, m, residual, ran_full}。
    ok=None 表示源檔缺失/管線拋異常（diffs 帶原因，m=None）。
    ran_full=True 表示該案例為 full 模式且指標級已過（殘差已計算，
    可供 --update 存入基線——與舊行為一致：無黃金檔時 residual 為 None）。
    """
    mode = case.get('mode', 'metric')
    src, gld = case_paths(case)
    if not Path(src).exists():
        return {'ok': None, 'diffs': ['源檔不存在'], 'm': None,
                'residual': None, 'ran_full': False}
    text = read_text(src)
    try:
        if mode == 'full':
            m, result_text = pipeline_metrics(text, with_text=True)
        else:
            m = pipeline_metrics(text)
    except Exception as e:
        return {'ok': None, 'diffs': [f'拋異常：{e}'], 'm': None,
                'residual': None, 'ran_full': False}

    base_m = base_entry.get('metrics') if base_entry else None
    ok, diffs = compare(m, base_m, mode)

    # full 模式：全文內容鎖定——比對「本次內容殘差」與基線殘差。
    # 零假陽性：與基線殘差一致則 PASS（既有人工修正殘差不誤報）；
    # 出現基線未見的新殘差 → FAIL，抓到「輸出變了但指標不變」的 bug。
    residual = None
    ran_full = False
    if mode == 'full' and ok:
        ran_full = True
        if Path(gld).exists():
            residual = content_residual(result_text, read_text(gld))
        base_residual = base_entry.get('content_residual') if base_entry else None
        if base_residual is None:
            diffs.append('full 模式缺基線內容殘差（先 --update/--selfcheck 重建基線）')
            ok = False
        elif residual != base_residual:
            new = [r for r in (residual or []) if r not in (base_residual or [])]
            if not new:
                new = [r for r in (residual or [])]  # 保護性列出
            diffs.append(f'全文內容鎖定失守（新殘差：{residual_brief(new)}）')
            ok = False

    return {'ok': ok, 'diffs': diffs, 'm': m, 'residual': residual,
            'ran_full': ran_full}


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
    run_content = {}   # full 模式：case -> 本次內容殘差（供更新基線）

    for case in cases:
        name = case['name']
        mode = case.get('mode', 'metric')
        base_entry = base_cases.get(name)
        r = evaluate_case(case, base_entry)

        if r['ok'] is None:
            failed.append((name, r['diffs']))
            continue
        m = r['m']
        run_metrics[name] = m
        ok, diffs = r['ok'], r['diffs']

        if r['ran_full']:
            run_content[name] = r['residual']

        base_m = base_entry.get('metrics') if base_entry else None
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
        new_cases = {}
        for k, v in run_metrics.items():
            entry = {'metrics': v, 'golden': base_cases.get(k, {}).get('golden')}
            if k in run_content:
                entry['content_residual'] = run_content.get(k)
                name_entry = next((c for c in cases if c['name'] == k), None)
                if name_entry and name_entry.get('mode') != 'full':
                    entry.pop('content_residual', None)
            new_cases[k] = entry
        BASELINE_PATH.write_text(
            json.dumps({'cases': new_cases}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\n已以本次結果刷新基線 → {BASELINE_PATH}（{len(run_metrics)} 案例）")
    return 0 if not failed else 1


# ---------------- 質檢閘門：--verify-learnings ----------------

def cmd_verify_learnings(manifest, baseline):
    """學習質檢閘門（P0）：pending 學習條目逐條「臨時套用→跑回歸→PASS 轉正」。

    只收「回歸已驗證」的條目：self_learn 發現的新年號/前綴一律 status='pending'，
    apply_learnings 只應用 verified 條目。本命令對每條 pending：
      ①無操作條目（年號已在 REIGNS／前綴已在 EMPEROR_PREFIXES）直接轉正；
      ②活條目臨時套用（與 apply_learnings 同款原地變異）→ 跑全部回歸案例
        vs 基線 → PASS 轉正（status='verified'，寫檔前自動備份 .bak）；
        FAIL 維持 pending（不會被應用），並列出首個失敗案例與原因。
    回滾：python nianpu_processor.py --revert（回滾最近一次寫入）。
    """
    print('─' * 78)
    print('學習質檢閘門（--verify-learnings）：pending → 臨時套用 → 回歸驗證')
    print('─' * 78)

    base_cases = (baseline or {}).get('cases', {}) if baseline else {}
    if not base_cases:
        print('▸ 缺基線——先跑 python tools/regression.py --selfcheck 建立基線')
        return 1

    pend = NP.pending_learnings()
    reigns = dict(pend['reigns'])
    prefixes = dict(pend['prefixes'])
    if not reigns and not prefixes:
        print('▸ 無待驗證（pending）條目——所有可應用學習均已驗證。')
        return 0

    n_cases = len(manifest['cases'])
    verified_r, verified_p, rejected = [], [], []

    # ①無操作條目：套用不產生任何效果（已被基座涵蓋），直接轉正
    for r in sorted(reigns):
        if r in NP.REIGNS:
            verified_r.append(r)
            print(f"  [PASS] 年號「{r}」：無操作（已在 REIGNS）")
            del reigns[r]
    for p in sorted(prefixes):
        if any(p == ep for ep, _ in NP.EMPEROR_PREFIXES):
            verified_p.append(p)
            print(f"  [PASS] 前綴「{p}」：無操作（已在 EMPEROR_PREFIXES）")
            del prefixes[p]

    # ②活條目：逐條臨時套用 → 跑回歸（原地變異保證管線調用時可見）
    def _gate_failures():
        fails = []
        for case in manifest['cases']:
            r = evaluate_case(case, base_cases.get(case['name']))
            if r['ok'] is not True:
                fails.append((case['name'], r['diffs']))
        return fails

    reigns_snap = list(NP.REIGNS)
    prefixes_snap = list(NP.EMPEROR_PREFIXES)
    for r in sorted(reigns):
        NP.REIGNS.append(r)
        try:
            fails = _gate_failures()
        finally:
            NP.REIGNS[:] = reigns_snap
        if fails:
            name, diffs = fails[0]
            rejected.append(('年號', r, name, diffs))
            print(f"  [FAIL] 年號「{r}」：{name}——{diffs[0] if diffs else ''}")
        else:
            verified_r.append(r)
            print(f"  [PASS] 年號「{r}」：回歸 {n_cases}/{n_cases} 全過")
    for p in sorted(prefixes):
        info = prefixes[p]
        NP.EMPEROR_PREFIXES.insert(0, (p, info['reign']))
        try:
            fails = _gate_failures()
        finally:
            NP.EMPEROR_PREFIXES[:] = prefixes_snap
        if fails:
            name, diffs = fails[0]
            rejected.append(('前綴', p, name, diffs))
            print(f"  [FAIL] 前綴「{p}」→ {info['reign']}：{name}——{diffs[0] if diffs else ''}")
        else:
            verified_p.append(p)
            print(f"  [PASS] 前綴「{p}」→ {info['reign']}：回歸 {n_cases}/{n_cases} 全過")

    # ③持久化：PASS 轉正（mark_learnings_verified 保存前自動備份 .bak）
    if verified_r or verified_p:
        n = NP.mark_learnings_verified(verified_r, verified_p)
        print(f"\n▸ 已轉正 {n} 條（status='verified'，learnings.json 已更新；"
              f"回滾：python nianpu_processor.py --revert）")
    if rejected:
        print(f"▸ {len(rejected)} 條未通過回歸，維持 pending（不會被應用）：")
        for kind, name, case_name, diffs in rejected:
            print(f"  ✗ {kind}「{name}」→ 失敗案例 {case_name}："
                  f"{'；'.join(diffs[:2])}")
        print("  （疑為假陽性學習；可用 --record 反饋作廢，或人工核查後刪除該條）")
    else:
        print('▸ 全部通過。')
    return 0 if not rejected else 1


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
    elif '--verify-learnings' in args:
        sys.exit(cmd_verify_learnings(manifest, baseline))
    elif '--run' in args:
        sys.exit(cmd_run(manifest, baseline,
                         full='--full' in args, update='--update' in args))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()