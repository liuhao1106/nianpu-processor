# -*- coding: utf-8 -*-
"""年譜覆蓋率測試腳本（以人物生卒年為錨）+ 已整理文件的三錨點檢查。

產出「測試報告」所需的標題數/覆蓋率/遺漏/可疑/序列斷裂/推定生卒年等數據。

用法：
    python tools/nianpu_coverage.py <年譜資料目錄> [輸出JSON路徑]

- <年譜資料目錄>：含各年譜資料夾的根目錄（本機範例 D:\workbuddy project\download）
- 輸出JSON：預設寫到 docs/nianpu_report_data.json（已 gitignore，供重跑對照）

方法：
- 分子：已整理輸出標題覆蓋到的不同公元年份（落於 [出生, 年譜末年] 區間）
- 分母：源文本中落於該區間的不同年份條目（以 干支/年齡/年號 一致性判斷，
  剔除注文/引文/世系/附錄）
- 標題/可疑/序列斷裂/推定出生年：直接對已整理文件跑 verify_anchors
- 純只讀：不寫檔、不呼叫 self_learn。
"""
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
import nianpu_processor as np

CASES = [
    ("羅忠節公年譜", r"羅忠節公年譜\羅忠節公年譜_完整.txt", r"羅忠節公年譜\羅忠節公年譜_整理.md"),
    ("警石府君年譜", r"警石府君年譜\警石府君年譜_完整.txt", r"警石府君年譜\警石府君年譜_已整理.md"),
    ("文貞公年譜", r"文貞公年譜\文貞公年譜_完整.txt", r"文貞公年譜\文貞公年譜_已整理.md"),
    ("涇舟老人洪琴西先生年譜", r"涇舟老人洪琴西先生年譜\涇舟老人洪琴西先生年譜_完整.txt", r"涇舟老人洪琴西先生年譜\涇舟老人洪琴西先生年譜_已整理.md"),
    ("殷譜經侍郎自定年譜", r"殷譜經侍郎自定年譜\殷譜經侍郎自定年譜_完整.txt", r"殷譜經侍郎自定年譜\殷譜經侍郎自定年譜_已整理.md"),
    ("項蘭生自訂年譜", r"项兰生自订年谱_整理\项兰生自订年谱_全文.md", r"项兰生自订年谱_整理\项兰生自订年谱_全文_已整理.md"),
    ("顧亭林先生年譜一卷", r"顧亭林先生年譜\顧亭林先生年譜_完整.txt", r"顧亭林先生年譜\顧亭林先生年譜_整理版.md"),
    ("施愚山先生年譜", r"施愚山先生年譜\施愚山先生年譜_完整.txt", r"施愚山先生年譜\施愚山先生年譜_已整理.md"),
    ("萬清軒先生年譜", r"万清轩年谱\萬清軒先生年譜_完整.txt", r"万清轩年谱\萬清軒先生年譜_整理_v2.md"),
    ("張清恪公年譜", r"張清恪公年譜\張清恪公年譜_完整.txt", r"張清恪公年譜\張清恪公年譜_年份切分.md"),
    ("沈端恪公年譜", r"沈端恪公年譜\沈端恪公年譜_完整.txt", r"沈端恪公年譜\沈端恪公年譜_完整_已整理.md"),
    ("澄懷主人自訂年譜", r"澄懷主人自訂年譜\澄懷主人自訂年譜_完整.txt", r"澄懷主人自訂年譜\澄懷主人自訂年譜_完整_已整理.md"),
    ("王船山先生年譜", r"王船山先生年譜\王船山先生年譜_完整.txt", r"王船山先生年譜\王船山先生年譜_已整理.md"),
    ("方柏堂先生譜系略", r"方柏堂先生譜系略\方柏堂先生譜系略_完整.txt", r"方柏堂先生譜系略\方柏堂先生譜系略_完整_已切分.md"),
    ("鼎甫府君年譜", r"鼎甫府君年譜\鼎甫府君年譜_完整.txt", r"鼎甫府君年譜\鼎甫府君年譜_完整_已整理.md"),
    ("吳竹如先生年譜", r"吳竹如先生年譜\吳竹如先生年譜_完整.txt", r"吳竹如先生年譜\吳竹如先生年譜_已整理.md"),
    ("先考松生府君年譜", r"先考松生府君年譜\先考松生府君年譜_完整.txt", r"先考松生府君年譜\先考松生府君年譜_已整理.md"),
    ("魏貞庵先生年譜", r"魏貞庵先生年譜\魏貞庵先生年譜_完整.txt", r"魏貞庵先生年譜\魏貞庵先生年譜_已整理.md"),
    ("小酉腴山館主人自著年譜", r"小酉腴山馆主人自著年谱\小酉腴山館主人自著年譜_完整.txt", r"小酉腴山馆主人自著年谱\小酉腴山館主人自著年譜_已整理.md"),
    ("桐溪達叟自編年譜", r"桐溪達叟自編年譜\桐溪達叟自編年譜_完整.txt", r"桐溪達叟自編年譜\桐溪達叟自編年譜_整理版.md"),
    ("黃黎洲先生年譜", r"黃黎洲先生年譜\黃黎洲先生年譜_完整.txt", r"黃黎洲先生年譜\黃黎洲先生年譜_已整理.md"),
    ("紫陽文公先生年譜", r"紫陽文公先生年譜\紫陽文公先生年譜_完整.txt", r"紫陽文公先生年譜\紫陽文公先生年譜_已整理.md"),
    ("唐一庵先生年譜", r"唐一庵先生年譜\唐一庵先生年譜_完整.txt", r"唐一庵先生年譜\唐一庵先生年譜_已整理.md"),
]
# 無年齡格式（純年份/純干支）等 anchor 多數決推不出出生年者，手動補
MANUAL_BIRTH = {"紫陽文公先生年譜": 1130, "魏貞庵先生年譜": 1616}
# 無年齡純年份格式：卒年無法由年齡推出，且源文本附録/追封條目會把 D 推遠，手動指定卒年
MANUAL_DEATH = {"紫陽文公先生年譜": 1200, "方柏堂先生譜系略": 1888}

