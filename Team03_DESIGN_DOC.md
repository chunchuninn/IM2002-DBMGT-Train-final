# Section 1 — Entity-Relationship Diagram
<img width="4109" height="2938" alt="final project ERD" src="https://github.com/user-attachments/assets/88772c2a-6710-47ad-af1b-5099e2cd6681" />


# Section2: Normalisation_Justification

| 評估維度 | 系統設計決策 | 解決之核心問題與預期效益 |
| :--- | :--- | :--- |
| **第三正規化 (3NF)** | 拆分車站實體屬性至獨立資料表 | 消除遞移相依以防止資料更新異常 |
| **反正規化 (De-norm)** | 將停靠站清單壓縮為單一 JSONB 陣列 | 迴避中介表關聯查詢以獲取極致讀取效能 |
| **密碼雜湊演算法** | 導入具備金鑰延展特性的 Argon2id | 墊高硬體運算成本以抵禦暴力破解攻擊 |
| **鹽值防護機制** | 強制為每筆憑證生成獨立且隨機之鹽值 | 確保相同密碼產出相異雜湊值以破除彩虹表 |

---

## 一、 第三正規化 (3NF) 設計決策

系統的 `national_rail_bookings` 資料表以 `booking_id` 作為主鍵來記錄購票交易資訊並僅儲存起迄站的 `station_id`。這些車站的實體名稱在功能相依（Functional Dependency）上完全依賴於作為候選鍵（Candidate Key）的 `station_id` 而非訂單主鍵。若將車站名稱直接寫入訂單紀錄將引發遞移相依（Transitive Dependency）問題而導致未來車站更名時必須同時修改海量歷史訂單。系統將車站實體屬性獨立拆分至 `national_rail_stations` 資料表以徹底消除遞移相依並確保資料庫架構符合第三正規化（3NF）的嚴謹標準。

系統的 `national_rail_schedules` 火車時刻表資料表同樣遵循第三正規化原則而僅透過 `layout_id` 來關聯座位配置。座位樣板的名稱與車廂排列細節在功能相依上完全依賴於 `layout_id` 而非時刻表主鍵 `schedule_id`。若將車廂結構直接寫入時刻表將導致所有採用同款車型的營運班次重複儲存相同的實體規格資料。系統將硬體規格獨立至 `national_rail_seat_layouts` 資料表以避免未來車隊改裝時必須逐一修改各班次設定所引發的更新異常。

系統的 `feedback` 意見回饋資料表與 `payments` 金流資料表在記錄互動與交易時僅儲存關聯的 `user_id` 而不包含使用者的電子郵件或姓名。這些個人聯絡資訊依賴於使用者主鍵 `user_id` 而非回饋紀錄的 `feedback_id` 或付款紀錄的 `payment_id`。若將使用者姓名寫入這些交易事實表將形成遞移相依並在使用者更改帳戶資訊時造成嚴重的資料不一致。這項設計確保了資料庫在處理頻繁新增的龐大營運紀錄時能維持無冗餘的正規化狀態。

---

## 二、 刻意的反正規化 (De-normalisation) 妥協

關聯式資料庫的傳統第一正規化（1NF）要求資料表欄位必須保持原子性以避免包含多重值。系統的 `national_rail_schedules` 資料表針對停靠站紀錄選擇跳過建立中介表（Junction Table）的正規化做法而直接將 `stops_in_order` 設計為儲存 JSONB 陣列的單一欄位。這項刻意的反正規化（De-normalisation）策略建立在火車沿線停靠站屬於高度穩定且極少變動的靜態資料特性之上。由於應用程式在查詢時刻表時必定需要一次性讀取完整的停站清單，將所有站點壓縮於單一陣列能避免跨表關聯查詢（JOIN）帶來的效能損耗而在維持資料正確性的同時換取了極致的讀取效能。

---

## 三、 密碼雜湊演算法的選擇

