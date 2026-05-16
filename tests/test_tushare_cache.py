from oribrink.config import Config
from oribrink.models import States
from oribrink.storage import Storage
from oribrink.tushare_cache import FIELDS, TushareRawCache, backtest_tushare_cache


def _write(cache: TushareRawCache, api_name: str, params: dict, rows: list[dict]):
    fields = FIELDS[api_name]
    columns = fields.split(",")
    items = [[r.get(c) for c in columns] for r in rows]
    cache.write(api_name, params, fields, items, columns)


def test_tushare_cache_writes_trade_day_data_by_month(tmp_path):
    cache = TushareRawCache(tmp_path / "raw")
    _write(cache, "daily", {"trade_date": "20250516"}, [])

    assert (tmp_path / "raw" / "daily" / "2025-05.jsonl").exists()


def test_backtest_tushare_cache_generates_kanglong_and_qianlong(tmp_path):
    raw_dir = tmp_path / "raw"
    cache = TushareRawCache(raw_dir)
    cfg = Config()
    cfg.tushare.raw_dir = str(raw_dir)
    storage = Storage(":memory:")

    _write(
        cache,
        "trade_cal",
        {"exchange": "SSE", "start_date": "20250514", "end_date": "20250516"},
        [
            {"exchange": "SSE", "cal_date": "20250514", "is_open": 1, "pretrade_date": "20250513"},
            {"exchange": "SSE", "cal_date": "20250515", "is_open": 1, "pretrade_date": "20250514"},
            {"exchange": "SSE", "cal_date": "20250516", "is_open": 1, "pretrade_date": "20250515"},
        ],
    )
    _write(
        cache,
        "limit_list_d",
        {"trade_date": "20250514"},
        [
            {
                "trade_date": "20250514", "ts_code": "000001.SZ", "name": "甲",
                "industry": "软件", "close": 10.0, "pct_chg": 10.0,
                "amount": 1000000, "float_mv": 5_000_000_000,
                "total_mv": 6_000_000_000, "turnover_ratio": 3.0,
                "fd_amount": 100000, "first_time": "92500", "last_time": "92500",
                "open_times": 0, "up_stat": "3/3", "limit_times": 3, "limit": "U",
            }
        ],
    )
    _write(
        cache,
        "limit_list_d",
        {"trade_date": "20250515"},
        [
            {
                "trade_date": "20250515", "ts_code": "000001.SZ", "name": "甲",
                "industry": "软件", "close": 10.0, "pct_chg": 8.0,
                "amount": 2000000, "float_mv": 5_000_000_000,
                "total_mv": 6_000_000_000, "turnover_ratio": 6.0,
                "first_time": "100000", "open_times": 1, "limit": "Z",
            }
        ],
    )
    _write(cache, "limit_list_d", {"trade_date": "20250516"}, [])
    for date, close, vol in [
        ("20250514", 10.0, 100.0),
        ("20250515", 10.0, 200.0),
        ("20250516", 10.5, 300.0),
    ]:
        _write(
            cache,
            "daily",
            {"trade_date": date},
            [
                {
                    "ts_code": "000001.SZ", "trade_date": date, "open": close,
                    "high": close, "low": close, "close": close,
                    "pre_close": close - 0.1, "vol": vol, "amount": 1000.0,
                }
            ],
        )
        _write(
            cache,
            "daily_basic",
            {"trade_date": date},
            [
                {
                    "ts_code": "000001.SZ", "trade_date": date,
                    "turnover_rate": 1.0, "volume_ratio": 1.0,
                    "free_share": 1000.0, "float_share": 1000.0,
                    "total_mv": 600000.0, "circ_mv": 500000.0,
                }
            ],
        )
    _write(cache, "stk_auction", {"trade_date": "20250514"}, [])
    _write(cache, "stk_auction", {"trade_date": "20250515"}, [])
    _write(
        cache,
        "stk_auction",
        {"trade_date": "20250516"},
        [
            {
                "ts_code": "000001.SZ", "trade_date": "20250516",
                "vol": 2000.0, "price": 10.5, "amount": 21000.0,
                "pre_close": 10.0, "turnover_rate": 1.0,
                "volume_ratio": 1.0, "float_share": 1000.0,
            }
        ],
    )

    result = backtest_tushare_cache(storage, cfg, "2025-05-14", "2025-05-16")

    assert result["kanglong"] == 1
    assert result["qianlong"] == 1
    kl = storage.query_snapshot("2025-05-15", States.KANGLONG, "kanglong")
    ql = storage.query_snapshot("2025-05-16", States.QIANLONG, "qianlong")
    assert kl[0]["code"] == "000001"
    assert ql[0]["auction_ratio"] == 0.1
    checks = storage.query_qianlong_checks("2025-05-16", "2025-05-15")
    assert checks[0]["code"] == "000001"
    assert checks[0]["passed"] == 1
    storage.close()


def test_backtest_cached_summary_keeps_counts(tmp_path):
    raw_dir = tmp_path / "raw"
    cache = TushareRawCache(raw_dir)
    cfg = Config()
    cfg.tushare.raw_dir = str(raw_dir)
    storage = Storage(":memory:")

    _write(
        cache,
        "trade_cal",
        {"exchange": "SSE", "start_date": "20250514", "end_date": "20250516"},
        [
            {"exchange": "SSE", "cal_date": "20250514", "is_open": 1, "pretrade_date": "20250513"},
            {"exchange": "SSE", "cal_date": "20250515", "is_open": 1, "pretrade_date": "20250514"},
        ],
    )
    storage.write_snapshot(
        [
            {
                "trade_date": "2025-05-15",
                "snapshot_type": "kanglong",
                "code": "000001",
                "name": "甲",
                "state": States.KANGLONG,
            }
        ],
        overwrite=False,
    )
    rid1 = storage.start_task_run("kanglong_task", "2025-05-15")
    storage.finish_task_run(rid1, "success", total=1, success=1)
    rid2 = storage.start_task_run("qianlong_task", "2025-05-15")
    storage.finish_task_run(rid2, "success", total=0, success=0)

    result = backtest_tushare_cache(storage, cfg, "2025-05-14", "2025-05-16")

    assert result["kanglong"] == 1
    assert result["qianlong"] == 0
    assert result["summary"][0]["cached"] is True
    assert result["summary"][0]["kanglong"] == 1
    storage.close()
