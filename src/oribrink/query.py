"""快照查询工具模块。

CLI 不再暴露 query 命令；这些函数保留给测试、脚本或后续内部工具使用。
底层只读 daily_state_snapshot 与 state_transition_history。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from .models import SnapshotType, States
from .storage import Storage


class QueryError(ValueError):
    """非法查询参数（日期格式、状态名等）。"""


def _check_date(date: str) -> str:
    try:
        dt.date.fromisoformat(date)
    except ValueError as e:
        raise QueryError(f"非法日期格式（应为 YYYY-MM-DD）: {date!r}") from e
    return date


def _check_state(state: str | None) -> str | None:
    if state is not None and state not in States.ALL:
        raise QueryError(
            f"非法状态名: {state!r}，应为 {' / '.join(States.ALL)}"
        )
    return state


def _check_snapshot_type(st: str | None) -> str | None:
    if st is not None and st not in SnapshotType.ALL:
        raise QueryError(
            f"非法快照类型: {st!r}，应为 {' / '.join(SnapshotType.ALL)}"
        )
    return st


def query_state_pool(
    storage: Storage,
    trade_date: str,
    state: str | None = None,
    snapshot_type: str | None = None,
    sort_by: str | None = None,
) -> list[dict]:
    """查询某日某状态池（state=None 时为当日全部状态池）。"""
    _check_date(trade_date)
    _check_state(state)
    _check_snapshot_type(snapshot_type)
    return storage.query_snapshot(trade_date, state, snapshot_type, sort_by)


def query_all_pools(
    storage: Storage, trade_date: str, snapshot_type: str | None = None
) -> dict[str, list[dict]]:
    """查询某日全部状态池，按状态分组。"""
    rows = query_state_pool(storage, trade_date, None, snapshot_type)
    grouped: dict[str, list[dict]] = {s: [] for s in States.ALL}
    for r in rows:
        grouped.setdefault(r["state"], []).append(r)
    return grouped


def query_stock_history(
    storage: Storage,
    code: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """某只股票的状态流转历史。"""
    if start_date:
        _check_date(start_date)
    if end_date:
        _check_date(end_date)
    return storage.query_transitions(
        code=str(code).zfill(6), start_date=start_date, end_date=end_date
    )


def query_new_transitions(
    storage: Storage, trade_date: str, to_state: str | None = None
) -> list[dict]:
    """某日新增状态变化。"""
    _check_date(trade_date)
    _check_state(to_state)
    return storage.query_transitions(transition_date=trade_date, to_state=to_state)


def export_rows(rows: list[dict], fmt: str, path: str | Path) -> Path:
    """导出查询结果。fmt: csv / json。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    elif fmt == "json":
        path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    else:
        raise QueryError(f"不支持的导出格式: {fmt!r}（csv / json）")
    return path
