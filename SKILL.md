---
name: nianpu-processor
description: 年譜處理器（nianpu-processor）工具。將中國年譜（chronological biography）文本按年份切分、自動補全年號、整理段落、**加標點／斷句**、**歸檔（複製到「年譜整理本」並更新清單）**。支援方柏堂（先生年N嵗）、萬清軒（直接年齡）、張清恪（公年N歲）、沈端恪（跨行年份+年齡）、公元年號/民國（公元一八七三年，同治十二年，岁次癸酉，一岁）等多種格式，已擴展至民國以後。標點由 LLM 依《標點規則》分塊執行（nianpu_biaodian.py：chunk→標點→merge→verify 字符保全校驗）；定稿後用 nianpu_archive.py 歸檔；改動腳本後用 tools/regression.py 跑回歸測試（testdata 黃金基線、自動生成 changelog 回歸行）。觸發詞：年譜、年谱、年月日、chronological biography、nianpu、nianpu-processor、加標點、断句、句读、标点、归档、归檔、整理本、清单、回歸測試、回归测试。
---

# 年譜整理工具 /nianpu-processor（入口頁）

一鍵處理中國年譜文本，完整管線：**年份切分/標題化 → 年號補全與字形正規化 → OCR 容錯 → 月份/季節分段 → 公元年標註 → 三錨點一致性檢查 → CBDB 核驗/年號誤配自動修正 → LLM 標點/斷句（字符保全校驗）→ 歸檔與清單同步**；帶自我進化（learnings.json）與回歸測試（tools/regression.py）。

> **本頁是入口，不是全文。** 只放執行必需的命令與決策規則；完整文件在 [README.md](README.md)（功能總覽、支援年份格式表、年號表、公元年換算、演算法、自訂配置、常見問題、更新日誌、已處理年譜清單）。需要細節時按需查閱 README，**勿在本頁補充易變事實**（版本號、部數、案例清單、更新日誌一律只活在 README）。

## 完整管線（收到「整理／加標點／歸檔某年譜」時依次執行）

```bash
# 1. 切分整理（含 L2 三錨點檢查、自動檢查報告、自我進化學習）
python nianpu_processor.py <輸入檔> [輸出檔]
# 2. 複查＋CBDB 生卒年核驗（--cbdb 不帶名時自動從卷首「公諱/先生諱」提取傳主）
python nianpu_processor.py --check <已整理.md> --cbdb <傳主名>
# 3. 一鍵套用年號誤配修正（CBDB 缺席時以內部「干支+年齡」共識出生年回退）
python nianpu_processor.py <輸入檔> [輸出檔] --fix
# 4. 三錨點衝突仲裁（--fix 無法判定時）：收集衝突 → LLM 逐條判定 → 保守套用＋復驗
python nianpu_arbitrate.py --request <已整理.md>     # → <名>_仲裁請求.md
python nianpu_arbitrate.py --apply <已整理.md> <仲裁結果.md>
# 5. 標點/斷句（正文無標點時）：分塊 → LLM 依 docs/標點規則.md 逐塊加標點（直接編輯 pun_XX.md）→ 合併（自動 verify）
python nianpu_biaodian.py --chunk <已整理.md>
python nianpu_biaodian.py --merge <已整理.md>        # → <名>_定稿.md
# 6. 歸檔（最後一步）：複製到年譜整理本＋同步 _清單.md/_清單.tsv
python nianpu_archive.py <定稿.md> [--book <書名>] [--date YYYY-MM-DD] [--note <備註>]
```

其他命令：

```bash
python nianpu_processor.py --record "錯" "對" [來源]   # 手動修正回饋（干支形近字累積 OCR 候選，不自動晉升）
python nianpu_processor.py --status                    # 學習狀態；--prune 清理無效記錄
python nianpu_processor.py <輸入> <輸出> --slots <槽位.json>   # 語義槽位配置（新格式不改正則）
python tools/regression.py --run                       # 改動腳本後必跑（回歸測試，詳見 docs/回歸測試.md）
python tools/regression.py --verify-learnings          # 學習質檢閘門：pending 條目逐條臨時套用→回歸→PASS 轉正
python nianpu_processor.py --revert                    # 回滾 learnings.json 最近一次寫入（.bak 單槽備份）
```

**路徑**：歸檔預設目錄與 `regression --full` 掃描根由環境變數 `NIANPU_ROOT` 解析（未設時為 `E:/2022/个人研究资料/年谱项目`；換機設定一次即可，見 README「路徑配置」）。

## 自主執行策略（AI 智能體必讀）

本工具旨在**一次呼叫、全自動完成一整套年譜處理**。收到「整理／加標點／歸檔某年譜」類指令時，依下列決策規則**自動執行，除非遇到必須人工裁決的真歧義，否則不要中途停下來問用戶**。

