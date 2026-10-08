#!/bin/bash

# CiteSpan Development Setup Script
# This script sets up the development environment

set -e

echo "🚀 Setting up CiteSpan Development Environment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create necessary directories
print_status "Creating necessary directories..."
mkdir -p data/uploads data/exports data/logs data/backups
mkdir -p config/environments
mkdir -p databases/postgresql

# Create environment file if it doesn't exist
if [ ! -f .env ]; then
    print_status "Creating .env file..."
    cat > .env << EOF
# Database Configuration
POSTGRES_PASSWORD=dev_password
NEO4J_PASSWORD=***REDACTED***

# MinIO Configuration
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin123

# Monitoring
GRAFANA_PASSWORD=admin123

# API Configuration
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
EOF
    print_warning "Please update the .env file with your actual configuration values."
fi

# Create PostgreSQL initialization script
print_status "Creating PostgreSQL initialization script..."
cat > databases/postgresql/init.sql << EOF
-- CiteSpan Database Initialization
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Create indexes for better performance
-- These will be created by the application migrations
EOF

# Create monitoring configuration
print_status "Creating monitoring configuration..."
mkdir -p docker/monitoring/grafana/dashboards
mkdir -p docker/monitoring/grafana/datasources

# Create Prometheus configuration
cat > docker/monitoring/prometheus.yml << EOF
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  # - "first_rules.yml"
  # - "second_rules.yml"

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'backend'
    static_configs:
      - targets: ['backend:8000']
    metrics_path: '/metrics'
    scrape_interval: 5s

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres:5432']
    scrape_interval: 10s

  - job_name: 'redis'
    static_configs:
      - targets: ['redis:6379']
    scrape_interval: 10s
EOF

# Build and start services
print_status "Building Docker images..."
docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml build

print_status "Starting development services..."
docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml up -d

# Wait for services to be ready
print_status "Waiting for services to be ready..."
sleep 30

# Check service health
print_status "Checking service health..."

# Check PostgreSQL
if docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml exec -T postgres pg_isready -U ufdr_user -d ufdr_analyzer_dev > /dev/null 2>&1; then
    print_status "✅ PostgreSQL is ready"
else
    print_error "❌ PostgreSQL is not ready"
fi

# Check Redis
if docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml exec -T redis redis-cli ping > /dev/null 2>&1; then
    print_status "✅ Redis is ready"
else
    print_error "❌ Redis is not ready"
fi

# Check Elasticsearch
if curl -f http://localhost:9200/_cluster/health > /dev/null 2>&1; then
    print_status "✅ Elasticsearch is ready"
else
    print_error "❌ Elasticsearch is not ready"
fi

# Check Backend
if curl -f http://localhost:8000/health > /dev/null 2>&1; then
    print_status "✅ Backend API is ready"
else
    print_error "❌ Backend API is not ready"
fi

# Check Frontend
if curl -f http://localhost:3000 > /dev/null 2>&1; then
    print_status "✅ Frontend is ready"
else
    print_error "❌ Frontend is not ready"
fi

print_status "🎉 Development environment setup complete!"
print_status ""
print_status "Services available at:"
print_status "  - Frontend: http://localhost:3000"
print_status "  - Backend API: http://localhost:8000"
print_status "  - API Documentation: http://localhost:8000/docs"
print_status "  - PgAdmin: http://localhost:5050"
print_status "  - Redis Commander: http://localhost:8081"
print_status "  - Elasticsearch: http://localhost:9200"
print_status "  - Neo4j Browser: http://localhost:7474"
print_status "  - MinIO Console: http://localhost:9001"
print_status ""
print_status "To stop the services:"
print_status "  docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml down"
print_status ""
print_status "To view logs:"
print_status "  docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml logs -f"
