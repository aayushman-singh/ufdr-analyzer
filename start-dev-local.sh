#!/bin/bash
# Start UFDR Analyzer with local PostgreSQL (no Docker required)

echo "========================================"
echo "Starting UFDR Analyzer (Local Setup)"
echo "========================================"
echo ""

echo "Checking PostgreSQL..."
if pg_ctl status -D "$HOME/postgres_data" > /dev/null 2>&1; then
    echo "[OK] PostgreSQL is already running"
else
    echo "[STARTING] PostgreSQL..."
    pg_ctl -D "$HOME/postgres_data" -l "$HOME/postgres_data/logfile" start
    echo "[OK] PostgreSQL started"
    sleep 2
fi

echo ""
echo "Testing PostgreSQL connection..."
if psql -h localhost -p 5432 -U ufdr_user -d ufdr_analyzer -c "SELECT 'Connection successful!' as status;" > /dev/null 2>&1; then
    echo "[OK] PostgreSQL connection successful"
else
    echo "[ERROR] PostgreSQL connection failed"
    echo "Please check your PostgreSQL configuration"
    exit 1
fi

echo ""
echo "========================================"
echo "Development Environment Ready!"
echo "========================================"
echo "PostgreSQL: localhost:5432"
echo "  - Database: ufdr_analyzer"
echo "  - User: ufdr_user"
echo "  - Password: ufdr_password"
echo ""
echo "Starting backend server..."
echo "Press Ctrl+C to stop"
echo ""
cd backend
python server.py