系統處理使用者安全憑證時採用 Argon2id 演算法來取代 MD5 與 SHA-1 等早期雜湊技術。MD5 與 SHA-1 在初始設計上極度追求資料處理與運算的速度。這種對運算速度的追求在現代資安環境中反而成為嚴重的安全漏洞。攻擊者能夠輕易利用現代圖形處理器等平行運算硬體每秒執行數十億次的暴力破解猜測。系統為了解決硬體加速猜測的威脅而必須主動增加單次雜湊的運算成本。Argon2id 演算法透過名為金鑰延展（Key stretching）的技術來實現這項成本控制。金鑰延展技術允許系統配置特定的時間成本與記憶體消耗量來刻意拖慢密碼處理的過程。這項資源消耗機制透過強制佔用大量記憶體與拉長運算時間來大幅墊高攻擊者的硬體投入成本，進而在面對針對性密碼猜測攻擊時展現出遠優於早期演算法的防護能力。

---

## 四、 鹽值管理與防禦機制

攻擊者發動彩虹表攻擊（Rainbow-table attack）時會預先計算大量常見密碼的雜湊值以建立龐大的對照表並在取得資料庫存取權後進行反查。系統為防禦此類攻擊會在每次建立新使用者的憑證時利用亂數生成器產生一組唯一的鹽值（Salt）。這組隨機字串會與使用者的明文密碼結合後才送入雜湊函數進行運算，例如當兩位使用者皆設定「password123」為密碼時，各自獨立的鹽值將使資料庫最終儲存的雜湊結果截然不同。這項機制使得攻擊者耗費巨資建立的彩虹表無法找到對應的雜湊值而徹底阻斷了透過預先計算進行反向破解的系統威脅。


# Section 3 — Graph Database Design Rationale  

TransitFlow 的 Neo4j graph database 用來建模城市捷運與國鐵系統中的站點連線關係。這個系統包含 city metro network 與 national rail network，兩者都由 stations、lines、adjacent stations 與 interchange points 組成。由於 route planning、cross-network transfer、alternative route search 和 delay ripple analysis 都需要沿著站點之間的連線進行多層查詢，因此使用 graph database 可以更自然地表達這類交通網路結構。

在 graph model 中，station 被設計為 node，站點之間的直接行駛路段被設計為 relationship，而每段連線上的 line、travel time 等資訊則作為 relationship properties。這樣的設計讓系統可以直接透過 graph traversal 查詢路線，而不需要在 relational table 中反覆進行多層 join。

---

## Nodes

Neo4j 中主要設計兩種 node labels：

```text
MetroStation
NationalRailStation
```

`MetroStation` 代表 city metro network 中的捷運站。每個 metro station 都是一個獨立 node，因為 station 是乘客移動與路線規劃的基本單位。Metro station 的主要 properties 包含：

```text
station_id
name
lines
```

其中，`station_id` 是系統內部使用的唯一識別碼，例如 `MS01`、`MS02`；`name` 是站點名稱，例如 Central Square、Riverside；`lines` 則記錄該站服務的 metro lines，例如 M1、M2、M3 或 M4。

`NationalRailStation` 代表 national rail network 中的國鐵站。它和 `MetroStation` 分開設計，是因為 metro 和 national rail 屬於不同的交通網路，路線結構與轉乘邏輯也不同。National rail station 的主要 properties 包含：

```text
station_id
name
lines
```

其中，`station_id` 例如 `NR01`、`NR02`；`name` 是站點名稱，例如 Central Station、Maplewood；`lines` 則記錄該站服務的 national rail lines，例如 NR1 或 NR2。

這些 properties 被放在 node 上，是因為它們描述的是 station 本身。例如，站名、站點 ID、該站服務哪些 lines，都是單一站點的基本資訊，而不是兩個站點之間的連線資訊。

---

## Relationships

Neo4j 中主要設計三種 relationship types：

