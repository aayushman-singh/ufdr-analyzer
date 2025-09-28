# UFDR Analyzer Makefile
# Easy commands for development and deployment

.PHONY: help dev prod test clean build logs stop restart backup restore

# Default target
help:
	@echo "UFDR Analyzer - Available Commands:"
	@echo ""
	@echo "Development:"
	@echo "  make dev          - Start development environment"
	@echo "  make dev-build    - Build development images"
	@echo "  make dev-logs     - View development logs"
	@echo "  make dev-stop     - Stop development environment"
	@echo ""
	@echo "Production:"
	@echo "  make prod         - Start production environment"
	@echo "  make prod-build   - Build production images"
	@echo "  make prod-logs    - View production logs"
	@echo "  make prod-stop    - Stop production environment"
	@echo ""
	@echo "Utilities:"
	@echo "  make test         - Run tests"
	@echo "  make clean        - Clean up containers and volumes"
	@echo "  make backup       - Create backup"
	@echo "  make restore      - Restore from backup"
	@echo "  make logs         - View all logs"
	@echo "  make restart      - Restart all services"

# Development commands
dev:
	@echo "🚀 Starting development environment..."
	./docker/scripts/setup-dev.sh

dev-build:
	@echo "🔨 Building development images..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml build

dev-logs:
	@echo "📋 Viewing development logs..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml logs -f

dev-stop:
	@echo "🛑 Stopping development environment..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml down

# Production commands
prod:
	@echo "🚀 Starting production environment..."
	./docker/scripts/setup-prod.sh

prod-build:
	@echo "🔨 Building production images..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml build

prod-logs:
	@echo "📋 Viewing production logs..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml logs -f

prod-stop:
	@echo "🛑 Stopping production environment..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml down

# Test commands
test:
	@echo "🧪 Running tests..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml exec backend python -m pytest

# Utility commands
clean:
	@echo "🧹 Cleaning up containers and volumes..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml down -v
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.prod.yml down -v
	docker system prune -f
	docker volume prune -f

backup:
	@echo "💾 Creating backup..."
	./docker/scripts/backup.sh

restore:
	@echo "📥 Restoring from backup..."
	@read -p "Enter backup directory path: " backup_dir; \
	./docker/scripts/restore.sh $$backup_dir

logs:
	@echo "📋 Viewing all logs..."
	docker-compose -f docker-compose.yml logs -f

restart:
	@echo "🔄 Restarting all services..."
	docker-compose -f docker-compose.yml restart

# Database commands
db-migrate:
	@echo "🗄️ Running database migrations..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml exec backend alembic upgrade head

db-reset:
	@echo "🗄️ Resetting database..."
	docker-compose -f docker-compose.yml -f docker/environments/docker-compose.dev.yml exec postgres psql -U ufdr_user -d ufdr_analyzer_dev -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# Monitoring commands
monitor:
	@echo "📊 Opening monitoring dashboards..."
	@echo "Prometheus: http://localhost:9090"
	@echo "Grafana: http://localhost:3001"
	@echo "PgAdmin: http://localhost:5050"
	@echo "Redis Commander: http://localhost:8081"

# Health check
health:
	@echo "🏥 Checking service health..."
	@echo "Backend API:"
	@curl -s http://localhost:8000/health || echo "❌ Backend not responding"
	@echo "Frontend:"
	@curl -s http://localhost:3000 > /dev/null && echo "✅ Frontend OK" || echo "❌ Frontend not responding"
	@echo "PostgreSQL:"
	@docker-compose exec -T postgres pg_isready -U ufdr_user -d ufdr_analyzer_dev > /dev/null 2>&1 && echo "✅ PostgreSQL OK" || echo "❌ PostgreSQL not responding"
	@echo "Redis:"
	@docker-compose exec -T redis redis-cli ping > /dev/null 2>&1 && echo "✅ Redis OK" || echo "❌ Redis not responding"
