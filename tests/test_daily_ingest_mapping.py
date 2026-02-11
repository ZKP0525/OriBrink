from datetime import date
from decimal import Decimal

from services.data_service.ingestion.daily_ingest import map_to_symbol_daily_row


def test_map_to_symbol_daily_row() -> None:
    row = {
        "symbol": "000001.XSHE",
        "trade_date": "2026-02-11",
        "open": 10.1,
        "high": 10.5,
        "low": 10.0,
        "close": 10.3,
        "volume": 123,
        "amount": 1234.56,
    }
    mapped = map_to_symbol_daily_row(row, "rqdata_v1")

    assert mapped["symbol"] == "000001.XSHE"
    assert mapped["trade_date"] == date(2026, 2, 11)
    assert mapped["open"] == Decimal("10.1")
    assert mapped["data_version"] == "rqdata_v1"