DIG = "零一二三四五六七八九"


def path(base, rel):
    return os.path.join(base, *rel.split("\\"))


def int_to_cn(n):
    if n <= 0:
        return []
    if n < 10:
        return [DIG[n]]
    if n == 10:
        return ["十"]
    if n < 20:
        one = DIG[n % 10]
        return [f"十{one}", f"十有{one}"]
    if n < 100:
        tens, ones = n // 10, n % 10
        tc = ["", "", "二十", "三十", "四十", "五十", "六十", "七十", "八十", "九十"]
        t = tc[tens]
        talt = "廿" if tens == 2 else ("卅" if tens == 3 else t)
        if ones == 0:
            return [t, talt] if talt != t else [t]
        base = t + DIG[ones]
        out = [base]
        if talt != t:
            out.append(talt + DIG[ones])
        return out
    # ≥100：按位（公元 一八七三=1873 格式）
    return ["".join(DIG[int(c)] for c in str(n))]


def build_gz_variants():
    """每個 60 週期索引 → 該干支的全部字形變體（已/己/巳、戍/戊/戌）"""
    vs = {}
    for i in range(60):
        pairs = set()
        for s in np._TG:
            if np._STEM_IDX.get(s) == i % 10:
                for b in np._DZ:
                    if np._BRANCH_IDX.get(b) == i % 12:
                        pairs.add(s + b)
        vs[i] = sorted(pairs)
    return vs


GZ_VAR = build_gz_variants()
GZ_RE = {i: "(?:" + "|".join(re.escape(g) for g in vs) + ")" for i, vs in GZ_VAR.items()}


