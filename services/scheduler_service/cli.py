import asyncio

from services.scheduler_service.runner import main as scheduler_main


def main() -> None:
    asyncio.run(scheduler_main())
