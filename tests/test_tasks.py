"""亢龙/潜龙任务端到端测试（monkeypatch 数据源，全程离线）。"""

import datetime as dt
from zoneinfo import ZoneInfo

from oribrink import tasks
from oribrink.models import AuctionData, DailyBar, States, ZtRow


def _bars(code, spec):
    return [DailyBar(date=d, code=code, close=c, volume=v) for d, c, v in spec]


def test_kanglong_non_trading_day_skipped(storage, cfg, monkeypatch):
    monkeypatch.setattr(tasks, "fetch_zt_pool", lambda d: [])
    res = tasks.run_kanglong_task(storage, cfg, "2025-05-17", send=False)
    assert res["status"] == "skipped"


def test_kanglong_uses_previous_limit_pool_not_current_state(storage, cfg, monkeypatch):
    storage.upsert_current_state(
        code="000999", name="旧飞龙", state=States.FEILONG,
        state_date="2025-05-12", free_market_cap=5e9,
    )

    monkeypatch.setattr(
        tasks, "fetch_previous_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=3,
                         free_market_cap=5e9, industry="软件")],
    )
    monkeypatch.setattr(
        tasks, "fetch_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=1,
                         break_board_count=2, free_market_cap=5e9,
                         industry="软件")],
    )
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", lambda d: [])
    monkeypatch.setattr(
        tasks, "fetch_daily_hist",
        lambda c, s, e: _bars(c, [("2025-05-15", 10.0, 100.0),
                                  ("2025-05-16", 11.0, 400.0)]),
    )

    r1 = tasks.run_kanglong_task(storage, cfg, "2025-05-16", send=False)
    assert r1["new_kanglong"] == 1
    assert storage.get_current("000001")["state"] == States.KANGLONG
    assert storage.get_current("000999")["state"] == States.FEILONG
    assert storage.query_snapshot("2025-05-16", States.KANGLONG, "kanglong")
    assert not storage.query_transitions(code="000999")

    tasks.run_kanglong_task(storage, cfg, "2025-05-16", send=False)
    assert len(storage.query_transitions(code="000001")) == 1


def test_kanglong_uses_snapshot_cache_on_rerun(storage, cfg, monkeypatch):
    monkeypatch.setattr(
        tasks, "fetch_previous_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=3,
                         free_market_cap=5e9, industry="软件")],
    )
    monkeypatch.setattr(
        tasks, "fetch_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=1,
                         break_board_count=2, free_market_cap=5e9,
                         industry="软件")],
    )
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", lambda d: [])
    monkeypatch.setattr(
        tasks, "fetch_daily_hist",
        lambda c, s, e: _bars(c, [("2025-05-15", 10.0, 100.0),
                                  ("2025-05-16", 11.0, 400.0)]),
    )

    first = tasks.run_kanglong_task(storage, cfg, "2025-05-16", send=False)
    assert first["new_kanglong"] == 1

    def fail_fetch(*args, **kwargs):
        raise AssertionError("should use snapshot cache")

    monkeypatch.setattr(tasks, "fetch_zt_pool", fail_fetch)
    monkeypatch.setattr(tasks, "fetch_previous_zt_pool", fail_fetch)
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", fail_fetch)
    monkeypatch.setattr(tasks, "fetch_daily_hist", fail_fetch)

    second = tasks.run_kanglong_task(storage, cfg, "2025-05-16", send=False)
    assert second["cached"] is True
    assert second["signals"][0]["code"] == "000001"
    assert second["signals"][0]["prev_lianban_count"] == 3


def test_kanglong_weekend_uses_latest_weekday(storage, cfg, monkeypatch):
    seen = []

    def zt_pool(d):
        seen.append(d)
        return []

    monkeypatch.setattr(tasks, "fetch_zt_pool", zt_pool)
    res = tasks.run_kanglong_task(storage, cfg, "2025-05-17", send=False)
    assert res["trade_date"] == "2025-05-16"
    assert res["status"] == "skipped"
    assert seen == ["2025-05-16"]


