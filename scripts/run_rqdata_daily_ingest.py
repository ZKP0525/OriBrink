#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta

from services.data_service.ingestion.daily_ingest import (
    DailyIngestRequest,
    RQDataDailyIngestionService,
)
from shared.infra import SessionLocal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run RQData daily ingestion into md.symbol_daily")
    parser.add_argument("--symbols", required=True, help="Comma separated symbols, e.g. 000001.XSHE,600519.XSHG")
    parser.add_argument("--start", default=(date.today() - timedelta(days=7)).isoformat(), help="start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat(), help="end date (YYYY-MM-DD)")
    parser.add_argument("--data-version", default="rqdata_v1", help="data version tag")
    return parser


async def main_async(args: argparse.Namespace) -> None:
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    request = DailyIngestRequest(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        data_version=args.data_version,
    )

    service = RQDataDailyIngestionService()
    async with SessionLocal() as session:
        result = await service.run(session, request)

    print(f"run_key={result.run_key} status={result.status} rows_upserted={result.rows_upserted}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
