# Section 4 — Vector / RAG Design

TransitFlow 的 policy document search 使用 pgvector extension 搭配 Retrieval-Augmented Generation技術。這個設計讓助理可以根據乘客的問題，從資料庫中找出語意最相近的 policy document，再交給 LLM 生成回答。不依賴關鍵字比對，而是比較文字的語意，因此就算乘客的問法和 policy 的用詞完全不同，系統仍然可以找到正確的規則。

---

## What Is Embedded

系統將以下幾類 policy document 轉為 vector embeddings 存入資料庫：

```text
refund_policy.json        — 退款與補償規則
ticket_types.json         — 票種說明
booking_rules.json        — 訂票規則
travel_policies.json      — 旅行相關規定
```

每份文件都包含 `title`、`category` 和 `content` 三個欄位。在 seeding 時，`content` 欄位的文字會被轉換成一個 768 維的 vector，存入 `policy_documents` 資料表的 `embedding` 欄位。

---

## Why Cosine Similarity

系統使用 cosine similarity 來比較兩個 vectors 的相似程度。

Cosine similarity 衡量的是兩個 vectors 在高維空間中的方向差異，而不是它們的長度magnitude。text embedding 中同一個概念用長句或短句表達，產生的 vector 長度會不同，但方向會非常接近。如果只看方向，就可以純粹比較語意，不受文字長短影響，就是 magnitude-independent 。

以一個具體的例子說明：

```text
"my train was 45 minutes late, what do I get back?"
"delay compensation policy for national rail"
```

這兩段文字的用詞幾乎沒有重疊，但在 embedding space 中的方向接近，因為語意相同。Cosine similarity 可以測量到這個相似性，關鍵字搜尋則無法。

Cosine similarity 的值介於 0 和 1 之間。值越接近 1，代表兩個 vectors 的方向越接近，語意越相似；值越接近 0，表語意越不相關。系統設有 `VECTOR_SIMILARITY_THRESHOLD`（預設 0.5），低於這個門檻的結果不會被回傳。

---

## The Full RAG Pipeline

當使用者提出 policy 相關問題時，系統會依序執行以下四個階段(以Ollama為例)：

**1. Query Embedding**

使用者的問題會被傳入 `nomic-embed-text` 模型，轉換成一個 768 維的 vector。這個模型與 seeding 時使用的模型相同，確保兩邊的 embedding space 一致。

**2. Similarity Search**

pgvector 使用 `<=>` operator（cosine distance）將 query vector 與資料庫中所有 policy document vectors 進行比較，找出方向最接近的前幾筆文件（預設 top-3，由 `VECTOR_TOP_K` 控制）。

對應的 SQL query 如下：

```sql
SELECT title, category, content,
       1 - (embedding <=> %s::vector) AS similarity
FROM policy_documents
WHERE 1 - (embedding <=> %s::vector) > %s
ORDER BY embedding <=> %s::vector
LIMIT %s
```

**3. Context Retrieval**

資料庫回傳相似度最高的 policy documents，包含 `title`、`category`、`content` 和 similarity score。這些文件是 LLM 回答問題時的依據。

這一步所以能找到正確文件，因為系統比較的是 vector 的方向，而不是文字本身。就算乘客的問法與 policy 的標題措辭完全不同，只要語意對齊，cosine similarity 就能辨識出來。

**4. Answer Generation**

Retrieved documents 會被注入 LLM 的 prompt，Ollama 閱讀問題與 policy 內容後，根據 document 的規則生成回答，而不是自行推測或捏造規則。

整個流程如下：

```text
使用者問題
  → nomic-embed-text（轉為 768 維 vector）
  → pgvector similarity search（找最相近的 policy documents）
  → 回傳 top-K documents
  → 注入 LLM prompt
  → Ollama 生成回答
```

---

## Embedding Dimension and Provider Lock-in

本系統使用 Ollama 的 `nomic-embed-text` 模型，產生 **768 維** vectors。

如果改用 Gemini 的 `gemini-embedding-001` 模型，embedding dimension 會變成 **3072 維**。兩個 provider 的 embedding space 不同，dimension 也不一致。

這可能會產生問題：如果在 seeding 完成後才切換 provider，資料庫中已存入的是 768 維 vectors，但新的 query 產生的是 3072 維 vectors。pgvector 無法比較 dimension 不同的 vectors，所有 similarity search 都會失敗，整個 RAG pipeline 就此中斷。

要安全切換 provider，必須：

1. 清空 `policy_documents` 資料表中的所有 embeddings
2. 改用新 provider 的 embedding model 重新執行 `python skeleton/seed_vectors.py`

---

## Summary

TransitFlow 的 vector / RAG design 讓系統可以依據語意查詢 policy documents，不依賴關鍵字比對。Policy documents 在 seeding 時被轉為 768 維 embeddings，存入 pgvector。查詢時，使用者的問題同樣被轉為 vector，再透過 cosine similarity 找出語意最相近的 documents，交給 LLM 生成回答。

Cosine similarity 的優點在於它是 magnitude-independent 的，只比較 vector 的方向，因此可以準確捕捉語意相似性，不受文字長短或用詞差異影響。

Embedding dimension 與 provider 綁定。本系統使用 Ollama（768 維）。切換 provider 後必須重新 embed 所有 documents，否則 dimension mismatch 會導致 RAG 功能失效。

---
