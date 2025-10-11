from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
import os
from neo4j import GraphDatabase
from dotenv import load_dotenv
from pathlib import Path

# Load .env file from absolute path
env_path = Path("S:/Repo/ufdr-analyzer/.env")
load_dotenv(dotenv_path=env_path)

router = APIRouter(prefix="/graph", tags=["GraphDB"])

# Neo4j connection
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USERNAME")  # Changed from NEO4J_USER to NEO4J_USERNAME
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

print(f"DEBUG: NEO4J_URI = {NEO4J_URI}")
print(f"DEBUG: NEO4J_USER = {NEO4J_USER}")
print(f"DEBUG: NEO4J_PASSWORD = {'*' * len(NEO4J_PASSWORD) if NEO4J_PASSWORD else 'None'}")

if not all([NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD]):
    raise ValueError(f"Neo4j credentials not found. URI: {NEO4J_URI}, USER: {NEO4J_USER}, PASSWORD: {'*' * len(NEO4J_PASSWORD) if NEO4J_PASSWORD else 'None'}")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# Request Models
class QueryRequest(BaseModel):
    query: str

class NodeIdRequest(BaseModel):
    node_id: str

class PathRequest(BaseModel):
    from_id: str
    to_id: str

class LabelRequest(BaseModel):
    label: str

class EntityRequest(BaseModel):
    label: str
    name: str

class BatchIngestRequest(BaseModel):
    people: List[Dict[str, Any]] = []
    messages: List[Dict[str, Any]] = []
    calls: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []

# Helper functions
def get_session():
    return driver.session()

def run_query(query: str, parameters: Dict = None):
    with get_session() as session:
        return session.run(query, parameters or {})

# Endpoints
@router.get("/nodes")
async def get_all_nodes():
    """Get all nodes from Neo4j"""
    try:
        with get_session() as session:
            result = session.run("MATCH (n) RETURN n")
            nodes = []
            for record in result:
                node = record["n"]
                nodes.append({
                    "id": node.get("id", str(node.id)),
                    "label": list(node.labels)[0] if node.labels else "Unknown",
                    "properties": dict(node)
                })
            return nodes
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get nodes: {str(e)}")

@router.get("/relationships")
async def get_all_relationships():
    """Get all relationships from Neo4j"""
    try:
        with get_session() as session:
            result = session.run("MATCH (from)-[r]->(to) RETURN from, r, to")
            relationships = []
            for record in result:
                relationships.append({
                    "from": record["from"].get("id", str(record["from"].id)),
                    "to": record["to"].get("id", str(record["to"].id)),
                    "type": record["r"].type
                })
            return relationships
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get relationships: {str(e)}")

