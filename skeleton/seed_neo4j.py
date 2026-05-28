"""
TransitFlow — Neo4j Seeder
Run once after starting Docker:
    python skeleton/seed_neo4j.py

Strategy:
  Reads databases/graph/seed.cypher and executes every statement against Neo4j.
  Statements are split on ';' (semicolons), comments and blank lines are skipped.
  Falls back to JSON-driven seeding if the cypher file is empty or missing.
"""

import json
import os
import re
import sys

sys.path.insert(0, ".")

from neo4j import GraphDatabase
from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

# ── paths ─────────────────────────────────────────────────────────────────────

_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, ".."))
_DATA_DIR    = os.path.join(_PROJECT_DIR, "train-mock-data")
_CYPHER_FILE = os.path.join(_PROJECT_DIR, "databases", "graph", "seed.cypher")


def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


# ── Cypher file parser ────────────────────────────────────────────────────────

def _parse_cypher(path: str) -> list[str]:
    """
    Read a .cypher file and return a list of non-empty, non-comment statements.
    Splits on ';' so multi-line statements (UNWIND ... MERGE) are kept intact.
    """
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    # 正規化換行符（Windows CRLF → LF）
    raw = raw.replace("\r\n", "\n")

    # 移除 // 注釋行
    lines = []
    for line in raw.splitlines():
        if line.strip().startswith("//"):
            continue
        lines.append(line)

    text = "\n".join(lines)

    # 以分號切割（每個完整語句結尾都有分號）
    # 但 UNWIND 區塊內的 MERGE 不含分號，整塊到結尾的 ; 才結束
    # split(";") 就能正確把每個獨立語句切開
    raw_parts = text.split(";")
    statements = []
    for part in raw_parts:
        s = part.strip()
        # 過濾掉空白與純注釋殘留
        if not s:
            continue
        # 過濾掉只剩注釋的片段
        non_comment = "\n".join(
            l for l in s.splitlines() if not l.strip().startswith("//")
        ).strip()
        if non_comment:
            statements.append(non_comment)

    return statements


# ── seeder ────────────────────────────────────────────────────────────────────

def seed():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    with driver.session() as session:

        # Step 1: 清空現有圖資料
        session.run("MATCH (n) DETACH DELETE n")
        print("  [OK] Cleared existing graph data  清空舊圖資料")

        # 清除舊的 constraints（重跑時避免衝突）
        existing = session.run("SHOW CONSTRAINTS YIELD name").data()
        for row in existing:
            session.run(f"DROP CONSTRAINT {row['name']}")
        if existing:
            print(f"  [OK] Dropped {len(existing)} existing constraint(s)  清除舊約束")

        # Step 2: 讀取並執行 seed.cypher
        if not os.path.exists(_CYPHER_FILE):
            print(f"  [WARN] seed.cypher not found at {_CYPHER_FILE}")
            print("         Falling back to JSON-driven seeding...")
            _seed_from_json(session)
            driver.close()
            return

        statements = _parse_cypher(_CYPHER_FILE)

        # 過濾掉純 "Deprecated" 說明行（舊版 seed.cypher 只有注釋）
        real_statements = [s for s in statements if not s.startswith("//")]

        if not real_statements:
            print("  [WARN] seed.cypher contains no executable statements.")
            print("         Falling back to JSON-driven seeding...")
            _seed_from_json(session)
            driver.close()
            return

        print(f"  Executing {len(real_statements)} Cypher statement(s) from seed.cypher...")

        counters = {
            "constraints": 0,
            "nodes":       0,
            "rels":        0,
        }

        for i, stmt in enumerate(real_statements, 1):
            result = session.run(stmt)
            summary = result.consume()
            c = summary.counters

            if c.constraints_added:
                counters["constraints"] += c.constraints_added
            nodes_created = c.nodes_created
            rels_created  = c.relationships_created
            counters["nodes"] += nodes_created
            counters["rels"]  += rels_created

            # 只在有實際效果時印出
            if nodes_created or rels_created or c.constraints_added:
                label = stmt.strip()[:60].replace("\n", " ")
                print(f"    [{i:02d}] nodes+{nodes_created:3d}  rels+{rels_created:3d}  │ {label}…")

        print(f"\n  Summary:")
        print(f"    Constraints created : {counters['constraints']}")
        print(f"    Nodes created       : {counters['nodes']}")
        print(f"    Relationships created: {counters['rels']}")

    driver.close()
    print("\n[OK] Neo4j graph seeded successfully.  圖資料庫建立完成")
    print("     Open http://localhost:7475 to explore the graph.")


