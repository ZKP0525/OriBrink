"""状态存储模块（SQLite，stdlib sqlite3，零额外依赖）。

四张表：
- current_stock_state    最近状态缓存
- state_transition_history  状态流转事件（去重 + 防重复通知）
- daily_state_snapshot   每日任务结果快照
- task_run_history       任务运行记录
另含可选 raw_data_snapshot 保存 AkShare 原始返回，便于排查误判。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS current_stock_state (
    code TEXT PRIMARY KEY,
    name TEXT,
    state TEXT NOT NULL,
    state_date TEXT NOT NULL,
    previous_state TEXT,
    previous_state_date TEXT,
    lianban_count INTEGER,
    industry TEXT,
    free_market_cap REAL,
    total_market_cap REAL,
    last_close REAL,
    last_volume REAL,
    today_volume REAL,
    volume_ratio REAL,
    break_board_count INTEGER,
    first_limit_time TEXT,
    last_limit_time TEXT,
    seal_amount REAL,
    turnover_rate REAL,
    auction_price REAL,
    auction_volume REAL,
    auction_amount REAL,
    auction_ratio REAL,
    gap_open_pct REAL,
    quality TEXT,
    reason TEXT,
    source_date TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS state_transition_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    from_state TEXT,
    to_state TEXT NOT NULL,
    transition_date TEXT NOT NULL,
    transition_task TEXT NOT NULL,
    reason TEXT,
    metrics_json TEXT,
    notified INTEGER DEFAULT 0,
    notified_at TEXT,
    created_at TEXT,
    UNIQUE (code, to_state, transition_date, transition_task)
);

CREATE TABLE IF NOT EXISTS daily_state_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    snapshot_time TEXT,
    snapshot_type TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    state TEXT NOT NULL,
    state_date TEXT,
    is_new_state INTEGER DEFAULT 0,
    previous_state TEXT,
    lianban_count INTEGER,
    industry TEXT,
    free_market_cap REAL,
    total_market_cap REAL,
    latest_price REAL,
    close_price REAL,
    last_close REAL,
    volume REAL,
    last_volume REAL,
    amount REAL,
    turnover_rate REAL,
    break_board_count INTEGER,
    first_limit_time TEXT,
    last_limit_time TEXT,
    seal_amount REAL,
    volume_ratio REAL,
    auction_price REAL,
    auction_volume REAL,
    auction_amount REAL,
    auction_ratio REAL,
    gap_open_pct REAL,
    quality TEXT,
    reason TEXT,
    source TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE (trade_date, snapshot_type, code, state)
);

CREATE TABLE IF NOT EXISTS task_run_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    status TEXT,
    total_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    error_summary TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS raw_data_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    data_type TEXT NOT NULL,
    symbol TEXT,
    payload_json TEXT,
    row_count INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS qianlong_candidate_check (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    kanglong_date TEXT,
    code TEXT NOT NULL,
    name TEXT,
    industry TEXT,
    free_market_cap REAL,
    auction_price REAL,
    auction_volume REAL,
    auction_amount REAL,
    last_close REAL,
    last_volume REAL,
    gap_open_pct REAL,
    auction_ratio REAL,
    quality TEXT,
    reason TEXT,
    passed INTEGER DEFAULT 0,
    source TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE (trade_date, code, source)
);
"""

SNAPSHOT_COLUMNS = (
    "trade_date", "snapshot_time", "snapshot_type", "code", "name", "state",
    "state_date", "is_new_state", "previous_state", "lianban_count", "industry",
    "free_market_cap", "total_market_cap", "latest_price", "close_price",
    "last_close", "volume", "last_volume", "amount", "turnover_rate",
    "break_board_count", "first_limit_time", "last_limit_time", "seal_amount",
    "volume_ratio", "auction_price", "auction_volume", "auction_amount",
    "auction_ratio", "gap_open_pct", "quality", "reason", "source",
)

