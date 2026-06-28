.PHONY: dev test backtest build clean setup

setup:
	cp .env.example .env
	@echo "Edit .env with your credentials, then run: make dev"

dev:
	docker compose up --build

dev-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && pytest tests/ -v

backtest:
	@echo "Run backtest via: POST http://localhost:8000/api/v1/backtest/run"

build:
	docker compose build

clean:
	docker compose down -v
	find . -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

logs:
	docker compose logs -f backend

migrate:
	cd backend && alembic upgrade head
