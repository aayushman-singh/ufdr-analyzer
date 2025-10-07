# backend/ingest/services/neo4j_service.py
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()


class Neo4jService:
    def __init__(self):
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USER")
        password = os.getenv("NEO4J_PASSWORD")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        if self.driver:
            self.driver.close()

    # ------------------------
    # Node creation
    # ------------------------
    def create_person(self, person: dict, add_placeholder_rel=False):
        """
        Optionally adds a self-loop or placeholder relationship to prevent
        isolated nodes from breaking neighbor/shortest_path queries.
        """
        with self.driver.session() as session:
            session.execute_write(
                lambda tx: tx.run(
                    "MERGE (p:Person {id: $id}) SET p.name = $name",
                    id=person["id"], name=person.get("name")
                )
            )
            if add_placeholder_rel:
                self.create_relationship(person["id"], person["id"], "SELF")

    def create_message(self, message: dict):
        with self.driver.session() as session:
            session.execute_write(
                lambda tx: tx.run(
                    "MERGE (m:Message {id: $id}) "
                    "SET m.content = $content, m.timestamp = $timestamp",
                    id=message["id"], content=message.get("content"),
                    timestamp=message.get("timestamp")
                )
            )

    def create_call(self, call: dict):
        with self.driver.session() as session:
            session.execute_write(
                lambda tx: tx.run(
                    "MERGE (c:Call {id: $id}) "
                    "SET c.caller = $caller, c.receiver = $receiver, c.duration = $duration",
                    id=call["id"], caller=call.get("caller"),
                    receiver=call.get("receiver"),
                    duration=call.get("duration")
                )
            )

    # ------------------------
    # Batch insertions
    # ------------------------
    def create_people_batch(self, people: list[dict]):
        for person in people:
            self.create_person(person)

    def create_messages_batch(self, messages: list[dict]):
        for message in messages:
            self.create_message(message)

    def create_calls_batch(self, calls: list[dict]):
        for call in calls:
            self.create_call(call)

    def create_relationship(self, from_id, to_id, relation_type):
        with self.driver.session() as session:
            session.execute_write(
                lambda tx: tx.run(
                    f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) "
                    f"MERGE (a)-[r:{relation_type}]->(b)",
                    from_id=from_id, to_id=to_id
                )
            )

    def create_relationships_batch(self, relationships: list[dict]):
        for rel in relationships:
            self.create_relationship(rel["from_id"], rel["to_id"], rel["type"])

    # ------------------------
    # Constraints
    # ------------------------
    def create_constraints(self):
        with self.driver.session() as session:
            session.execute_write(lambda tx: tx.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE"
            ))
            session.execute_write(lambda tx: tx.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Message) REQUIRE m.id IS UNIQUE"
            ))
            session.execute_write(lambda tx: tx.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Call) REQUIRE c.id IS UNIQUE"
            ))

    # ------------------------
    # Query methods
    # ------------------------
    def get_all_nodes(self, label: str):
        with self.driver.session() as session:
            return session.execute_read(
                lambda tx: [record["n"] for record in tx.run(f"MATCH (n:{label}) RETURN n")]
            )

    def get_neighbors(self, node_id):
        with self.driver.session() as session:
            result = session.execute_read(
                lambda tx: [record["n"]["id"] for record in tx.run(
                    "MATCH (a {id: $node_id})--(n) RETURN n",
                    node_id=node_id
                )]
            )
            return result or []

    def get_shortest_path(self, from_id, to_id):
        with self.driver.session() as session:
            result = session.execute_read(
                lambda tx: tx.run(
                    """
                    MATCH p=shortestPath((a {id: $from_id})-[*]-(b {id: $to_id}))
                    RETURN [n IN nodes(p) | n.id] AS path
                    """,
                    from_id=from_id, to_id=to_id
                ).single()
            )
            return result["path"] if result else []

    # ------------------------
    # Centrality & Community Detection
    # ------------------------
    def get_degree_centrality(self, label):
        with self.driver.session() as session:
            return session.execute_read(
                lambda tx: [
                    {"id": record["n"]["id"], "degree": record["degree"]}
                    for record in tx.run(
                        f"MATCH (n:{label})-[r]-() "
                        "RETURN n, count(r) AS degree "
                        "ORDER BY degree DESC"
                    )
                ]
            )

    def detect_communities_simple(self, label):
        """
        Simple neighborhood-based community detection.
        Works without Graph Data Science library.
        """
        with self.driver.session() as session:
            def run_query(tx):
                result = tx.run(
                    f"""
                    MATCH (n:{label})
                    OPTIONAL MATCH (n)-[:CALLED|SENT*]-(m:{label})
                    RETURN n.id AS nodeId, collect(DISTINCT m.id) AS community
                    """
                )
                return [{"id": r["nodeId"], "community": r["community"]} for r in result]

            return session.execute_read(run_query)

    # ------------------------
    # Full graph for frontend visualization
    # ------------------------
    def get_full_graph(self):
        with self.driver.session() as session:
            nodes = session.execute_read(
                lambda tx: [
                    {"id": record["n"]["id"], "label": list(record["n"].labels)[0]}
                    for record in tx.run("MATCH (n) RETURN n")
                ]
            )
            edges = session.execute_read(
                lambda tx: [
                    {"from": record["from"]["id"], "to": record["to"]["id"], "type": record["type"]}
                    for record in tx.run("MATCH (from)-[r]->(to) RETURN from, r AS type, to")
                ]
            )
            return {"nodes": nodes, "edges": edges}
