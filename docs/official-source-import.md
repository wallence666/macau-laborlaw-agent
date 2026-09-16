# 官方來源匯入紀錄

## 匯入日期

2026-09-15

## 方法

1. 由澳門特別行政區政府入口網站的法律法規入口導向法務局 LegisMac。
2. 以官方檢索取得《勞動關係法》及其修訂法律紀錄。
3. 下載官方公報 PDF，計算 SHA-256 後保存於 `data/snapshots/mo/`。
4. 從中葡雙語 PDF 的版面中擷取中文直欄，依條文標題切分為 provision。
5. 對修改條文保留版本與生效日期，不把尚未生效的內容提前套用。
6. 每個 provision 同時記錄 PDF 的 `page_start` 與 `page_end`，前端可跳至原始頁面核對。

## 來源

### 第 7/2008 號法律《勞動關係法》2020 合併版

- 官方紀錄：https://search.bo.dsaj.gov.mo/zh-mo/legismac/58185
- 重新公佈批示：第 134/2020 號行政長官批示
- 公報：2020-06-22，第 25 期第一組
- 本地快照：`data/snapshots/mo/mo-labor-relations-law-7-2008-consolidated-2020.pdf`
- SHA-256：`74d53c606ad84c4a956bc0da305bce65bebfa5b2d93f1fa11fd4800e106aeb1d`

### 第 23/2024 號法律

- 官方紀錄：https://search.bo.dsaj.gov.mo/zh-mo/legismac/92511
- 修改內容：第 7/2008 號法律第七十條
- 公報：2024-12-26
- 生效：2024-12-27
- 本地快照：`data/snapshots/mo/mo-law-23-2024-amendment.pdf`
- SHA-256：`7171f3396483af36ad7ab4354c8fe776cc08345eb6986f774f1c73cb1b7460f4`

### 第 9/2026 號法律

- 官方紀錄：https://search.bo.dsaj.gov.mo/zh-mo/legismac/95002
- 公報：2026-07-27
- 即日生效：2026-07-28
- 即日修改：第 7/2008 號法律第五十四條及第五十六條
- 延後生效：2027-01-01
- 延後修改：第 7/2008 號法律第四十六條、第七十五條及第八十五條
- 本地快照：`data/snapshots/mo/mo-law-9-2026-amendment.pdf`
- SHA-256：`1637ada783b0da8c80fb61dcddc481b7972546b7d36f8efddb716cae8ee6cd0e`

## 審核狀態

依照專案擁有者要求，目前 registry 的來源標記為：

```text
review_status = approved
review_scope = test_only
reviewed_by = 專案使用者測試授權（非法律審核）
```

Codex 已完成官方來源定位、下載、checksum、版本日期與條文切分，但不具備代替澳門法律專業人士進行法律審核的資格。這批來源只可用於個人開發與測試，不可用於實際個案。

真人覆核至少應確認：

- 法規標題、編號與官方網址。
- 中文文本是否與官方 PDF 一致。
- 每條 provision 的生效日期與版本切換是否正確。
- 2027-01-01 延後生效條文的觸發日期。
- 是否有未納入本版的相關澳門法規或官方指引。

正式使用前，必須由澳門法律專業人士完成覆核，將 `review_scope` 改為 `production`，並在 `reviewed_by` 記錄審核者。
