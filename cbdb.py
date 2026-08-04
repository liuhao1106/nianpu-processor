# -*- coding: utf-8 -*-
"""CBDB（中國歷代人物傳記資料庫）輔助模組，供 nianpu_processor 使用。

- get_person(name)：查 CBDB 生卒年（帶快取 cbdb_cache.json，斷網/查無回傳 None）
- extract_person_name(text)：從年譜卷首「公諱X／公姓X諱Y」提取傳主名
- 設計原則：CBDB 是「strong hint」，缺資料或斷網時完全回退，不影響工具既有行為
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

_BASE = Path(__file__).parent
_CACHE_PATH = _BASE / "cbdb_cache.json"


def load_cache():
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache):
    try:
        _CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def query_cbdb(name):
    """查 CBDB API，回傳 dict（id/name/birth/death/years_lived/dynasty）或 None。"""
    url = ("https://cbdb.fas.harvard.edu/cbdbapi/person.php?name="
           + urllib.parse.quote(name) + "&o=json")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    try:
        bi = data["Package"]["PersonAuthority"]["PersonInfo"]["Person"]["BasicInfo"]
    except Exception:
        return None
    birth = bi.get("YearBirth")
    death = bi.get("YearDeath")
    return {
        "id": bi.get("PersonId"),
        "name": bi.get("ChName"),
        "eng": bi.get("EngName"),
        "birth": int(birth) if birth else None,
        "death": int(death) if death else None,
        "years_lived": bi.get("YearsLived"),
        "dynasty": bi.get("Dynasty"),
    }


def get_person(name, force=False):
    """帶快取：先讀 cbdb_cache.json；miss 才查 API，結果（含 None）一併回寫快取。"""
    if not name:
        return None
    cache = load_cache()
    if not force and name in cache:
        return cache.get(name)
    p = query_cbdb(name)
    cache[name] = p
    save_cache(cache)
    return p


# 已知傳主「號/諡/齋號 → 本名」對應（見測試報告 CBDB 核驗一節）。
# 供自動提取用：年譜標題/卷首出現這些別稱時，直接解析為可查 CBDB 的本名。
# 非限定性——使用者仍可 --cbdb <本名> 覆蓋。
KNOWN_ALIASES = {
    "紫陽": "朱熹", "晦庵": "朱熹", "考亭": "朱熹", "紫陽文公": "朱熹",
    "顧亭林": "顧炎武", "亭林": "顧炎武",
    "王船山": "王夫之", "船山": "王夫之",
    "黃黎洲": "黃宗羲", "黎洲": "黃宗羲", "南雷": "黃宗羲",
    "施愚山": "施閏章", "愚山": "施閏章",
    "萬清軒": "萬斛泉", "清軒": "萬斛泉",
    "張清恪": "張伯行",
    "沈端恪": "沈近思",
    "魏貞庵": "魏裔介", "貞庵": "魏裔介",
    "方柏堂": "方宗誠", "柏堂": "方宗誠",
    "涇舟": "洪汝奎", "洪琴西": "洪汝奎", "琴西": "洪汝奎",
    "桐溪達叟": "嚴辰", "桐溪": "嚴辰",
    "澄懷主人": "張廷玉", "澄懷": "張廷玉",
    "警石": "錢泰吉",
    "鼎甫": "沈維鐈",
    "吳竹如": "吳廷棟", "竹如": "吳廷棟",
    "唐一庵": "唐樞", "一庵": "唐樞",
    "文貞": "李光地",
    "羅忠節": "羅澤南", "忠節": "羅澤南",
    "松生": "丁丙",
    "殷譜經": "殷兆鏞", "譜經": "殷兆鏞",
}


def extract_person_name(text, limit=4000):
    """從年譜卷首提取傳主名。

    優先序：①已知別稱（紫陽→朱熹、亭林→顧炎武…，比對標題/卷首）
    ②「公姓X諱Y」→ 姓+名；③「公/府君/先生/主人諱Y」→ 名。
    回傳可查 CBDB 的名字字串，無法判定回傳 None。
    """
    head = text[:limit]
    # ① 已知別稱：僅比對標題區（前 2 行，含「X先生年譜」字樣），避免正文誤配
    title_area = "\n".join(head.split("\n")[:2])
    for alias, name in KNOWN_ALIASES.items():
        if alias in title_area:
            return name
    # ② 公姓X諱Y / ③ 公諱Y
    m = re.search(r"公姓([一-鿿]{1,2})諱([一-鿿]{1,3})", head)
    if m:
        return m.group(1) + m.group(2)
    m = re.search(r"(?:公|府君|先生|主人|翁|先君子)諱([一-鿿]{1,3})", head)
    if m:
        return m.group(1)
    return None
