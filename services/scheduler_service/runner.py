import asyncio
import logging

from services.scheduler_service.scheduler import build_scheduler, start_scheduler, stop_scheduler
from shared.logging import configure_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    configure_logging()
    scheduler = build_scheduler()
    start_scheduler(scheduler)
    logger.info("scheduler runner up")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("scheduler runner interrupted")
    finally:
        stop_scheduler(scheduler)


if __name__ == "__main__":
    asyncio.run(main())
