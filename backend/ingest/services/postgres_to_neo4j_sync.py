"""
PostgreSQL to Neo4j Data Synchronization Service
Extracts data from PostgreSQL and creates graph structure in Neo4j
"""

import os
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select
from neo4j import GraphDatabase
from dotenv import load_dotenv
from pathlib import Path
from database import get_session
from db_setup import User, Run, Message, Call, Contact, Media, AleappArtifact, AleappReport, Query

# Load environment variables
env_path = Path("S:/Repo/ufdr-analyzer/.env")
load_dotenv(dotenv_path=env_path)

class PostgresToNeo4jSync:
    def __init__(self):
        # Neo4j connection
        self.neo4j_uri = os.getenv("NEO4J_URI")
        self.neo4j_user = os.getenv("NEO4J_USERNAME")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD")
        
        if not all([self.neo4j_uri, self.neo4j_user, self.neo4j_password]):
            raise ValueError("Neo4j credentials not found in environment variables")
        
        self.neo4j_driver = GraphDatabase.driver(
            self.neo4j_uri, 
            auth=(self.neo4j_user, self.neo4j_password)
        )
    
    def close(self):
        """Close Neo4j driver connection"""
        if self.neo4j_driver:
            self.neo4j_driver.close()
    
    def clear_neo4j_data(self):
        """Clear all data from Neo4j (optional - for fresh start)"""
        with self.neo4j_driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            print("✅ Cleared all Neo4j data")
    
    def sync_all_data(self, clear_existing: bool = False):
        """Sync all data from PostgreSQL to Neo4j"""
        if clear_existing:
            self.clear_neo4j_data()
        
        print("🔄 Starting PostgreSQL to Neo4j synchronization...")
        
        # Get database session
        with next(get_session()) as db_session:
            # Sync in order of dependencies
            self.sync_users(db_session)
            self.sync_runs(db_session)
            self.sync_contacts(db_session)
            self.sync_messages(db_session)
            self.sync_calls(db_session)
            self.sync_media(db_session)
            self.sync_aleapp_artifacts(db_session)
            self.sync_queries(db_session)
            
            # Create relationships
            self.create_relationships()
        
        print("✅ Data synchronization completed!")
    
    def sync_users(self, db_session: Session):
        """Sync users from PostgreSQL to Neo4j"""
        print("📤 Syncing users...")
        
        users = db_session.exec(select(User)).all()
        
        with self.neo4j_driver.session() as session:
            for user in users:
                session.run(
                    """
                    MERGE (u:User {id: $id})
                    SET u.username = $username,
                        u.email = $email,
                        u.is_admin = $is_admin,
                        u.created_at = $created_at
                    """,
                    id=str(user.id),
                    username=user.username,
                    email=user.email,
                    is_admin=user.is_admin,
                    created_at=user.created_at.isoformat()
                )
        
        print(f"✅ Synced {len(users)} users")
    
    def sync_runs(self, db_session: Session):
        """Sync runs from PostgreSQL to Neo4j"""
        print("📤 Syncing runs...")
        
        runs = db_session.exec(select(Run)).all()
        
        with self.neo4j_driver.session() as session:
            for run in runs:
                session.run(
                    """
                    MERGE (r:Run {id: $id})
                    SET r.ufdr_file_name = $ufdr_file_name,
                        r.status = $status,
                        r.start_time = $start_time,
                        r.end_time = $end_time,
                        r.file_content_hash = $file_content_hash,
                        r.original_file_path = $original_file_path
                    """,
                    id=str(run.id),
                    ufdr_file_name=run.ufdr_file_name,
                    status=run.status,
                    start_time=run.start_time.isoformat(),
                    end_time=run.end_time.isoformat() if run.end_time else None,
                    file_content_hash=run.file_content_hash,
                    original_file_path=run.original_file_path
                )
        
        print(f"✅ Synced {len(runs)} runs")
    
    def sync_contacts(self, db_session: Session):
        """Sync contacts from PostgreSQL to Neo4j"""
        print("📤 Syncing contacts...")
        
        contacts = db_session.exec(select(Contact)).all()
        
        with self.neo4j_driver.session() as session:
            for contact in contacts:
                session.run(
                    """
                    MERGE (c:Contact {id: $id})
                    SET c.name = $name,
                        c.number = $number
                    """,
                    id=str(contact.id),
                    name=contact.name,
                    number=contact.number
                )
        
        print(f"✅ Synced {len(contacts)} contacts")
    
    def sync_messages(self, db_session: Session):
        """Sync messages from PostgreSQL to Neo4j"""
        print("📤 Syncing messages...")
        
        messages = db_session.exec(select(Message)).all()
        
        with self.neo4j_driver.session() as session:
            for message in messages:
                session.run(
                    """
                    MERGE (m:Message {id: $id})
                    SET m.sender = $sender,
                        m.receiver = $receiver,
                        m.timestamp = $timestamp,
                        m.content = $content
                    """,
                    id=str(message.id),
                    sender=message.sender,
                    receiver=message.receiver,
                    timestamp=message.timestamp.isoformat(),
                    content=message.content
                )
        
        print(f"✅ Synced {len(messages)} messages")
    
    def sync_calls(self, db_session: Session):
        """Sync calls from PostgreSQL to Neo4j"""
        print("📤 Syncing calls...")
        
        calls = db_session.exec(select(Call)).all()
        
        with self.neo4j_driver.session() as session:
            for call in calls:
                session.run(
                    """
                    MERGE (c:Call {id: $id})
                    SET c.caller = $caller,
                        c.receiver = $receiver,
                        c.timestamp = $timestamp,
                        c.duration = $duration
                    """,
                    id=str(call.id),
                    caller=call.caller,
                    receiver=call.receiver,
                    timestamp=call.timestamp.isoformat(),
                    duration=call.duration
                )
        
        print(f"✅ Synced {len(calls)} calls")
    
    def sync_media(self, db_session: Session):
        """Sync media files from PostgreSQL to Neo4j"""
        print("📤 Syncing media files...")
        
        media_files = db_session.exec(select(Media)).all()
        
        with self.neo4j_driver.session() as session:
            for media in media_files:
                session.run(
                    """
                    MERGE (m:Media {id: $id})
                    SET m.original_path = $original_path,
                        m.storage_path = $storage_path,
                        m.media_type = $media_type
                    """,
                    id=str(media.id),
                    original_path=media.original_path,
                    storage_path=media.storage_path,
                    media_type=media.media_type
                )
        
        print(f"✅ Synced {len(media_files)} media files")
    
    def sync_aleapp_artifacts(self, db_session: Session):
        """Sync ALEAPP artifacts from PostgreSQL to Neo4j"""
        print("📤 Syncing ALEAPP artifacts...")
        
        artifacts = db_session.exec(select(AleappArtifact)).all()
        
        with self.neo4j_driver.session() as session:
            for artifact in artifacts:
                session.run(
                    """
                    MERGE (a:Artifact {id: $id})
                    SET a.artifact_type = $artifact_type,
                        a.filename = $filename,
                        a.file_path = $file_path,
                        a.category = $category,
                        a.row_count = $row_count,
                        a.created_at = $created_at
                    """,
                    id=str(artifact.id),
                    artifact_type=artifact.artifact_type,
                    filename=artifact.filename,
                    file_path=artifact.file_path,
                    category=artifact.category,
                    row_count=artifact.row_count,
                    created_at=artifact.created_at.isoformat()
                )
        
        print(f"✅ Synced {len(artifacts)} ALEAPP artifacts")
    
    def sync_queries(self, db_session: Session):
        """Sync queries from PostgreSQL to Neo4j"""
        print("📤 Syncing queries...")
        
        queries = db_session.exec(select(Query)).all()
        
        with self.neo4j_driver.session() as session:
            for query in queries:
                session.run(
                    """
                    MERGE (q:Query {id: $id})
                    SET q.query_text = $query_text,
                        q.results_count = $results_count,
                        q.execution_time = $execution_time,
                        q.created_at = $created_at
                    """,
                    id=str(query.id),
                    query_text=query.query_text,
                    results_count=query.results_count,
                    execution_time=query.execution_time,
                    created_at=query.created_at.isoformat()
                )
        
        print(f"✅ Synced {len(queries)} queries")
    
    def create_relationships(self):
        """Create relationships between nodes in Neo4j"""
        print("🔗 Creating relationships...")
        
        with self.neo4j_driver.session() as session:
            # User -> Run relationships
            session.run("""
                MATCH (u:User), (r:Run)
                WHERE u.id = r.user_id
                MERGE (u)-[:CREATED]->(r)
            """)
            
            # Run -> Message relationships
            session.run("""
                MATCH (r:Run), (m:Message)
                WHERE r.id = m.run_id
                MERGE (r)-[:CONTAINS]->(m)
            """)
            
            # Run -> Call relationships
            session.run("""
                MATCH (r:Run), (c:Call)
                WHERE r.id = c.run_id
                MERGE (r)-[:CONTAINS]->(c)
            """)
            
            # Run -> Contact relationships
            session.run("""
                MATCH (r:Run), (c:Contact)
                WHERE r.id = c.run_id
                MERGE (r)-[:CONTAINS]->(c)
            """)
            
            # Run -> Media relationships
            session.run("""
                MATCH (r:Run), (m:Media)
                WHERE r.id = m.run_id
                MERGE (r)-[:CONTAINS]->(m)
            """)
            
            # Run -> Artifact relationships
            session.run("""
                MATCH (r:Run), (a:Artifact)
                WHERE r.id = a.run_id
                MERGE (r)-[:CONTAINS]->(a)
            """)
            
            # User -> Query relationships
            session.run("""
                MATCH (u:User), (q:Query)
                WHERE u.id = q.user_id
                MERGE (u)-[:EXECUTED]->(q)
            """)
            
            # Message sender/receiver relationships
            session.run("""
                MATCH (m:Message)
                WHERE m.sender IS NOT NULL AND m.receiver IS NOT NULL
                MERGE (sender:Person {id: m.sender})
                MERGE (receiver:Person {id: m.receiver})
                MERGE (sender)-[:SENT]->(m)
                MERGE (m)-[:TO]->(receiver)
            """)
            
            # Call caller/receiver relationships
            session.run("""
                MATCH (c:Call)
                WHERE c.caller IS NOT NULL AND c.receiver IS NOT NULL
                MERGE (caller:Person {id: c.caller})
                MERGE (receiver:Person {id: c.receiver})
                MERGE (caller)-[:CALLED]->(receiver)
            """)
        
        print("✅ Relationships created successfully!")
    
    def get_sync_stats(self) -> Dict[str, int]:
        """Get statistics about the synchronized data"""
        with self.neo4j_driver.session() as session:
            stats = {}
            
            # Count nodes by type
            node_types = ['User', 'Run', 'Contact', 'Message', 'Call', 'Media', 'Artifact', 'Query', 'Person']
            for node_type in node_types:
                result = session.run(f"MATCH (n:{node_type}) RETURN count(n) as count")
                stats[node_type] = result.single()["count"]
            
            # Count relationships
            result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
            stats['Relationships'] = result.single()["count"]
            
            return stats
