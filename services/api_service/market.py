from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.infra import get_session

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/daily")
async def get_daily_bars(
    symbol: str = Query(..., description="e.g. 000001.XSHE"),
    start: date = Query(..., description="start date"),
    end: date = Query(..., description="end date"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    rows = await session.execute(
        text(
            """
            SELECT symbol, trade_date, open, high, low, close, volume, amount, data_version
            FROM md.symbol_daily
            WHERE symbol = :symbol
              AND trade_date >= :start
              AND trade_date <= :end
            ORDER BY trade_date ASC
            """
        ),
        {"symbol": symbol, "start": start, "end": end},
    )

    bars: list[dict[str, object]] = []
    for row in rows.mappings().all():
        bars.append(
            {
                "symbol": row["symbol"],
                "trade_date": row["trade_date"].isoformat(),
                "open": _to_float(row["open"]),
                "high": _to_float(row["high"]),
                "low": _to_float(row["low"]),
                "close": _to_float(row["close"]),
                "volume": row["volume"],
                "amount": _to_float(row["amount"]),
                "data_version": row["data_version"],
            }
        )

    return {"symbol": symbol, "count": len(bars), "bars": bars}


def _to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