def test_kanglong_zero_result_is_cached(storage, cfg, monkeypatch):
    monkeypatch.setattr(
        tasks, "fetch_previous_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=3,
                         free_market_cap=5e9, industry="软件")],
    )
    monkeypatch.setattr(
        tasks, "fetch_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=1,
                         break_board_count=0, free_market_cap=5e9,
                         industry="软件")],
    )
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", lambda d: [])

    first = tasks.run_kanglong_task(storage, cfg, "2025-05-16", send=False)
    assert first["status"] == "success"
    assert first["new_kanglong"] == 0

    def fail_fetch(*args, **kwargs):
        raise AssertionError("should use zero-result task cache")

    monkeypatch.setattr(tasks, "fetch_zt_pool", fail_fetch)
    monkeypatch.setattr(tasks, "fetch_previous_zt_pool", fail_fetch)
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", fail_fetch)

    second = tasks.run_kanglong_task(storage, cfg, "2025-05-16", send=False)
    assert second["cached"] is True
    assert second["signals"] == []


def test_qianlong_precomputes_previous_trading_day_kanglong(storage, cfg, monkeypatch):
    def zt_pool(d):
        if d == "2025-05-16":
            return [ZtRow(code="000001", name="甲", lianban_count=1,
                          break_board_count=2, free_market_cap=5e9,
                          industry="软件")]
        return []

    monkeypatch.setattr(tasks, "fetch_zt_pool", zt_pool)
    monkeypatch.setattr(
        tasks, "fetch_previous_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=3,
                         free_market_cap=5e9, industry="软件")],
    )
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", lambda d: [])
    monkeypatch.setattr(
        tasks, "fetch_daily_hist",
        lambda c, s, e: _bars(c, [("2025-05-15", 10.0, 100.0),
                                  ("2025-05-16", 11.0, 400.0)]),
    )
    monkeypatch.setattr(
        tasks, "fetch_auction",
        lambda c: AuctionData(code=c, price=11.5, volume=30.0, amount=345.0),
    )

    res = tasks.run_qianlong_task(
        storage, cfg, "2025-05-19", send=False, latest_date="2025-05-19"
    )
    assert res["kanglong_date"] == "2025-05-16"
    assert res["new_qianlong"] == 1
    assert storage.get_current("000001")["state"] == States.QIANLONG
    assert storage.query_snapshot("2025-05-16", States.KANGLONG, "kanglong")
    ql = storage.query_snapshot("2025-05-19", States.QIANLONG, "qianlong")
    assert len(ql) == 1 and ql[0]["quality"] in ("合格", "优质")

    hist = storage.query_transitions(code="000001")
    assert [h["to_state"] for h in hist] == [States.KANGLONG, States.QIANLONG]


def test_qianlong_reports_failed_check_reason(storage, cfg, monkeypatch):
    def zt_pool(d):
        if d == "2025-05-16":
            return [ZtRow(code="000001", name="甲", lianban_count=1,
                          break_board_count=2, free_market_cap=10e9,
                          industry="软件")]
        return []

    monkeypatch.setattr(tasks, "fetch_zt_pool", zt_pool)
    monkeypatch.setattr(
        tasks, "fetch_previous_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=3,
                         free_market_cap=10e9, industry="软件")],
    )
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", lambda d: [])
    monkeypatch.setattr(
        tasks, "fetch_daily_hist",
        lambda c, s, e: _bars(c, [("2025-05-15", 10.0, 100.0),
                                  ("2025-05-16", 11.0, 400.0)]),
    )
    monkeypatch.setattr(
        tasks, "fetch_auction",
        lambda c: AuctionData(code=c, price=11.5, volume=4.0, amount=46.0),
    )

    res = tasks.run_qianlong_task(
        storage, cfg, "2025-05-19", send=False, latest_date="2025-05-19"
    )
    assert res["new_qianlong"] == 0
    assert res["checks"][0]["auction_ratio"] == 0.01
    assert "2.50%" in res["checks"][0]["reason"]


