# OriBrink

![alt text](asset/banner.png)

## Week-1 Bootstrap

### 1. Prepare environment

```bash
cp .env.example .env
bash scripts/bootstrap.sh
```

Notes:
- Recommended Python: `3.11+`
- Requires `uv`: https://docs.astral.sh/uv/getting-started/installation/

### 2. Start local dependencies

```bash
docker compose up -d
```

### 3. Run API

```bash
uv run oribrink-api
```

Run scheduler as a standalone process (recommended in a separate terminal):

```bash
uv run oribrink-scheduler
```

### 4. Check health

```bash
curl http://localhost:8000/health
```

Expected response includes `postgres`, `redis`, and `scheduler` status.
`scheduler` is reported as `external_process` from API health endpoint.

## Common commands

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy services shared
uv run pytest
uv run alembic upgrade head
uv run alembic current
bash scripts/check.sh
```

## Project Structure

```text
services/
  api_service/
  scheduler_service/
  data_service/
  feature_service/
  strategy_service/
  backtest_service/
  selection_service/
  review_service/
shared/
  config/
  logging/
web/
  dashboard/
docs/
sql/
```
