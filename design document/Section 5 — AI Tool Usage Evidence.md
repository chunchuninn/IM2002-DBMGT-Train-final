# Section 5 — AI Tool Usage Evidence

## Example 1 — Schema 設計：兩張 station 表之間的循環外鍵問題

**Context**

在設計 `schema.sql` 的過程中，`metro_stations` 和 `national_rail_stations` 兩張表需要互相參照：`metro_stations.interchange_national_rail_station_id` 參照 `national_rail_stations`，而 `national_rail_stations.interchange_metro_station_id` 則參照 `metro_stations`。這造成了循環 foreign key 依賴關係。問題在於 seeding 時，兩張表都需要先有資料另一張才能建立 FK，但 PostgreSQL 預設在每一行 insert 時就立即驗證 FK，導致無論先插入哪一張表都會出錯。

**Prompt**

> 我有兩張表互相有 foreign key，metro_stations 參照 national_rail_stations，national_rail_stations 也參照 metro_stations。seeding 時不管先插哪張都會 FK violation，要怎麼解決？

**Outcome**

Claude 建議在兩個 `ALTER TABLE` constraint 的結尾加上 `DEFERRABLE INITIALLY DEFERRED`。這個設定讓 PostgreSQL 把 FK 驗證延後到整個 transaction commit 時才執行，而不是每行 insert 後立即檢查。這樣兩張表就可以在同一個 transaction 內依序插入，commit 時兩邊都已有資料，FK 驗證就能通過。這個建議是正確的，直接套用到 `schema.sql` 後問題解決。

---

## Example 2 — 除錯：Cypher 檔案解析器在 UNWIND 區塊失敗（AI 給出錯誤答案的案例）

**Context**

`skeleton/seed_neo4j.py` 需要讀取 `databases/graph/seed.cypher` 並逐一執行其中的 Cypher statements。Cypher 檔案包含 `CREATE CONSTRAINT`、`MERGE` 和 `UNWIND` 等不同類型的語句，每個語句以分號結尾。AI 撰寫了一個用分號切割的 parser 來拆出每個 statement。

**Prompt**

> seed_neo4j.py 用分號切割 seed.cypher 並執行每個 statement。CONSTRAINT 的部分正常，但第三個 statement 報錯：「WITH is required between MERGE and UNWIND」，要怎麼修 parser？

**Outcome**

Claude 的第一個修正方案加入了 CRLF 正規化與更嚴格的 comment 過濾，但錯誤仍然出現，parser 仍然只切出 5 個 statements。AI 一開始判斷問題出在 Python 的解析邏輯，但真正的原因其實是 `seed.cypher` 裡有兩行 `MERGE` 語句漏掉了結尾分號——MS20 Thornton 那行和 NR10 Langford End 那行都缺少 `;`，導致 parser 把它們和後面的 `UNWIND` 區塊合併成一個無效的 statement。

這個問題是透過執行 `grep -n ";" databases/graph/seed.cypher` 來計算實際分號數量，再對照預期的 statement 數量才發現的。解法是直接在 `seed.cypher` 的兩行補上缺少的分號，而不是修改 parser。這是一個 AI 診斷錯誤方向的案例——它把注意力放在 Python 程式碼上，但問題實際上出在資料檔案本身。

---

## Example 3 — Seeding 邏輯：將 payments 和 feedback 分流到正確的欄位

**Context**

`payments.json` 和 `feedback.json` 都只有單一個 `booking_id` 欄位，但這個 ID 可能指向訂單BK或搭乘紀錄MT。Schema 設計了兩個獨立的 nullable FK 欄位——`national_rail_booking_id` 和 `metro_travel_id`——並用 CHECK constraint 確保每筆紀錄只能填其中一個。Seeding 時需要判斷每筆資料應該填入哪個欄位。

**Prompt**

> payments.json 裡的 booking_id 可能是 BK001 或 MT001。我的 schema 有兩個獨立的 FK 欄位，seeding 時要怎麼判斷該填哪個？

**Outcome**

Claude 建議用 `booking_id` 的前綴作為分流依據：`BK` 開頭填入 `national_rail_booking_id`，`MT` 開頭填入 `metro_travel_id`，遇到無法識別的前綴則直接 raise `ValueError`，讓壞資料在 seeding 階段就被發現，而不是無聲地略過。同樣的邏輯也套用在 `feedback` 的 seeding 上。這個方法不需要額外的資料庫查詢，直接配合 schema 的 exclusive arc CHECK constraint 運作，建議正確且直接採用。

---