```text
(:MetroStation)-[:METRO_LINK]->(:MetroStation)

(:NationalRailStation)-[:RAIL_LINK]->(:NationalRailStation)

(:MetroStation)-[:TRANSFER_TO]->(:NationalRailStation)
```

`METRO_LINK` 表示兩個相鄰 metro stations 之間的直接連線。這種 relationship 代表乘客可以直接從一個捷運站搭乘到下一個捷運站。例如，`MS01` 可以透過 M1 連到 `MS02`，也可以透過 M2 連到 `MS07`。因此，`METRO_LINK` 用來描述 metro network 內部的 station-to-station connection。

`METRO_LINK` 的主要 properties 包含：

```text
line
travel_time_min
```

`line` 表示該段連線屬於哪一條 metro line，例如 M1 或 M2。`travel_time_min` 表示這兩個站點之間的預估旅行時間。

`RAIL_LINK` 表示兩個相鄰 national rail stations 之間的直接連線。這種 relationship 代表乘客可以直接從一個國鐵站搭乘到下一個國鐵站。例如，`NR01` 可以透過 NR1 連到 `NR02`，也可以透過 NR2 連到 `NR06`。因此，`RAIL_LINK` 用來描述 national rail network 內部的 station-to-station connection。

`RAIL_LINK` 的主要 properties 包含：

```text
line
travel_time_min
```

`line` 表示該段連線屬於哪一條 national rail line，例如 NR1 或 NR2。`travel_time_min` 表示這兩個站點之間的預估旅行時間。

`TRANSFER_TO` 表示 metro station 和 national rail station 之間的 walkway / transfer passage。對於同時具有 metro 和 national rail 轉乘功能的地點，我們沒有將兩個系統合併成同一個 node，而是分別建立 metro station node 和 national rail station node，再用 `TRANSFER_TO` relationship 連接。

例如：

```text
MS01 Central Square  ↔  NR01 Central Station
MS07 Old Town        ↔  NR03 Old Town Junction
MS15 Ferndale        ↔  NR07 Ferndale Rail
```

雖然這些站點在現實中可能位於同一個交通樞紐或相鄰區域，但在系統設計上，它們仍然代表不同的交通網路節點。`MS01` 是 metro network 中的 station，而 `NR01` 是 national rail network 中的 station。兩者服務的 lines、fare rules、schedule logic 和 routing behavior 都不同，因此不應該被合併成同一個 node。

中間的 `TRANSFER_TO` relationship 則代表乘客從 metro platform 走到 national rail platform 的實體 walkway，而不是列車行駛路段。這樣設計可以保留兩種交通網路各自的結構，同時又能支援跨系統路線查詢。

`TRANSFER_TO` 的主要 properties 包含：

```text
type
travel_time_min
```

`type` 可以表示轉乘方式，例如 `Walkway`；`travel_time_min` 表示完成轉乘需要的時間。這樣在計算跨系統路線時，Dijkstra’s algorithm 可以把 walkway 的時間成本一起納入總旅行時間，而不是把轉乘視為零成本。

這個設計比直接合併 station node 更準確，因為它可以同時保留兩個交通系統的獨立性，並且清楚表達跨系統轉乘所需的時間與路徑。如果將 metro station 和 rail station 合併成同一個 node，系統就無法準確表示轉乘時間，也無法區分「在同一個交通系統內換線」與「跨系統轉乘」這兩種不同情境。

---

## Properties Design

在這個 graph model 中，node properties 和 relationship properties 的分工是根據資料的語意決定的。

`station_id`、`name` 和 `lines` 被放在 station node 上，因為它們描述的是 station 本身。例如，`MS01` 的站名是 Central Square，服務 M1 和 M2；`NR01` 的站名是 Central Station，服務 NR1 和 NR2。這些資訊不會因為前往哪個相鄰站而改變，因此適合作為 node properties。

