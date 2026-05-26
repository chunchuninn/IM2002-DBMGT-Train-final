// Deprecated: seeding is now done via skeleton/seed_neo4j.py
// which loads data directly from train-mock-data/ JSON files.
//
// If you prefer Cypher-file seeding, implement your graph schema here.
// Run with: python skeleton/seed_neo4j.py (or via the Neo4j Browser)

// 1. 建立唯一約束，防止資料重覆亂掉
CREATE CONSTRAINT FOR (s:MetroStation) REQUIRE s.station_id IS UNIQUE;
CREATE CONSTRAINT FOR (s:NationalRailStation) REQUIRE s.station_id IS UNIQUE;

// 2. 建立捷運 MS01 節點
MERGE (m1:MetroStation {station_id: "MS01"})
SET m1.name = "Central Square", m1.lines = ["M1", "M2"];

// 3. 建立捷運 MS02 節點
MERGE (m2:MetroStation {station_id: "MS02"})
SET m2.name = "Riverside", m2.lines = ["M1"];

// 4. 建立一間假想的火車站 NR01（為了測試跨網轉乘）
MERGE (r1:NationalRailStation {station_id: "NR01"})
SET r1.name = "Central Rail Station";

// 5. 建立起 MS01 -> MS02 的單向捷運線關係
MATCH (a:MetroStation {station_id: "MS01"})
MATCH (b:MetroStation {station_id: "MS02"})
MERGE (a)-[link:METRO_LINK {line: "M1"}]->(b)
SET link.travel_time_min = 3;

// 6. 建立起 MS02 -> MS01 的反向捷運線關係（因為雙向都能坐車）
MATCH (a:MetroStation {station_id: "MS02"})
MATCH (b:MetroStation {station_id: "MS01"})
MERGE (a)-[link:METRO_LINK {line: "M1"}]->(b)
SET link.travel_time_min = 3;

// 7. 建立 MS01 與 NR01 之間的雙向「跨網轉乘線」//transfer_time_min 是否需要？？
MATCH (m:MetroStation {station_id: "MS01"})
MATCH (r:NationalRailStation {station_id: "NR01"})
MERGE (m)-[:INTERCHANGE_TO {transfer_time_min: 5}]->(r)
MERGE (r)-[:INTERCHANGE_TO {transfer_time_min: 5}]->(m);

