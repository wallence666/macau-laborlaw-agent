# 澳門勞動法資訊 Agent MVP

這是一個依照 `勞動法Agent_MVP企劃書.md` 實作的最小可執行垂直切片。第一版先把資料契約、檢索、引用驗證、風險升級與 CLI 串起來，不急著拆成多個服務。

![澳門勞動法 Agent 介面](docs/images/demo.png)

## 目前安全邊界

- 法域固定為澳門特別行政區。
- 只使用 `data/source-registry/registry.json` 中 `review_status=approved` 且符合生效日期的來源。
- 沒有已審核來源時，系統會回傳 `insufficient_sources`，不會自行生成法條、條號或法律結論。
- 每個法律主張都必須對應到系統實際取得的證據，並通過逐字引用驗證。
- 高風險、證據不足、版本衝突、引用失敗或角色衝突會要求真人處理。
- 預設審計紀錄只保存來源 ID、狀態與風險代碼，不保存原始問題、個人資料或案件事實。
- 輸出不是正式法律意見。

目前已從澳門特別行政區公報與法務局 LegisMac 匯入 4 個官方來源、106 個 provision。依照專案擁有者要求，來源現時標記為 `review_status=approved`、`review_scope=test_only`，方便在本機測試 Agent。

這批來源沒有經澳門法律專業人士覆核，只可用於個人開發與測試，不可用於實際個案。Agent 每次使用這些來源時都會在 `risks` 加入測試用途警告。

目前匯入範圍：

- 第 7/2008 號法律《勞動關係法》，第 134/2020 號行政長官批示重新公佈的合併版。
- 第 23/2024 號法律修改的第七十條，自 2024-12-27 生效。
- 第 9/2026 號法律即日生效的第五十四條及第五十六條，自 2026-07-28 生效。
- 第 9/2026 號法律延後生效的第四十六條、第七十五條及第八十五條，自 2027-01-01 生效。

來源 PDF 位於 `data/snapshots/mo/`，逐字引用與 checksum 見 `docs/official-source-import.md`。

## 執行

需求：Python 3.11 或以上。

### 可視化介面

#### 啟動

```powershell
python run_ui.py
```

開啟 `http://127.0.0.1:8765`。介面包含案件角色、事件日期、補充事實、動態追問、法源原文、風險提示及 `trace_id`。前端與 API 均由本機 Python 標準庫提供，不依賴外部服務。

指定其他連接埠：

```powershell
python run_ui.py --port 8877
```

#### 停止

若服務在前景終端執行，按：

```text
Ctrl+C
```

若使用另一個 PowerShell 視窗停止預設連接埠 `8765`：

```powershell
$port = 8765
Get-NetTCPConnection -LocalPort $port -State Listen |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

確認服務已停止：

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
```

若命令沒有輸出，代表 `8765` 已無服務。

在 Linux 或 macOS 停止服務：

```bash
lsof -ti tcp:8765 | xargs kill
```

當使用者無法提供追問所需的資料時，可選擇「按現有資料分析」。系統會繼續檢索並回傳有限分析，同時保留未提供事實、加入 `partial_analysis` 風險提示；高風險、引用失敗或來源不足仍會阻止回答。

右上角「問題已解決」會關閉目前案件的伺服器狀態，清空對話、事實與回答，並建立新的 `case_id`。歷史紀錄按鈕可查看之前的問題、回答狀態、摘要、條號與 `trace_id`；紀錄只保存在本機瀏覽器，最多保留 30 筆，不保存 API Key 或完整案件事實。

右上角「規則模式」可開啟 AI 模型設定。介面支援 OpenAI-compatible
`/chat/completions` 端點，可設定 Base URL、模型名稱、API Key 及
Temperature。API Key 預設只保存在目前頁面的 JavaScript 記憶體；勾選
「只在這個瀏覽器分頁記住設定」後才寫入 `sessionStorage`，不會寫入
registry、SQLite 或審計檔。

![AI 模型設定](docs/images/model-settings.png)

模型啟用後會負責：

- 從自然語言抽取日期、議題與檢索查詢。
- 根據檢索到的原文產生受證據約束的分析。

A3 檢索、A5 引用驗證與 A6 風險升級仍是確定性程式控制。模型未能提供精確引文時，系統會阻止回答並要求真人處理。沒有 API Key 時，介面維持規則模式。

每個 provision 現在保存 `page_start`、`page_end` 及 PDF 端點。法源卡片上的「PDF 第 N 頁」會開啟官方 PDF 快照並跳至對應頁面，方便直接核對原文。

![PDF 頁碼引用](docs/images/pdf-link.png)

### 命令列

```powershell
python run_agent.py `
  --query "工資沒有依時支付，我可以怎樣做？" `
  --role employee `
  --fact work_location=澳門 `
  --fact event_date=2026-09-01
```

輸出為結構化 JSON。上述例子目前可以取得《勞動關係法》第六十二條，回傳基本報酬應於支付義務到期日起九個工作日內支付，並附上測試用途警告。

直接使用套件模組：

```powershell
$env:PYTHONPATH="src"
python -m laborlaw_agent `
  --query "公司更改我的休息日" `
  --role employee `
  --fact work_location=澳門 `
  --fact event_date=2026-09-01
```

互動追問模式會持續要求缺少的事實，直到工作流完成或需要真人處理：

```powershell
python run_agent.py --interactive
```

## 測試

```powershell
python -m pytest
```

測試使用明確標示為 `[測試資料]` 且網域為 `test.invalid` 的來源，只驗證程式契約，不代表任何澳門法律內容。

## 目錄

```text
src/laborlaw_agent/
├── models.py       # 共用狀態、證據與回答 schema
├── policies.py     # 議題、必要事實與高風險規則
├── repository.py   # 官方來源 registry、版本過濾與檢索
├── agents.py       # A1-A8 邏輯角色
├── workflow.py     # A0 協調、停止與升級
├── audit.py        # 最小化審計紀錄
├── cli.py          # 命令列介面
└── web/            # 本機 Web API 與靜態前端
```

## 加入已審核來源

`data/source-registry/registry.json` 的 `sources` 陣列每筆資料需包含企劃書要求的來源 metadata，並以 `provisions` 保存條文層級內容。只有法律審核者確認後，才可把 `review_status` 設為 `approved`。

詳細欄位與政策見 `docs/source-policy.md` 和 `docs/agent-contracts.md`。

AI 模型接線說明見 `docs/llm-integration.md`。

## 授權

本專案使用 MIT License，詳見 `LICENSE`。系統輸出只供資訊與初步風險評估，不構成正式法律意見。

## 重建官方來源索引

在 Codex 主執行環境中，使用內附的 PDF 依賴執行：

```powershell
$env:PYTHONPATH="C:\Users\walle\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
python scripts/build_macau_labor_registry.py --approve-for-testing
```

未傳入 `--approve-for-testing` 時，腳本會把來源標記為 `pending`。測試核准不是法律審核，也不會產生 `review_scope=production` 的來源。