相對地，`line` 和 `travel_time_min` 被放在 relationship 上，因為它們描述的是兩個站點之間的連線。例如，`MS01` 到 `MS02` 和 `MS01` 到 `MS07` 是不同的連線，可能屬於不同 lines，也有不同的 travel time。如果把這些資訊放在 station node 上，會無法準確表達每一段 route segment 的差異。

因此，將 `travel_time_min` 放在 relationship 上，可以讓系統把每一段 station-to-station connection 當成一條 weighted edge。後續在做 fastest route search 時，Dijkstra’s algorithm 就可以直接使用 `travel_time_min` 作為 edge weight，找出總旅行時間最短的 path。

---

## Node Identity

Graph database 使用 `station_id` 作為 station node 的唯一識別欄位。

例如：

```text
MS01 = Central Square
MS07 = Old Town
NR01 = Central Station
NR03 = Old Town Junction
```

選擇 `station_id` 作為 node identity，是因為它比 station name 更穩定，也更適合作為系統內部查詢與建立 relationships 的 key。站名可能會有相似名稱或顯示名稱調整，但 `station_id` 是固定的系統識別碼，可以避免查詢時發生混淆。

此外，`station_id` 的 prefix 也能清楚區分不同交通網路。`MS` 代表 metro station，`NR` 代表 national rail station。這讓 query function 可以使用一致的方式接收 origin 和 destination，例如：

```cypher
MATCH (start {station_id: $origin}), (end {station_id: $dest})
```

這種設計讓 route search、interchange path、alternative route 和 delay ripple analysis 都可以用相同的 identity property 進行查詢。

---

## Why Graph Database Is Suitable for This Design  

TransitFlow 的核心查詢需求是 route planning，而 route planning 本質上是 graph traversal problem。使用者通常不只是查詢單一 station 的資料，而是想知道兩個 stations 之間如何連接、哪一條 path 最快、是否需要轉乘，以及某個 station 發生延誤時會影響哪些相鄰 stations。

在 graph database 中，這些問題可以直接透過 nodes 和 relationships 表達。Station 是 node，station-to-station connection 是 relationship，travel time 是 relationship weight。這樣的資料結構和交通網路本身高度一致。

以 fastest route search 為例，Neo4j 可以使用 Dijkstra’s algorithm。系統從 origin station node 出發，沿著 `METRO_LINK`、`RAIL_LINK` 或 `TRANSFER_TO` relationships 搜尋 destination station，並使用 `travel_time_min` 作為 edge weight。Dijkstra’s algorithm 會持續選擇目前累積成本最低的下一個可到達 station，最後找出總旅行時間最低的 path。

如果使用 relational database 實作同樣的 multi-hop routing，則需要透過 recursive CTE 反覆查詢 station connection table。SQL query 需要不斷將 connection table 與自身 join，累積目前走過的 path，記錄已經拜訪過的 stations 以避免 cycle，計算每一條可能 path 的 total travel time，最後再從所有候選路徑中選出成本最低的結果。雖然這在 SQL 中可以做到，但寫法會更複雜，也比較不符合交通網路本身的資料結構。

對於 delay ripple analysis，graph database 也更自然。當某個 station 發生延誤時，系統可以從該 station 出發，沿著 `METRO_LINK`、`RAIL_LINK` 和 `TRANSFER_TO` relationships 向外擴展，找出 one-hop、two-hop 或更多 hops 以內可能受到影響的 stations。這個邏輯接近 breadth-first search，也就是 BFS。相較之下，如果用 relational database 實作，就需要再次使用 recursive CTE，一層一層展開相鄰 stations。Neo4j 因為直接把 relationships 當成資料模型的一部分，所以可以更直接地表達這種 N-hop traversal。


---

## Query Type 1: Fastest Route Search

第一種 query type 是 fastest route search，也就是查詢兩個 stations 之間總旅行時間最短的路線。

系統會接收：

```text
origin_id
destination_id
network
```

