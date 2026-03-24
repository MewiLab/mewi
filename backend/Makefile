# Runner
PY := uv run
PYTEST_ARGS ?=

.PHONY: test test-all lint format fix update-tapes ci help migration migrate migrate-ci

help:
	@echo "make test         - pytest excluding paid tests"
	@echo "make test-all     - run all tests (may cost money)"

# Default: Run free tests
test:
	$(PY) pytest -m "not paid" $(PYTEST_ARGS)

test-s:
	$(PY) pytest -m "not paid" -s

# Potentially expensive (opt-in)
test-all:
	@test "$(CONFIRM_PAID)" = "1" || (echo "Set CONFIRM_PAID=1 to run paid tests"; exit 1)
	$(PY) pytest $(PYTEST_ARGS)

# ------------------------------------------------------------------
# DB Migrations (Docker Integration)
# ------------------------------------------------------------------

# 1. GENERATE the script (Run this when you change models.py)
# Usage: make migration msg="add skills table"
migration:
	# ✅ FIX 2: Safety check for empty message
	@test -n "$(msg)" || (echo "Error: msg is undefined. Usage: make migration msg='your message'"; exit 1)
	docker compose exec agent-runtime alembic revision --autogenerate -m "$(msg)"

# 2. APPLY the changes (Run this if you want to update DB without restarting)
# Usage: make migrate
migrate:
	docker compose exec agent-runtime alembic upgrade head

migrate-ci:
	$(PY) alembic upgrade head