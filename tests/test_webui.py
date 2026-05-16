from oribrink.config import Config
from oribrink.models import States
from oribrink.storage import Storage
from oribrink.webui import render_dashboard


def test_render_dashboard_shows_saved_snapshots_and_runs(tmp_path):
    cfg = Config()
    storage = Storage(":memory:")
    storage.write_snapshot(
        [
            {
                "trade_date": "2025-05-14",
                "snapshot_type": "kanglong",
                "code": "000001",
                "name": "甲",
                "state": States.KANGLONG,
                "reason": "曾飞龙在天",
                "volume_ratio": 2.0,
                "free_market_cap": 5_000_000_000,
            }
        ],
        overwrite=False,
    )
    storage.write_snapshot(
        [
            {
                "trade_date": "2025-05-15",
                "snapshot_type": "qianlong",
                "code": "000001",
                "name": "甲",
                "state": States.QIANLONG,
                "reason": "曾亢龙有悔",
                "auction_ratio": 0.1,
                "gap_open_pct": 0.05,
            }
        ],
        overwrite=False,
    )
    storage.replace_qianlong_checks(
        "2025-05-15",
        "2025-05-14",
        [
            {
                "code": "000002",
                "name": "乙",
                "reason": "高开 1.00% < 3.00%",
                "auction_ratio": 0.02,
            }
        ],
        "test",
    )
    run_id = storage.start_task_run("kanglong_task", "2025-05-15")
    storage.finish_task_run(run_id, "success", total=1, success=1)

    html = render_dashboard(storage, cfg, {})

    assert "2025-05-15" in html
    assert "000001" in html
    assert "筛选规则" in html
    assert "昨日亢龙" in html
    assert "有事件" in html
    assert "昨日亢龙原因" in html
    assert "2.00倍" in html
    assert "今日潜龙" in html
    assert "进化失败的亢龙" in html
    assert "今日亢龙" in html
    assert "高开 1.00% &lt; 3.00%" in html
    assert "Tushare 原始缓存" not in html
    storage.close()
