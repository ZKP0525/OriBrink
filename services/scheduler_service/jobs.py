import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def heartbeat_job() -> None:
    logger.info("scheduler heartbeat at %s", datetime.now(UTC).isoformat())
