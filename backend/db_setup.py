import datetime
import uuid
import random
import json
from typing import List, Optional

from sqlmodel import Field, SQLModel, Relationship, create_engine, Session
from sqlalchemy import Column, TEXT
# Vector extension will be handled at runtime
VECTOR_AVAILABLE = False
Vector = None


class User(SQLModel, table=True):
    """Represents a user of the system (an Investigating Officer)."""
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    username: str = Field(index=True)
    email: str = Field(unique=True)
    password_hash: str
    is_admin: bool = False
    created_at: datetime.datetime = Field(
        default_factory=datetime.datetime.now)

    # Relationships to other tables
    runs: List["Run"] = Relationship(back_populates="user")
    rules: List["Rule"] = Relationship(back_populates="user")
    backups: List["Backup"] = Relationship(back_populates="user")
    queries: List["Query"] = Relationship(back_populates="user")


class Rule(SQLModel, table=True):
    """
    Represents a specific natural language query or pattern.
    These are the "recipes" the AI will follow.
    """
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    title: str = Field(index=True)
    description: str
    query_text: str  # The natural language query, e.g.,
    # "Show me all WhatsApp chats mentioning Bitcoin"
    created_at: datetime.datetime = Field(
        default_factory=datetime.datetime.now)
    is_template: bool = False

    # Relationship to the user who created it
    user: User = Relationship(back_populates="rules")
    results: List["Result"] = Relationship(back_populates="rule")


class Run(SQLModel, table=True):
    """
    Represents a single analysis session on an ingested UFDR report.
    This tracks the entire process from ingestion to completion.
    """
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    ufdr_file_name: str
    status: str  # e.g., "ingesting", "analyzing", "complete", "failed"
    start_time: datetime.datetime = Field(
        default_factory=datetime.datetime.now)
    end_time: Optional[datetime.datetime]
    extraction_metadata: Optional[str] = Field(default=None, sa_column=Column(TEXT))  # JSON string for UFDR extraction metadata
    file_content_hash: Optional[str] = Field(default=None, index=True)  # SHA-256 hash for deduplication
    original_file_path: Optional[str] = Field(default=None)  # Original file path for reference

    # Relationships
    user: User = Relationship(back_populates="runs")
    results: List["Result"] = Relationship(back_populates="run")
    messages: List["Message"] = Relationship(back_populates="run")
    calls: List["Call"] = Relationship(back_populates="run")
    contacts: List["Contact"] = Relationship(back_populates="run")
    media: List["Media"] = Relationship(back_populates="run")
    aleapp_artifacts: List["AleappArtifact"] = Relationship(back_populates="run")
    aleapp_reports: List["AleappReport"] = Relationship(back_populates="run")
    queries: List["Query"] = Relationship(back_populates="run")

class Result(SQLModel, table=True):
    """
    Represents a finding or piece of evidence identified by a
    specific rule within a run.
    This is where the actionable data is stored.
    """
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="run.id")
    rule_id: uuid.UUID = Field(foreign_key="rule.id")
    result_type: str  # e.g., "chat", "call_log", "contact"
    evidence_data: str  # A stringified JSON object containing the found data
    created_at: datetime.datetime = Field(
        default_factory=datetime.datetime.now)
    confidence_score: Optional[float] = None

    # Relationships
    run: Run = Relationship(back_populates="results")
    rule: Rule = Relationship(back_populates="results")


class Backup(SQLModel, table=True):
    """
    Implements the snapshot storage and audit logging.
    A log of important system events or database snapshots.
    """
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    event_type: str  # e.g. "database_snapshot", "user_login", "security_event"
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
    description: str
    snapshot_path: Optional[str] = None  # Path to the actual snapshot file

    # Relationship
    user: User = Relationship(back_populates="backups")


class Message(SQLModel, table=True):
    """Represents a message from UFDR data."""
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="run.id")
    sender: str
    receiver: str
    timestamp: datetime.datetime
    content: str
    # Note: Vector field will be added later when pgvector is available

    # Relationship
    run: Run = Relationship(back_populates="messages")


class Call(SQLModel, table=True):
    """Represents a call from UFDR data."""
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="run.id")
    caller: str
    receiver: str
    timestamp: datetime.datetime
    duration: Optional[int] = None  # Duration in seconds

    # Relationship
    run: Run = Relationship(back_populates="calls")


class Contact(SQLModel, table=True):
    """Represents a contact from UFDR data."""
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="run.id")
    name: str
    number: str

    # Relationship
    run: Run = Relationship(back_populates="contacts")


class Media(SQLModel, table=True):
    """Represents media files from UFDR data."""
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="run.id")
    original_path: str
    storage_path: str
    media_type: Optional[str] = None

    # Relationship
    run: Run = Relationship(back_populates="media")


