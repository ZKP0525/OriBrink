import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.scheduler_service.jobs import heartbeat_job
from shared.config import settings

logger = logging.getLogger(__name__)


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        heartbeat_job,
        trigger=IntervalTrigger(seconds=settings.scheduler_heartbeat_seconds),
        id="heartbeat",
        replace_existing=True,
    )
    return scheduler


def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info("scheduler started")


def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler stopped")
