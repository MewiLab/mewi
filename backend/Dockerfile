# ──────────────────────────────────────────────────────────────
# Dockerfile — CI / staging / production ONLY
#
# This image is self-contained: code + deps + runtime.
# For local development, run the app natively (see Makefile: make dev).
# ──────────────────────────────────────────────────────────────

### Stage 1: install dependencies ###
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1

# Install deps first (cached unless pyproject.toml or uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --link-mode=copy


### Stage 2: lean runtime image ###
FROM python:3.12-slim

WORKDIR /app

# Copy only the venv from builder — no uv, no build tools
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY . .

EXPOSE 8000

# No --reload in production
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]