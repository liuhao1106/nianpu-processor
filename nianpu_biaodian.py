#!/usr/bin/env python3
"""
年譜標點助手 — Nianpu Biaodian Helper
======================================
把「已整理但無標點」的年譜 markdown（含 ### 年份標題與 **季節** 標記）交給 LLM 加標點。

工作流（標點由 LLM 執行，本腳本只負責切分／合併／字符保全校驗）：

  1. python nianpu_biaodian.py --chunk <已整理.md>          # 按年份塊切分 → <名>_pun/pun_01.md, pun_02.md …
  2. LLM 逐塊加標點（依 SKILL.md 與 docs/標點規則.md；可人工審校每塊）
  3. python nianpu_biaodian.py --merge  <已整理.md>          # 合併標點塊 → <名>_定稿.md（附帶自動 verify）
  4. python nianpu_biaodian.py --verify <已整理.md> <定稿.md>  # 去標點後逐字比對，報丢失/增字/錯序

「字符保全校驗」：把定稿去標點／去空白後與已整理逐字比對，任何丢字、增字、改字、錯序都會被報出，
確保 LLM 加標點的過程不改動原文。若標點時順手改了 OCR 誤字（如 一十→二十），會列為「內容差異」供人工確認。

選項：
  --size  <字數>   每塊目標字數（預設 2500；年份塊不跨塊拆開）
  --dir   <目錄>   標點塊目錄（預設 <已整理檔同名>_pun/）
  --out   <檔案>   定稿輸出路徑（預設 <已整理名>_定稿.md）
  --max   <N>      verify 最多報出的差異數（預設 20）
"""

import re, sys, os, glob
from pathlib import Path
import difflib

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def read_text(path):
    data = Path(path).read_bytes()
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'big5'):
        try:
            return data.decode(enc).replace('\r\n', '\n').replace('\r', '\n')
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')


def parse_sections(text):
    """依 ### 標題切成 sections；回傳 (front_matter_lines, [(heading, [body_lines]), ...])。"""
    lines = text.split('\n')
    front = []
    sections = []
    cur_heading = None
    cur_body = []
    for ln in lines:
        if ln.startswith('### '):
            if cur_heading is not None:
                sections.append((cur_heading, cur_body))
            cur_heading = ln
            cur_body = []
        elif cur_heading is None:
            front.append(ln)
        else:
            cur_body.append(ln)
    if cur_heading is not None:
        sections.append((cur_heading, cur_body))
    return front, sections


# ======== 切分 ========
def cmd_chunk(inp, size, outdir):
    text = read_text(inp)
    front, sections = parse_sections(text)
    if not sections:
        print(f"錯誤：找不到任何 ### 年份標題，{inp} 不是已整理格式？")
        sys.exit(1)

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for old in sorted(glob.glob(str(outdir / 'pun_*.md'))):
        os.remove(old)

    chunks = []
    cur = list(front)  # 卷首隨第一塊
    cur_len = sum(len(l) for l in front)
    cur_has_block = False
    for heading, body in sections:
        block = [heading] + body
        block_len = sum(len(l) for l in block)
        # 當前塊已含至少一個年份塊、再加就超限 → 收束（年份塊不拆，故單塊超限也整塊入下一塊）
        if cur_has_block and cur_len + block_len > size:
            chunks.append(cur)
            cur = []
            cur_len = 0
            cur_has_block = False
        cur.extend(block)
        cur_len += block_len
        cur_has_block = True
    if cur:
        chunks.append(cur)

    paths = []
    for i, chunk in enumerate(chunks, 1):
        p = outdir / f'pun_{i:02d}.md'
        p.write_text('\n'.join(chunk) + ('\n' if chunk else ''), encoding='utf-8')
        paths.append(p)
    total = sum(len(l) for l in text.split('\n'))
    print(f"讀取：{inp}（{len(sections)} 個年份標題，約 {total} 字）")
    print(f"切分：{len(chunks)} 塊 → {outdir}/")
    for i, p in enumerate(paths, 1):
        print(f"  {p.name}（{p.stat().st_size} bytes）")
    print("\n接下來：請 LLM 依 docs/標點規則.md 逐塊加標點（可直接編輯每塊檔案）。")


# ======== 合併 ========
def cmd_merge(inp, outdir, out):
    outdir = Path(outdir)
    puns = sorted(glob.glob(str(outdir / 'pun_*.md')),
                  key=lambda p: int(re.search(r'pun_(\d+)', p).group(1)))
    if not puns:
        print(f"錯誤：{outdir}/ 下沒有 pun_*.md 標點塊。")
        sys.exit(1)
    parts = []
    for p in puns:
        t = read_text(p).strip('\n')
        t = re.sub(r'<!--.*?-->', '', t, flags=re.S)  # 剥除块尾「改字記錄」等 HTML 注释，避免泄漏进定稿
        t = t.strip('\n')
        if t:
            parts.append(t)
    merged = '\n\n'.join(parts) + '\n'
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(merged, encoding='utf-8')
    print(f"合併：{len(puns)} 塊 → {out}")
    print()
    print_verify(read_text(inp), merged, inp, out)


