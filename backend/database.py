# backend/database.py
import os
from sqlmodel import create_engine, Session, SQLModel
from config import POSTGRES_URL

# Get database connection details from environment variables
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    POSTGRES_URL
)

# SQL echo is OFF by default: this is forensic data, and SQLAlchemy's echo logs
# statements and bound parameters (phone numbers, message text, identifiers).
# Enable explicitly with SQL_ECHO=1 only for local debugging.
_echo = os.getenv("SQL_ECHO", "0").lower() in ("1", "true", "yes")

# Connection-pool tuning is PostgreSQL-specific. SQLite (used by the test
# suite and CI) rejects these kwargs, so apply them only for non-sqlite URLs.
_engine_kwargs: dict = {"echo": _echo}
if not DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update(
        pool_size=20,        # PostgreSQL connection pool settings for large uploads
        max_overflow=30,
        pool_timeout=30,
        pool_recycle=3600,
    )

# Create the SQLAlchemy engine.
engine = create_engine(DATABASE_URL, **_engine_kwargs)


def get_session():
    """Dependency to get a database session."""
    with Session(engine) as session:
        yield session


def create_db_and_tables():
    """A function to create all tables. Call this from main.py."""
    SQLModel.metadata.create_all(engine)