class AleappArtifact(SQLModel, table=True):
    """Represents ALEAPP analysis artifacts."""
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="run.id")
    artifact_type: str  # e.g., "csv", "json", "html"
    filename: str
    file_path: str
    category: Optional[str] = None
    row_count: Optional[int] = None
    data: Optional[str] = None  # JSON string for structured data
    created_at: datetime.datetime = Field(
        default_factory=datetime.datetime.now)

    # Relationship
    run: Run = Relationship(back_populates="aleapp_artifacts")


class AleappReport(SQLModel, table=True):
    """Represents ALEAPP HTML reports."""
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="run.id")
    report_type: str  # e.g., "html", "summary"
    filename: str
    file_path: str
    created_at: datetime.datetime = Field(
        default_factory=datetime.datetime.now)

    # Relationship
    run: Run = Relationship(back_populates="aleapp_reports")


class Query(SQLModel, table=True):
    """Tracks natural language queries executed against UFDR data."""
    id: Optional[uuid.UUID] = Field(
        default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="run.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    query_text: str  # Original natural language query
    intent: Optional[str] = None  # Classified intent (e.g., "crypto_search", "foreign_numbers")
    parameters: Optional[str] = Field(default=None, sa_column=Column(TEXT))  # JSON of extracted query parameters
    results_summary: Optional[str] = Field(default=None, sa_column=Column(TEXT))  # JSON summary of results
    result_count: int = 0  # Number of results returned
    execution_time: Optional[float] = None  # Query execution time in seconds
    status: str = "pending"  # "pending", "completed", "failed"
    error_message: Optional[str] = None  # Error message if query failed
    created_at: datetime.datetime = Field(
        default_factory=datetime.datetime.now)

    # Relationships
    run: Run = Relationship(back_populates="queries")
    user: User = Relationship(back_populates="queries")


# 2. Database Setup and Seeding
def create_db_and_tables(engine):
    """
    Creates the database and all tables defined by the SQLModel classes.
    Drops existing tables first to ensure a clean state.
    """
    # Drop all existing tables before creating new ones
    SQLModel.metadata.drop_all(engine)

    # Create the database and all tables
    SQLModel.metadata.create_all(engine)
    print("Database and tables created successfully.")


def seed_db_with_sample_data(session: Session):
    """Seeds the database with sample data for testing and demonstration."""
    print("Seeding database with sample data...")

    # ------------------ USERS ------------------
    users_to_add = []
    usernames = ["IO Sharma", "IO Mehta", "IO Singh", "IO Khan", "IO Patel",
                 "IO Kumar", "IO Joshi", "IO Reddy", "IO Menon",
                 "Admin Divyanshi"]
    for i in range(10):
        is_admin = (i == 9)  # Last user is admin
        user = User(
            username=usernames[i],
            email=f"{usernames[i].lower().replace(' ', '.')}@investigator.gov",
            password_hash=f"hashed_password_{i+1}",
            is_admin=is_admin
        )
        users_to_add.append(user)
    session.add_all(users_to_add)
    session.commit()
    for user in users_to_add:
        session.refresh(user)

    # ------------------ RULES ------------------
    rules_to_add = []
    rule_queries = [
        "Find all chats mentioning 'Bitcoin', 'Ethereum', or 'USDT'.",
        "List all calls to or from international numbers.",
        "Show contacts with suspicious names like 'Mr. X' or 'Ghost'.",
        "Identify messages with financial terms like 'transfer' or 'payment'.",
        "Search for mentions of specific locations like 'Kolkata' or 'Delhi'.",
        "Show messages containing images or videos.",
        "List all web browsing history related to a specific domain.",
        "Find all deleted messages from social media apps.",
        "Identify chats with keywords related to illegal activities.",
        "Show all contacts in the suspect's 'favorites' list."
    ]
    for i in range(10):
        rule = Rule(
            user_id=users_to_add[i % 10].id,
            title=f"Query {i+1}: {rule_queries[i]}",
            description=f"Automated query for rule {i+1}.",
            query_text=rule_queries[i]
        )
        rules_to_add.append(rule)
    session.add_all(rules_to_add)
    session.commit()
    for rule in rules_to_add:
        session.refresh(rule)

    # ------------------ RUNS ------------------
    runs_to_add = []
    statuses = ["complete", "complete", "ingesting", "failed", "analyzing"]
    for i in range(10):
        run = Run(
            user_id=users_to_add[i % 10].id,
            ufdr_file_name=f"Case-2023_0{i+1}_Phone_Dump.ufdr",
            status=random.choice(statuses),
            end_time=datetime.datetime.now() if statuses[i % 5] in [
                "complete", "analyzing", "failed"] else None
        )
        runs_to_add.append(run)
    session.add_all(runs_to_add)
    session.commit()
    for run in runs_to_add:
        session.refresh(run)

    # ------------------ RESULTS ------------------
    results_to_add = []
    evidence_types = ["chat", "call_log", "contact", "location", "web_history"]
    for i in range(10):
        result_type = random.choice(evidence_types)
        evidence_data = {}
        if result_type == "chat":
            evidence_data = {
                "app": random.choice(["WhatsApp", "Telegram", "Signal"]),
                "message": f"Message related to query for rule {i+1}.",
                "from_number": f"+9198765432{i}",
                "timestamp": datetime.datetime.now().isoformat()
            }
        elif result_type == "call_log":
            evidence_data = {
                "direction": random.choice(["Incoming", "Outgoing"]),
                "from_number": f"+9198765432{i}",
                "to_number": f"+1555123456{i}",
                "duration_sec": random.randint(30, 600),
                "timestamp": datetime.datetime.now().isoformat()
            }
        elif result_type == "contact":
            evidence_data = {
                "name": f"Suspect {i+1}",
                "phone_number": f"+9199998888{i}",
                "email": f"suspect{i+1}@example.com"
            }
        elif result_type == "location":
            evidence_data = {
                "latitude": 28.6139 + random.uniform(-0.1, 0.1),
                "longitude": 77.2090 + random.uniform(-0.1, 0.1),
                "timestamp": datetime.datetime.now().isoformat()
            }
        elif result_type == "web_history":
            evidence_data = {
                "url": f"https://www.example.com/page{i+1}",
                "title": f"Web Page Title {i+1}",
                "visit_count": random.randint(1, 10)
            }

        result = Result(
            run_id=runs_to_add[i % 10].id,
            rule_id=rules_to_add[i % 10].id,
            result_type=result_type,
            evidence_data=json.dumps(evidence_data),
            confidence_score=random.uniform(0.7, 0.99)
        )
        results_to_add.append(result)
    session.add_all(results_to_add)
    session.commit()

    # ------------------ BACKUPS ------------------
    backups_to_add = []
    backup_events = ["database_snapshot", "user_login", "security_event",
                     "system_update"]
    for i in range(10):
        event_type = random.choice(backup_events)
        backup = Backup(
            user_id=users_to_add[i % 10].id,
            event_type=event_type,
            description=f"Log for event type: {event_type} number {i+1}",
            snapshot_path=f"/backups/daily/snapshot_{i+1}.db"
            if event_type == "database_snapshot" else None
        )
        backups_to_add.append(backup)
    session.add_all(backups_to_add)
    session.commit()

    print("Sample data successfully added to the database.")


if __name__ == "__main__":
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    from config import POSTGRES_CONFIG

    # Check if vector extension is available first
    vector_extension_available = False

    # First, create the database if it doesn't exist
    try:
        # Connect to PostgreSQL server (not to specific database)
        conn = psycopg2.connect(
            host=POSTGRES_CONFIG['host'],
            port=POSTGRES_CONFIG['port'],
            user=POSTGRES_CONFIG['user'],
            password=POSTGRES_CONFIG['password'],
            database='postgres'  # Connect to default postgres database
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        # Check if database exists
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (POSTGRES_CONFIG['database'],))
        if not cursor.fetchone():
            cursor.execute(f'CREATE DATABASE "{POSTGRES_CONFIG["database"]}"')
            print(f"Created database '{POSTGRES_CONFIG['database']}'")
        else:
            print(f"Database '{POSTGRES_CONFIG['database']}' already exists")

        cursor.close()
        conn.close()

        # Connect to the target database to install vector extension
        conn = psycopg2.connect(
            host=POSTGRES_CONFIG['host'],
            port=POSTGRES_CONFIG['port'],
            user=POSTGRES_CONFIG['user'],
            password=POSTGRES_CONFIG['password'],
            database=POSTGRES_CONFIG['database']
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        # Install vector extension (optional)
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            vector_extension_available = True
            print("Vector extension installed successfully")
        except Exception as vec_error:
            print(f"Warning: Could not install vector extension: {vec_error}")
            print("Vector search functionality will be limited")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Error setting up database: {e}")
        exit(1)

    # Vector extension check complete

    # Now use the engine from database.py
    from database import engine
    create_db_and_tables(engine)

    with Session(engine) as session:
        seed_db_with_sample_data(session)

    print("\nDatabase setup and seeding complete.")
    if vector_extension_available:
        print("PostgreSQL database with vector support configured successfully.")
    else:
        print("PostgreSQL database configured successfully (without vector support).")
