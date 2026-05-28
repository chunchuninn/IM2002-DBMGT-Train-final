"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.

GRAPH ROLE:
  - Model the dual transit network (city metro M1–M4 + national rail NR1–NR2)
  - Find fastest routes (Dijkstra by travel_time_min via APOC)
  - Find cheapest routes (Dijkstra by fare via APOC)
  - Find alternative routes avoiding a given station
  - Find cross-network interchange paths (metro → rail or rail → metro)
  - Show delay ripple: which stations are affected within N hops

STUDENT TASK
------------
Design your graph schema (node labels, relationship types, properties)
based on the data in train-mock-data/, seed it with skeleton/seed_neo4j.py,
then implement the query_ functions below.

Functions prefixed with `query_` are called by the agent (skeleton/agent.py).
"""

from __future__ import annotations

from typing import Optional

from neo4j import GraphDatabase

from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


def _driver():
    """Return a Neo4j driver. Caller is responsible for closing."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a session, run Cypher, return data.

def example_count_nodes() -> int:
    """Example: count all nodes currently in the graph."""
    with _driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS total")
            return result.single()["total"]

# TODO: Implement the query_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
    """
    Find the fastest path between two stations, minimising total travel time.
    Uses apoc.algo.dijkstra (APOC required; enabled in docker-compose.yml).

    Args:
        origin_id:       e.g. "MS01" or "NR01"
        destination_id:  e.g. "MS09" or "NR05"
        network:         "metro", "rail", or "auto" (inferred from IDs)

    Returns:
        dict with keys: found, origin_id, destination_id,
                        total_time_min, path (list of station dicts), legs
    """
    # 1. 根據傳進來的 network 參數，決定演算法可以走哪些線
    # 如果指定 metro，就只能走捷運線；指定 rail 就只能走鐵路；auto 則是全部都能走（包含轉乘）
    if network == "metro":
        rel_types = "METRO_LINK"
    elif network == "rail":
        rel_types = "RAIL_LINK"
    else:
        rel_types = "METRO_LINK|RAIL_LINK|TRANSFER_TO"

    # 2. 撰寫 APOC Dijkstra 語法
    cypher_query = f"""
    MATCH (start {{station_id: $origin}}), (end {{station_id: $dest}})
    CALL apoc.algo.dijkstra(start, end, '{rel_types}', 'travel_time_min') YIELD path, weight
    RETURN path, weight
    """

    # 3. 預設找不到時的基本回傳格式
    response = {
        "found": False,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "total_time_min": 0,
        "path": [],
        "legs": []
    }

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher_query, origin=origin_id, dest=destination_id)
            record = result.single()
            
        # 如果資料庫有算出一條路徑
        if record and record["path"]:
            response["found"] = True
            response["total_time_min"] = int(record["weight"]) # 權重就是總時間
                
            neo4j_path = record["path"]
                
        # 4. 拆解路徑中的「所有車站 (Nodes)」放進 path
        station_list = []
        for node in neo4j_path.nodes:
            station_list.append({
                "station_id": node["station_id"],
                "name": node["name"]
                    })
        response["path"] = station_list
                
        # 5. 拆解路徑中的「每一段搭乘/換乘 (Relationships)」放進 legs
        leg_list = []
        for rel in neo4j_path.relationships:
         # 判斷這是一段什麼樣的連線
                    rel_type = rel.type
                    line_info = rel.get("line") if rel.get("line") else rel.get("type", "Unknown")
                    
                    leg_list.append({
                        "from_station_id": rel.start_node["station_id"],
                        "to_station_id": rel.end_node["station_id"],
                        "type": rel_type,
                        "line_or_type": line_info,
                        "duration_min": rel["travel_time_min"]
                    })
        response["legs"] = leg_list

    return response


# ── CHEAPEST ROUTE (Dijkstra by fare) ────────────────────────────────────────

def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
    """
    Find the cheapest path between two stations, minimising total estimated fare.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        network:         "metro", "rail", or "auto"
        fare_class:      "standard" or "first" (national rail only)

    Returns:
        dict with found, total_fare_usd (approximate), stations, legs
    """
    raise NotImplementedError("TODO: implement after designing your graph schema")


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[list[dict]]:
    """
    Find paths between two stations that avoid a specific intermediate station.
    Useful for routing around a delayed or closed station.

    Args:
        origin_id:         e.g. "NR01"
        destination_id:    e.g. "NR05"
        avoid_station_id:  e.g. "NR03"
        network:           "metro", "rail", or "auto"
        max_routes:        max number of alternatives to return

    Returns:
        List of routes, each route is a list of leg dicts
    """
    raise NotImplementedError("TODO: implement after designing your graph schema")


# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find a path between a metro station and a national rail station (or vice versa)
    crossing the network boundary via interchange relationships.

    Args:
        origin_id:       e.g. "MS03" (metro) or "NR05" (national rail)
        destination_id:  e.g. "NR05" (national rail) or "MS09" (metro)

    Returns:
        dict with found, stations list, interchange points, total_time_min
    """
    raise NotImplementedError("TODO: implement after designing your graph schema")


# ── DELAY RIPPLE ANALYSIS ─────────────────────────────────────────────────────

def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]:
    """
    Find all stations within N hops of a delayed or disrupted station.
    Works on both metro and national rail networks.

    Args:
        delayed_station_id: e.g. "NR03" or "MS01"
        hops:               how many connections out to search (default 2)

    Returns:
        List of dicts: {station_id, name, hops_away, lines_affected}
    """
    raise NotImplementedError("TODO: implement after designing your graph schema")


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.

    Args:
        station_id: e.g. "MS01" or "NR01"
    """
    cypher_query = """
    MATCH (start {station_id: $st_id})-[r]-(neighbor)
    WHERE type(r) IN ['METRO_LINK', 'RAIL_LINK', 'TRANSFER_TO']
    RETURN neighbor.station_id AS id, 
           neighbor.name AS name, 
           type(r) AS rel_type,
           COALESCE(r.line, r.type) AS line_or_type, 
           r.travel_time_min AS time
    """
    
    connections = []
    
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher_query, st_id=station_id)
            
            for record in result:
                connections.append({
                    "station_id": record["id"],
                    "name": record["name"],
                    "connection_type": record["rel_type"], # 是捷運、國鐵還是轉乘
                    "line": record["line_or_type"],        # M1, NR1 或 Walkway
                    "travel_time_min": record["time"]     
                })
                
    return connections