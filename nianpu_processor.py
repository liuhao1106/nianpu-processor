#!/usr/bin/env python3
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
"""

from nianpu_core import *          # noqa: F401,F403
from nianpu_core import main       # noqa: F401

if __name__ == '__main__':
    main()
