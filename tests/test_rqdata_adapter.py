from datetime import date

from services.data_service.adapters.rqdata_adapter import RQDataAdapter
from shared.config import settings


class FakeFrame:
    def reset_index(self) -> "FakeFrame":
        return self

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return [
            {
                "order_book_id": "000001.XSHE",
                "date": date(2026, 2, 10),
                "open": 10.0,
                "high": 10.5,
                "low": 9.9,
                "close": 10.2,
                "volume": 12345,
                "total_turnover": 123456.7,
            }
        ]


class FakeRQDataC:
    def __init__(self) -> None:
        self.init_called_with: dict[str, object] | None = None
        self.init_call_count = 0

    def init(self, **kwargs: object) -> None:
        self.init_called_with = kwargs
        self.init_call_count += 1

    def info(self) -> dict[str, str]:
        return {"status": "ok"}

    def get_price(self, **_: object) -> FakeFrame:
        return FakeFrame()


def test_rqdata_adapter_health_and_fetch() -> None:
    old_mode, old_uri, old_license = settings.rqdata_auth_mode, settings.rqdata_uri, settings.rqdata_license
    settings.rqdata_auth_mode = "kwargs"
    settings.rqdata_uri = ""
    settings.rqdata_license = ""

    fake = FakeRQDataC()
    adapter = RQDataAdapter(init_kwargs={"username": "u", "password": "p"})
    adapter._rqdatac = fake

    try:
        assert adapter._health_check_sync() is True
        rows = adapter._fetch_price_sync(
            symbols=["000001.XSHE"],
            start_date="2026-02-01",
            end_date="2026-02-10",
            frequency="1d",
            fields=["open", "close"],
        )

        assert fake.init_called_with == {"username": "u", "password": "p"}
        assert len(rows) == 1
        assert rows[0]["symbol"] == "000001.XSHE"
        assert rows[0]["trade_date"] == "2026-02-10"
        assert rows[0]["close"] == 10.2
    finally:
        settings.rqdata_auth_mode = old_mode
        settings.rqdata_uri = old_uri
        settings.rqdata_license = old_license


def test_rqdata_adapter_inits_once_per_adapter() -> None:
    old_mode, old_uri, old_license = settings.rqdata_auth_mode, settings.rqdata_uri, settings.rqdata_license
    settings.rqdata_auth_mode = "kwargs"
    settings.rqdata_uri = ""
    settings.rqdata_license = ""

    fake = FakeRQDataC()
    adapter = RQDataAdapter(init_kwargs={"username": "u", "password": "p"})
    adapter._rqdatac = fake

    try:
        assert adapter._health_check_sync() is True
        rows = adapter._fetch_price_sync(
            ["000001.XSHE"],
            "2026-02-01",
            "2026-02-10",
            "1d",
            ["open", "close"],
        )
        assert len(rows) == 1
        assert fake.init_call_count == 1
    finally:
        settings.rqdata_auth_mode = old_mode
        settings.rqdata_uri = old_uri
        settings.rqdata_license = old_license
