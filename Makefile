.PHONY: help dev test lint format build deploy-local clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

dev: ## Start all services for development
	docker compose up -d
	@echo "✅ Frontend: http://localhost:3000"
	@echo "✅ Backend:  http://localhost:8000"
	@echo "✅ API Docs: http://localhost:8000/docs"

test: ## Run all tests (backend + frontend)
	cd backend && uv run pytest -x --tb=short
	cd frontend && pnpm test

test-backend: ## Run backend tests only
	cd backend && uv run pytest -x -v

test-frontend: ## Run frontend tests only
	cd frontend && pnpm test

lint: ## Lint everything
	cd backend && uv run ruff check . && uv run mypy app/
	cd frontend && pnpm lint

format: ## Format all code
	cd backend && uv run ruff format .
	cd frontend && pnpm prettier --write 'src/**/*.{ts,tsx}'

build: ## Build production images
	docker compose build

deploy-local: ## Full local deployment with health checks
	docker compose up -d --build
	@echo "Waiting for services..."
	@sleep 5
	docker compose exec backend uv run alembic upgrade head
	@curl -sf http://localhost:8000/health > /dev/null && echo "✅ Backend healthy" || echo "❌ Backend failed"
	@curl -sf http://localhost:3000 > /dev/null && echo "✅ Frontend healthy" || echo "❌ Frontend failed"

migrate: ## Run database migrations
	cd backend && uv run alembic upgrade head

migrate-create: ## Create a new migration (usage: make migrate-create MSG="description")
	cd backend && uv run alembic revision --autogenerate -m "$(MSG)"

clean: ## Stop all services and remove volumes
	docker compose down -v
	@echo "✅ All services stopped, volumes removed"

logs: ## Follow logs from all services
	docker compose logs -f

status: ## Show status of all services
	docker compose ps