CURRENT_COLUMNS = (
    "code", "name", "state", "state_date", "previous_state", "previous_state_date",
    "lianban_count", "industry", "free_market_cap", "total_market_cap",
    "last_close", "last_volume", "today_volume", "volume_ratio",
    "break_board_count", "first_limit_time", "last_limit_time", "seal_amount",
    "turnover_rate", "auction_price", "auction_volume", "auction_amount",
    "auction_ratio", "gap_open_pct", "quality", "reason", "source_date",
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Storage:
    """SQLite 封装。``db_path=":memory:"`` 用于测试。"""

    def __init__(self, db_path: str):
        if db_path != ":memory:":
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ----------------------- current_stock_state ------------------------- #
    def get_current(self, code: str) -> dict | None:
        cur = self.conn.execute(
            "SELECT * FROM current_stock_state WHERE code = ?", (code,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_current_by_state(self, state: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM current_stock_state WHERE state = ? ORDER BY code", (state,)
        )
        return [dict(r) for r in cur.fetchall()]

    def upsert_current_state(self, **fields: Any) -> None:
        """按 code 插入/更新当前状态。仅 CURRENT_COLUMNS 内字段生效。"""
        data = {k: v for k, v in fields.items() if k in CURRENT_COLUMNS}
        existing = self.get_current(data["code"])
        now = _now()
        data["updated_at"] = now
        if existing is None:
            data["created_at"] = now
            cols = list(data)
            self.conn.execute(
                f"INSERT INTO current_stock_state ({','.join(cols)}) "
                f"VALUES ({','.join('?' for _ in cols)})",
                [data[c] for c in cols],
            )
        else:
            cols = [c for c in data if c != "code"]
            self.conn.execute(
                f"UPDATE current_stock_state SET {','.join(f'{c}=?' for c in cols)} "
                "WHERE code = ?",
                [data[c] for c in cols] + [data["code"]],
            )
        self.conn.commit()

    # --------------------- state_transition_history ---------------------- #
    def record_transition(
        self,
        code: str,
        name: str,
        from_state: str | None,
        to_state: str,
        transition_date: str,
        transition_task: str,
        reason: str,
        metrics: dict | None = None,
    ) -> bool:
        """写流转事件。返回 True=新插入，False=已存在（用于防重复通知）。"""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO state_transition_history "
            "(code,name,from_state,to_state,transition_date,transition_task,"
            "reason,metrics_json,notified,created_at) VALUES (?,?,?,?,?,?,?,?,0,?)",
            (
                code, name, from_state, to_state, transition_date, transition_task,
                reason, json.dumps(metrics or {}, ensure_ascii=False, default=str),
                _now(),
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def unnotified_transitions(
        self, transition_date: str, transition_task: str, to_state: str | None = None
    ) -> list[dict]:
        sql = (
            "SELECT * FROM state_transition_history WHERE transition_date=? "
            "AND transition_task=? AND notified=0"
        )
        params: list[Any] = [transition_date, transition_task]
        if to_state:
            sql += " AND to_state=?"
            params.append(to_state)
        sql += " ORDER BY id"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def mark_notified(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        self.conn.executemany(
            "UPDATE state_transition_history SET notified=1, notified_at=? WHERE id=?",
            [(_now(), i) for i in ids],
        )
        self.conn.commit()

    def query_transitions(
        self,
        code: str | None = None,
        transition_date: str | None = None,
        to_state: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM state_transition_history WHERE 1=1"
        params: list[Any] = []
        if code:
            sql += " AND code=?"
            params.append(code)
        if transition_date:
            sql += " AND transition_date=?"
            params.append(transition_date)
        if to_state:
            sql += " AND to_state=?"
            params.append(to_state)
        if start_date:
            sql += " AND transition_date>=?"
            params.append(start_date)
        if end_date:
            sql += " AND transition_date<=?"
            params.append(end_date)
        sql += " ORDER BY transition_date ASC, id ASC"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # ---------------------- daily_state_snapshot ------------------------- #
    def write_snapshot(self, rows: list[dict], overwrite: bool) -> int:
        """写快照行。overwrite=True 时同唯一键覆盖，否则忽略已存在行。"""
        if not rows:
            return 0
        now = _now()
        conflict = (
            "ON CONFLICT(trade_date,snapshot_type,code,state) DO UPDATE SET "
            + ",".join(
                f"{c}=excluded.{c}"
                for c in SNAPSHOT_COLUMNS
                if c not in ("trade_date", "snapshot_type", "code", "state")
            )
            + ",updated_at=excluded.updated_at"
            if overwrite
            else "ON CONFLICT(trade_date,snapshot_type,code,state) DO NOTHING"
        )
        sql = (
            f"INSERT INTO daily_state_snapshot ({','.join(SNAPSHOT_COLUMNS)},"
            f"created_at,updated_at) VALUES "
            f"({','.join('?' for _ in SNAPSHOT_COLUMNS)},?,?) {conflict}"
        )
        n = 0
        for row in rows:
            params = [row.get(c) for c in SNAPSHOT_COLUMNS] + [now, now]
            self.conn.execute(sql, params)
            n += 1
        self.conn.commit()
        return n

    def query_snapshot(
        self,
        trade_date: str,
        state: str | None = None,
        snapshot_type: str | None = None,
        sort_by: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM daily_state_snapshot WHERE trade_date=?"
        params: list[Any] = [trade_date]
        if state:
            sql += " AND state=?"
            params.append(state)
        if snapshot_type:
            sql += " AND snapshot_type=?"
            params.append(snapshot_type)
        allowed = set(SNAPSHOT_COLUMNS)
        if sort_by and sort_by in allowed:
            sql += f" ORDER BY {sort_by} DESC"
        else:
            sql += " ORDER BY state, lianban_count DESC, auction_ratio DESC"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def snapshot_exists(self, trade_date: str, snapshot_type: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM daily_state_snapshot WHERE trade_date=? AND snapshot_type=? "
            "LIMIT 1",
            (trade_date, snapshot_type),
        )
        return cur.fetchone() is not None

    # ------------------------ task_run_history --------------------------- #
    def start_task_run(self, task_name: str, trade_date: str) -> int:
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO task_run_history "
            "(task_name,trade_date,started_at,status,created_at) VALUES (?,?,?,?,?)",
            (task_name, trade_date, now, "running", now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_task_run(
        self,
        run_id: int,
        status: str,
        total: int = 0,
        success: int = 0,
        error: int = 0,
        error_summary: str = "",
    ) -> None:
        self.conn.execute(
            "UPDATE task_run_history SET finished_at=?,status=?,total_count=?,"
            "success_count=?,error_count=?,error_summary=? WHERE id=?",
            (_now(), status, total, success, error, error_summary, run_id),
        )
        self.conn.commit()

    def query_task_runs(self, trade_date: str | None = None) -> list[dict]:
        if trade_date:
            cur = self.conn.execute(
                "SELECT * FROM task_run_history WHERE trade_date=? ORDER BY id",
                (trade_date,),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM task_run_history ORDER BY id DESC LIMIT 50"
            )
        return [dict(r) for r in cur.fetchall()]

    # ------------------------ raw_data_snapshot -------------------------- #
    def save_raw(
        self, trade_date: str, data_type: str, payload: Any, symbol: str | None = None
    ) -> None:
        try:
            text = json.dumps(payload, ensure_ascii=False, default=str)
            count = len(payload) if hasattr(payload, "__len__") else None
        except (TypeError, ValueError):
            text, count = str(payload), None
        self.conn.execute(
            "INSERT INTO raw_data_snapshot "
            "(trade_date,data_type,symbol,payload_json,row_count,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (trade_date, data_type, symbol, text, count, _now()),
        )
        self.conn.commit()

    # --------------------- qianlong_candidate_check --------------------- #
    def replace_qianlong_checks(
        self,
        trade_date: str,
        kanglong_date: str | None,
        checks: list[dict],
        source: str,
    ) -> int:
        self.conn.execute(
            "DELETE FROM qianlong_candidate_check WHERE trade_date=? AND source=?",
            (trade_date, source),
        )
        now = _now()
        for row in checks:
            self.conn.execute(
                """
                INSERT INTO qianlong_candidate_check
                (trade_date,kanglong_date,code,name,industry,free_market_cap,
                 auction_price,auction_volume,auction_amount,last_close,last_volume,
                 gap_open_pct,auction_ratio,quality,reason,passed,source,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    trade_date,
                    kanglong_date,
                    row.get("code"),
                    row.get("name"),
                    row.get("industry"),
                    row.get("free_market_cap"),
                    row.get("auction_price"),
                    row.get("auction_volume"),
                    row.get("auction_amount"),
                    row.get("last_close"),
                    row.get("last_volume"),
                    row.get("gap_open_pct"),
                    row.get("auction_ratio"),
                    row.get("quality"),
                    row.get("reason"),
                    1 if str(row.get("reason") or "").startswith("入选") else 0,
                    source,
                    now,
                    now,
                ),
            )
        self.conn.commit()
        return len(checks)

    def query_qianlong_checks(
        self, trade_date: str, kanglong_date: str | None = None
    ) -> list[dict]:
        sql = "SELECT * FROM qianlong_candidate_check WHERE trade_date=?"
        params: list[Any] = [trade_date]
        if kanglong_date is not None:
            sql += " AND kanglong_date=?"
            params.append(kanglong_date)
        sql += " ORDER BY passed DESC, auction_ratio DESC, code"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]


def open_storage(db_path: str) -> Storage:
    return Storage(db_path)