1. **不要問「格式／年號／是否需要標點／是否需要歸檔」**。所有這些都由工具自動檢測（`classify_format`、格式族判定、自我進化年號庫）。一律直接跑。
2. **遇新格式、新年號、新字形時，不問用戶**，交由工具的自動檢測與自我進化系統處理——這是本工具的設計目標（見 README「自我進化」章）；只有工具完全無法判讀（連起手格式都打不開）時才求助。
3. **預設跑完整管線**：切分整理 → `--check` 三錨點檢查 → `--cbdb` ／ `--fix`（含 CBDB 缺席時內部共識出生年回退）→ 三錨點衝突交 `--arbitrate` 仲裁 → （若原始正文無標點）`nianpu_biaodian` 分塊標點 → 最後**直接歸檔** `nianpu_archive`。上述每一步都不需向用戶確認即可執行。
4. **「供人工確認／供人工核對／候選規則」類輸出（如缺年清單、標點 verify 的「內容差異」、OCR 候選規則）是「結尾報告裡列給人看的清單」，不是「叫你在中途停下來等用戶」**。把這些項目**集中收進流程末尾的一次性總結報告**呈給用戶即可，不要為此中斷處理。
5. **自動修正的邊界**：OCR 誤字（有規律可循或比對可得）、年號年序錯位（干支＋年齡可校正）、跨行年份合併、標題補全、三錨點衝突（有共識／CBDB／干支參照時）→ **直接自動修**。只在完全沒有參照可依（無年齡、干支歧義、無 CBDB、共識不足以判定）的真正僵局時，才把該單項拿出來請用戶裁決——但仍先把其餘可自動處理的部分做完。
6. **完成定義**：走完上述管線並已歸檔後，輸出一次總結，單獨列出：標題數／覆蓋率／推定出生年／自動修正的清單（原→改）／待用戶人工確認的項目。這份總結即本輪工作的收尾，不需要再問「是否還要做 X」。

## 基本操作規則

1. **README.md 是唯一全文**——每次改進（腳本、learnings、成功案例）同步更新 README（功能、支援格式、更新日誌、已處理清單等）。**SKILL.md 只是入口**，不含易變事實，兩者不存在同步問題。
2. **每次處理新年譜成功後，記錄到 README「已成功處理的年譜」表**（含格式與備註）。
3. **手動修正要回饋到學習系統**——`--record` 錄入錯→對映射，經驗寫入 `learnings.json`（已納入版本管理，隨案例里程碑一併 commit）。
4. **改動腳本後回歸測試**——跑 `python tools/regression.py --run`，全部 PASS 才收工；有 FAIL 先修。功能確有改進時先 `--run` 確認 PASS，再 `--run --update` 刷新基線。注意：回歸標的為「基礎規則集」（不走 `apply_learnings()`），learnings 演化不在回歸範圍。
5. **學習條目須過質檢閘門才生效**——self_learn 發現的年號/前綴一律 `pending`，不會被自動應用；須跑 `python tools/regression.py --verify-learnings`（逐條臨時套用→回歸→PASS 轉正）。轉正錯了可 `python nianpu_processor.py --revert` 回滾最近一次 learnings 寫入。
6. **首年（出生條目）正文必須保留「{名}生於/生于/生/誕」等動詞**——標題只是借用日期顯示，正文出生句須原樣保留；常見錯誤形態與檢查法見 README「常見問題」。

## 文檔地圖

| 文檔 | 內容 |
|------|------|
| [README.md](README.md) | **唯一全文**：功能總覽、支援年份格式表、年號表、公元年換算、處理流程、演算法、自訂配置、路徑配置（NIANPU_ROOT）、常見問題、更新日誌、已處理年譜清單、許可證 |
| [docs/標點規則.md](docs/標點規則.md) | LLM 標點/斷句規則（逐塊標點前必讀） |
| [docs/回歸測試.md](docs/回歸測試.md) | 回歸套件設計（模式分級、黃金基線、既有缺口） |
| [docs/整理前後RAG效果對比報告.md](docs/整理前後RAG效果對比報告.md) | 整理價值實證（BM25 受限預算召回率） |
| [docs/年譜整理工具測試報告.md](docs/年譜整理工具測試報告.md) | 全量實測報告（覆蓋率/CBDB/三錨點/--fix/仲裁） |
| [docs/進化路線圖.md](docs/進化路線圖.md) | 後續進化方向（事件層、曆法引擎、校勘證據鏈等） |
| [../nianpu-social-network/SKILL.md](../nianpu-social-network/SKILL.md) | 下游延伸：人際網絡數據提取（hyperextract） |
