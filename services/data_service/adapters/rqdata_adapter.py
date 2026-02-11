import importlib
import logging
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, cast

from shared.config import settings

logger = logging.getLogger(__name__)


class RQDataAdapter:
    """RQData source adapter backed by rqdatac client."""

    def __init__(self, init_kwargs: dict[str, Any] | None = None, market: str | None = None) -> None:
        self._init_kwargs = init_kwargs if init_kwargs is not None else settings.rqdata_init_kwargs
        self._market = market if market is not None else settings.rqdata_market
        self._rqdatac: Any | None = None
        self._initialized = False

    def source_id(self) -> str:
        return "rqdata"

    def capabilities(self) -> dict[str, Any]:
        return {
            "market": self._market,
            "frequencies": ["1d", "1m", "tick"],
            "apis": ["get_price", "get_call_auction", "get_ticks"],
        }

    async def fetch(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        symbols = cast(list[str], request.get("symbols", []))
        if not symbols:
            raise ValueError("request.symbols is required")

        start_date = cast(str | date | datetime, request.get("start_date"))
        end_date = cast(str | date | datetime, request.get("end_date"))
        if start_date is None or end_date is None:
            raise ValueError("request.start_date and request.end_date are required")

        frequency = cast(str, request.get("frequency", "1d"))
        fields = cast(list[str] | None, request.get("fields"))

        return self._fetch_price_sync(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            fields=fields,
        )

    async def health_check(self) -> bool:
        try:
            return self._health_check_sync()
        except Exception:
            logger.exception("rqdata health check failed")
            return False

    def _load_client(self) -> Any:
        if self._rqdatac is None:
            try:
                self._rqdatac = importlib.import_module("rqdatac")
            except ModuleNotFoundError as exc:
                raise ModuleNotFoundError(
                    "rqdatac is not installed. Install and configure it before using RQDataAdapter."
                ) from exc
        return self._rqdatac

    def _ensure_initialized(self) -> Any:
        client = self._load_client()
        if not self._initialized:
            settings.apply_rqdata_runtime_env()
            mode = settings.rqdata_auth_mode.lower()
            use_uri_mode = mode == "uri" or (mode == "auto" and bool(settings.rqdata_resolved_uri))
            if use_uri_mode:
                client.init()
            elif self._init_kwargs:
                client.init(**self._init_kwargs)
            else:
                client.init()
            self._initialized = True
        return client

    def _health_check_sync(self) -> bool:
        client = self._ensure_initialized()
        _ = client.info()
        return True

    def _fetch_price_sync(
        self,
        symbols: list[str],
        start_date: str | date | datetime,
        end_date: str | date | datetime,
        frequency: str,
        fields: list[str] | None,
    ) -> list[dict[str, Any]]:
        client = self._ensure_initialized()

        frame = client.get_price(
            order_book_ids=symbols,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            fields=fields,
            expect_df=True,
        )

        if frame is None:
            return []

        normalized = frame.reset_index()
        records: list[dict[str, Any]] = []

        for row in normalized.to_dict(orient="records"):
            symbol = row.get("order_book_id") or row.get("order_book_ids")
            dt_value = row.get("date") or row.get("datetime")

            if isinstance(dt_value, datetime):
                ts = dt_value.isoformat()
                trade_date = dt_value.date().isoformat()
            elif isinstance(dt_value, date):
                ts = dt_value.isoformat()
                trade_date = dt_value.isoformat()
            else:
                ts = str(dt_value)
                trade_date = str(dt_value)[:10]

            mapped: dict[str, Any] = {
                "source": self.source_id(),
                "symbol": symbol,
                "ts": ts,
                "trade_date": trade_date,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "amount": row.get("total_turnover") or row.get("amount"),
            }

            for key, value in cast(Mapping[str, Any], row).items():
                mapped.setdefault(key, value)

            records.append(mapped)

        return records
