from oribrink.models import States, TaskName
from oribrink.storage import Storage


def test_upsert_current_state_insert_then_update(storage: Storage):
    storage.upsert_current_state(
        code="000001", name="平安银行", state=States.FEILONG,
        state_date="2025-05-15", lianban_count=3,
    )
    row = storage.get_current("000001")
    assert row["state"] == States.FEILONG and row["lianban_count"] == 3

    storage.upsert_current_state(
        code="000001", name="平安银行", state=States.KANGLONG,
        state_date="2025-05-16", lianban_count=4,
    )
    row = storage.get_current("000001")
    assert row["state"] == States.KANGLONG and row["lianban_count"] == 4
    assert len(storage.get_current_by_state(States.KANGLONG)) == 1


def test_record_transition_dedup(storage: Storage):
    first = storage.record_transition(
        "000001", "平安银行", States.FEILONG, States.KANGLONG,
        "2025-05-15", TaskName.KANGLONG, "亢龙", {"k": 1},
    )
    second = storage.record_transition(
        "000001", "平安银行", States.FEILONG, States.KANGLONG,
        "2025-05-15", TaskName.KANGLONG, "亢龙", {"k": 1},
    )
    assert first is True and second is False  # 防重复通知
    assert len(storage.query_transitions(code="000001")) == 1


def test_notification_flow(storage: Storage):
    storage.record_transition(
        "000001", "平安银行", States.FEILONG, States.KANGLONG,
        "2025-05-15", TaskName.KANGLONG, "r", {},
    )
    un = storage.unnotified_transitions("2025-05-15", TaskName.KANGLONG, States.KANGLONG)
    assert len(un) == 1
    storage.mark_notified([un[0]["id"]])
    assert storage.unnotified_transitions("2025-05-15", TaskName.KANGLONG) == []


def test_snapshot_uniqueness_and_query(storage: Storage):
    row = {
        "trade_date": "2025-05-15", "snapshot_type": "kanglong", "code": "000001",
        "name": "平安银行", "state": States.FEILONG, "lianban_count": 3,
    }
    assert storage.write_snapshot([row], overwrite=False) == 1
    storage.write_snapshot([row], overwrite=False)  # 重复不新增
    res = storage.query_snapshot("2025-05-15", States.FEILONG, "kanglong")
    assert len(res) == 1
    assert storage.snapshot_exists("2025-05-15", "kanglong")


def test_task_run_lifecycle(storage: Storage):
    rid = storage.start_task_run(TaskName.KANGLONG, "2025-05-15")
    storage.finish_task_run(rid, "success", total=10, success=10)
    runs = storage.query_task_runs("2025-05-15")
    assert runs[0]["status"] == "success" and runs[0]["total_count"] == 10