@router.get("/full_graph")
async def get_full_graph(limit: int = 1000, node_types: str = None):
    """Get graph data with pagination and filtering"""
    try:
        with get_session() as session:
            # Build node query with filtering
            node_query = "MATCH (n)"
            if node_types:
                types = node_types.split(",")
                type_filter = " OR ".join([f"n:{t}" for t in types])
                node_query += f" WHERE {type_filter}"
            node_query += f" RETURN n LIMIT {limit}"
            
            # Get nodes
            nodes_result = session.run(node_query)
            nodes = []
            for record in nodes_result:
                node = record["n"]
                nodes.append({
                    "id": node.get("id", str(node.id)),
                    "label": list(node.labels)[0] if node.labels else "Unknown",
                    "properties": dict(node)
                })
            
            # Get relationships (only between the nodes we're returning)
            node_ids = [node["id"] for node in nodes]
            if node_ids:
                edges_query = f"""
                MATCH (from)-[r]->(to) 
                WHERE from.id IN {node_ids} AND to.id IN {node_ids}
                RETURN from, r, to
                LIMIT {limit}
                """
                edges_result = session.run(edges_query)
                edges = []
                for record in edges_result:
                    edges.append({
                        "from": record["from"].get("id", str(record["from"].id)),
                        "to": record["to"].get("id", str(record["to"].id)),
                        "type": record["r"].type
                    })
            else:
                edges = []
            
            return {
                "nodes": nodes, 
                "edges": edges,
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "limit": limit,
                "has_more": len(nodes) == limit
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get graph: {str(e)}")

@router.post("/query")
async def run_custom_query(request: QueryRequest):
    """Run a custom Cypher query"""
    try:
        with get_session() as session:
            result = session.run(request.query)
            records = []
            for record in result:
                records.append(dict(record))
            return records
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

@router.post("/neighbors")
async def get_neighbors(request: NodeIdRequest):
    """Get neighbors of a specific node"""
    try:
        with get_session() as session:
            result = session.run(
                "MATCH (a {id: $node_id})--(n) RETURN n.id as neighbor_id",
                node_id=request.node_id
            )
            neighbors = [record["neighbor_id"] for record in result]
            return {"node_id": request.node_id, "neighbors": neighbors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get neighbors: {str(e)}")

@router.post("/shortest_path")
async def get_shortest_path(request: PathRequest):
    """Get shortest path between two nodes"""
    try:
        with get_session() as session:
            result = session.run(
                """
                MATCH p=shortestPath((a {id: $from_id})-[*]-(b {id: $to_id}))
                RETURN [n IN nodes(p) | n.id] AS path
                """,
                from_id=request.from_id, to_id=request.to_id
            )
            record = result.single()
            path = record["path"] if record else []
            return {
                "from": request.from_id,
                "to": request.to_id,
                "path": path,
                "length": len(path)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get shortest path: {str(e)}")

@router.post("/centrality")
async def get_centrality(request: LabelRequest):
    """Get degree centrality for nodes of a specific label"""
    try:
        with get_session() as session:
            result = session.run(
                f"MATCH (n:{request.label})-[r]-() RETURN n.id as id, count(r) AS degree ORDER BY degree DESC",
                label=request.label
            )
            centrality = []
            for record in result:
                centrality.append({
                    "id": record["id"],
                    "degree": record["degree"]
                })
            return centrality
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get centrality: {str(e)}")

@router.post("/community_detection")
async def get_communities(request: LabelRequest):
    """Get community detection for nodes of a specific label"""
    try:
        with get_session() as session:
            result = session.run(
                f"""
                MATCH (n:{request.label})
                OPTIONAL MATCH (n)-[:CALLED|SENT*]-(m:{request.label})
                RETURN n.id AS nodeId, collect(DISTINCT m.id) AS community
                """,
                label=request.label
            )
            communities = []
            for record in result:
                communities.append({
                    "id": record["nodeId"],
                    "community": record["community"]
                })
            return communities
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get communities: {str(e)}")

@router.post("/add_entity")
async def add_entity(request: EntityRequest):
    """Add a new entity to the graph"""
    try:
        with get_session() as session:
            node_id = request.name
            session.run(
                f"MERGE (n:{request.label} {{id: $id}}) SET n.name = $name",
                id=node_id, name=request.name
            )
            return {"message": f"Node '{request.name}' of type '{request.label}' added successfully", "id": node_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add entity: {str(e)}")

@router.post("/batch_ingest")
async def batch_ingest(request: BatchIngestRequest):
    """Batch ingest data into Neo4j"""
    try:
        with get_session() as session:
            # Add people
            for person in request.people:
                session.run(
                    "MERGE (p:Person {id: $id}) SET p.name = $name",
                    id=person["id"], name=person.get("name")
                )
            
            # Add messages
            for message in request.messages:
                session.run(
                    "MERGE (m:Message {id: $id}) SET m.content = $content, m.timestamp = $timestamp",
                    id=message["id"], content=message.get("content"),
                    timestamp=message.get("timestamp")
                )
            
            # Add calls
            for call in request.calls:
                session.run(
                    "MERGE (c:Call {id: $id}) SET c.caller = $caller, c.receiver = $receiver, c.duration = $duration",
                    id=call["id"], caller=call.get("caller"),
                    receiver=call.get("receiver"), duration=call.get("duration")
                )
            
            # Add relationships
            for rel in request.relationships:
                session.run(
                    f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) MERGE (a)-[r:{rel['type']}]->(b)",
                    from_id=rel["from_id"], to_id=rel["to_id"]
                )
            
            return {"message": "Batch ingestion completed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to batch ingest: {str(e)}")

# Health check
@router.get("/health")
async def health_check():
    """Check Neo4j connection health"""
    try:
        with get_session() as session:
            result = session.run("RETURN 1 as test")
            return {"status": "healthy", "message": "Neo4j connection successful"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Neo4j connection failed: {str(e)}")

@router.get("/stats")
async def get_graph_stats():
    """Get graph statistics without loading all data"""
    try:
        with get_session() as session:
            stats = {}
            
            # Count nodes by type
            node_types = ['User', 'Run', 'Contact', 'Message', 'Call', 'Media', 'Artifact', 'Query', 'Person']
            for node_type in node_types:
                result = session.run(f"MATCH (n:{node_type}) RETURN count(n) as count")
                stats[node_type] = result.single()["count"]
            
            # Count total relationships
            result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
            stats['Relationships'] = result.single()["count"]
            
            return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

@router.get("/sample")
async def get_sample_data(node_type: str = "User", limit: int = 10):
    """Get a sample of nodes of a specific type"""
    try:
        with get_session() as session:
            result = session.run(f"MATCH (n:{node_type}) RETURN n LIMIT {limit}")
            nodes = []
            for record in result:
                node = record["n"]
                nodes.append({
                    "id": node.get("id", str(node.id)),
                    "label": list(node.labels)[0] if node.labels else "Unknown",
                    "properties": dict(node)
                })
            return {"nodes": nodes, "count": len(nodes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get sample data: {str(e)}")