def read(path_):
    raw = open(path_, "rb").read()
    for enc in ("utf-8", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def clean_source(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = np._apply_ocr_fixes(text)
    text = np._normalize_reign_variants(text)
    text = re.sub(r"〔[^〕]*〕", "", text)   # 註文/引文
    return text


def resolve_heading_year(h, B, prev_year=None):
    """依 年齡→(年號∧干支一致)→唯一干支→年號→就近干支 推標題的公元年。"""
    info = np._parse_heading_anchors(h)
    age, gz_idx, reign_ad = info["age_int"], info["ganzhi_idx"], info["reign_ad"]
    if age is not None:
        return B + age - 1
    cands = [y for y in range(B - 1, B + 111) if (y - 4) % 60 == gz_idx] if gz_idx is not None else []
    if reign_ad is not None:
        if not cands or reign_ad in cands:
            return reign_ad
        if len(cands) == 1:
            return cands[0]
        return reign_ad
    if cands:
        if len(cands) == 1:
            return cands[0]
        if prev_year:
            return min(cands, key=lambda c: abs(c - prev_year))
        return cands[0]
    return None


_DIGIT_BEFORE = r"(?<![一二三四五六七八九十百零〇廿卅和])"
_AGE_END = r"(?:[嵗歲歳𡻕岁]|[。，,、；;\n]|$)"


def age_consistent(Y, B, src):
    """源文本中 干支 Y（或年號+年序）附近有與壽命一致的 N 嵗（N = Y−B+1）。
    容許 gap 內跨一個句號（「…卒。七十歲」）或一個換行（跨行格式「康熙十六年\n公七歲」）；
    年齡前加數字界 lookbehind，避免「六十三嵗」的「三」被當作年齡 3 誤配。"""
    gzr = GZ_RE[(Y - 4) % 60]
    age_cands = sorted((re.escape(a) for a in int_to_cn(Y - B + 1)), key=len, reverse=True)
    age_alt = "|".join(age_cands)
    gap = r"(?:[^。\n]{0,25}?(?:。|\n)[^。\n]{0,20}?|[^。\n]{0,40}?)"
    pre = r"(?:公|先生|府君)?(?:年)?"
    # A：干支 + 年齡
    patA = gzr + gap + pre + _DIGIT_BEFORE + "(" + age_alt + ")" + _AGE_END
    if re.search(patA, src):
        return True
    # B：年號+年序年 + 年齡（無干支的跨行格式，如 康熙十六年\n公七歲）
    for reign, start in np.REIGN_START_YEARS.items():
        n = Y - start + 1
        if 1 <= n <= 60:
            for yr in int_to_cn(n):
                patB = r"(?:" + reign + r")" + yr + r"年" + gap + pre + _DIGIT_BEFORE + "(" + age_alt + ")" + _AGE_END
                if re.search(patB, src):
                    return True
    return False


def source_has_year(Y, B, src):
    """源文本是否以「干支+年齡」或「年號+年+干支」或「公元」方式記錄了年份 Y。"""
    if age_consistent(Y, B, src):
        return True
    gzr = GZ_RE[(Y - 4) % 60]
    for reign, start in np.REIGN_START_YEARS.items():
        n = Y - start + 1
        if 1 <= n <= 60:
            for yr in int_to_cn(n):
                pat = r"(?:" + reign + r")" + yr + r"年[，,、。]?" + gzr
                if re.search(pat, src):
                    return True
                pat2 = gzr + r"[，,、。]?(?:" + reign + r")" + yr + r"年"
                if re.search(pat2, src):
                    return True
    for ad in int_to_cn(Y):
        if re.search(r"公元" + ad + r"年", src):
            return True
    return False


def derive_birth_from_ages(headings):
    """無年號標注的檔案：用「干支+年齡」多數決推出生年。"""
    pairs = []
    for h in headings:
        info = np._parse_heading_anchors(h)
        if info["age_int"] is not None and info["ganzhi_idx"] is not None:
            pairs.append((info["age_int"], info["ganzhi_idx"]))
    if not pairs:
        return None
    best, best_n = None, -1
    for B in range(1400, 1951):
        n = sum(1 for age, gz in pairs if (B + age - 1 - 4) % 60 == gz)
        if n > best_n:
            best, best_n = B, n
    return best


def analyze(base, label, src_rel, out_rel):
    src = clean_source(read(path(base, src_rel)))
    out = read(path(base, out_rel))
    suspects, seq_bad, birth_anchor, total_all = np.verify_anchors(out)

    headings = [l[4:].strip() for l in out.split('\n') if l.startswith('### ')]
    B = birth_anchor or MANUAL_BIRTH.get(label) or derive_birth_from_ages(headings)
    if B is None:
        for h in headings:
            info = np._parse_heading_anchors(h)
            if info["ganzhi_idx"] is not None:
                c = [y for y in range(1600, 2000) if (y - 4) % 60 == info["ganzhi_idx"]]
                if len(c) == 1:
                    B = c[0]
                    break
            if info["reign_ad"] is not None:
                B = info["reign_ad"]
                break

    years = {}
    prev_y = None
    year_titles = 0
    for h in headings:
        if B is None:
            break
        y = resolve_heading_year(h, B, prev_y)
        if y is not None and B - 1 <= y <= B + 110:
            year_titles += 1
            years.setdefault(y, 0)
            years[y] += 1
            prev_y = y
    covered = set(years)

    if B is None:
        return {"label": label, "titles": 0, "all_headings": len(headings), "coverage": 0.0,
                "covered": 0, "expected": 0, "missed_years": [], "birth": None, "death": None,
                "suspects": len(suspects), "seq_bad": len(seq_bad), "birth_anchor": None}

    # 卒年 = 最後一個「年齡一致」的年份（真條目幾乎都有年齡；卷首/附録追述多無）
    age_yrs = {y for y in range(B, B + 111) if age_consistent(y, B, src)}
    D = (MANUAL_DEATH.get(label)
         or (max(age_yrs) if age_yrs else (max(covered) if covered else B)))
    D = min(D, B + 110)

    expected = {y for y in range(B, D + 1) if source_has_year(y, B, src)}
    expected |= covered
    missed = sorted(expected - covered)
    cov = round(len(covered) / len(expected) * 100, 1) if expected else 0.0

    return {
        "label": label, "titles": year_titles, "all_headings": len(headings),
        "coverage": cov, "covered": len(covered), "expected": len(expected),
        "missed_years": missed, "birth": B, "death": D,
        "suspects": len(suspects), "seq_bad": len(seq_bad), "birth_anchor": birth_anchor,
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    base = sys.argv[1]
    out_json = sys.argv[2] if len(sys.argv) >= 3 else os.path.join(REPO_ROOT, "docs", "nianpu_report_data.json")
    np.apply_learnings()
    results = []
    for label, src_rel, out_rel in CASES:
        r = analyze(base, label, src_rel, out_rel)
        results.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("DONE ->", out_json)


if __name__ == "__main__":
    main()
