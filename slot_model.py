#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年譜語義槽位模型（v1 原型）— slot_model.py
============================================
把「每年譜改一次正則」的維護模式，抽象為「填一張語義槽位表」：

一條年份條目永遠由三類錨點構成，不同年譜只是錨點的具體值不同：
  ① 紀年錨點（年號／年序／干支／公元，取 ≥1）
  ② 年齡錨點（先生/公/府君/傳主名/無 前綴 + N嵗）
  ③ 事件錨點（生/卒/出生日期/事件）

正則由槽位「生成」而非「手寫」；LLM 只負責兩端：
  ── 入口：讀新年譜開頭 + few-shot 範例 → 輸出槽位 JSON（決定配置）
  ── 出口：L2 三錨點「干支 vs 年號 vs 年齡」打架時 → LLM 讀上下文仲裁

本模組提供：SLOT_SCHEMA（槽位定義）、FEWSHOT（已處理年譜的槽位實例）、
llm_prompt()（入口 prompt）、slots_to_fmt()（槽位 → 工具格式族配置）。
"""
from __future__ import annotations

# ======== 槽位 schema ========
SLOT_SCHEMA = {
    "reigns": "年譜使用的年號（如 同治/光緒/民國…）；無則空串列",
    "year_style": "紀年形式：reign_seq（年號N年）| ganzhi_only（僅干支）| ad（公元N年）| minguo（民國N年）| mixed",
    "gz_age": "干支直接接年齡（bool，如 庚子二歲／丙戌，年四十八歲；無年號前綴，年號僅出生條目與更替處）",
    "uses_ganzhi": "是否帶干支（bool）",
    "person_prefix": "年齡前綴：先生|公|府君|傳主名（直接填名字，如 希濤）|無",
    "age_connector": "前綴與年齡間的連接字：年|無",
    "age_suffix": "年齡後綴：嵗|歲|岁|歳",
    "age_position": "年齡位置：緊跟干支|隔標點|隔長文|跨行",
    "no_person": "無稱謂直接附年齡（bool，如 十二年癸丑二歲）",
    "bare_years": "無年齡純年份（bool，如 紹興元年辛亥）",
    "has_birth_entry": "是否含出生條目（bool）",
    "birth_form": "出生條目形式：名+生|先生生|公生|生於|日期無生字",
    "monthly_split": "是否按春/夏/秋/冬、月份分段（bool）",
    "modern_heading": "已是年份標題（bool，現代學者年譜）",
    "cross_line": "年份與年齡跨行（bool，如 康熙十六年\\n公七歲）",
    "default_reign": "全譜未寫明年號時強制補上的年號（如 同治）；留空則靠條目自帶年號",
    "ocr_variants": "已知 OCR 字形變體，如 光緖→光緒（字典型）",
}

# ======== few-shot：已處理年譜 → 槽位實例 ========
# 來源：README/SKILL「已成功處理的年譜」清單（格式欄＋備註欄）
FEWSHOT = [
    {"name": "方柏堂先生譜系略", "format": "先生年N嵗",
     "slots": {"reigns": [], "year_style": "reign_seq", "uses_ganzhi": True,
               "person_prefix": "先生", "age_connector": "年", "age_suffix": "嵗",
               "age_position": "緊跟干支", "no_person": False, "bare_years": False,
               "has_birth_entry": True, "birth_form": "先生生", "monthly_split": False,
               "modern_heading": False, "cross_line": False, "default_reign": "",
               "ocr_variants": {}}},
    {"name": "文貞公年譜", "format": "公年N歲（明清之際）",
     "slots": {"reigns": ["崇禎", "順治", "康熙"], "year_style": "reign_seq",
               "uses_ganzhi": True, "person_prefix": "公", "age_connector": "年",
               "age_suffix": "歲", "age_position": "緊跟干支", "no_person": False,
               "bare_years": False, "has_birth_entry": True, "birth_form": "公生",
               "monthly_split": True, "modern_heading": False, "cross_line": False,
               "default_reign": "", "ocr_variants": {}}},
    {"name": "警石府君年譜", "format": "府君年N歲",
     "slots": {"reigns": ["乾隆", "嘉慶", "道光", "咸豐", "同治"], "year_style": "reign_seq",
               "uses_ganzhi": True, "person_prefix": "府君", "age_connector": "年",
               "age_suffix": "歲", "age_position": "緊跟干支", "no_person": False,
               "bare_years": False, "has_birth_entry": True, "birth_form": "府君生",
               "monthly_split": True, "modern_heading": False, "cross_line": False,
               "default_reign": "", "ocr_variants": {}}},
    {"name": "黃黎洲先生年譜", "format": "公N嵗（無「年」連接）",
     "slots": {"reigns": ["萬曆", "崇禎", "順治", "康熙"], "year_style": "reign_seq",
               "uses_ganzhi": True, "person_prefix": "公", "age_connector": "無",
               "age_suffix": "嵗", "age_position": "緊跟干支", "no_person": False,
               "bare_years": False, "has_birth_entry": True, "birth_form": "公生",
               "monthly_split": False, "modern_heading": False, "cross_line": False,
               "default_reign": "", "ocr_variants": {"萬厤": "萬曆"}}},
    {"name": "袁觀瀾先生手編年譜", "format": "傳主名前綴（名+N歲）＋民國無干支",
     "slots": {"reigns": ["同治", "光緒", "宣統", "民國"], "year_style": "mixed",
               "uses_ganzhi": True, "person_prefix": "希濤", "age_connector": "年",
               "age_suffix": "歲", "age_position": "緊跟干支", "no_person": False,
               "bare_years": True, "has_birth_entry": True, "birth_form": "名+生",
               "monthly_split": True, "modern_heading": False, "cross_line": True,
               "default_reign": "同治", "ocr_variants": {"光緖": "光緒"}}},
    {"name": "陽明先生年譜", "format": "先生年N嵗（明，含皇帝前綴）",
     "slots": {"reigns": ["成化", "弘治", "正德", "嘉靖"], "year_style": "reign_seq",
               "uses_ganzhi": True, "person_prefix": "先生", "age_connector": "年",
               "age_suffix": "嵗", "age_position": "緊跟干支", "no_person": False,
               "bare_years": True, "has_birth_entry": True, "birth_form": "先生生",
               "monthly_split": False, "modern_heading": False, "cross_line": False,
               "default_reign": "成化", "ocr_variants": {}}},
    {"name": "萬清軒先生年譜", "format": "無稱謂直接附年齡",
     "slots": {"reigns": [], "year_style": "reign_seq", "uses_ganzhi": True,
               "person_prefix": "無", "age_connector": "無", "age_suffix": "歲",
               "age_position": "緊跟干支", "no_person": True, "bare_years": False,
               "has_birth_entry": True, "birth_form": "先生生", "monthly_split": False,
               "modern_heading": False, "cross_line": False, "default_reign": "",
               "ocr_variants": {}}},
    {"name": "殷譜經侍郎自定年譜", "format": "無稱謂直接附年齡（含「，年N歲」）",
     "slots": {"reigns": ["嘉慶", "道光", "咸豐", "同治", "光緒"], "year_style": "reign_seq",
               "uses_ganzhi": True, "person_prefix": "無", "age_connector": "無",
               "age_suffix": "歲", "age_position": "緊跟干支", "no_person": True,
               "bare_years": False, "has_birth_entry": True, "birth_form": "生於",
               "monthly_split": False, "modern_heading": False, "cross_line": False,
               "default_reign": "", "ocr_variants": {"光緖": "光緒"}}},
    {"name": "沈端恪公年譜", "format": "跨行年份+年齡",
     "slots": {"reigns": ["康熙", "雍正"], "year_style": "reign_seq", "uses_ganzhi": True,
               "person_prefix": "公", "age_connector": "無", "age_suffix": "歲",
               "age_position": "跨行", "no_person": False, "bare_years": False,
               "has_birth_entry": True, "birth_form": "公生", "monthly_split": False,
               "modern_heading": False, "cross_line": True, "default_reign": "",
               "ocr_variants": {}}},
    {"name": "紫陽文公先生年譜", "format": "無年齡純年份（朱熹）",
     "slots": {"reigns": ["建炎", "紹興", "隆興", "乾道", "淳熙", "紹熙", "慶元"],
               "year_style": "reign_seq", "uses_ganzhi": True, "person_prefix": "無",
               "age_connector": "無", "age_suffix": "嵗", "age_position": "無年齡",
               "no_person": False, "bare_years": True, "has_birth_entry": True,
               "birth_form": "名+生", "monthly_split": False, "modern_heading": False,
               "cross_line": False, "default_reign": "", "ocr_variants": {}}},
    {"name": "項蘭生自訂年譜", "format": "公元年號/民國（公元一八七三年…）",
     "slots": {"reigns": ["同治", "光緒", "宣統", "民國"], "year_style": "ad",
               "uses_ganzhi": True, "person_prefix": "無", "age_connector": "無",
               "age_suffix": "岁", "age_position": "緊跟", "no_person": True,
               "bare_years": False, "has_birth_entry": True, "birth_form": "日期無生字",
               "monthly_split": False, "modern_heading": False, "cross_line": False,
               "default_reign": "", "ocr_variants": {}}},
    {"name": "劉熙載年譜", "format": "現代學者年譜 A（已有標題）",
     "slots": {"reigns": ["嘉慶", "道光", "咸豐", "同治", "光緒"], "year_style": "reign_seq",
               "uses_ganzhi": True, "person_prefix": "無", "age_connector": "無",
               "age_suffix": "岁", "age_position": "在標題內", "no_person": True,
               "bare_years": False, "has_birth_entry": True, "birth_form": "日期無生字",
               "monthly_split": False, "modern_heading": True, "cross_line": False,
               "default_reign": "", "ocr_variants": {}}},
    {"name": "王欣夫先生編年事輯稿", "format": "現代學者年譜 B（公元在前標題）",
     "slots": {"reigns": ["光緒", "民國"], "year_style": "ad", "uses_ganzhi": True,
               "person_prefix": "無", "age_connector": "無", "age_suffix": "歲",
               "age_position": "在標題內", "no_person": True, "bare_years": False,
               "has_birth_entry": True, "birth_form": "日期無生字", "monthly_split": False,
               "modern_heading": True, "cross_line": False, "default_reign": "",
               "ocr_variants": {}}},
    {"name": "重刻鄭端簡公年譜", "format": "行首裸干支（公N歲稀疏）",
     "slots": {"reigns": ["弘治", "正德", "嘉靖", "隆慶"], "year_style": "ganzhi_only",
               "uses_ganzhi": True, "person_prefix": "公", "age_connector": "無",
               "age_suffix": "歲", "age_position": "緊跟干支", "no_person": False,
               "bare_years": True, "has_birth_entry": True, "birth_form": "公生",
               "monthly_split": True, "modern_heading": False, "cross_line": False,
               "default_reign": "", "ocr_variants": {"内午": "丙午", "内申": "丙申", "壬戍": "壬戌"}}},
    {"name": "李恕谷先生年譜", "format": "干支+直接年齡（gz_age）",
     "slots": {"reigns": ["順治", "康熙", "雍正"], "year_style": "ganzhi_only",
               "gz_age": True, "uses_ganzhi": True, "person_prefix": "先生",
               "age_connector": "年", "age_suffix": "嵗", "age_position": "緊跟干支",
               "no_person": False, "bare_years": False, "has_birth_entry": True,
               "birth_form": "先生生", "monthly_split": False, "modern_heading": False,
               "cross_line": False, "default_reign": "", "ocr_variants": {}}},
]

PROMPT_TEMPLATE = """你是年譜格式分析器。把「每年譜改一次正則」變成「填一張語義槽位表」。

