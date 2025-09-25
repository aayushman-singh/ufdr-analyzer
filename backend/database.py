# backend/database.py
import os
from sqlmodel import create_engine, Session, SQLModel
from config import POSTGRES_URL

# Get database connection details from environment variables
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    POSTGRES_URL
)

# Create the SQLAlchemy engine with PostgreSQL optimizations
engine = create_engine(
    DATABASE_URL,
    echo=True,
    # PostgreSQL connection pool settings for large uploads
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    pool_recycle=3600
)


def get_session():
    """Dependency to get a database session."""
    with Session(engine) as session:
        yield session


def create_db_and_tables():
    """A function to create all tables. Call this from main.py."""
    SQLModel.metadata.create_all(engine)
