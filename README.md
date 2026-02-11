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
- RQData credentials must stay in local `.env` only. Do not commit keys.

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
uv run python scripts/rqdata_smoke_test.py
uv run python scripts/run_rqdata_daily_ingest.py --symbols 000001.XSHE --start 2026-02-01 --end 2026-02-10
```

## RQData configuration

Preferred: use URI/license mode.

Example:

```env
RQDATA_AUTH_MODE=uri
RQDATA_URI=rqdata://license:<your-rqdata-license>@rqdatad-pro.ricequant.com:16011
```

Then run:

```bash
uv run python scripts/rqdata_smoke_test.py
uv run alembic upgrade head
uv run python scripts/run_rqdata_daily_ingest.py --symbols 000001.XSHE --start 2026-02-01 --end 2026-02-10
```

Optional helper script:

```bash
bash scripts/setup_rqdata_env.sh "<your-rqdata-license>"
```

Fallback (kwargs mode):

```env
RQDATA_AUTH_MODE=kwargs
RQDATA_INIT_KWARGS_JSON={"username":"...","password":"...","addr":"rqdatad-pro.ricequant.com:16011"}
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
