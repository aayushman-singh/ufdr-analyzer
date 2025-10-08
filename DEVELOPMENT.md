# UFDR Analyzer - Development Setup

## 🚀 Quick Start

**TL;DR:**
- **Have PostgreSQL installed?** Run `./start-dev-local.bat` (Windows) or `./start-dev-local.sh` (Linux/Mac)
- **Want Docker setup?** Install Docker Desktop, then run `./start-dev-services.bat`

Choose your preferred setup method:

### Option 1: Local Setup (No Docker) ⚡ FASTEST TO START

**For users with MSYS2 PostgreSQL already installed**

**Prerequisites:**
- PostgreSQL (via MSYS2 or standalone)
- Python 3.10+
- Git

**One-Command Start:**
```bash
# Windows
./start-dev-local.bat

# Linux/Mac/Git Bash
./start-dev-local.sh
```

This script will:
- ✅ Check if PostgreSQL is running (start if needed)
- ✅ Test database connection
- ✅ Start the backend server automatically
- ✅ Run completely hands-free (no prompts or pauses)

---

### Option 2: Docker Setup (Recommended for Teams) 🐳

**Best for new contributors and consistent environments**

**Prerequisites:**
- Docker Desktop installed ([Download here](https://www.docker.com/products/docker-desktop/))
- Python 3.10+
- Git

### Setup Steps

1. **Start Development Services** (PostgreSQL + MeiliSearch)

   **Windows (PowerShell/CMD):**
   ```bash
   ./start-dev-services.bat
   ```

   **Linux/Mac/Git Bash:**
   ```bash
   ./start-dev-services.sh
   ```

   **Or manually:**
   ```bash
   docker compose -f docker-compose.dev.yml up -d
   ```

2. **Install Python Dependencies**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

3. **Start the Backend Server**
   ```bash
   python server.py
   ```

4. **Access the Application**
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs
   - MeiliSearch: http://localhost:7700

### Stop Services

```bash
docker compose -f docker-compose.dev.yml down
```

To also remove data volumes:
```bash
docker compose -f docker-compose.dev.yml down -v
```

---

## Alternative: Manual PostgreSQL Setup (MSYS2)

If you prefer not to use Docker:

### 1. Start PostgreSQL (MSYS2)

**First time only - Initialize database:**
```bash
initdb -D $HOME/postgres_data
```

**Start PostgreSQL:**
```bash
pg_ctl -D $HOME/postgres_data start
```

**Create database and user:**
```bash
psql -h localhost -p 5432 -U $USER -d postgres
```

Then in PostgreSQL prompt:
```sql
CREATE DATABASE ufdr_analyzer;
CREATE USER ufdr_user WITH PASSWORD 'ufdr_password';
GRANT ALL PRIVILEGES ON DATABASE ufdr_analyzer TO ufdr_user;
GRANT ALL PRIVILEGES ON SCHEMA public TO ufdr_user;
GRANT CREATE ON SCHEMA public TO ufdr_user;
\q
```

**Stop PostgreSQL:**
```bash
pg_ctl -D $HOME/postgres_data stop
```

---

## Configuration

### Database Connection

The backend uses these connection details by default:
- Host: `localhost`
- Port: `5432`
- Database: `ufdr_analyzer`
- User: `ufdr_user`
- Password: `ufdr_password`

To override, set the `DATABASE_URL` environment variable:
```bash
export DATABASE_URL="postgresql://user:password@host:port/database"
```

### MeiliSearch (Optional)

MeiliSearch provides enhanced full-text search capabilities. The application works without it, but search features will be limited.

- URL: `http://localhost:7700`
- To override: `export MEILI_URL="http://your-meili-url:7700"`

---

## Data Ingestion

### Ingest a UFDR file

Make sure PostgreSQL is running first, then:

```bash
cd backend
python ingest_cli.py ../Android_13_Image.ufdr
```

The ingestion process will:
- Extract the UFDR file
- Run ALEAPP for Android forensic analysis
- Parse all data (messages, contacts, calls, media)
- Store in PostgreSQL and index in MeiliSearch

**Note:** The process is fully automated and hands-free. If you see connection errors, make sure PostgreSQL is running.

---

## Troubleshooting

### PostgreSQL Connection Refused

**Docker setup:**
```bash
# Check if container is running
docker compose -f docker-compose.dev.yml ps

# View logs
docker compose -f docker-compose.dev.yml logs postgres

# Restart services
docker compose -f docker-compose.dev.yml restart
```

**Manual setup:**
```bash
# Check if PostgreSQL is running
pg_ctl status -D $HOME/postgres_data

# Start if not running
pg_ctl -D $HOME/postgres_data start
```

### Permission Errors

If you see "permission denied for schema public":
```bash
psql -h localhost -p 5432 -U $USER -d ufdr_analyzer
```

Then:
```sql
GRANT ALL PRIVILEGES ON SCHEMA public TO ufdr_user;
GRANT CREATE ON SCHEMA public TO ufdr_user;
ALTER USER ufdr_user CREATEDB;
```

### Port Already in Use

If port 5432 or 7700 is already in use:

**Find what's using the port:**
```bash
# Windows
netstat -ano | findstr :5432

# Linux/Mac
lsof -i :5432
```

**Change the port in docker-compose.dev.yml:**
```yaml
ports:
  - "5433:5432"  # Use 5433 instead of 5432
```

Then update `backend/config.py` accordingly.

---

## Why Docker is Recommended

### Problems with Manual Setup:
- ❌ PostgreSQL doesn't run as a service on MSYS2
- ❌ Must manually start/stop database each session
- ❌ Complex permission configuration
- ❌ Different setup steps for Windows/Mac/Linux
- ❌ Easy to forget to start services

### Benefits of Docker:
- ✅ One command starts everything
- ✅ Consistent across all platforms
- ✅ Services auto-start when Docker is running
- ✅ Easy to reset/clean data
- ✅ No permission issues
- ✅ Isolated from system installations

---

## Development Workflow

### Daily Development

1. **Start services** (only needed once per session):
   ```bash
   ./start-dev-services.bat  # or .sh
   ```

2. **Start backend** (in a new terminal):
   ```bash
   cd backend
   python server.py
   ```

3. **Make your changes** - the server auto-reloads

4. **Stop services** when done:
   ```bash
   docker compose -f docker-compose.dev.yml down
   ```

### Database Management

**Connect to PostgreSQL:**
```bash
docker exec -it ufdr_postgres_dev psql -U ufdr_user -d ufdr_analyzer
```

**Backup database:**
```bash
docker exec ufdr_postgres_dev pg_dump -U ufdr_user ufdr_analyzer > backup.sql
```

**Restore database:**
```bash
docker exec -i ufdr_postgres_dev psql -U ufdr_user ufdr_analyzer < backup.sql
```

**Reset database:**
```bash
docker compose -f docker-compose.dev.yml down -v
docker compose -f docker-compose.dev.yml up -d
```

---

## Next Steps

- Read the main [README.md](README.md) for project overview
- Check [backend/README.md](backend/README.md) for API documentation
- View API documentation at http://localhost:8000/docs

