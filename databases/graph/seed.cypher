// Deprecated: seeding is now done via skeleton/seed_neo4j.py
// which loads data directly from train-mock-data/ JSON files.
//
// If you prefer Cypher-file seeding, implement your graph schema here.
// Run with: python skeleton/seed_neo4j.py (or via the Neo4j Browser)

// 1. 建立唯一約束，防止資料重覆亂掉
CREATE CONSTRAINT FOR (s:MetroStation) REQUIRE s.station_id IS UNIQUE;
CREATE CONSTRAINT FOR (s:NationalRailStation) REQUIRE s.station_id IS UNIQUE;

// =============================================
// 2. METRO STATIONS (20 nodes)
// =============================================
MERGE (:MetroStation {station_id: "MS01", name: "Central Square",  lines: ["M1","M2"]})
MERGE (:MetroStation {station_id: "MS02", name: "Riverside",       lines: ["M1"]})
MERGE (:MetroStation {station_id: "MS03", name: "Northgate",       lines: ["M1"]})
MERGE (:MetroStation {station_id: "MS04", name: "Elm Park",        lines: ["M1","M3"]})
MERGE (:MetroStation {station_id: "MS05", name: "Westfield",       lines: ["M1"]})
MERGE (:MetroStation {station_id: "MS06", name: "Harbour View",    lines: ["M2"]})
MERGE (:MetroStation {station_id: "MS07", name: "Old Town",        lines: ["M2"]})
MERGE (:MetroStation {station_id: "MS08", name: "University",      lines: ["M2","M4"]})
MERGE (:MetroStation {station_id: "MS09", name: "Queensbridge",    lines: ["M2"]})
MERGE (:MetroStation {station_id: "MS10", name: "Parkside",        lines: ["M3"]})
MERGE (:MetroStation {station_id: "MS11", name: "Greenhill",       lines: ["M3"]})
MERGE (:MetroStation {station_id: "MS12", name: "Lakeshore",       lines: ["M3","M4"]})
MERGE (:MetroStation {station_id: "MS13", name: "Clifton",         lines: ["M3"]})
MERGE (:MetroStation {station_id: "MS14", name: "Eastwick",        lines: ["M4"]})
MERGE (:MetroStation {station_id: "MS15", name: "Ferndale",        lines: ["M4"]})
MERGE (:MetroStation {station_id: "MS16", name: "Hilltop",         lines: ["M4"]})
MERGE (:MetroStation {station_id: "MS17", name: "Broadmoor",       lines: ["M1","M4"]})
MERGE (:MetroStation {station_id: "MS18", name: "Sunnyvale",       lines: ["M2"]})
MERGE (:MetroStation {station_id: "MS19", name: "Redwood",         lines: ["M3"]})
MERGE (:MetroStation {station_id: "MS20", name: "Thornton",        lines: ["M1"]});

// =============================================
// 3. NATIONAL RAIL STATIONS (10 nodes)
// =============================================
MERGE (:NationalRailStation {station_id: "NR01", name: "Central Station",    lines: ["NR1","NR2"]})
MERGE (:NationalRailStation {station_id: "NR02", name: "Maplewood",          lines: ["NR1"]})
MERGE (:NationalRailStation {station_id: "NR03", name: "Old Town Junction",  lines: ["NR1"]})
MERGE (:NationalRailStation {station_id: "NR04", name: "Ashford",            lines: ["NR1"]})
MERGE (:NationalRailStation {station_id: "NR05", name: "Stonehaven",         lines: ["NR1"]})
MERGE (:NationalRailStation {station_id: "NR06", name: "Bridgeport",         lines: ["NR2"]})
MERGE (:NationalRailStation {station_id: "NR07", name: "Ferndale Halt",      lines: ["NR2"]})
MERGE (:NationalRailStation {station_id: "NR08", name: "Coalport",           lines: ["NR2"]})
MERGE (:NationalRailStation {station_id: "NR09", name: "Dunmore",            lines: ["NR2"]})
MERGE (:NationalRailStation {station_id: "NR10", name: "Langford End",       lines: ["NR2"]});

