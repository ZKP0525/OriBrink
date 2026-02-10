from fastapi import FastAPI

from services.api_service.health import check_postgres, check_redis
from shared.config import settings
from shared.logging import configure_logging

configure_logging()
app = FastAPI(title=settings.app_name)


@app.get("/health")
async def health() -> dict[str, object]:
    postgres_ok, redis_ok = await check_postgres(), await check_redis()
    return {
        "status": "ok" if postgres_ok and redis_ok else "degraded",
        "env": settings.app_env,
        "services": {
            "postgres": postgres_ok,
            "redis": redis_ok,
            "scheduler": "external_process",
        },
    }


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "OriBrink API running"}