def test_qianlong_weekend_uses_latest_weekday(storage, cfg, monkeypatch):
    def zt_pool(d):
        if d == "2025-05-15":
            return [ZtRow(code="000001", name="甲", lianban_count=1,
                          break_board_count=2, free_market_cap=5e9,
                          industry="软件")]
        return []

    monkeypatch.setattr(tasks, "fetch_zt_pool", zt_pool)
    monkeypatch.setattr(
        tasks, "fetch_previous_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=3,
                         free_market_cap=5e9, industry="软件")],
    )
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", lambda d: [])
    monkeypatch.setattr(
        tasks, "fetch_daily_hist",
        lambda c, s, e: _bars(c, [("2025-05-14", 10.0, 100.0),
                                  ("2025-05-15", 11.0, 400.0)]),
    )
    monkeypatch.setattr(
        tasks, "fetch_auction",
        lambda c: AuctionData(code=c, price=11.5, volume=30.0, amount=345.0),
    )

    res = tasks.run_qianlong_task(
        storage, cfg, "2025-05-17", send=False, latest_date="2025-05-17"
    )
    assert res["trade_date"] == "2025-05-16"
    assert res["kanglong_date"] == "2025-05-15"
    assert res["new_qianlong"] == 1


def test_qianlong_before_1600_uses_previous_trade_date(storage, cfg, monkeypatch):
    def zt_pool(d):
        if d == "2026-05-13":
            return [ZtRow(code="000001", name="甲", lianban_count=1,
                          break_board_count=2, free_market_cap=5e9,
                          industry="软件")]
        return []

    monkeypatch.setattr(tasks, "fetch_zt_pool", zt_pool)
    monkeypatch.setattr(
        tasks, "fetch_previous_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=3,
                         free_market_cap=5e9, industry="软件")],
    )
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", lambda d: [])
    monkeypatch.setattr(
        tasks, "fetch_daily_hist",
        lambda c, s, e: _bars(c, [("2026-05-12", 10.0, 100.0),
                                  ("2026-05-13", 11.0, 400.0)]),
    )
    monkeypatch.setattr(
        tasks, "fetch_auction",
        lambda c: AuctionData(code=c, price=11.5, volume=30.0, amount=345.0),
    )

    now = dt.datetime(2026, 5, 15, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    res = tasks.run_qianlong_task(
        storage, cfg, "2026-05-15", send=False, latest_now=now
    )
    assert res["trade_date"] == "2026-05-14"
    assert res["kanglong_date"] == "2026-05-13"
    assert res["new_qianlong"] == 1
    assert "16:00" in res["data_note"]


def test_qianlong_skipped_when_previous_day_has_no_kanglong(storage, cfg, monkeypatch):
    monkeypatch.setattr(
        tasks, "fetch_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=1)],
    )
    monkeypatch.setattr(
        tasks, "fetch_previous_zt_pool",
        lambda d: [ZtRow(code="000001", name="甲", lianban_count=3)],
    )
    monkeypatch.setattr(tasks, "fetch_zbgc_pool", lambda d: [])

    res = tasks.run_qianlong_task(
        storage, cfg, "2025-05-19", send=False, latest_date="2025-05-19"
    )
    assert res["status"] == "success"
    assert res["new_qianlong"] == 0


def test_qianlong_uncached_history_is_not_recalculated(storage, cfg, monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise AssertionError("historical qianlong should not hit datasource")

    monkeypatch.setattr(tasks, "fetch_zt_pool", fail_fetch)
    monkeypatch.setattr(tasks, "fetch_auction", fail_fetch)

    res = tasks.run_qianlong_task(
        storage, cfg, "2025-05-15", send=False, latest_date="2025-05-19"
    )
    assert res["status"] == "skipped"
    assert "暂不支持" in res["reason"]
