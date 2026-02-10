from typing import cast

from redis.asyncio import Redis

from shared.config import settings


def create_redis_client() -> Redis:
    return cast(Redis, Redis.from_url(settings.redis_dsn, decode_responses=True))
