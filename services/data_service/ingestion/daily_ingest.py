from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.data_service.adapters import RQDataAdapter


@dataclass(slots=True)
class DailyIngestRequest:
    symbols: list[str]
    start_date: str
    end_date: str
    data_version: str


@dataclass(slots=True)
class DailyIngestResult:
    run_key: str
    status: str
    rows_upserted: int


def _parse_trade_date(raw: Any) -> date:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        return date.fromisoformat(raw[:10])
    raise ValueError(f"unsupported trade_date value: {raw}")


def _to_decimal(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    return Decimal(str(raw))


def map_to_symbol_daily_row(raw: dict[str, Any], data_version: str) -> dict[str, Any]:
    symbol = raw.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol is required")

    return {
        "symbol": symbol,
        "trade_date": _parse_trade_date(raw.get("trade_date")),
        "open": _to_decimal(raw.get("open")),
        "high": _to_decimal(raw.get("high")),
        "low": _to_decimal(raw.get("low")),
        "close": _to_decimal(raw.get("close")),
        "prev_close": _to_decimal(raw.get("prev_close")),
        "volume": int(raw["volume"]) if raw.get("volume") is not None else None,
        "amount": _to_decimal(raw.get("amount")),
        "turnover_rate": _to_decimal(raw.get("turnover_rate")),
        "adj_factor": _to_decimal(raw.get("adj_factor")),
        "is_limit_up": raw.get("is_limit_up"),
        "is_limit_down": raw.get("is_limit_down"),
        "data_version": data_version,
    }


class RQDataDailyIngestionService:
    def __init__(self, adapter: RQDataAdapter | None = None) -> None:
        self._adapter = adapter if adapter is not None else RQDataAdapter()

    async def run(self, session: AsyncSession, request: DailyIngestRequest) -> DailyIngestResult:
        run_key = f"daily_ingest_{uuid4().hex[:12]}"
        started = time.time()

        await session.execute(
            text(
                """
                INSERT INTO sys.job_runs (job_name, run_key, status, metadata_json)
                VALUES (:job_name, :run_key, :status, CAST(:metadata_json AS jsonb))
                """
            ),
            {
                "job_name": "rqdata_daily_ingest",
                "run_key": run_key,
                "status": "running",
                "metadata_json": (
                    '{"symbols": %d, "start_date": "%s", "end_date": "%s", "data_version": "%s"}'
                    % (len(request.symbols), request.start_date, request.end_date, request.data_version)
                ),
            },
        )
        await session.commit()

        try:
            raw_rows = await self._adapter.fetch(
                {
                    "symbols": request.symbols,
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                    "frequency": "1d",
                    "fields": [
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "total_turnover",
                    ],
                }
            )
            upsert_rows = [map_to_symbol_daily_row(row, request.data_version) for row in raw_rows]

            if upsert_rows:
                await session.execute(
                    text(
                        """
                        INSERT INTO md.symbol_daily (
                            symbol, trade_date, open, high, low, close, prev_close,
                            volume, amount, turnover_rate, adj_factor,
                            is_limit_up, is_limit_down, data_version
                        ) VALUES (
                            :symbol, :trade_date, :open, :high, :low, :close, :prev_close,
                            :volume, :amount, :turnover_rate, :adj_factor,
                            :is_limit_up, :is_limit_down, :data_version
                        )
                        ON CONFLICT (symbol, trade_date, data_version)
                        DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            prev_close = EXCLUDED.prev_close,
                            volume = EXCLUDED.volume,
                            amount = EXCLUDED.amount,
                            turnover_rate = EXCLUDED.turnover_rate,
                            adj_factor = EXCLUDED.adj_factor,
                            is_limit_up = EXCLUDED.is_limit_up,
                            is_limit_down = EXCLUDED.is_limit_down,
                            updated_at = now()
                        """
                    ),
                    upsert_rows,
                )

            duration_ms = int((time.time() - started) * 1000)
            await session.execute(
                text(
                    """
                    UPDATE sys.job_runs
                    SET status = :status,
                        finished_at = now(),
                        duration_ms = :duration_ms,
                        metadata_json = CAST(:metadata_json AS jsonb)
                    WHERE run_key = :run_key
                    """
                ),
                {
                    "status": "success",
                    "duration_ms": duration_ms,
                    "metadata_json": '{"rows_upserted": %d}' % len(upsert_rows),
                    "run_key": run_key,
                },
            )
            await session.commit()
            return DailyIngestResult(run_key=run_key, status="success", rows_upserted=len(upsert_rows))
        except Exception as exc:
            duration_ms = int((time.time() - started) * 1000)
            await session.execute(
                text(
                    """
                    UPDATE sys.job_runs
                    SET status = :status,
                        finished_at = now(),
                        duration_ms = :duration_ms,
                        error_message = :error_message
                    WHERE run_key = :run_key
                    """
                ),
                {
                    "status": "failed",
                    "duration_ms": duration_ms,
                    "error_message": str(exc)[:4000],
                    "run_key": run_key,
                },
            )
            await session.commit()
            raise
