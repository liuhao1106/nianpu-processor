# -*- coding: utf-8 -*-
"""年份內容按月份／季節分段。"""



import re

from .constants import _SEASONS, _SEASON_MONTHS, _SEASON_EXCLUDE_CONTINUATION


def split_by_month(text):
    """按月份/季節分段，將年份內的內容按 春/夏/秋/冬 拆分。

    識別模式：
      - 春正月/二月/三月，夏四月/五月/六月，秋七月/八月/九月，冬十月/十一月/十二月
      - 僅季節（春、夏、秋、冬）
      - 「是春」「是夏」「是秋」「是冬」
      - 是歲、是年（歸入前段）

    輸出格式：**春正月**內容...\n\n**夏四月**內容...
    """
    all_labels = _build_all_labels()

    pattern = re.compile(
        r'(?:(?<=[。？！\n○\s])|^)((?:是)?(?:'
        + '|'.join(
            f'{s}(?:' + '|'.join(_SEASON_MONTHS[s]) + ')?'
            for s in _SEASONS
        )
        + r')|是歲|是年)'
    )

    lines = text.split('\n')
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('### '):
            result_lines.append(line)
            i += 1
            year_content = []
            while i < len(lines):
                if not lines[i].strip():
                    year_content.append(lines[i])
                    i += 1
                    continue
                if lines[i].startswith('### ') or lines[i].startswith('---') or lines[i].startswith('## '):
                    break
                year_content.append(lines[i])
                i += 1

            content_text = '\n'.join(year_content)
            if content_text.strip():
                processed = _process_year_content(content_text, all_labels, pattern)
            else:
                processed = content_text
            result_lines.append(processed)
        else:
            result_lines.append(line)
            i += 1
    return '\n'.join(result_lines)


def _build_all_labels():
    """生成所有月份/季節標籤，用於匹配和清理。"""
    all_labels = []
    for s in _SEASONS:
        all_labels.append(f'是{s}')
        all_labels.append(s)
        for m in _SEASON_MONTHS[s]:
            all_labels.append(f'{s}{m}')
    all_labels.append('是歲')
    all_labels.append('是年')
    all_labels.sort(key=len, reverse=True)
    return all_labels


def _is_season_compound(content, m):
    """裸季節字（春/夏/秋/冬）後緊跟複合詞續字（如 秋闈、冬至、春秋、春仲）時，不當季節分段。"""
    label = m.group(1)
    if label not in _SEASONS:
        return False
    nxt = content[m.end():m.end() + 1]
    return nxt in _SEASON_EXCLUDE_CONTINUATION.get(label, '')


def _process_year_content(content, all_labels, pattern):
    """處理一年內的內容，按季節分段並以 **標籤** 標記。"""
    matches = [m for m in pattern.finditer(content) if not _is_season_compound(content, m)]
    if not matches:
        return content

    # 按匹配位置分割成段
    segments = []
    for j, m in enumerate(matches):
        label = m.group(1)
        start = m.start()
        end = matches[j + 1].start() if j < len(matches) - 1 else len(content)

        if j == 0 and start > 0:
            segments.append(('', content[0:start].strip()))

        segments.append((label, content[start:end].strip()))

    # 合併 是歲/是年 到前段
    filtered = []
    for label, text in segments:
        cleaned = text.strip()
        if not cleaned:
            continue
        if label in ('是歲', '是年'):
            if filtered:
                pl, pt = filtered[-1]
                filtered[-1] = (pl, pt + '\n\n' + cleaned)
            else:
                filtered.append(('', cleaned))
        else:
            filtered.append((label, cleaned))

    if not filtered:
        return content

    # 若僅有是歲/是年且無季節標籤，返回原內容
    has_season = any(l not in ('', ) for l, _ in filtered)
    if not has_season and len(filtered) <= 1:
        return content

    # 輸出格式：**季節**內容
    output = []
    for label, text in filtered:
        if not label:
            output.append(text)
        else:
            cleaned = text
            for l in all_labels:
                if cleaned.startswith(l):
                    cleaned = cleaned[len(l):].lstrip('，、 ')
                    break
            output.append(f'**{label}**{cleaned}')

    return '\n\n'.join(output)
