import pytest

from oribrink.config import Config
from oribrink.models import SnapshotType, States
from oribrink.query import (
    QueryError,
    export_rows,
    query_all_pools,
    query_state_pool,
)
from oribrink.snapshot import build_snapshot_row, persist_snapshot
from oribrink.storage import Storage


def test_build_snapshot_row_maps_metrics():
    row = build_snapshot_row(
        trade_date="2025-05-15", state=States.FEILONG, code="000001",
        name="平安银行", state_date="2025-05-15", is_new_state=True,
        previous_state=None, reason="连板 3",
        metrics={"lianban_count": 3, "free_market_cap": 5e9, "today_volume": 999},
        source="zt",
    )
    assert row["lianban_count"] == 3
    assert row["free_market_cap"] == 5e9
    assert row["volume"] == 999  # today_volume -> volume
    assert row["is_new_state"] == 1


def test_persist_snapshot_rerun_falls_back_to_manual(storage: Storage):
    cfg = Config()  # overwrite_on_rerun=False
    rows = [build_snapshot_row(
        trade_date="2025-05-15", state=States.FEILONG, code="000001", name="A",
        state_date="2025-05-15", is_new_state=True, previous_state=None,
        reason="r", metrics={}, source="zt",
    )]
    t1, n1 = persist_snapshot(storage, cfg, "2025-05-15", SnapshotType.KANGLONG, rows)
    assert t1 == SnapshotType.KANGLONG and n1 == 1

    rows2 = [build_snapshot_row(
        trade_date="2025-05-15", state=States.FEILONG, code="000002", name="B",
        state_date="2025-05-15", is_new_state=True, previous_state=None,
        reason="r", metrics={}, source="zt",
    )]
    t2, _ = persist_snapshot(storage, cfg, "2025-05-15", SnapshotType.KANGLONG, rows2)
    assert t2 == SnapshotType.MANUAL  # 已存在 kanglong -> 改写 manual


def test_query_no_data_returns_empty(storage: Storage):
    assert query_state_pool(storage, "2025-05-15", States.FEILONG) == []


def test_query_invalid_inputs(storage: Storage):
    with pytest.raises(QueryError):
        query_state_pool(storage, "2025/05/15")
    with pytest.raises(QueryError):
        query_state_pool(storage, "2025-05-15", "不存在状态")


def test_query_all_pools_grouped(storage: Storage):
    for code, state in [("1", States.FEILONG), ("2", States.KANGLONG)]:
        storage.write_snapshot(
            [{"trade_date": "2025-05-15", "snapshot_type": "kanglong",
              "code": code, "name": code, "state": state}],
            overwrite=False,
        )
    grouped = query_all_pools(storage, "2025-05-15")
    assert len(grouped[States.FEILONG]) == 1
    assert len(grouped[States.KANGLONG]) == 1
    assert grouped[States.QIANLONG] == []


def test_export_csv_and_json(tmp_path):
    rows = [{"code": "000001", "name": "平安银行", "lianban": 3}]
    csv_path = export_rows(rows, "csv", tmp_path / "out.csv")
    json_path = export_rows(rows, "json", tmp_path / "out.json")
    assert csv_path.exists() and "000001" in csv_path.read_text(encoding="utf-8-sig")
    assert json_path.exists() and "平安银行" in json_path.read_text(encoding="utf-8")
    with pytest.raises(QueryError):
        export_rows(rows, "xlsx", tmp_path / "out.xlsx")
