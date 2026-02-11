#!/usr/bin/env python3
import asyncio
from datetime import date, timedelta

from services.data_service.adapters import RQDataAdapter
from shared.logging import configure_logging


async def main() -> None:
    configure_logging()
    adapter = RQDataAdapter()
    healthy = await adapter.health_check()
    print(f"rqdata health: {'ok' if healthy else 'failed'}")

    if not healthy:
        try:
            adapter._health_check_sync()
        except Exception as exc:
            print(f"rqdata error: {type(exc).__name__}: {exc}")
            keys = sorted(adapter._init_kwargs.keys())
            print(f"RQDATA_INIT_KWARGS_JSON keys: {keys}")
            print("hint: verify init kwargs format against rqdatac.init(...) docs.")
        return

    end_day = date.today() - timedelta(days=1)
    start_day = end_day - timedelta(days=5)
    request = {
        "symbols": ["000001.XSHE"],
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "frequency": "1d",
        "fields": ["open", "high", "low", "close", "volume", "total_turnover"],
    }
    rows = await adapter.fetch(request)

    print(f"rows fetched: {len(rows)}")
    if rows:
        print("sample row:")
        print(rows[0])


if __name__ == "__main__":
    asyncio.run(main())
