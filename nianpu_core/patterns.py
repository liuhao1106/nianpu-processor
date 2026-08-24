# -*- coding: utf-8 -*-
"""格式族分類（classify_format）與全文匹配模式構建（_build_full_pattern）。"""



import re

from .constants import (
    REIGNS, EMPEROR_PREFIXES, PERSON_PREFIXES,
    AGE_SUFFIXES, AGE_DIGITS, AGE_SUFFIX_REQUIRED,
    _TG, _DZ, STEM_BRANCH,
)
from .base import _build_year_pattern, detect_person_prefixes, _gz_age_connector
from .expand import _find_gz_age_birth_ref
from .modern import try_parse_modern_heading


def classify_format(text):
    """偵測年譜格式族，決定套用哪些年份 pattern 子集，降低誤配率。

    二元特徵：
      person    — 有「先生/公/府君〔年〕N嵗」（方柏堂/張清恪/府君風格）
      no_person — 有「N年干支…N嵗」無稱謂直接年齡（萬清軒/澄懷主人/顧亭林風格）
      ad        — 含「公元N年」（近現代/民國年譜）
    回傳 dict；兩個 count 皆 >0 表示混合格式（套用全部 pattern）。
    """
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_req = AGE_SUFFIX_REQUIRED
    extra_person = detect_person_prefixes(text)
    person = '(?:' + '|'.join(PERSON_PREFIXES + extra_person) + r')'
    reign_alt = '|'.join(REIGNS)
    emp_alt = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)

    # 有稱謂：先生/公/府君/傳主名 [年] N嵗
    person_age = re.compile(person + r'(?:年)?\s*' + an + as_req)
    n_person = len(person_age.findall(text))

    # 無稱謂：N年[標點]干支[標點][年]N嵗（年齡緊接干支，避免誤配「，先生年N嵗」）
    no_person_age = re.compile(
        r'(?:' + emp_alt + r')?(?:' + reign_alt + r')?' + y + r'年[，,、。]?' + sb
        + r'[，,、。]?\s*(?:年)?' + an + as_req
    )
    n_no_person = len(no_person_age.findall(text))

    n_ad = len(re.findall(r'公元[一二三四五六七八九零〇]{3,4}年', text))

    # 無年齡純年份（朱熹年譜風格）：(前綴)?(年號)?N年干支 於行首/句末
    # 干支必備，避免誤配正文年份引用（如「淳熙元年，始拜命」無干支）
    # 注意：此處不加「排除緊接/間隔年齡」的 lookahead —— 顧亭林出生/卒年條目
    # （萬厯四十一年癸丑五月二十八日生一歲／康熙二十一年壬戌正月初九日卒）也是
    # 「N年干支＋日期＋生/卒」的 bare 形態；加了會讓 n_bare 掉到閾值(5)以下，
    # bare 模式被關閉，顧亭林童年條目丟失萬曆年號與公元年（回歸）。年齡竊取
    # 已由 entry_bare 自身的強化 lookahead 解決（見 _build_full_pattern）。
    bare_pat = re.compile(
        r'(?:^|(?<=[。！？；〕\n]))\s*'
        + r'(?:' + emp_alt + r')?(?:' + reign_alt + r')?'
        + y + r'年' + sb
    )
    n_bare = len(bare_pat.findall(text))

    # 行首裸干支年標（重刻鄭端簡公年譜等）：全譜以行首裸干支紀年，如「庚申、」「己亥春入京」
    # 「丁卯。公九歲」「戊申在尚寶」。限行首且後不接干支（防「已未庚申」連續誤切）。
    # 連續 ≥5 個才視為該格式族——避免散文干支日期（如「辛亥鼎革」「辛酉五月望前一日」）誤觸發
    bare_gz_pat = re.compile(
        r'^[○〇]?[' + _TG + r'][' + _DZ + r'](?![甲乙丙丁戊己已庚辛壬癸巳])'
    )
    n_bare_gz = sum(1 for line in text.split('\n') if bare_gz_pat.match(line.strip()))

    # 干支+直接年齡（李恕谷先生年譜等）：干支緊接年齡（庚子二歲／丙戌，年四十八歲／
    # 壬寅，康熙元年四歲）。干支前不接「年」（排除 N年干支N歲 無稱謂格式）；
    # 條目內嵌段落，以 句號/逗號/行首/年齡後綴 為邊界。連續 ≥5 個才視為該格式族，
    # 且優於 bare_gz（同譜行首亦有散文干支時不再誤用行首裸干支）。
    gz_age_pat = re.compile(
        r'(?:^|(?<=[。！？；〕，、\n' + AGE_SUFFIXES + r']))\s*'
        + r'(?<!年)'
        + sb
        + _gz_age_connector()
        + an + as_req
    )
    n_gz_age = len(gz_age_pat.findall(text))

    # 純年齡（行首/句末「N歲，」無任何紀年錨點；曹月川先生年譜等）：
    # 全譜僅以年齡紀年，唯一紀年錨點是出生條目（年號N年干支…生）。
    # 需出生條目可被 _find_gz_age_birth_ref 解析（年號播種）才啟用；
    # 連續 ≥5 避免散文誤觸發；與其他格式族互斥（判定表 below）。
    pure_age_pat = re.compile(
        r'(?:(?:^|(?<=\n))\s*' + an + as_req + r')'           # 行首：不需後接標點（二十歲嘗曰）
        + r'|(?<=[。！？；〕])' + an + as_req + r'(?:[，,、。]|(?=[春夏秋冬]))'  # 句中：需標點/季節
    )
    n_pure_age = len(pure_age_pat.findall(text))
    pure_age_birth_ok = _find_gz_age_birth_ref(text) is not None

    # 現代學者年譜：已有年份標題（年號N年 干支 公元年 年齡），非待切分。
    # 判定：≥2 行能被 try_parse_modern_heading(allow_plain=True) 解析——
    # 含帶 # 前綴標題與無 # 前綴的純文字獨立年份行（四錨點覆蓋整行）。
    # 傳統年譜原始文本無公元年，不會誤觸發；已整理傳統檔的「（1806年）」在括號內，
    # 因「公元年在干支後緊接」的要求而不被視為現代格式。
    n_modern = sum(1 for line in text.split('\n')
                   if try_parse_modern_heading(line, allow_plain=True) is not None)

    # 判定表：閾值集中在此（None 表示 count>0 即觸發）；優先級互斥亦表驅動，
    # 避免新增格式族時繼續堆疊 if（gz_age 優於 bare_gz：同譜兩者共存時不誤用行首裸干支）。
    _THRESH = {'bare': 5, 'bare_gz': 5, 'gz_age': 5, 'pure_age': 5, 'modern': 2}
    _ORDER = ['person', 'no_person', 'ad', 'bare', 'bare_gz', 'gz_age', 'pure_age', 'modern']
    counts = {'person': n_person, 'no_person': n_no_person, 'ad': n_ad,
              'bare': n_bare, 'bare_gz': n_bare_gz, 'gz_age': n_gz_age,
              'pure_age': n_pure_age, 'modern': n_modern}
    fmt = {k: counts[k] >= _THRESH.get(k, 1) for k in _ORDER}
    fmt['person'] = fmt['person'] or bool(extra_person)   # 傳主名前綴偵測亦算有稱謂
    fmt['bare_gz'] = fmt['bare_gz'] and not fmt['gz_age']
    # bare 優於 bare_gz：純年份格式（朱熹式）年譜的行首散文干支多是記日（紫陽文公
    # 紹熙五年節內「辛丑，受詔進講」等日干支），誤用 bare_gz 展開會造出「紹熙五十
    # 二年」之類不可能年份。僅當行首裸干支多於完整年標（bare_gz 為主導）時才啟用。
    fmt['bare_gz'] = fmt['bare_gz'] and not (fmt['bare'] and n_bare > n_bare_gz)
    # 純年齡只在此譜無任何其他格式族時啟用（避免干擾萬清軒/李恕谷等既有格式）
    fmt['pure_age'] = fmt['pure_age'] and pure_age_birth_ok and not any(
        fmt[k] for k in ('person', 'no_person', 'ad', 'bare', 'bare_gz', 'gz_age', 'modern'))
    fmt['_person_extra'] = extra_person
    fmt['_counts'] = tuple(counts[k] for k in _ORDER)
    return fmt


