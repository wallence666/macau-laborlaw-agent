# AI 模型接線

## 介面

Web UI 右上角提供模型設定，支援 OpenAI-compatible Chat Completions
端點：

```text
POST {BASE_URL}/chat/completions
Authorization: Bearer {API_KEY}
```

Base URL 可為：

```text
https://api.openai.com/v1
http://127.0.0.1:11434/v1
```

本機端點可不填 API Key；遠端端點必須提供 API Key。

## DeepSeek 範例

依 DeepSeek 官方 API 文件，設定如下：

```text
Base URL：https://api.deepseek.com
模型名稱：deepseek-flash
```

Agent 會呼叫：

```text
https://api.deepseek.com/chat/completions
```

`deepseek-v4-flash` 是舊名稱，目前官方以 `deepseek-flash` 作為模型名稱。

DeepSeek 的 thinking mode 預設為 enabled，且預設 reasoning effort 為
`high`。結構化 JSON 任務若沿用預設值，推理 token 可能耗盡 `max_tokens`，
使最終 `message.content` 為空或被截斷。Agent 對 DeepSeek 請求會明確加入：

```json
{"thinking": {"type": "disabled"}}
```

若模型仍回傳空 content 或不可解析內容，Agent 會提高輸出額度並自動重試
一次，同時回報 `finish_reason` 與 `reasoning_content` 狀態，方便排除問題。

## Windows socket 錯誤

若測試連線出現 `WinError 10013`，表示執行 `run_ui.py` 的 Python 程序沒有
Windows socket 權限，並非 API Key 或模型名稱錯誤。重新啟動服務時必須允許
Python 使用網絡：

```powershell
python run_ui.py --port 8766
```

## 模型工作

模型只負責需要語言理解的步驟：

1. A1 事實抽取：把相對日期和口語描述轉成結構化事實。
2. A2 檢索規劃：產生語義檢索查詢，但不得生成法條編號。
3. A4 分析：只根據 A3 取得的 evidence 產生條文說明。

每條 A4 分析都必須包含：

```json
{
  "statement": "分析說明",
  "evidence_id": "evidence-id",
  "quote": "evidence 原文中的精確片段"
}
```

## 不可交給模型控制的步驟

- A3 只能查詢已審核 registry。
- A5 會逐字驗證 quote，失敗即阻止回答。
- A6 保留法域、高風險、引用失敗與版本衝突的升級權。
- 模型不得引入未提供的法條、金額、期限、判例或程序。
- API Key 不會寫入案件狀態、審計紀錄或來源 registry。
