#!/bin/bash

# UFDR Analyzer Production Setup Script
# This script sets up the production environment

set -e

echo "🚀 Setting up UFDR Analyzer Production Environment..."

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

# Check if .env file exists
if [ ! -f .env ]; then
    print_error ".env file not found. Please create it with production configuration."
    exit 1
fi

# Create necessary directories
print_status "Creating necessary directories..."
mkdir -p data/uploads data/exports data/logs data/backups
mkdir -p config/environments
mkdir -p databases/postgresql
mkdir -p docker/nginx/ssl

# Create production environment file
print_status "Creating production environment configuration..."
cat > docker/environments/production.env << EOF
# Production Environment Configuration
NODE_ENV=production
DEBUG=false
LOG_LEVEL=info

# Database Configuration
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
NEO4J_PASSWORD=${NEO4J_PASSWORD}

# MinIO Configuration
MINIO_ROOT_USER=${MINIO_ROOT_USER}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}

# API Configuration
SECRET_KEY=${SECRET_KEY}
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Monitoring
GRAFANA_PASSWORD=${GRAFANA_PASSWORD}
EOF

# Create SSL certificate directory structure
print_status "Setting up SSL configuration..."
if [ ! -f docker/nginx/ssl/cert.pem ] || [ ! -f docker/nginx/ssl/key.pem ]; then
    print_warning "SSL certificates not found. Creating self-signed certificates for development..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout docker/nginx/ssl/key.pem \
        -out docker/nginx/ssl/cert.pem \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=ufdr.local"
    print_warning "For production, replace these with real SSL certificates."
fi

# Create backup script
print_status "Creating backup script..."
cat > docker/scripts/backup.sh << 'EOF'
#!/bin/bash
# Backup script for production data

BACKUP_DIR="/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Creating backup in $BACKUP_DIR..."

# Backup PostgreSQL
docker-compose exec -T postgres pg_dump -U ufdr_user ufdr_analyzer_prod > "$BACKUP_DIR/postgres_backup.sql"

# Backup Neo4j
docker-compose exec -T neo4j neo4j-admin dump --database=neo4j --to="$BACKUP_DIR/neo4j_backup.dump"

# Backup MinIO data
docker-compose exec -T minio mc mirror /data "$BACKUP_DIR/minio_data"

# Backup application data
cp -r data/uploads "$BACKUP_DIR/"
cp -r data/exports "$BACKUP_DIR/"

echo "Backup completed: $BACKUP_DIR"
EOF

chmod +x docker/scripts/backup.sh

# Create restore script
print_status "Creating restore script..."
cat > docker/scripts/restore.sh << 'EOF'
#!/bin/bash
# Restore script for production data

if [ -z "$1" ]; then
    echo "Usage: $0 <backup_directory>"
    exit 1
fi

BACKUP_DIR="$1"

if [ ! -d "$BACKUP_DIR" ]; then
    echo "Backup directory not found: $BACKUP_DIR"
    exit 1
fi

echo "Restoring from backup: $BACKUP_DIR"

# Restore PostgreSQL
if [ -f "$BACKUP_DIR/postgres_backup.sql" ]; then
    docker-compose exec -T postgres psql -U ufdr_user -d ufdr_analyzer_prod < "$BACKUP_DIR/postgres_backup.sql"
fi

# Restore Neo4j
if [ -f "$BACKUP_DIR/neo4j_backup.dump" ]; then
    docker-compose exec -T neo4j neo4j-admin load --database=neo4j --from="$BACKUP_DIR/neo4j_backup.dump"
fi

# Restore MinIO data
if [ -d "$BACKUP_DIR/minio_data" ]; then
    docker-compose exec -T minio mc mirror "$BACKUP_DIR/minio_data" /data
fi

# Restore application data
if [ -d "$BACKUP_DIR/uploads" ]; then
    cp -r "$BACKUP_DIR/uploads" data/
fi

if [ -d "$BACKUP_DIR/exports" ]; then
    cp -r "$BACKUP_DIR/exports" data/
fi

echo "Restore completed"
EOF

chmod +x docker/scripts/restore.sh

# Build and start production services
print_status "Building production Docker images..."
docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml build

print_status "Starting production services..."
docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml up -d

# Wait for services to be ready
print_status "Waiting for services to be ready..."
sleep 60

# Check service health
print_status "Checking service health..."

# Check PostgreSQL
if docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml exec -T postgres pg_isready -U ufdr_user -d ufdr_analyzer_prod > /dev/null 2>&1; then
    print_status "✅ PostgreSQL is ready"
else
    print_error "❌ PostgreSQL is not ready"
fi

# Check Redis
if docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml exec -T redis redis-cli ping > /dev/null 2>&1; then
    print_status "✅ Redis is ready"
else
    print_error "❌ Redis is not ready"
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

print_status "🎉 Production environment setup complete!"
print_status ""
print_status "Services available at:"
print_status "  - Frontend: http://localhost:3000"
print_status "  - Backend API: http://localhost:8000"
print_status "  - API Documentation: http://localhost:8000/docs"
print_status "  - Prometheus: http://localhost:9090"
print_status "  - Grafana: http://localhost:3001"
print_status ""
print_status "To stop the services:"
print_status "  docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml down"
print_status ""
print_status "To view logs:"
print_status "  docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml logs -f"
print_status ""
print_status "To create backups:"
print_status "  ./docker/scripts/backup.sh"
print_status ""
print_status "To restore from backup:"
print_status "  ./docker/scripts/restore.sh <backup_directory>"
