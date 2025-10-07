# UFDR Analyzer Backend – API Instructions for Frontend

## 1. Project Overview
This backend provides APIs to interact with the UFDR Analyzer system. It handles ingestion, processing, and retrieval of data from Neo4j and PostgreSQL.  

The frontend can consume these APIs to display data in dashboards, tables, or visualizations.

---

## 2. How to Access APIs
The backend runs locally at:  

http://localhost:8000/


> Note: Replace `localhost` with the server URL if deployed.

---

## 3. Authentication
Currently, no authentication is required for local development.  

If authentication is added later, include headers like:

Authorization: Bearer <TOKEN>
Content-Type: application/json


---

## 4. List of APIs

### 4.1 Graph Router
**Base Path:** `/graph`  

| Endpoint               | Method | Description               | Request Body                       | Response                    |
|------------------------|--------|--------------------------|-----------------------------------|-----------------------------|
| `/graph/nodes`         | GET    | Fetch all nodes from Neo4j | None                              | JSON array of nodes         |
| `/graph/relationships` | GET    | Fetch all relationships    | None                              | JSON array of relationships |
| `/graph/query`         | POST   | Run custom Neo4j query     | `{ "query": "<CYPHER_QUERY>" }`  | Query result in JSON        |

#### Example: Fetch all nodes
```bash
GET http://localhost:8000/graph/nodes

Response:

[
  {"id": "1", "label": "Person", "properties": {"name": "Alice"}},
  {"id": "2", "label": "Person", "properties": {"name": "Bob"}}
]


Example: Run custom query
POST http://localhost:8000/graph/query
Content-Type: application/json

{
  "query": "MATCH (n:Person) RETURN n LIMIT 5"
}

Response:

[
  {"id": "1", "label": "Person", "properties": {"name": "Alice"}}
]

4.2 PostgreSQL / Data Router

Base Path: /data

Endpoint	Method	Description	Request Body	Response
/data/test-connection	GET	Checks database connection	None	JSON with status
/data/query	POST	Run custom SQL query	{ "query": "<SQL_QUERY>" }	Query result in JSON
Example: Test connection
GET http://localhost:8000/data/test-connection


Response:

{
  "status": "success",
  "message": "Postgres connection OK"
}

5. How to Extract API Data in Frontend

Use Axios or Fetch API in React to make HTTP requests.

Example: GET request
import axios from "axios";

const fetchNodes = async () => {
  const response = await axios.get("http://localhost:8000/graph/nodes");
  console.log(response.data);
}

Example: POST request
const queryData = async () => {
  const response = await axios.post("http://localhost:8000/graph/query", {
    query: "MATCH (n:Person) RETURN n LIMIT 5"
  });
  console.log(response.data);
}


Map the JSON response to display data in tables, charts, or graphs.

6. Notes

Make sure the backend is running before calling APIs.

Use Postman or Curl to test APIs during development.

Any new endpoints added should be documented in this README file.


This keeps **all content inside Markdown**, fully formatted, tables intact, and code blocks ready for copy-paste.  

If you want, I can also **add a table of all endpoints with their sample responses in one place** so the frontend dev has a ready reference. This makes it extremely developer-friendly. Do you want me to do that?