定義：一條年份條目由三類錨點構成（不同年譜只是錨點值不同）——
  ① 紀年錨點：年號／年序／干支／公元
  ② 年齡錨點：先生/公/府君/傳主名/無 前綴 + N嵗
  ③ 事件錨點：生／卒／出生日期／事件

槽位 schema：
{slots_schema}

已處理年譜的槽位實例（few-shot）：
{examples}

── 請閱讀以下新年譜的開頭文本，輸出它的槽位 JSON（只輸出 JSON，不要說明）──

{text_head}
"""


def llm_prompt(text_head: str, examples=None) -> str:
    """生成「新年譜開頭 → 槽位 JSON」的 LLM prompt。"""
    if examples is None:
        examples = FEWSHOT
    schema_lines = "\n".join(f"  {k}：{v}" for k, v in SLOT_SCHEMA.items())
    ex_lines = "\n".join(
        f"【{e['name']}】（{e['format']}）\n"
        + _json_lines(e["slots"])
        for e in examples
    )
    return PROMPT_TEMPLATE.format(
        slots_schema=schema_lines,
        examples=ex_lines,
        text_head=text_head[:1200],
    )


def _json_lines(d: dict) -> str:
    import json
    return json.dumps(d, ensure_ascii=False, indent=2)


# ======== 出口：L2 三錨點衝突的 LLM 仲裁 ========
ARBITRATE_TEMPLATE = """你是年譜校勘者。以下條目在「年號年→公元」「干支→公元」「年齡→公元」
三個錨點間打架（L2 檢查標出）。請結合上下文定奪哪個錨點有誤、正確值應是什麼。

