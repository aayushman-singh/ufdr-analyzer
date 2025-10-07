#!/bin/bash
# Start development services for UFDR Analyzer

echo "========================================"
echo "Starting UFDR Analyzer Dev Services"
echo "========================================"
echo ""

echo "Starting PostgreSQL and MeiliSearch..."
docker compose -f docker-compose.dev.yml up -d

echo ""
echo "Waiting for services to be ready..."
sleep 5

echo ""
echo "========================================"
echo "Services Status:"
echo "========================================"
docker compose -f docker-compose.dev.yml ps

echo ""
echo "========================================"
echo "Development services are ready!"
echo "========================================"
echo "PostgreSQL: localhost:5432"
echo "  - Database: ufdr_analyzer"
echo "  - User: ufdr_user"
echo "  - Password: ufdr_password"
echo ""
echo "MeiliSearch: http://localhost:7700"
echo ""
echo "To start the backend server, run:"
echo "  cd backend"
echo "  python server.py"
echo ""
echo "To stop services, run:"
echo "  docker compose -f docker-compose.dev.yml down"
echo "========================================"

