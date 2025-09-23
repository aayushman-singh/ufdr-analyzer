# backend/database.py
import os
from sqlmodel import create_engine, Session, SQLModel

# Get database connection details from environment variables
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./database.db"
)

# Create the SQLAlchemy engine (works with both SQLite and PostgreSQL)
engine = create_engine(DATABASE_URL, echo=True)


def get_session():
    """Dependency to get a database session."""
    with Session(engine) as session:
        yield session


def create_db_and_tables():
    """A function to create all tables. Call this from main.py."""
    SQLModel.metadata.create_all(engine)
