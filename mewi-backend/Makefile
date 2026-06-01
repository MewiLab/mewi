# Runners
PY := uv run --extra report-agent
PY_GRAPH := uv run --extra report-agent --extra graph-memory
PYTEST_ARGS ?=

# Docker / local services
COMPOSE := docker compose
APP_SERVICE := mewi_agent_runtime
REDIS_SERVICE := redis
GRAPH_SERVICE := neo4j

# Local graph-memory defaults. Override at call-site when needed:
#   make dev-graph NEO4J_PASSWORD=secret
# Graph memory still needs MEMORY_PGVECTOR_DSN in .env or the shell.
NEO4J_USER ?= neo4j
NEO4J_PASSWORD ?= mewi-neo4j-dev
LOCAL_NEO4J_URL ?= bolt://localhost:7687
DOCKER_NEO4J_URL ?= bolt://neo4j:7687
GRAPH_ENV := MEMORY_GRAPH_ENABLED=true MEMORY_NEO4J_URL=$(LOCAL_NEO4J_URL) MEMORY_NEO4J_USERNAME=$(NEO4J_USER) MEMORY_NEO4J_PASSWORD=$(NEO4J_PASSWORD)
DOCKER_GRAPH_ENV := MEMORY_GRAPH_ENABLED=true MEMORY_NEO4J_URL=$(DOCKER_NEO4J_URL) MEMORY_NEO4J_USERNAME=$(NEO4J_USER) MEMORY_NEO4J_PASSWORD=$(NEO4J_PASSWORD)

.PHONY: help sync sync-graph dev dev-graph redis-up graph-up graph-down graph-logs graph-shell docker-up docker-up-core docker-up-graph docker-down test test-s test-unit test-graph test-integration test-all migration migrate migrate-ci

help:
	@echo ""
	@echo "  Development"
	@echo "    make sync             - install normal backend dependencies"
	@echo "    make sync-graph       - install backend + graph-memory dependencies"
	@echo "    make dev              - start Redis + app with hot reload"
	@echo "    make dev-graph        - start Redis + Neo4j + app with graph memory on"
	@echo "                            requires MEMORY_PGVECTOR_DSN for full mem0 graph memory"
	@echo ""
	@echo "  Services"
	@echo "    make redis-up         - start Redis only"
	@echo "    make graph-up         - start Redis + Neo4j graph database"
	@echo "    make graph-down       - stop Neo4j graph database"
	@echo "    make graph-logs       - follow Neo4j logs"
	@echo "    make graph-shell      - open cypher-shell in Neo4j"
	@echo ""
	@echo "  Docker"
	@echo "    make docker-up        - build image + run full stack: app, Redis, and Neo4j"
	@echo "    make docker-up-core   - build image + run app and Redis only"
	@echo "    make docker-up-graph  - alias for docker-up"
	@echo "    make docker-down      - stop Docker stack"
	@echo ""
	@echo "  Testing"
	@echo "    make test             - unit tests (free, mocked)"
	@echo "    make test-s           - unit tests with stdout"
	@echo "    make test-graph       - unit tests with graph-memory extra installed"
	@echo "    make test-integration - integration tests (needs .env + Redis)"
	@echo "    make test-all         - all tests (set CONFIRM_PAID=1)"
	@echo ""
	@echo "  Database"
	@echo "    make migration msg='...'  - create Alembic migration"
	@echo "    make migrate              - apply migrations"
	@echo ""

# -- Development ------------------------------------------------------------

sync:
	uv sync --extra report-agent

sync-graph:
	uv sync --extra report-agent --extra graph-memory

# Daily workflow: Redis in Docker, app runs natively with hot reload
dev:
	$(COMPOSE) up -d $(REDIS_SERVICE)
	@echo "Redis is up. Starting uvicorn..."
	$(PY) uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

dev-graph:
	$(COMPOSE) --profile graph-memory up -d --wait $(REDIS_SERVICE) $(GRAPH_SERVICE)
	@echo "Redis + Neo4j are up. Starting uvicorn with graph memory enabled..."
	@echo "Graph memory also needs MEMORY_PGVECTOR_DSN in .env or the shell."
	$(GRAPH_ENV) $(PY_GRAPH) uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# -- Services ---------------------------------------------------------------

redis-up:
	$(COMPOSE) up -d $(REDIS_SERVICE)

graph-up:
	$(COMPOSE) --profile graph-memory up -d --wait $(REDIS_SERVICE) $(GRAPH_SERVICE)

graph-down:
	$(COMPOSE) --profile graph-memory stop $(GRAPH_SERVICE)

graph-logs:
	$(COMPOSE) --profile graph-memory logs -f $(GRAPH_SERVICE)

graph-shell:
	$(COMPOSE) --profile graph-memory exec $(GRAPH_SERVICE) cypher-shell -u $(NEO4J_USER) -p "$(NEO4J_PASSWORD)"

# -- Docker -----------------------------------------------------------------

docker-up:
	$(DOCKER_GRAPH_ENV) $(COMPOSE) --profile graph-memory up -d --wait $(REDIS_SERVICE) $(GRAPH_SERVICE)
	$(DOCKER_GRAPH_ENV) $(COMPOSE) --profile graph-memory up --build -d $(APP_SERVICE)

docker-up-core:
	$(COMPOSE) up --build -d $(REDIS_SERVICE) $(APP_SERVICE)

docker-up-graph: docker-up

docker-down:
	$(COMPOSE) --profile graph-memory down

# -- Testing ---------------------------------------------------------------

test:
	$(PY) pytest tests/unit -m "not paid" $(PYTEST_ARGS)

test-s:
	$(PY) pytest tests/unit -m "not paid" -s $(PYTEST_ARGS)

test-unit: test

test-graph:
	$(PY_GRAPH) pytest tests/unit -m "not paid" $(PYTEST_ARGS)

test-integration:
	@test "$(CONFIRM_PAID)" = "1" || (echo "Set CONFIRM_PAID=1 to run integration tests"; exit 1)
	$(PY) pytest tests/integration -m "paid" -s $(PYTEST_ARGS)

test-all:
	@test "$(CONFIRM_PAID)" = "1" || (echo "Set CONFIRM_PAID=1 to run all tests"; exit 1)
	$(PY) pytest $(PYTEST_ARGS)

# -- Database --------------------------------------------------------------

migration:
	@test -n "$(msg)" || (echo "Usage: make migration msg='your message'"; exit 1)
	$(COMPOSE) exec $(APP_SERVICE) alembic revision --autogenerate -m "$(msg)"

migrate:
	$(COMPOSE) exec $(APP_SERVICE) alembic upgrade head

migrate-ci:
	$(PY) alembic upgrade head
