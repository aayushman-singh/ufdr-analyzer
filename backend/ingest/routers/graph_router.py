# backend/ingest/routers/graph_router.py
from fastapi import APIRouter
from pydantic import BaseModel
from ingest.services.neo4j_service import Neo4jService

router = APIRouter(prefix="/graph", tags=["GraphDB"])
neo_service = Neo4jService()

# ------------------------
# Request Models
# ------------------------
class EntityModel(BaseModel):
    label: str
    name: str

class BatchIngestModel(BaseModel):
    people: list[dict] = []
    messages: list[dict] = []
    calls: list[dict] = []
    relationships: list[dict] = []

class NodeIdModel(BaseModel):
    node_id: str

class PathModel(BaseModel):
    from_id: str
    to_id: str

class LabelModel(BaseModel):
    label: str

# ------------------------
# Endpoints
# ------------------------
@router.post("/add_entity")
async def add_entity(entity: EntityModel):
    node_id = entity.name
    neo_service.create_person({"id": node_id, "name": entity.name}, add_placeholder_rel=True)
    return {"message": f"Node '{entity.name}' of type '{entity.label}' added successfully", "id": node_id}

@router.post("/batch_ingest")
def batch_ingest(data: BatchIngestModel):
    if data.people:
        neo_service.create_people_batch(data.people)
    if data.messages:
        neo_service.create_messages_batch(data.messages)
    if data.calls:
        neo_service.create_calls_batch(data.calls)
    if data.relationships:
        neo_service.create_relationships_batch(data.relationships)
    return {"message": "Batch ingestion completed successfully"}

@router.post("/neighbors")
def neighbors(node: NodeIdModel):
    neighbors_list = neo_service.get_neighbors(node.node_id)
    return {"node_id": node.node_id, "neighbors": neighbors_list}

@router.post("/shortest_path")
def shortest_path(path: PathModel):
    path_list = neo_service.get_shortest_path(path.from_id, path.to_id)
    return {"from": path.from_id, "to": path.to_id, "path": path_list, "length": len(path_list)}

@router.post("/centrality")
def centrality(label: LabelModel):
    centrality_list = neo_service.get_degree_centrality(label.label)
    return {"label": label.label, "centrality": centrality_list}

@router.post("/community_detection")
def community_detection(label: LabelModel):
    communities = neo_service.detect_communities_simple(label.label)
    return {"label": label.label, "communities": communities}

# ------------------------
# New endpoint: Full graph for frontend
# ------------------------
@router.get("/full_graph")
def full_graph():
    """
    Returns the complete graph (nodes + relationships) for visualization on frontend.
    """
    graph_data = neo_service.get_full_graph()
    return graph_data