規則：優先相信「干支+公元」這一對（干支無歧義），再倒推年號年序／年齡；
若上下文能鎖定年號（如相鄰條目都是 X 年號），則以年號為準修正干支或年序。

衝突條目：
{conflicts}

── 請逐條輸出：條目 / 判定哪個錨點錯 / 正確寫法（標題應改成什麼）──
"""


def arbitrate_prompt(conflict_headings, context=''):
    """生成「L2 三錨點衝突 → 仲裁」的 LLM prompt。"""
    conflicts = "\n".join(f"  - {h}" for h in conflict_headings)
    return ARBITRATE_TEMPLATE.format(conflicts=conflicts) + (
        f"\n── 上下文（鄰近正文）──\n{context[:800]}" if context else "")


def slots_to_fmt(slots: dict) -> dict:
    """槽位配置 → 工具可用的格式族 dict（與 classify_format 的回傳相容）。

    供 nianpu_processor --slots 使用：直接覆蓋格式分類與傳主名前綴，
    使「新格式」不需改正則，只需 LLM 填好槽位。
    """
    person_prefix = (slots or {}).get("person_prefix") or ""
    extra = []
    if person_prefix and person_prefix not in ("先生", "公", "府君", "無", ""):
        extra = [person_prefix]
    fmt = {
        "person": (slots or {}).get("no_person") is False and (
            person_prefix in ("先生", "公", "府君", "無") or bool(extra)),
        "no_person": bool((slots or {}).get("no_person")),
        "ad": bool((slots or {}).get("year_style") == "ad"),
        "bare": bool((slots or {}).get("bare_years")),
        # 行首裸干支年標（重刻鄭端簡公年譜等）：全譜以「庚申、」「己亥春入京」行首裸干支紀年
        "bare_gz": bool((slots or {}).get("year_style") == "ganzhi_only"),
        # 干支+直接年齡（李恕谷先生年譜等）：庚子二歲／丙戌，年四十八歲
        "gz_age": bool((slots or {}).get("gz_age")),
        "modern": bool((slots or {}).get("modern_heading")),
        "_person_extra": extra,
    }
    # 優先級互斥：gz_age（干支+直接年齡）與 bare_gz（行首裸干支）同譜共存時不誤用行首裸干支
    if fmt["gz_age"]:
        fmt["bare_gz"] = False
    # 無稱謂直接年齡格式：no_person 為真，person 為假
    if fmt["no_person"]:
        fmt["person"] = False
    return fmt