// =================================================================
// 4. 建立捷運雙向連線 (METRO_LINK)
// =================================================================
UNWIND [
  // --- M1 green line ---
  {from: "MS20", to: "MS05", line: "M1", color: "Green", time: 2},
  {from: "MS05", to: "MS01", line: "M1", color: "Green", time: 3},
  {from: "MS01", to: "MS02", line: "M1", color: "Green", time: 3},
  {from: "MS02", to: "MS03", line: "M1", color: "Green", time: 2},
  {from: "MS03", to: "MS04", line: "M1", color: "Green", time: 4},
  {from: "MS04", to: "MS17", line: "M1", color: "Green", time: 3},

  // --- M2 blue line ---
  {from: "MS06", to: "MS01", line: "M2", color: "Blue", time: 3},
  {from: "MS01", to: "MS07", line: "M2", color: "Blue", time: 2},
  {from: "MS07", to: "MS18", line: "M2", color: "Blue", time: 2},
  {from: "MS18", to: "MS08", line: "M2", color: "Blue", time: 4},
  {from: "MS08", to: "MS09", line: "M2", color: "Blue", time: 3},

  // --- M3 orange line ---
  {from: "MS13", to: "MS19", line: "M3", color: "Orange", time: 2},
  {from: "MS19", to: "MS11", line: "M3", color: "Orange", time: 3},
  {from: "MS11", to: "MS10", line: "M3", color: "Orange", time: 2},
  {from: "MS10", to: "MS12", line: "M3", color: "Orange", time: 4},
  {from: "MS12", to: "MS04", line: "M3", color: "Orange", time: 3},

  // --- M4 red line ---
  {from: "MS17", to: "MS08", line: "M4", color: "Red", time: 4},
  {from: "MS08", to: "MS12", line: "M4", color: "Red", time: 4},
  {from: "MS12", to: "MS14", line: "M4", color: "Red", time: 4},
  {from: "MS14", to: "MS15", line: "M4", color: "Red", time: 2},
  {from: "MS15", to: "MS16", line: "M4", color: "Red", time: 3}
] AS link

MATCH (a:MetroStation {station_id: link.from})
MATCH (b:MetroStation {station_id: link.to})
MERGE (a)-[:METRO_LINK {line: link.line, color: link.color, travel_time_min: link.time}]->(b)
MERGE (b)-[:METRO_LINK {line: link.line, color: link.color, travel_time_min: link.time}]->(a);

// =================================================================
// 5. 建立國鐵雙向連線 (RAIL_LINK)
// =================================================================
UNWIND [
  // --- NR1 purple line ---
  {from: "NR01", to: "NR02", line: "NR1", color: "Purple", time: 12},
  {from: "NR02", to: "NR03", line: "NR1", color: "Purple", time: 18},
  {from: "NR03", to: "NR04", line: "NR1", color: "Purple", time: 15},
  {from: "NR04", to: "NR05", line: "NR1", color: "Purple", time: 20},

  // --- NR2 brown line ---
  {from: "NR01", to: "NR06", line: "NR2", color: "Brown", time: 14},
  {from: "NR06", to: "NR07", line: "NR2", color: "Brown", time: 16},
  {from: "NR07", to: "NR08", line: "NR2", color: "Brown", time: 22},
  {from: "NR08", to: "NR09", line: "NR2", color: "Brown", time: 21},
  {from: "NR09", to: "NR10", line: "NR2", color: "Brown", time: 19}
] AS link

MATCH (a:NationalRailStation {station_id: link.from})
MATCH (b:NationalRailStation {station_id: link.to})
MERGE (a)-[:RAIL_LINK {line: link.line, color: link.color, travel_time_min: link.time}]->(b)
MERGE (b)-[:RAIL_LINK {line: link.line, color: link.color, travel_time_min: link.time}]->(a);

// =================================================================
// 6.建立捷運與國鐵之間的跨系統轉乘通道
// =================================================================
UNWIND [
  {metro_id: "MS01", rail_id: "NR01", type: "Walkway", time: 5}, // Central 轉乘
  {metro_id: "MS07", rail_id: "NR03", type: "Walkway", time: 4}, // Old Town 轉乘
  {metro_id: "MS15", rail_id: "NR07", type: "Walkway", time: 3}  // Ferndale 轉乘
] AS transfer

MATCH (m:MetroStation {station_id: transfer.metro_id})
MATCH (r:NationalRailStation {station_id: transfer.rail_id})
MERGE (m)-[:TRANSFER_TO {type: transfer.type, walk_time_min: transfer.time}]->(r)
MERGE (r)-[:TRANSFER_TO {type: transfer.type, walk_time_min: transfer.time}]->(m);