def _build_full_pattern(fmt=None):
    """構建用於全文替換的正則表達式（匹配年份+年齡，替換為###標題）。

    fmt: classify_format() 的結果。為 None 時套用全部 8 種 pattern（相容舊行為）；
    指定後只套用該格式族相關的子集（如 純無稱謂年譜 排除 有稱謂 pattern，
    避免把正文「崇禎九年，巡按御史王公一…」中的「公一」誤當「公一歲」）。
    若分類產生空集合，退回全部 pattern 以免漏切。
    """
    y = _build_year_pattern()
    sb = STEM_BRANCH
    an = AGE_DIGITS
    as_ = r'[' + AGE_SUFFIXES + r']?'
    as_required = AGE_SUFFIX_REQUIRED  # 後綴必備（無稱謂直接年齡格式）

    ap = '|'.join(re.escape(p) for p, _ in EMPEROR_PREFIXES)
    ar = '|'.join(REIGNS)
    extra_person = (fmt or {}).get('_person_extra') or []
    person = '(?:' + '|'.join(PERSON_PREFIXES + extra_person) + r')'
    pp = r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')?'

    # 出生條目：X年干支...先生生/公生/府君生（含跨一句號變體，如「成化十三年丁酉
    # 十月十六日庚戌戌時。先生生」——出生日期與「先生生」分句，陳紫峰年譜）
    # 中間段禁冒號（：/：）：出生句不含引述，防止「…曰：治亂生於人心」的「生於」誤當出生
    _birth_sb = sb if (fmt or {}).get('gz_age') else ''
    birth = (r'(?:' + _birth_sb + r')?' + pp + y + r'年(?:' + sb + r')?'
             + r'(?:[^。\n：:]{0,120}?'                       # ① 同句：X年...先生生
             + r'|[^。\n：:]{0,60}?。[^。\n：:]{0,60}?)'       # ② 跨一句號：X年...。先生生
             + person + r'生(?:於)?' + r'[，。、]?')

    # 年份條目（有干支）
    # 匹配：可能前綴 + N年干支 + [最多120字，不含換行與句號] + 先生[年]N嵗
    # 中間文字限制不跨句號，防止一個條目吞噬其後的真實年份（如「道光元年辛巳三十一歲。府君…二年壬午三十二歲」）
    # [，,、。]?\s* 容許干支後直接接句號的斷裂格式（如「四十五年丁巳。公八嵗」），與 entry_sb_no_person 一致
    entry_sb = (
        pp + y + r'年' + sb
        + r'[，,、。]?\s*' + r'[^。\n]{0,120}?'  # 中間最多120字，不跨句號（原為60字）
        + person + r'(?:年)?\s*' + an + as_ # 先生[年]N嵗
        + r'[，。、]?'                    # 消耗年齡後綴後的標點
    )

    # 年份條目（無干支，但有年號前綴，如「順治元年，先生二十六歲」）
    entry_no_sb = (
        r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')'  # 年號前綴是必需的
        + y + r'年'
        + r'(?!' + sb + r')'        # 後面不是干支
        + r'[^。\n]*?'
        + person + r'(?:年)?\s*' + an + as_
        + r'[，。、]?'                    # 消耗年齡後綴後的標點
    )

    # 出生條目（無直接年齡）：干支，年號年。公...生於
    birth_direct = (
        r'(?:^|(?<=[。！？；\n]))\s*'    # 行首或句末
        + sb + r'[，,]\s*'               # 干支+逗號
        + r'(?:' + ap + r')?(?:' + ar + r')?' + y + r'年'  # 前綴+年號+年
        + r'[^。]{0,100}?。\s*公[^。]{0,200}?' + r'生(?:於)?'
        + r'[，。、]?'                    # 消耗生於後的標點
    )

    # 直接干支+公N嵗（無年號前綴）
    # 匹配：行首/句末的干支 + 必需標點 + 内容 + 稱謂+年齡
    # 標點為必需，避免把「乙丑春，與…先生一」中的「乙丑+季節」誤判為年份條目
    entry_sb_direct = (
        r'(?:^|(?<=[。！？；\n]))\s*'   # 行首或句末
        + r'(?<!年)'                     # 干支前不能有「年」
        + sb                             # 干支
        + r'[，,、。]\s*'               # 必需標點（逗號/句號）
        + r'[^。\n]{0,30}?'              # 中間内容（最多30字，不跨句號）
        + person + r'(?:年)?\s*' + an + as_  # 稱謂+年齡
        + r'[，。、]?'                    # 消耗年齡後綴後的標點
    )

    # 出生條目（直接生於，無先生/公前綴，澄懷主人/自定年譜風格）
    # 匹配：康熙十一年壬子，是年...生於京師。 ／ 嘉慶十一年丙寅十月一日戌時。兆鏞生於...
    # (?<!先) 防止把「先生於」中的「生於」誤判為出生（先生於≠生於）
    # 第二分支容許跨一個句號（「…戌時。{人名}生於」），解決自定年譜「{年}干支{月日時}。{名}生於」出生條目
    # 中間段禁止冒號（：/：）：出生句不含引述，防止把「…有感嘆曰：治亂生於人心」的
    # 「生於」（義為「起於」，非出生）誤當出生條目（關中李二曲先生履歷紀略 康熙九年庚戌）
    birth_no_person = (
        r'(?:' + ap + r')?(?:' + ar + r')?'  # 前綴（含年號）
        + y + r'年(?:' + sb + r')?'           # N年 + 可選干支
        + r'(?:'                                # 兩分支：
        + r'[^。\n：:]{0,120}?'                 #  ① 直接生於（不跨句號/冒號，原為60）
        + r'|[^。\n：:]{0,60}?。[^。\n：:]{0,60}?'  #  ② 跨一句號（…戌時。兆鏞生於）
        + r')'
        + r'(?<!先)生於'                        # 生於
    )

    # 年份條目（有干支，無先生/公前綴，澄懷主人/殷譜經風格）
    # 匹配：十二年癸丑二歲 ／ 雍正元年癸卯五十二歲 ／ 光緖元年乙亥，年七十歳
    # 也支援年與干支間有逗號：十年，壬子六十一歲 ／ 五年。丙寅六十一歲
    # 年齡後綴必備 + 可選「年」前綴，避免把「嘉慶十一年丙寅十月」中的「十」誤判為年齡
    entry_sb_no_person = (
        r'(?:' + ap + r')?(?:' + ar + r')?'  # 可選前綴（皇帝廟號+年號）
        + y + r'年[，,、。]?' + sb              # N年 + 可選標點 + 干支
        + r'[，,、。]?\s*'                      # 可選標點
        + r'(?:年)?'                            # 可選「年」前綴（光緖元年乙亥，年七十歳）
        + an + as_required                      # 年齡數字 + 嵗/歲（後綴必備）
        + r'[，。、]?'                           # 消耗年齡後綴後的標點
    )

    # 公元年格式（近現代/民國年譜）：公元一八七三年，同治十二年，岁次癸酉，一岁。
    # 公元N年（3-4位中文數字）+ 可選年號年（同治十二年/民國元年/宣統三年）+ 可選岁次干支 + N岁（後綴必備）
    # 必須有年齡，避免誤切世系簡述等「公元N年」無年齡的敘述
    ad_years = r'[一二三四五六七八九零〇]{3,4}'
    ad_entry = (
        r'公元' + ad_years + r'年'
        + r'(?:，?' + r'(?:' + ar + r')' + y + r'年)?'   # 可選：年號年
        + r'(?:，?岁次' + sb + r')?'                      # 可選：岁次干支
        + r'，?' + an + as_required                       # 年齡（後綴必備）
        + r'[。，]?'                                       # 消耗結尾標點
    )

    # 無年齡純年份（朱熹年譜風格）：(前綴)?(年號)?N年干支，無年齡
    # 匹配：紹興元年辛亥 ／ 四年甲寅 ／ 孝宗隆興元年癸未 ／ 光宗紹熙元年庚戍
    # 限行首或句末/註文後，且干支必備（區分正文年份引用「淳熙元年，始拜命」）
    # 放在 alternation 末尾：有年齡的條目（entry_sb_no_person 等）先匹配，避免此 pattern 搶走「N年干支」部分
    age_lookahead = (r'(?!(?:[，,、。]?\s*)?(?:(?:' + person + r')?(?:年)?\s*)?'
                     + an + r'[' + AGE_SUFFIXES + r'])')
    entry_bare = (
        r'(?:^|(?<=[。！？；〕\n]))\s*'      # 行首或句末/註文後
        + r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')?'  # 可選前綴（皇帝廟號）+年號
        + y + r'年' + sb                         # N年干支（干支必備）
        + age_lookahead
        + r'[，,、。]?'                          # 消耗干支後標點（「二十六年丙子，七月」）
    )

    # 行首裸干支年標（重刻鄭端簡公年譜等）：庚申、／己亥春入京／丁卯。公九歲／戊申在尚寶
    # 限行首（句末/文中的散文干支日期如「甲寅、乙卯以來」「戊午陜巴之復」不切），
    # 干支後不接干支（防「已未庚申」連續誤切）。標題為「干支」；年號+年序+公元
    # 由 insert() 依「當前年號 + 干支週期」推算（_expand_bare_gz_heading）。
    # 由格式分類 bare_gz（或 --slots year_style=ganzhi_only）開關，避免散文干支誤觸發。
    entry_bare_gz = (
        r'(?:^|(?<=\n))\s*'                    # 行首
        + r'[○〇]?'                             # 可選段落標記
        + r'(?<!年)'                             # 干支前不能有「年」
        + r'(?P<gz>[' + _TG + r'][' + _DZ + r'])'  # 干支
        + r'(?![甲乙丙丁戊己已庚辛壬癸巳])'       # 後不接干支
        + r'[，,、。]?'
    )

    # bare_gz 模式的行首完整年標變體：僅「行首」的 (前綴)?(年號)?N年干支
    # （如卷首「嘉靖三十八年己未」「隆慶元年丁卯」）。句末的 N年干支（散文引用，
    # 如「永樂十九年辛丑」「二十六年甲申」）不切——bare_gz 格式的年標以行首為準。
    entry_bare_ls = (
        r'(?:^|(?<=\n))\s*'
        + r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')?'
        + y + r'年' + sb
        + age_lookahead
        + r'[，,、。]?'
    )
    # bare_gz 模式的句末「元年」變體：僅 句末/註文後 的「元年干支」（年號更替，
    # 如「…魁浙。嘉靖元年壬午，舉…」）。非元年的句末 N年干支 皆為散文引用，不切。
    entry_bare_se_yuan = (
        r'(?<=[。！？；〕])\s*'
        + r'(?:中華)?(?:' + ap + r')?(?:' + ar + r')?'
        + r'元年' + sb
        + age_lookahead
        + r'[，,、。]?'
    )

    # 干支+直接年齡（李恕谷先生年譜等）：庚子二歲／丙戌，年四十八歲／壬寅，康熙元年四歲。
    # 干支前不接「年」（排除 N年干支N歲 無稱謂格式）與年號；標題為「干支(中間)N歲」，
    # 年號+年序+公元 由 insert() 依「出生年 + 年齡/干支週期」推算（_expand_gz_age_heading）。
    entry_gz_age = (
        r'(?:^|(?<=[。！？；〕，、\n' + AGE_SUFFIXES + r']))\s*'
        + r'(?<!年)'
        + r'(?P<gz>[' + _TG + r'][' + _DZ + r'])'
        + _gz_age_connector()
        + an + as_required
        + r'[，。、]?'                    # 消耗年齡後綴後的標點（避免正文殘留「，孝慤…」）
    )

    # 純年齡（曹月川先生年譜等：全譜僅以「N歲，」紀年，無年號/干支錨點）：
    # — entry_pure_age_birth：出生條目「年號N年干支」原子化（僅消費紀年錨點，
    #   日期與「生」動詞留在正文），_expand_pure_age_heading 原樣保留為出生標題
    # — entry_pure_age：消費「N歲（，）」＋後接標點；年號年序/干支/公元年由
    #   insert() 依出生條目（出生年＋年齡−1）推算
    entry_pure_age_birth = (
        r'(?:^|(?<=[。！？；〕\n]))\s*'
        + r'(?:(?:中華)?(?:' + ap + r')?(?P<pubr>' + ar + r'))'
        + r'(?P<puy>' + y + r')年(?P<pugz>' + sb + r')'
        + r'(?=[一-十]{1,2}[月日]|[春夏秋冬]|\d)'
    )
    entry_pure_age = (
        r'(?:(?:^|(?<=\n))\s*'
        + r'(?P<puage>' + an + as_required + r')(?:[，,、。]|(?=[春夏秋冬]))?'  # 行首：可選吞標點
        + r'|(?<=[。！？；〕])'
        + r'(?P<puage2>' + an + as_required + r')(?:[，,、。]|(?=[春夏秋冬])))'  # 句中：需標點/季節
    )

    # 依格式族選擇 pattern 子集（fmt=None 時全部套用）
    # 出生 pattern（birth/birth_direct/birth_no_person）一律啟用：
    #   1) 兩種格式（先生生 / 公生於 / 生於）的出生條目都會種下年號，若排除則後續條目
    #      失去年號前綴（如羅忠節公「先生生」出生後，各條目丟失嘉慶年號與公元年註記）
    #   2) 出生 pattern 均需「先生生/公生/生於」等特定動詞，誤配風險低
    # 分類只決定「年份條目」pattern（有稱謂 entry_*  vs  無稱謂 entry_sb_no_person  vs  無年齡 entry_bare）
    alts = []
    if fmt is None or fmt.get('ad'):
        alts.append(ad_entry)
    alts.extend([birth, birth_direct, birth_no_person])
    if fmt is None or fmt.get('person'):
        alts.extend([entry_sb, entry_no_sb, entry_sb_direct])
    if fmt is None or fmt.get('no_person'):
        alts.append(entry_sb_no_person)
    if fmt is not None and fmt.get('gz_age'):
        alts.append(entry_gz_age)   # 干支+直接年齡（李恕谷等）；僅 gz_age 格式啟用
    if fmt is not None and fmt.get('pure_age'):
        alts.append(entry_pure_age_birth)  # 純年齡出生條目（年號N年干支原子化）
        alts.append(entry_pure_age)        # 純年齡：行首/句末「N歲」
    if fmt is None:
        alts.append(entry_bare)
        alts.append(entry_bare_gz)   # 保險：全部 pattern 時也含行首裸干支
    else:
        # 純朱熹式（bare，非 bare_gz）：用通用 entry_bare（行首或句末）
        if fmt.get('bare') and not fmt.get('bare_gz'):
            alts.append(entry_bare)   # 放末尾：有年齡條目優先
        # 行首裸干支年標格式（bare_gz）：N年干支僅行首／句末元年；行首裸干支
        if fmt.get('bare_gz'):
            alts.append(entry_bare_ls)      # 行首完整年標（卷首）
            alts.append(entry_bare_se_yuan) # 句末元年（年號更替）
            alts.append(entry_bare_gz)      # 行首裸干支
    if not alts:   # 保險：分類異常導致空集合時退回全部，避免漏切
        alts = [ad_entry, birth, entry_sb, entry_no_sb, birth_direct,
                entry_sb_direct, birth_no_person, entry_sb_no_person, entry_bare, entry_bare_gz]
    return re.compile('(?:' + '|'.join(alts) + ')')
