import logging

from redis.asyncio import Redis
from sqlalchemy import text

from shared.infra import SessionLocal, create_redis_client

logger = logging.getLogger(__name__)


async def check_postgres() -> bool:
    try:
        async with SessionLocal() as session:
            await session.execute(text("select 1"))
        return True
    except Exception:
        logger.exception("postgres health check failed")
        return False


async def check_redis() -> bool:
    client: Redis = create_redis_client()
    try:
        pong = await client.ping()
        return bool(pong)
    except Exception:
        logger.exception("redis health check failed")
        return False
    finally:
        await client.close()
