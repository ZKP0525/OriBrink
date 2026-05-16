import pandas as pd
import pytest

from oribrink import datasource as ds


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("09:25:00", "09:25:00"),
        ("092500", "09:25:00"),
        (92500, "09:25:00"),
        ("93000", "09:30:00"),
        (141354, "14:13:54"),
        ("150000", "15:00:00"),
        (93000.0, "09:30:00"),
        ("2026-05-15 09:25:00", "09:25:00"),
        ("2026-05-15T14:13:54", "14:13:54"),
        ("", None),
        ("nan", None),
        (None, None),
        ("-", None),
    ],
)
def test_normalize_time(raw, expected):
    assert ds.normalize_time(raw) == expected


def test_date_conversion():
    assert ds.to_akshare_date("2025-05-15") == "20250515"
    assert ds.to_akshare_date("20250515") == "20250515"
    assert ds.to_iso_date("20250515") == "2025-05-15"
    assert ds.to_iso_date("2025-05-15") == "2025-05-15"


def test_normalize_zt_pool_basic_and_missing_fields():
    df = pd.DataFrame(
        [
            {
                "代码": "1", "名称": "平安银行", "涨跌幅": 10.0, "最新价": 12.3,
                "成交额": 1e8, "流通市值": 5e9, "总市值": 6e9, "换手率": 3.2,
                "封板资金": 2e8, "首次封板时间": 93000, "最后封板时间": "143000",
                "炸板次数": 1, "连板数": 3, "所属行业": "银行",
            },
            {"代码": "600519", "名称": "贵州茅台"},  # 缺失大量字段
        ]
    )
    rows = ds.normalize_zt_pool(df)
    assert len(rows) == 2
    assert rows[0].code == "000001"  # 左补零
    assert rows[0].first_limit_time == "09:30:00"
    assert rows[0].last_limit_time == "14:30:00"
    assert rows[0].lianban_count == 3
    assert rows[1].code == "600519"
    assert rows[1].lianban_count is None  # 缺失 -> None，不报错


def test_normalize_previous_zt_pool_alias_fields():
    df = pd.DataFrame(
        [
            {
                "代码": "1259", "名称": "利仁科技", "昨日封板时间": "092500",
                "昨日连板数": 4, "涨停统计": "5/5", "所属行业": "小家电",
            }
        ]
    )
    rows = ds.normalize_zt_pool(df)
    assert rows[0].code == "001259"
    assert rows[0].lianban_count == 4
    assert rows[0].first_limit_time == "09:25:00"
    assert rows[0].last_limit_time == "09:25:00"


def test_normalize_empty_dataframe():
    assert ds.normalize_zt_pool(pd.DataFrame()) == []
    assert ds.normalize_zbgc_pool(None) == []


def test_normalize_auction_picks_0925_from_tencent_detail():
    df = pd.DataFrame(
        [
            {"成交时间": "09:25:02", "成交价格": 6.99, "成交量": 574372,
             "成交金额": 401486210},
            {"成交时间": "09:30:02", "成交价格": 7.07, "成交量": 27125,
             "成交金额": 19124289},
        ]
    )
    au = ds.normalize_auction(df, "601991")
    assert au is not None
    assert au.time == "09:25:02"
    assert au.price == 6.99
    assert au.volume == 574372
    assert au.amount == 401486210


def test_normalize_auction_missing_returns_none():
    df = pd.DataFrame([{"成交时间": "09:20:00", "成交价格": 10.0, "成交量": 100}])
    assert ds.normalize_auction(df, "000001") is None


def test_normalize_daily_hist_tx_keeps_volume_lots():
    # 腾讯回退源英文列 amount 与腾讯成交明细成交量口径一致，均按手处理。
    df = pd.DataFrame(
        [
            {"date": "2026-05-14", "open": 10.0, "close": 10.5,
             "high": 10.6, "low": 9.9, "amount": 123400.0},
            {"date": "2026-05-13", "open": 9.5, "close": 10.0,
             "high": 10.1, "low": 9.4, "amount": 80000.0},
        ]
    )
    bars = ds.normalize_daily_hist_tx(df, "000001")
    assert [b.date for b in bars] == ["2026-05-13", "2026-05-14"]  # 升序
    assert bars[1].close == 10.5
    assert bars[1].volume == 123400.0
    assert bars[1].code == "000001"


def test_market_prefix():
    assert ds._market_prefix("600000") == "sh600000"
    assert ds._market_prefix("000001") == "sz000001"
    assert ds._market_prefix("300750") == "sz300750"
    assert ds._market_prefix("830799") == "bj830799"


def test_fetch_daily_hist_falls_back_to_tencent(monkeypatch):
    def em_fail(*a, **k):
        raise RuntimeError("Connection aborted RemoteDisconnected")

    tx_df = pd.DataFrame(
        [{"date": "2026-05-14", "open": 1.0, "close": 1.1,
          "high": 1.2, "low": 0.9, "amount": 5000.0}]
    )
    monkeypatch.setattr(ds, "_raw_daily_hist", em_fail)
    monkeypatch.setattr(ds, "_raw_daily_hist_tx", lambda *a, **k: tx_df)
    bars = ds.fetch_daily_hist("000001", "2026-05-01", "2026-05-14")
    assert len(bars) == 1 and bars[0].volume == 5000.0


def test_fetch_daily_hist_both_sources_fail(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(ds, "_raw_daily_hist", boom)
    monkeypatch.setattr(ds, "_raw_daily_hist_tx", boom)
    with pytest.raises(ds.DataSourceError):
        ds.fetch_daily_hist("000001", "2026-05-01", "2026-05-14")


def test_fetch_zt_pool_wraps_errors(monkeypatch):
    def boom(_):
        raise RuntimeError("network down")

    monkeypatch.setattr(ds, "_raw_zt_pool", boom)
    with pytest.raises(ds.DataSourceError):
        ds.fetch_zt_pool("2025-05-15")
