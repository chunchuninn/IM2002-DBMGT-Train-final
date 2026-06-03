# Section 6 — Reflection & Trade-offs

---

## Design Decision 1：使用 JSONB 儲存 `stops_in_order` 和 `fare_classes`

在設計 `national_rail_schedules` 和 `metro_schedules` 表的過程中，我們選擇用 JSONB 欄位儲存 `stops_in_order`（站序陣列）和 `fare_classes`（票價結構），而不是建立獨立的 junction table。

具體理由如下：`stops_in_order` 是一個有序陣列，代表這個班次依序經過的站點。如果拆成獨立的 `schedule_stops` table，每次查詢站序都需要額外的 JOIN 和 `ORDER BY`，而且 stops 的順序是 schedule 的固有屬性，不會被其他 table 單獨修改或參照。用 JSONB 讓這個關係保持在同一行，查詢更直接。

`fare_classes` 的結構是 `{"standard": {"base_fare_usd": 2.50, "per_stop_rate_usd": 1.50}, "first": {...}}`，艙等數量固定，也不會被其他表單獨查詢。用 JSONB 讓票價結構與班次資料保持在同一筆記錄中，避免不必要的 JOIN。

這個決策的代價是無法對 JSONB 內部欄位建立一般的 B-tree index，但在這個系統的使用情境下，每次查詢都是讀取整個 schedule 的資料，這個代價是可以接受的。

---

## Design Decision 2：將 `user_credential` 獨立成一張表

在設計 user 相關 schema 時，我們選擇將 `stored_hash`、`secret_question` 和 `secret_answer_hash` 這些機敏欄位獨立到 `user_credential` 表，而不是直接放在 `users` 表中。

具體理由是 principle of least exposure：`users` 表儲存的是公開的個人資料（姓名、email、電話、生日），這些欄位在很多情境下都需要被查詢，例如顯示使用者名稱、驗證 email 是否存在、查詢訂單歸屬等。如果密碼 hash 和秘密答案 hash 也放在同一張表，所有對 `users` 的 SELECT 查詢都有機會意外帶出機敏資料。

將 credential 分離到獨立的表後，只有登入驗證和密碼重設這兩個明確的操作才需要存取 `user_credential`，其餘查詢不會碰到這些欄位。這讓機敏資料的存取範圍更窄，也更容易在未來對這張表單獨設定更嚴格的存取控制。

---

## Production Concern：Secret Management 與初始密碼的處理

目前的開發環境有兩個在 production 系統中需要改變的地方。

第一，`registered_users.json` 中的密碼是明文，seeding 完成後這個檔案仍然留在 repository 中。在 production 環境，初始帳號的密碼不應該存在版本控制裡。正確的做法是透過 secret management 系統（例如 HashiCorp Vault 或雲端平台的 AWS Secrets Manager）注入初始 credential，並在使用者第一次登入時強制要求修改密碼，確保明文密碼不會長期存在於任何地方。

第二，`.env` 檔案包含資料庫的連線帳號與密碼，目前靠 `.gitignore` 防止被意外 commit。在 production 環境，這種做法依賴開發者手動管理，風險較高。應該改用環境變數注入或 secret manager 統一管理，讓應用程式在啟動時從安全來源取得這些設定，而不是依賴本地的 `.env` 檔案。
