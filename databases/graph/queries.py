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

# ── Fare constants (aligned with ticket_types.json) ──────────────────────────
METRO_BASE_FARE     = 0.80
METRO_PER_STOP_RATE = 0.30
 
# National rail fare rates (confirm with Member A after PostgreSQL schema is finalised)
RAIL_BASE_FARE_STANDARD      = 2.00
RAIL_PER_STOP_RATE_STANDARD  = 0.80
RAIL_BASE_FARE_FIRST         = 3.50
RAIL_PER_STOP_RATE_FIRST     = 1.20

# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a session, run Cypher, return data.

def example_count_nodes() -> int:
    """Example: count all nodes currently in the graph."""
    with _driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS total")
            return result.single()["total"]

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
    # 1. Determine which relationship types Dijkstra is allowed to traverse.
    #    "metro"  → metro lines only
    #    "rail"   → national rail lines only
    #    "auto"   → all types including TRANSFER_TO for cross-network journeys
    if network == "metro":
        rel_types = "METRO_LINK"
    elif network == "rail":
        rel_types = "RAIL_LINK"
    else:
        rel_types = "METRO_LINK|RAIL_LINK|TRANSFER_TO"

    # 2. Build the Cypher query using APOC Dijkstra.
    #    travel_time_min is used as the edge weight so the result is the fastest route.
    cypher_query = f"""
    MATCH (start {{station_id: $origin}}), (end {{station_id: $dest}})
    CALL apoc.algo.dijkstra(start, end, '{rel_types}', 'travel_time_min') YIELD path, weight
    RETURN path, weight
    """

    # 3. Set up a default response for when no path is found.
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

            # Only process the record inside the session block where neo4j_path is accessible.
            if record and record["path"]:
                response["found"] = True
                # Dijkstra returns the total cost as 'weight', which equals total travel time.
                response["total_time_min"] = int(record["weight"])

                neo4j_path = record["path"]

                # 4. Extract all station nodes from the path into a readable list.
                station_list = []
                for node in neo4j_path.nodes:
                    station_list.append({
                        "station_id": node["station_id"],
                        "name": node["name"]
                    })
                response["path"] = station_list

                # 5. Extract each relationship (leg) from the path.
                #    Each leg describes one segment: which line was taken and how long it took.
                leg_list = []
                for rel in neo4j_path.relationships:
                    rel_type = rel.type
                    # METRO_LINK and RAIL_LINK carry a 'line' property (e.g. "M1", "NR1").
                    # TRANSFER_TO has no 'line', so fall back to its 'type' property (e.g. "Walkway").
                    line_info = rel.get("line") if rel.get("line") else rel.get("type", "Unknown")

                    leg_list.append({
                        "from_station_id": rel.start_node["station_id"],
                        "to_station_id":   rel.end_node["station_id"],
                        "type":            rel_type,
                        "line_or_type":    line_info,
                        "duration_min":    rel["travel_time_min"]
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
    Based on ticket_types.json, the fare is stops-based, so the cheapest route
    is the one with the fewest stops (shortest path).

    Args:
        origin_id:       e.g. "NR01" or "MS01"
        destination_id:  e.g. "NR05" or "MS05"
        network:         "metro", "rail", or "auto"
        fare_class:      "standard" or "first" (national rail only)

    Returns:
        dict with found, total_fare_usd, stops_travelled, stations, legs
    """
    # 1. Determine allowed relationship types based on the 'network' parameter.
    # 'auto' allows crossing between Metro and National Rail via transfers.
    if network == "metro":
        rel_types = "METRO_LINK"
    elif network == "rail":
        rel_types = "RAIL_LINK"
    else:
        rel_types = "METRO_LINK|RAIL_LINK|TRANSFER_TO"

    # 2. Cypher Query: Use shortestPath() for optimal performance.
    # We use .replace() to safely inject relationship types without f-string curly brace conflicts.
    cypher_query = """
    MATCH (start {station_id: $origin}), (end {dest_id})
    MATCH p = shortestPath((start)-[:REL_TYPES_PLACEHOLDER*]-(end))
    RETURN p
    """.replace('REL_TYPES_PLACEHOLDER', rel_types)
    cypher_query = cypher_query.replace('{dest_id}', '{station_id: $dest}') # Fix for clean string formatting

    # 3. Default response format if no route is found
    response = {
        "found": False,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "total_fare_usd": 0.0,
        "stops_travelled": 0,
        "stations": [],
        "legs": []
    }

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher_query, origin=origin_id, dest=destination_id)
            record = result.single()

            if record and record["p"]:
                response["found"] = True
                neo4j_path = record["p"]

                # 4. Extract all stations (nodes) along the path
                station_list = []
                for node in neo4j_path.nodes:
                    station_list.append({
                        "station_id": node["station_id"],
                        "name": node["name"]
                    })
                response["stations"] = station_list

                # 5. Extract legs and count stops per transit system
                leg_list = []
                metro_stops = 0
                rail_stops = 0

                for rel in neo4j_path.relationships:
                    rel_type = rel.type
                    line_info = rel.get("line") if rel.get("line") else rel.get("type", "Unknown")
                    
                    if rel_type == "METRO_LINK":
                        metro_stops += 1
                    elif rel_type == "RAIL_LINK":
                        rail_stops += 1

                    leg_list.append({
                        "from_station_id": rel.start_node["station_id"],
                        "to_station_id": rel.end_node["station_id"],
                        "type": rel_type,
                        "line_or_type": line_info
                    })
                
                response["legs"] = leg_list
                response["stops_travelled"] = metro_stops + rail_stops

                # 6. Apply pricing formulas (simulated based on ticket_types.json)
                # Metro formula: base_fare + (stops * per_stop_rate)
                # Rail formula: base_fare + (stops * per_stop_rate_by_class)
                total_fare = 0.0
                
                if metro_stops > 0:
                    # Metro: $0.80 base + $0.30 per stop
                    total_fare += 0.80 + (metro_stops * 0.30)
                
                if rail_stops > 0:
                    # Rail: $2.00 base + rate based on fare class
                    rail_base = 2.00
                    rail_per_stop = 1.50 if fare_class == "standard" else 3.00
                    total_fare += rail_base + (rail_stops * rail_per_stop)

                response["total_fare_usd"] = round(total_fare, 2)

    return response

# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[dict]:
    """
    Find alternative paths between two stations that avoid a specific intermediate station.
    Useful for routing around a delayed, closed, or congested station.

    Args:
        origin_id:         e.g. "NR01" or "MS01"
        destination_id:    e.g. "NR05" or "MS05"
        avoid_station_id:  e.g. "NR03" or "MS03"
        network:           "metro", "rail", or "auto"
        max_routes:        Maximum number of alternative routes to return

    Returns:
        List of dicts: {"route": [list of station dicts], "total_time_min": int}
    """
    # 1. Determine allowed relationship types dynamically
    # 'auto' allows taking both systems and transferring between them
    if network == "metro":
        rel_types = "METRO_LINK"
    elif network == "rail":
        rel_types = "RAIL_LINK"
    else:
        rel_types = "METRO_LINK|RAIL_LINK|TRANSFER_TO"

    # 2. Cypher Query
    # Key optimizations:
    # - Used *1..20 to prevent unbounded path searching (Performance safety)
    # - Removed strict directionality (->) to allow bidirectional routing
    # - Removed strict node labels to allow cross-system transfers
    cypher_query = """
    MATCH (origin {station_id: $oid}), (destination {dest_id})
    
    // Find paths up to 20 hops long using the allowed transit networks
    MATCH path = (origin)-[:REL_TYPES_PLACEHOLDER*1..20]-(destination)
    
    // Filter out any path that contains the avoided station
    WHERE NONE(node IN nodes(path) WHERE node.station_id = $avoid)
    
    // Calculate total journey time for each candidate path
    WITH path,
         reduce(t = 0, r IN relationships(path) | t + COALESCE(r.travel_time_min, 0)) AS total_time
         
    ORDER BY total_time ASC
    LIMIT $max_routes
    
    // Format the output
    RETURN [node IN nodes(path) | {
                station_id: node.station_id,
                name:       node.name
            }] AS route,
           total_time AS total_time_min
    """.replace('REL_TYPES_PLACEHOLDER', rel_types)
    
    # Safe string replacement for Cypher curly braces
    cypher_query = cypher_query.replace('{dest_id}', '{station_id: $did}')

    alternatives = []

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                cypher_query, 
                oid=origin_id, 
                did=destination_id,
                avoid=avoid_station_id, 
                max_routes=max_routes
            )
            
            # 3. Parse the result into the expected Python list
            for row in result:
                alternatives.append({
                    "route": row["route"],
                    "total_time_min": row["total_time_min"]
                })

    return alternatives

# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find the fastest path between a metro station and a national rail station,
    optimised by travel time using Dijkstra's algorithm.
    Accurately identifies the physical interchange boundary stations.

    Args:
        origin_id:       e.g. "MS01" (Metro) or "NR01" (Rail)
        destination_id:  e.g. "NR05" (Rail) or "MS05" (Metro)

    Returns:
        dict with found, stations, interchange_points, legs, total_time_min
    """
    # Cypher Query: Coalesce r.line to ensure we capture line names (e.g., 'M1', 'Walkway')
    cypher_query = """
    MATCH (origin {station_id: $oid}), (destination {station_id: $did})
    CALL apoc.algo.dijkstra(
        origin, destination,
        'METRO_LINK|RAIL_LINK|TRANSFER_TO',
        'travel_time_min'
    )
    YIELD path, weight
    RETURN path, weight AS total_time_min
    """

    response = {
        "found": False,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "total_time_min": 0.0,
        "stations": [],
        "legs": [],
        "interchange_points": []
    }

    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher_query, oid=origin_id, did=destination_id)
            record = result.single()

            if record and record["path"]:
                response["found"] = True
                response["total_time_min"] = record["total_time_min"]
                neo4j_path = record["path"]

                # 1. Parse all stations along the path
                station_list = []
                for node in neo4j_path.nodes:
                    station_list.append({
                        "station_id": node["station_id"],
                        "name": node["name"]
                    })
                response["stations"] = station_list

                # 2. Parse legs and locate precise interchange points
                leg_list = []
                interchange_set = set() # Use a set to avoid duplicate boundary stations

                for rel in neo4j_path.relationships:
                    rel_type = rel.type
                    line_info = rel.get("line") if rel.get("line") else rel.get("type", "Unknown")

                    # BUG FIX: If the relationship is a physical walkway transfer,
                    # both flanking stations are the true interchange hubs!
                    if rel_type == "TRANSFER_TO":
                        interchange_set.add(rel.start_node["station_id"])
                        interchange_set.add(rel.end_node["station_id"])

                    leg_list.append({
                        "from_station_id": rel.start_node["station_id"],
                        "to_station_id": rel.end_node["station_id"],
                        "type": rel_type,
                        "line_or_type": line_info,
                        "travel_time_min": rel["travel_time_min"]
                    })
                
                response["legs"] = leg_list

                # 3. Filter interchange stations details into the final list
                response["interchange_points"] = [
                    s for s in station_list if s["station_id"] in interchange_set
                ]

    return response

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
    # Using triple quotes for cleaner, standard Cypher multi-line formatting
    cypher_query = """
    MATCH (start {station_id: $st_id})-[r]-(neighbor) 
    
    // Explicitly whitelist relationship types to prevent unexpected results
    WHERE type(r) IN ['METRO_LINK', 'RAIL_LINK', 'TRANSFER_TO'] 
    
    // BUG FIX: In Cypher, type(r) returns the relationship label (e.g., 'TRANSFER_TO').
    // r.type would look for a property key named 'type' instead.
    RETURN neighbor.station_id AS id, 
           neighbor.name AS name, 
           type(r) AS rel_type, 
           COALESCE(r.line, type(r)) AS line_or_type, 
           r.travel_time_min AS time
    """
 
    connections = []
 
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher_query, st_id=station_id)
 
            for record in result:
                connections.append({
                    "station_id":      record["id"],
                    "name":            record["name"],
                    "connection_type": record["rel_type"],     # METRO_LINK, RAIL_LINK, or TRANSFER_TO
                    "line":            record["line_or_type"], # e.g. "M1", "NR1", or "TRANSFER_TO"
                    "travel_time_min": record["time"]
                })
 
    return connections


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.

    Args:
        station_id: e.g. "MS01" or "NR01"
    """
    cypher_query = """()
    MATCH (start {station_id: $st_id})-[r]-(neighbor) 
    WHERE type(r) IN ['METRO_LINK', 'RAIL_LINK', 'TRANSFER_TO']
    RETURN neighbor.station_id AS id, 
           neighbor.name AS name, 
           type(r) AS rel_type,
           COALESCE(r.line, r.type) AS line_or_type, 
           r.travel_time_min AS time
    """
# Undirected match (-[r]-) catches connections regardless of edge direction.
# WHERE whitelist prevents unexpected results if new relationship types are added.
# COALESCE: METRO_LINK/RAIL_LINK return r.line (e.g. "M1"), TRANSFER_TO falls back to r.type (e.g. "Walkway").
# Explicitly whitelist relationship types to prevent unexpected results ,if new relationship types are added to the graph in the future.
# COALESCE returns the first non-null value.
# METRO_LINK and RAIL_LINK edges carry a 'line' property (e.g. "M1", "NR1").
# TRANSFER_TO edges have no 'line', so it falls back to r.type (e.g. "Walkway").   
    connections = []
    
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(cypher_query, st_id=station_id)
            
            for record in result:
                connections.append({
                    "station_id": record["id"],
                    "name": record["name"],
                    "connection_type": record["rel_type"], # metro, national rail or walkway
                    "line": record["line_or_type"],        # eg, M1, NR1 or Walkway
                    "travel_time_min": record["time"]     
                })
    return connections