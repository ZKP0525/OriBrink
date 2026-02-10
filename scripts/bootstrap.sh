#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install from: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

uv sync --extra dev
cp -n .env.example .env || true

echo "Bootstrap complete. Run: docker compose up -d && uv run oribrink-api"
