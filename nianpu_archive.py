#!/usr/bin/env python3
"""
年譜歸檔助手 — Nianpu Archive Helper
=====================================
年譜整理定稿後，複製一份到「年譜整理本」資料夾（檔名統一為「書名.md」），
並同步更新清單 `_清單.md`（表格＋部數）與 `_清單.tsv`。

用法：
  python nianpu_archive.py <定稿.md> [--book <書名>] [--date YYYY-MM-DD] [--note <備註>] [--dir <整理本目錄>]

說明：
  --book  本資料夾檔名（不含 .md），預設由定稿檔名去尾碼推得（_整理定稿/_定稿/_已整理/_整理/_完整/_合并…）
  --date  整理日期，預設取定稿檔案的修改日期
  --note  清單備註
  --dir   整理本資料夾，預設 E:/2022/个人研究资料/年谱项目/年譜整理稿/年譜整理本

若「書名.md」已在清單中（同書再版），改為更新該列而非新增；清單部數隨之刷新。
"""

import re, sys
import shutil
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

DEFAULT_ARCHIVE_DIR = Path(r'E:/2022/个人研究资料/年谱项目/年譜整理稿/年譜整理本')
MANIFEST_MD = '_清單.md'
MANIFEST_TSV = '_清單.tsv'

# 由定稿檔名推乾淨書名：去常見尾碼（繁/簡、含 _ 或無 _ 變體）
SUFFIXES = [
    '_整理定稿', '_整理稿', '_定稿', '_已整理', '_整理', '_完整', '_合併', '_合并',
    '_merged', '_全文', '_全本', '_单版', '_單版', '_卷1-7', '_已切分', '_整理版',
    '_完整_已整理', '_整理_v2', '_已整理_v2',
]
SUFFIX_RE = re.compile(
    '(' + '|'.join(re.escape(s) for s in sorted(SUFFIXES, key=len, reverse=True)) + ')$'
)


def clean_book_name(stem):
    name = stem
    while True:
        new = SUFFIX_RE.sub('', name)
        new = re.sub(r'_(?:v\d+|\d+)$', '', new)
        new = new.strip('_ ')
        if new == name:
            return new
        name = new


def read_text(path):
    data = Path(path).read_bytes()
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'big5'):
        try:
            return data.decode(enc).replace('\r\n', '\n').replace('\r', '\n')
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')


def source_path_str(src, archive_dir):
    """來源路徑：在「年谱项目」根目錄下用相對路徑（含分類前綴），否則用絕對路徑。"""
    root = archive_dir.parent.parent  # 年譜整理稿 → 年谱项目
    try:
        rel = Path(os_relpath(src, root))
    except Exception:
        rel = Path(str(src))
    if str(rel).startswith('..'):
        return str(src)
    return str(rel)


def os_relpath(path, start):
    import os
    return os.path.relpath(path, start)


def upsert_tsv(tsv_path, fields):
    """fields = [檔名, 書名, 原檔名, 來源路徑, 日期, 備註]；同檔名更新該列，否則附列。"""
    lines = [l for l in read_text(tsv_path).split('\n')]
    if not lines or not lines[0].startswith('檔名'):
        print(f"⚠ {tsv_path} 開頭非標題列，略過 tsv 更新"); return False
    header = lines[0]
    body = [l for l in lines[1:] if l.strip()]
    hit = None
    for i, l in enumerate(body):
        if l.split('\t')[0] == fields[0]:
            hit = i; break
    if hit is not None:
        body[hit] = '\t'.join(fields)
        print(f"• {tsv_path.name}：更新既有列「{fields[0]}」")
    else:
        body.append('\t'.join(fields))
        print(f"• {tsv_path.name}：新增列「{fields[0]}」")
    Path(tsv_path).write_text(header + '\n' + '\n'.join(body) + '\n', encoding='utf-8')
    return True


def upsert_md(md_path, fields):
    """fields = [書名, 原檔名, 來源資料夾, 日期, 備註]；同檔名更新該列，否則附列並刷新部數。"""
    lines = read_text(md_path).split('\n')
    hit = None
    last_data = -1
    for i, l in enumerate(lines):
        if l.startswith('| ') and '.md' in l and '|---' not in l:
            last_data = i
            if l.split('|')[2].strip() == fields[0]:   # [1]=#序，[2]=書名（本資料夾檔名）
                hit = i
    if hit is not None:
        cols = lines[hit].split('|')
        # 保留原 #，更新其餘欄位（cols[2..6] = 書名/原檔名/來源資料夾/日期/備註）
        for k, v in enumerate(fields):
            cols[k + 2] = ' ' + v + ' '
        lines[hit] = '|'.join(cols)
        print(f"• {md_path.name}：更新既有列「{fields[0]}」")
    else:
        n = len([l for l in lines if l.startswith('| ') and '.md' in l and '|---' not in l]) + 1
        row = f'| {n} | ' + ' | '.join(fields) + ' |'
        insert_at = last_data + 1 if last_data >= 0 else len(lines)
        lines.insert(insert_at, row)
        print(f"• {md_path.name}：新增列「{fields[0]}」")
    # 刷新部數「共 **N** 部」
    count = len([l for l in lines if l.startswith('| ') and '.md' in l and '|---' not in l and '|#' not in l])
    for i, l in enumerate(lines):
        m = re.search(r'共 \*\*(\d+)\*\* 部', l)
        if m:
            lines[i] = re.sub(r'共 \*\*\d+\*\* 部', f'共 **{count}** 部', l)
            break
    Path(md_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return True


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__); sys.exit(1)

    def opt(name, default=None):
        nonlocal argv
        if name in argv:
            i = argv.index(name)
            v = argv[i + 1] if i + 1 < len(argv) else default
            argv = argv[:i] + argv[i + 2:]
            return v
        return default

    src = Path(argv[0])
    if not src.exists():
        print(f"錯誤：找不到檔案 {src}"); sys.exit(1)
    book = opt('--book') or clean_book_name(src.stem)
    date = opt('--date') or datetime.fromtimestamp(src.stat().st_mtime).strftime('%Y-%m-%d')
    note = opt('--note') or ''
    archive_dir = Path(opt('--dir') or DEFAULT_ARCHIVE_DIR)

    if not archive_dir.exists():
        print(f"錯誤：整理本資料夾不存在 {archive_dir}"); sys.exit(1)

    dest = archive_dir / f'{book}.md'
    same = dest.exists() and dest.read_bytes() == src.read_bytes()
    shutil.copy2(src, dest)
    print(f"✓ 已複製 → {dest}" + ("（內容與原檔相同）" if same else ""))

    tsv = archive_dir / MANIFEST_TSV
    md = archive_dir / MANIFEST_MD
    orig_name = src.name
    src_path = source_path_str(src, archive_dir)
    fields_tsv = [f'{book}.md', book, orig_name, src_path, date, note]
    src_dir = str(Path(src_path).parent)
    if src_dir == '.':
        src_dir = '年譜整理稿 根目錄'  # 來源直接在年譜整理稿根目錄下
    fields_md = [f'{book}.md', orig_name, src_dir, date, note]

    ok = True
    if tsv.exists():
        ok &= upsert_tsv(tsv, fields_tsv)
    if md.exists():
        ok &= upsert_md(md, fields_md)
    if not ok:
        print("⚠ 清單更新不完整，請人工檢查。")
        sys.exit(1)
    print(f"✓ 清單已同步（{date}）：{book}.md")


if __name__ == '__main__':
    main()
