#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install from: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for local infra checks"
  exit 1
fi

echo "[1/6] Sync dependencies"
uv sync --extra dev

echo "[2/6] Ensure local infra is running"
docker compose up -d >/dev/null

echo "[3/6] Lint"
uv run ruff check .

echo "[4/6] Type check"
uv run mypy services shared

echo "[5/6] Tests"
uv run pytest -q

echo "[6/6] DB migration status"
uv run alembic upgrade head
uv run alembic current

echo "All checks passed"