當 `network = metro` 時，系統只會 traversing `METRO_LINK`。  
當 `network = rail` 時，系統只會 traversing `RAIL_LINK`。  
當 `network = auto` 時，系統會同時 traversing：

```text
METRO_LINK
RAIL_LINK
TRANSFER_TO
```

這樣的設計讓同一個 route search function 可以支援 metro-only、rail-only 和 cross-network journeys。

在 fastest route search 中，`travel_time_min` 被當作 edge weight，因此系統找出的不是經過站數最少的 route，而是總旅行時間最低的 route。這比較符合實際交通情境，因為站數較少不一定代表旅行時間較短，尤其是在 metro、national rail 和 transfer path 同時存在的情況下。

---

## Query Type 2: Cross-Network Interchange Path

第二種 query type 是 cross-network interchange path，也就是查詢 metro 和 national rail 之間的跨系統路線。

這個查詢依賴 `TRANSFER_TO` relationships。`TRANSFER_TO` 把原本分開的 metro network 和 national rail network 連接起來，讓 route search 可以從 metro station 走到 national rail station，或從 national rail station 走到 metro station。

例如：

```text
MS01 ↔ NR01
MS07 ↔ NR03
MS15 ↔ NR07
```

這些 transfer relationships 讓系統可以在同一條 path 中同時包含 metro segments、rail segments 和 transfer segments。當系統查詢 cross-network route 時，它可以同時 traversing `METRO_LINK`、`RAIL_LINK` 和 `TRANSFER_TO`，並回傳完整的 route legs。

這種設計也讓系統可以指出具體的 interchange points，而不是只回傳起點和終點。對使用者來說，這可以清楚知道在哪一站需要從 metro 轉到 national rail，或從 national rail 轉到 metro。

---

## Query Type 3: Alternative Route Avoiding a Station

第三種 query type 是 alternative route search，也就是在某個 station 無法通行時，查詢避開該 station 的替代路線。

這類 query 會接收：

```text
origin_id
destination_id
avoid_station_id
network
```

系統會將 `avoid_station_id` 對應的 station node 排除在 path 之外，然後重新搜尋 origin 到 destination 的可行路線。這個功能適合處理 station closure、service disruption 或 temporary congestion。

在 graph model 中，避開某個 station 的邏輯很直覺，因為 route 本身就是一串 station nodes 和 connection relationships。系統只要在 traversal 過程中排除特定 node，就可以避免回傳經過該站的 path。

---

## Query Type 4: Delay Ripple Analysis  

第四種 query type 是 delay ripple analysis，也就是查詢某個 station 發生延誤時，哪些 nearby stations 可能受到影響。

這個查詢之所以適合 graph model，是因為延誤影響通常會沿著實體交通連線向外擴散。如果 `NR03` 發生延誤，系統可以從 `NR03` 這個 node 出發，沿著與它相連的 relationships 找出直接受到影響的 stations。例如，`NR03` 可以透過 `RAIL_LINK` 連到 `NR02` 和 `NR04`，也可以透過 `TRANSFER_TO` walkway 連到 metro station `MS07`。因此，graph model 可以同時捕捉 rail network 內部的影響，以及跨系統轉乘可能造成的影響。

這個查詢邏輯接近 breadth-first search。系統可以先找出 one-hop neighbors，也就是與 delayed station 直接相連的站點；如果需要分析更大的影響範圍，也可以繼續往外找 two-hop 或 N-hop neighbors。因為 Neo4j 已經把 stations 存成 nodes，並把 station-to-station connections 存成 relationships，所以查詢可以直接沿著真實交通網路的結構進行 traversal。

如果使用 relational database，則需要透過 recursive CTE 反覆查詢 connection table，才能逐層展開相鄰站點。相比之下，graph database 的 node / relationship structure 更自然地支援 delay ripple analysis，也更容易控制查詢範圍，例如只查一跳、兩跳，或指定 relationship types。


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