# ── JSON fallback（seed.cypher 是空白時使用）─────────────────────────────────

def _seed_from_json(session):
    """
    Fallback: build the graph directly from train-mock-data/ JSON files.
    Uses the same node labels and relationship types as seed.cypher:
      MetroStation, NationalRailStation, METRO_LINK, RAIL_LINK, TRANSFER_TO
    """
    metro_stations = _load("metro_stations.json")
    rail_stations  = _load("national_rail_stations.json")

    # --- MetroStation nodes ---
    for s in metro_stations:
        session.run(
            """
            MERGE (n:MetroStation {station_id: $sid})
            SET n.name  = $name,
                n.lines = $lines
            """,
            sid=s["station_id"], name=s["name"], lines=s.get("lines", []),
        )
    print(f"  [OK] MetroStation nodes: {len(metro_stations)}")

    # --- NationalRailStation nodes ---
    for s in rail_stations:
        session.run(
            """
            MERGE (n:NationalRailStation {station_id: $sid})
            SET n.name  = $name,
                n.lines = $lines
            """,
            sid=s["station_id"], name=s["name"], lines=s.get("lines", []),
        )
    print(f"  [OK] NationalRailStation nodes: {len(rail_stations)}")

    # --- METRO_LINK relationships (from adjacent_stations) ---
    ml_count = 0
    for s in metro_stations:
        for adj in s.get("adjacent_stations", []):
            session.run(
                """
                MATCH (a:MetroStation {station_id: $from_id})
                MATCH (b:MetroStation {station_id: $to_id})
                MERGE (a)-[:METRO_LINK {line: $line, travel_time_min: $time}]->(b)
                MERGE (b)-[:METRO_LINK {line: $line, travel_time_min: $time}]->(a)
                """,
                from_id=s["station_id"],
                to_id=adj["station_id"],
                line=adj["line"],
                time=adj["travel_time_min"],
            )
            ml_count += 1
    print(f"  [OK] METRO_LINK relationships: {ml_count}")

    # --- RAIL_LINK relationships ---
    rl_count = 0
    for s in rail_stations:
        for adj in s.get("adjacent_stations", []):
            session.run(
                """
                MATCH (a:NationalRailStation {station_id: $from_id})
                MATCH (b:NationalRailStation {station_id: $to_id})
                MERGE (a)-[:RAIL_LINK {line: $line, travel_time_min: $time}]->(b)
                MERGE (b)-[:RAIL_LINK {line: $line, travel_time_min: $time}]->(a)
                """,
                from_id=s["station_id"],
                to_id=adj["station_id"],
                line=adj["line"],
                time=adj["travel_time_min"],
            )
            rl_count += 1
    print(f"  [OK] RAIL_LINK relationships: {rl_count}")

    # --- TRANSFER_TO relationships (metro ↔ rail interchange) ---
    tx_count = 0
    for s in metro_stations:
        if s.get("is_interchange_national_rail") and s.get("interchange_national_rail_station_id"):
            session.run(
                """
                MATCH (m:MetroStation {station_id: $metro_id})
                MATCH (r:NationalRailStation {station_id: $rail_id})
                MERGE (m)-[:TRANSFER_TO {walk_time_min: 5}]->(r)
                MERGE (r)-[:TRANSFER_TO {walk_time_min: 5}]->(m)
                """,
                metro_id=s["station_id"],
                rail_id=s["interchange_national_rail_station_id"],
            )
            tx_count += 1
    print(f"  [OK] TRANSFER_TO relationships: {tx_count}")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Connecting to Neo4j...  連線中")
    seed()
