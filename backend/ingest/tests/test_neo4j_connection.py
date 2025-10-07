from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")

try:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        result = session.run("RETURN '✅ Connected to Neo4j AuraDB!' AS message")
        print(result.single()["message"])
    driver.close()
except Exception as e:
    print("❌ Connection failed:", e)
