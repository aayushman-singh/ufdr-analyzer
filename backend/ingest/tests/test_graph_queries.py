import asyncio
from backend.ingest.services.neo4j_service import Neo4jService

neo_service = Neo4jService()

# ------------------------
# Sample UFDR data
# ------------------------
people = [
    {"id": "P1", "name": "Alice"},
    {"id": "P2", "name": "Bob"},
    {"id": "P3", "name": "Charlie"},
]

messages = [
    {"id": "M1", "content": "Hello Bob", "timestamp": "2025-10-07T10:00:00"},
    {"id": "M2", "content": "Hi Alice", "timestamp": "2025-10-07T10:05:00"},
]

calls = [
    {"id": "C1", "caller": "P1", "receiver": "P2", "duration": 300},
    {"id": "C2", "caller": "P2", "receiver": "P3", "duration": 200},
]

relationships = [
    {"from_id": "P1", "to_id": "M1", "type": "SENT"},
    {"from_id": "P2", "to_id": "M2", "type": "SENT"},
    {"from_id": "P1", "to_id": "P2", "type": "CALLED"},
    {"from_id": "P2", "to_id": "P3", "type": "CALLED"},
]

# ------------------------
# Phase 3 Test
# ------------------------
def run_tests():
    print("Creating constraints...")
    neo_service.create_constraints()

    print("Batch inserting nodes and relationships...")
    neo_service.create_people_batch(people)
    neo_service.create_messages_batch(messages)
    neo_service.create_calls_batch(calls)
    neo_service.create_relationships_batch(relationships)

    # Test neighbors
    print("\nNeighbors of P2:")
    neighbors = neo_service.get_neighbors("P2")
    print(neighbors)

    # Test shortest path
    print("\nShortest path from P1 to P3:")
    path = neo_service.get_shortest_path("P1", "P3")
    print(path)

    # Test centrality
    print("\nDegree centrality for Person:")
    centrality = neo_service.get_degree_centrality("Person")
    for node in centrality:
        print(node)

    # Test community detection
    print("\nCommunity detection for Person:")
    communities = neo_service.detect_communities_simple("Person")
    for node in communities:
        print(node)

    neo_service.close()
    print("\nPhase 3 tests completed.")


if __name__ == "__main__":
    run_tests()