# ======== 標點（校驗用） ========
# 加標點過程唯一應做的改動是插入標點；以下字元在比對兩側對稱剝除。
STRIP = set('。，、；：？！「」『』《》〈〉·…—–－·．‘’“”"\'()（）#*[]【】{}`~^=<>')
PUNCT_HALFWIDTH = set(',.?;:!')

def clean(s):
    return ''.join(c for c in s if c not in STRIP and not c.isspace())


def print_verify(orig, final, orig_path, final_path):
    """去標點後逐字比對。回傳 (differences, extra_warn)。"""
    issues = 0

    # 1) 年份標題必須逐字一致（LLM 不得改動 ### 行）
    o_h = [l for l in orig.split('\n') if l.startswith('### ')]
    f_h = [l for l in final.split('\n') if l.startswith('### ')]
    if o_h != f_h:
        issues += 1
        print("⚠ 年份標題不一致（標點時不應改動 ### 標題）：")
        for x, y in zip(o_h, f_h):
            if x != y:
                print(f"  原：{x}")
                print(f"  現：{y}")
        if len(o_h) != len(f_h):
            print(f"  （原 {len(o_h)} 條 / 現 {len(f_h)} 條）")

    # 2) 半形標點警告
    half = sorted({c for c in final if c in PUNCT_HALFWIDTH and c in STRIP})
    if half:
        issues += 1
        print(f"⚠ 定稿含有半形標點 {half}，應為全形（，。？！；：）")

    # 3) 去標點逐字比對
    c_o, c_f = clean(orig), clean(final)
    if c_o == c_f:
        print(f"✓ 字符保全校驗通過：去標點後與 {Path(orig_path).name} 完全一致（{len(c_o)} 字），無丢字/增字/改字。")
        return issues
    issues += 1
    print(f"⚠ 字符保全有差異：原 {len(c_o)} 字 / 現 {len(c_f)} 字，以下為去標點後仍不一致處：")
    sm = difflib.SequenceMatcher(None, c_o, c_f)
    shown = 0
    maxshow = 20
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        shown += 1
        if shown > maxshow:
            print(f"  …尚有更多（共 {len([g for g in sm.get_opcodes() if g[0] != 'equal'])} 處）")
            break
        ctx = 22
        o_ctx = c_o[max(0, i1 - ctx):i2 + ctx]
        f_ctx = c_f[max(0, j1 - ctx):j2 + ctx]
        print(f"  第{shown}處 [{tag}] 原偏移{i1}-{i2} / 現偏移{j1}-{j2}")
        print(f"    原：…{o_ctx}…")
        print(f"    現：…{f_ctx}…")
    return issues


def cmd_verify(orig_path, final_path):
    print_verify(read_text(orig_path), read_text(final_path), orig_path, final_path)


# ======== 命令列 ========
def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(1)

    def opt(name, default=None):
        nonlocal argv
        if name in argv:
            i = argv.index(name)
            v = argv[i + 1] if i + 1 < len(argv) else default
            argv = argv[:i] + argv[i + 2:]
            return v
        return default

    mode = argv[0]
    argv = argv[1:]
    size = int(opt('--size', '2500'))
    outdir = opt('--dir')
    out = opt('--out')
    maxn = int(opt('--max', '20'))

    if mode == '--chunk':
        if not argv:
            print("用法：nianpu_biaodian.py --chunk <已整理.md> [--size 2500] [--dir <目錄>]")
            sys.exit(1)
        inp = Path(argv[0])
        if not inp.exists():
            print(f"錯誤：找不到檔案 {inp}"); sys.exit(1)
        d = outdir or (inp.parent / (inp.stem + '_pun'))
        cmd_chunk(inp, size, d)
    elif mode == '--merge':
        if not argv:
            print("用法：nianpu_biaodian.py --merge <已整理.md> [--dir <標點塊目錄>] [--out <定稿.md>]")
            sys.exit(1)
        inp = Path(argv[0])
        if not inp.exists():
            print(f"錯誤：找不到檔案 {inp}"); sys.exit(1)
        d = outdir or (inp.parent / (inp.stem + '_pun'))
        o = out or (inp.parent / (inp.stem.replace('_已整理', '') + '_定稿.md'))
        cmd_merge(inp, d, o)
    elif mode == '--verify':
        if len(argv) < 2:
            print("用法：nianpu_biaodian.py --verify <已整理.md> <定稿.md>")
            sys.exit(1)
        cmd_verify(argv[0], argv[1])
    else:
        print(f"未知模式：{mode}")
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
