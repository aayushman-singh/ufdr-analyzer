from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

try:
    with engine.connect() as connection:
        result = connection.execute(text("SELECT version();"))
        print("✅ Connected successfully to PostgreSQL")
        print("Database version:", result.scalar())
except Exception as e:
    print("❌ Connection failed:", e)
