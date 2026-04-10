# Runner
PY := uv run
PYTEST_ARGS ?=

.PHONY: help dev docker-up docker-down test test-s test-unit test-integration test-all migration migrate migrate-ci

help:
	@echo ""
	@echo "  Development"
	@echo "    make dev              - start Redis + app with hot reload"
	@echo "    make docker-up        - build image + run full stack in Docker"
	@echo "    make docker-down      - stop everything"
	@echo ""
	@echo "  Testing"
	@echo "    make test             - unit tests (free, mocked)"
	@echo "    make test-s           - unit tests with stdout"
	@echo "    make test-integration - integration tests (needs .env + Redis)"
	@echo "    make test-all         - all tests (set CONFIRM_PAID=1)"
	@echo ""
	@echo "  Database"
	@echo "    make migration msg='...'  - create Alembic migration"
	@echo "    make migrate              - apply migrations"
	@echo ""

# ── Development ──────────────────────────────────────────────

# Daily workflow: Redis in Docker, app runs natively with hot reload
dev:
	docker compose up -d redis
	@echo "Redis is up. Starting uvicorn..."
	$(PY) uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Build the image and run everything in Docker (test before deploy)
docker-up:
	docker compose --profile deploy up --build -d

docker-down:
	docker compose --profile deploy down

# ── Testing ──────────────────────────────────────────────────

test:
	$(PY) pytest tests/unit -m "not paid" $(PYTEST_ARGS)

test-s:
	$(PY) pytest tests/unit -m "not paid" -s $(PYTEST_ARGS)

test-unit: test

test-integration:
	@test "$(CONFIRM_PAID)" = "1" || (echo "Set CONFIRM_PAID=1 to run integration tests"; exit 1)
	$(PY) pytest tests/integration -m "paid" -s $(PYTEST_ARGS)

test-all:
	@test "$(CONFIRM_PAID)" = "1" || (echo "Set CONFIRM_PAID=1 to run all tests"; exit 1)
	$(PY) pytest $(PYTEST_ARGS)

# ── Database ─────────────────────────────────────────────────

migration:
	@test -n "$(msg)" || (echo "Usage: make migration msg='your message'"; exit 1)
	docker compose --profile deploy exec agent-runtime alembic revision --autogenerate -m "$(msg)"

migrate:
	docker compose --profile deploy exec agent-runtime alembic upgrade head

migrate-ci:
	$(PY) alembic upgrade head