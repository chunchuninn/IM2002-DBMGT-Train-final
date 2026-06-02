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

以 fastest route search 為例，Neo4j 可以使用 Dijkstra’s algorithm。系統從 origin station node 出發，沿著 `METRO_LINK`、`RAIL_LINK` 或 `TRANSFER_TO` relationships 搜尋 destination station，並使用 `travel_time_min` 計算每一條 path 的總成本。最後，系統會回傳總旅行時間最低的 route。

如果使用 relational database 實作同樣的 multi-hop routing，則需要透過 recursive CTE 反覆查詢 station connection table。查詢過程中還需要記錄已經走過的 stations、避免 cycle、累加 total travel time，最後再排序出成本最低的 path。相較之下，graph database 更直接地把這些 traversal logic 表達出來，也更適合維護 shortest path、interchange path 和 alternative route 這類查詢。

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

這個查詢會從 delayed station node 出發，沿著 `METRO_LINK`、`RAIL_LINK` 和 `TRANSFER_TO` relationships 找出相鄰站點。它的概念接近 BFS，也就是從一個起點向外擴展一層或多層，找出 N hops 以內的 connected stations。

例如，如果 `NR03` 發生延誤，系統可以查出它直接連接的 national rail stations，也可以透過 `TRANSFER_TO` 找到與它相連的 metro station。這樣可以幫助 assistant 回答哪些 stations 或 routes 可能受到延誤波及。

這種查詢很適合 graph database，因為 delay ripple 本身就是沿著 network connection 擴散的問題。透過 graph traversal，系統可以自然地從一個 station 找到相鄰 stations，並根據 hops 或 relationship type 控制查詢範圍。

---

## Summary

Overall, the Neo4j graph design models the physical transit network as connected data. `MetroStation` and `NationalRailStation` are stored as nodes, while `METRO_LINK`, `RAIL_LINK`, and `TRANSFER_TO` are stored as relationships. Station-level information such as `station_id`, `name`, and `lines` is stored as node properties, while segment-level information such as `line` and `travel_time_min` is stored as relationship properties.

For interchange stations, the design deliberately keeps metro stations and national rail stations as separate nodes, connected by `TRANSFER_TO` relationships that represent walkways. This allows the system to preserve the independence of the two transport networks while still supporting cross-network journeys. It also allows transfer time to be included in total route cost instead of treating transfers as zero-cost movements.

This design supports fastest route search, cross-network interchange paths, alternative routes, and delay ripple analysis. It also allows Dijkstra’s algorithm and graph traversal to be applied directly to the station network. Compared with implementing these routing queries only through relational joins and recursive CTEs, the graph model better matches the structure of the transit system and makes the route-related queries easier to express and maintain.
