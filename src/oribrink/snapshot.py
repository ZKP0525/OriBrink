"""每日状态快照模块。

把状态识别结果落成 daily_state_snapshot 行。任务结果来自指定日期的数据源，
不能用当前状态表反推。

重跑策略：
- overwrite_on_rerun=True  -> 覆盖同 (trade_date, snapshot_type) 快照；
- overwrite_on_rerun=False -> 若已存在则改写为 manual 快照，保留原始任务快照。
"""

from __future__ import annotations

from datetime import datetime

from .config import Config
from .models import SnapshotType
from .storage import Storage

# strategy.metrics 的 key -> 快照列名
_METRIC_MAP = {
    "lianban_count": "lianban_count",
    "prev_lianban_count": "lianban_count",
    "industry": "industry",
    "free_market_cap": "free_market_cap",
    "total_market_cap": "total_market_cap",
    "latest_price": "latest_price",
    "last_close": "last_close",
    "last_volume": "last_volume",
    "amount": "amount",
    "turnover_rate": "turnover_rate",
    "break_board_count": "break_board_count",
    "first_limit_time": "first_limit_time",
    "last_limit_time": "last_limit_time",
    "seal_amount": "seal_amount",
    "volume_ratio": "volume_ratio",
    "auction_price": "auction_price",
    "auction_volume": "auction_volume",
    "auction_amount": "auction_amount",
    "auction_ratio": "auction_ratio",
    "gap_open_pct": "gap_open_pct",
    "quality": "quality",
}


def build_snapshot_row(
    *,
    trade_date: str,
    state: str,
    code: str,
    name: str,
    state_date: str,
    is_new_state: bool,
    previous_state: str | None,
    reason: str,
    metrics: dict,
    source: str,
) -> dict:
    """构造一行快照（snapshot_type 由 persist 阶段统一回填）。"""
    row: dict = {
        "trade_date": trade_date,
        "snapshot_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "code": code,
        "name": name,
        "state": state,
        "state_date": state_date,
        "is_new_state": 1 if is_new_state else 0,
        "previous_state": previous_state,
        "reason": reason,
        "source": source,
    }
    for mkey, col in _METRIC_MAP.items():
        if mkey in metrics and metrics[mkey] is not None:
            row[col] = metrics[mkey]
    # 收盘快照里 today_volume 即当日成交量
    if "today_volume" in metrics and metrics["today_volume"] is not None:
        row.setdefault("volume", metrics["today_volume"])
    return row


def persist_snapshot(
    storage: Storage,
    cfg: Config,
    trade_date: str,
    snapshot_type: str,
    rows: list[dict],
) -> tuple[str, int]:
    """落库并应用重跑策略。返回 (实际快照类型, 写入行数)。"""
    overwrite = cfg.snapshot.overwrite_on_rerun
    effective = snapshot_type
    if storage.snapshot_exists(trade_date, snapshot_type) and not overwrite:
        effective = SnapshotType.MANUAL
    for r in rows:
        r["trade_date"] = trade_date
        r["snapshot_type"] = effective
    written = storage.write_snapshot(rows, overwrite=overwrite)
    return effective, written
