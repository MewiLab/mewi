# Runner
PY := uv run
PYTEST_ARGS ?=

.PHONY: test test-s test-all test-unit test-integration help migration migrate migrate-ci

help:
	@echo "make test              - unit tests only (free, no API calls)"
	@echo "make test-s            - unit tests with stdout"
	@echo "make test-unit         - same as 'make test'"
	@echo "make test-integration  - paid tests only (needs .env + running services)"
	@echo "make test-all          - all tests (set CONFIRM_PAID=1)"

# ── Unit tests (free, mocked) ────────────────────────────────
test:
	$(PY) pytest -m "not paid" $(PYTEST_ARGS)

test-s:
	$(PY) pytest -m "not paid" -s $(PYTEST_ARGS)

test-unit: test

# ── Integration tests (paid, real APIs) ──────────────────────
test-integration:
	@test "$(CONFIRM_PAID)" = "1" || (echo "⚠️  Set CONFIRM_PAID=1 to run paid tests"; exit 1)
	$(PY) pytest tests/integration -m "paid" -s $(PYTEST_ARGS)

# ── Everything ───────────────────────────────────────────────
test-all:
	@test "$(CONFIRM_PAID)" = "1" || (echo "⚠️  Set CONFIRM_PAID=1 to run paid tests"; exit 1)
	$(PY) pytest $(PYTEST_ARGS)

# ── DB migrations ────────────────────────────────────────────
migration:
	@test -n "$(msg)" || (echo "Error: msg is undefined. Usage: make migration msg='your message'"; exit 1)
	docker compose exec agent-runtime alembic revision --autogenerate -m "$(msg)"

migrate:
	docker compose exec agent-runtime alembic upgrade head

migrate-ci:
	$(PY) alembic upgrade head