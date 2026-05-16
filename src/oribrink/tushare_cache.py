"""Tushare 原始 JSONL 缓存与历史回算适配。

collect 阶段只保存必要接口的原始返回；backtest 阶段只读这些 JSONL，
不再访问网络，便于后续反复调整策略。
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import Config
from .datasource import normalize_time
from .logging import get_logger
from .models import AuctionData, Candidate, DailyBar, SnapshotType, States, TaskName, TaskStatus
from .snapshot import build_snapshot_row, persist_snapshot
from .storage import Storage
from .strategy import evaluate_kanglong, evaluate_qianlong, kanglong_triggered_codes, select_feilong
from .tasks import _qianlong_checks
from .models import ZbRow, ZtRow

log = get_logger("tushare")

COLLECT_APIS = ("limit_list_d", "daily", "daily_basic", "stk_auction")

FIELDS = {
    "trade_cal": (
        "exchange,cal_date,is_open,pretrade_date"
    ),
    "limit_list_d": (
        "trade_date,ts_code,name,industry,close,pct_chg,amount,limit_amount,"
        "float_mv,total_mv,turnover_ratio,fd_amount,first_time,last_time,"
        "open_times,up_stat,limit_times,limit"
    ),
    "daily": "ts_code,trade_date,open,high,low,close,pre_close,vol,amount",
    "daily_basic": (
        "ts_code,trade_date,turnover_rate,volume_ratio,free_share,float_share,"
        "total_mv,circ_mv"
    ),
    "stk_auction": (
        "ts_code,trade_date,vol,price,amount,pre_close,turnover_rate,"
        "volume_ratio,float_share"
    ),
}


class TushareError(RuntimeError):
    """Tushare 请求或缓存读取异常。"""


def _iso_to_ts(date: str) -> str:
    return str(date).strip()[:10].replace("-", "")


def _ts_to_iso(date: str) -> str:
    s = str(date).strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _code(ts_code: str | None) -> str:
    return str(ts_code or "").split(".")[0].zfill(6)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def _request_key(api_name: str, params: dict, fields: str | None) -> str:
    text = json.dumps(
        {"api_name": api_name, "params": params, "fields": fields},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _period_for(api_name: str, params: dict) -> str:
    if api_name == "trade_cal":
        start = str(params.get("start_date", "unknown"))
        end = str(params.get("end_date", start))
        return f"{start[:4]}-{end[:4]}"
    trade_date = str(params.get("trade_date", "unknown"))
    return f"{trade_date[:4]}-{trade_date[4:6]}"


class TushareRawCache:
    """按接口/年份保存 Tushare 原始请求结果。"""

    def __init__(self, raw_dir: str | Path):
        self.raw_dir = Path(raw_dir)

    def _path(self, api_name: str, params: dict) -> Path:
        if api_name == "trade_cal":
            return self.raw_dir / "trade_cal.jsonl"
        return self.raw_dir / api_name / f"{_period_for(api_name, params)}.jsonl"

    def has(self, api_name: str, params: dict, fields: str | None) -> bool:
        key = _request_key(api_name, params, fields)
        path = self._path(api_name, params)
        if not path.exists():
            return False
        return any(r.get("request_key") == key for r in self._read_lines(path))

    def write(
        self, api_name: str, params: dict, fields: str | None, items: list[list], columns: list[str]
    ) -> Path:
        path = self._path(api_name, params)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "provider": "tushare",
            "api_name": api_name,
            "params": params,
            "fields": columns,
            "items": items,
            "row_count": len(items),
            "request_key": _request_key(api_name, params, fields),
            "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return path

    def latest(self, api_name: str, params: dict, fields: str | None = None) -> dict | None:
        path = self._path(api_name, params)
        if not path.exists():
            return None
        key = _request_key(api_name, params, fields) if fields else None
        found = None
        for record in self._read_lines(path):
            if key is None or record.get("request_key") == key:
                found = record
        return found

    def rows(self, api_name: str, params: dict, fields: str | None = None) -> list[dict]:
        record = self.latest(api_name, params, fields)
        if not record:
            return []
        columns = record.get("fields") or []
        return [dict(zip(columns, item)) for item in record.get("items") or []]

    def records(self, api_name: str) -> list[dict]:
        if api_name == "trade_cal":
            path = self.raw_dir / "trade_cal.jsonl"
            return self._read_lines(path) if path.exists() else []
        root = self.raw_dir / api_name
        records: list[dict] = []
        for path in sorted(root.glob("*.jsonl")):
            records.extend(self._read_lines(path))
        return records

    def _read_lines(self, path: Path) -> list[dict]:
        rows = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows


class TushareClient:
    """第三方 Tushare HTTP 兼容接口。"""

    def __init__(
        self,
        token: str,
        endpoint: str,
        request_interval: float = 0.65,
        timeout: float = 30.0,
        retry_attempts: int = 3,
        retry_backoff: float = 10.0,
    ):
        if not token:
            raise TushareError("缺少 tushare.token，请在 config.toml 的 [tushare] 中配置")
        self.token = token
        self.endpoint = endpoint.rstrip("/")
        self.request_interval = max(0.0, request_interval)
        self.timeout = timeout
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self._last_request = 0.0

    def query(self, api_name: str, params: dict, fields: str | None = None) -> tuple[list[str], list[list]]:
        last: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return self._query_once(api_name, params, fields)
            except TushareError as e:
                last = e
                if attempt >= self.retry_attempts:
                    break
                wait = self.retry_backoff * attempt
                log.warning(
                    "%s %s 请求失败，第 %d/%d 次重试前等待 %.1f 秒：%s",
                    api_name,
                    params,
                    attempt,
                    self.retry_attempts,
                    wait,
                    e,
                )
                time.sleep(wait)
        raise last  # type: ignore[misc]

    def _query_once(self, api_name: str, params: dict, fields: str | None = None) -> tuple[list[str], list[list]]:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        payload: dict[str, Any] = {"api_name": api_name, "params": params}
        if fields:
            payload["fields"] = fields
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip",
                "x-api-key": self.token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
        except urllib.error.URLError as e:
            raise TushareError(f"{api_name} 请求失败: {e}") from e
        finally:
            self._last_request = time.monotonic()
        data = json.loads(raw.decode("utf-8"))
        if data.get("code") not in (0, None):
            raise TushareError(f"{api_name} 返回错误: {data.get('msg') or data}")
        block = data.get("data") or {}
        return list(block.get("fields") or []), list(block.get("items") or [])


def _trade_dates(cache: TushareRawCache, start: str, end: str) -> list[str]:
    start_ts, end_ts = _iso_to_ts(start), _iso_to_ts(end)
    rows = []
    for record in cache.records("trade_cal"):
        columns = record.get("fields") or []
        for item in record.get("items") or []:
            row = dict(zip(columns, item))
            cal_date = str(row.get("cal_date") or "")
            if start_ts <= cal_date <= end_ts:
                rows.append(row)
    dates = {_ts_to_iso(r["cal_date"]) for r in rows if int(r.get("is_open") or 0) == 1}
    return sorted(dates)


def _limit_rows(cache: TushareRawCache, date: str) -> list[dict]:
    return cache.rows("limit_list_d", {"trade_date": _iso_to_ts(date)}, FIELDS["limit_list_d"])


def _daily_rows(cache: TushareRawCache, date: str) -> dict[str, DailyBar]:
    rows = cache.rows("daily", {"trade_date": _iso_to_ts(date)}, FIELDS["daily"])
    return {
        _code(r.get("ts_code")): DailyBar(
            date=date,
            code=_code(r.get("ts_code")),
            open=_num(r.get("open")),
            close=_num(r.get("close")),
            high=_num(r.get("high")),
            low=_num(r.get("low")),
            volume=_num(r.get("vol")),
            amount=_num(r.get("amount")),
        )
        for r in rows
    }


def _auction_rows(cache: TushareRawCache, date: str) -> dict[str, AuctionData]:
    rows = cache.rows("stk_auction", {"trade_date": _iso_to_ts(date)}, FIELDS["stk_auction"])
    data = {}
    for r in rows:
        vol_shares = _num(r.get("vol"))
        data[_code(r.get("ts_code"))] = AuctionData(
            code=_code(r.get("ts_code")),
            time="09:25:00",
            price=_num(r.get("price")),
            volume=(vol_shares / 100.0) if vol_shares is not None else None,
            amount=_num(r.get("amount")),
        )
    return data


def _zt_rows(rows: list[dict]) -> list[ZtRow]:
    out = []
    for r in rows:
        if r.get("limit") != "U":
            continue
        out.append(
            ZtRow(
                code=_code(r.get("ts_code")),
                name=str(r.get("name") or ""),
                pct_change=_num(r.get("pct_chg")),
                latest_price=_num(r.get("close")),
                amount=_num(r.get("amount")),
                free_market_cap=_num(r.get("float_mv")),
                total_market_cap=_num(r.get("total_mv")),
                turnover_rate=_num(r.get("turnover_ratio")),
                seal_amount=_num(r.get("fd_amount")),
                first_limit_time=normalize_time(r.get("first_time")),
                last_limit_time=normalize_time(r.get("last_time")),
                break_board_count=_int(r.get("open_times")),
                lianban_count=_int(r.get("limit_times")),
                industry=(str(r.get("industry")).strip() or None) if r.get("industry") else None,
            )
        )
    return out


def _zb_rows(rows: list[dict]) -> list[ZbRow]:
    out = []
    for r in rows:
        if r.get("limit") != "Z":
            continue
        out.append(
            ZbRow(
                code=_code(r.get("ts_code")),
                name=str(r.get("name") or ""),
                pct_change=_num(r.get("pct_chg")),
                latest_price=_num(r.get("close")),
                amount=_num(r.get("amount")),
                free_market_cap=_num(r.get("float_mv")),
                total_market_cap=_num(r.get("total_mv")),
                turnover_rate=_num(r.get("turnover_ratio")),
                first_limit_time=normalize_time(r.get("first_time")),
                break_board_count=_int(r.get("open_times")),
                industry=(str(r.get("industry")).strip() or None) if r.get("industry") else None,
            )
        )
    return out


def collect_tushare_raw(cfg: Config, start: str, end: str, refresh: bool = False) -> dict:
    """按交易日采集必要 Tushare 原始数据到 JSONL。"""
    cache = TushareRawCache(cfg.tushare.raw_dir)
    client = TushareClient(
        cfg.tushare.token, cfg.tushare.endpoint,
        cfg.tushare.request_interval, cfg.tushare.timeout,
        cfg.tushare.retry_attempts, cfg.tushare.retry_backoff,
    )
    start_ts, end_ts = _iso_to_ts(start), _iso_to_ts(end)
    calls = 0
    skipped = 0
    failures: list[str] = []

    def fetch(api_name: str, params: dict, fields: str) -> None:
        nonlocal calls, skipped
        if not refresh and cache.has(api_name, params, fields):
            skipped += 1
            log.info("命中 Tushare 原始缓存 %s %s", api_name, params)
            return
        try:
            columns, items = client.query(api_name, params, fields)
        except TushareError as e:
            failures.append(f"{api_name} {params}: {e}")
            log.error("采集失败 %s %s：%s", api_name, params, e)
            return
        cache.write(api_name, params, fields, items, columns)
        calls += 1
        log.info("已采集 %s %s: %d 行", api_name, params, len(items))

    cal_params = {"exchange": "SSE", "start_date": start_ts, "end_date": end_ts}
    fetch("trade_cal", cal_params, FIELDS["trade_cal"])
    if failures:
        return {
            "status": TaskStatus.PARTIAL,
            "from": start,
            "to": end,
            "calls": calls,
            "skipped": skipped,
            "failures": failures,
            "raw_dir": cfg.tushare.raw_dir,
        }
    dates = _trade_dates(cache, start, end)
    if not dates:
        return {"status": TaskStatus.SKIPPED, "reason": "交易日历为空", "calls": calls}

    for trade_date in dates:
        params = {"trade_date": _iso_to_ts(trade_date)}
        for api_name in COLLECT_APIS:
            fetch(api_name, params, FIELDS[api_name])
    return {
        "status": TaskStatus.PARTIAL if failures else TaskStatus.SUCCESS,
        "from": start,
        "to": end,
        "trade_days": len(dates),
        "calls": calls,
        "skipped": skipped,
        "failures": failures,
        "raw_dir": cfg.tushare.raw_dir,
    }


def _candidate_from_feilong(result, prev_date: str) -> Candidate:
    m = result.metrics
    return Candidate(
        code=result.code,
        name=result.name,
        prev_state=States.FEILONG,
        prev_state_date=prev_date,
        lianban_count=m.get("lianban_count"),
        free_market_cap=m.get("free_market_cap"),
        industry=m.get("industry"),
    )


def _kanglong_for_date(
    cache: TushareRawCache, cfg: Config, trade_date: str, prev_date: str
) -> tuple[list, list[str], int]:
    prev_zt_rows = _zt_rows(_limit_rows(cache, prev_date))
    zt_rows = _zt_rows(_limit_rows(cache, trade_date))
    zb_rows = _zb_rows(_limit_rows(cache, trade_date))
    prev_feilong, anomalies = select_feilong(prev_zt_rows, cfg.strategy)
    candidates = [_candidate_from_feilong(r, prev_date) for r in prev_feilong]
    if not candidates:
        return [], anomalies, 0

    zt_by_code = {r.code: r for r in zt_rows}
    zb_by_code = {r.code: r for r in zb_rows}
    triggered = kanglong_triggered_codes(candidates, zt_by_code, zb_by_code, cfg.strategy)
    daily_today = _daily_rows(cache, trade_date)
    daily_prev = _daily_rows(cache, prev_date)
    volumes = {}
    for c in candidates:
        if c.code not in triggered:
            continue
        today_b = daily_today.get(c.code)
        prev_b = daily_prev.get(c.code)
        volumes[c.code] = (
            today_b.volume if today_b else None,
            prev_b.volume if prev_b else None,
        )
    results, a2 = evaluate_kanglong(
        candidates, zt_by_code, zb_by_code, volumes, cfg.strategy
    )
    return results, anomalies + a2, len(candidates)


def _qianlong_for_date(
    cache: TushareRawCache, cfg: Config, trade_date: str, prev_date: str, kanglong_results: list
) -> tuple[list, list[dict], list[str], int]:
    if not kanglong_results:
        return [], [], [], 0
    candidates = [
        Candidate(
            code=r.code,
            name=r.name,
            prev_state=States.KANGLONG,
            prev_state_date=prev_date,
            free_market_cap=r.metrics.get("free_market_cap"),
            industry=r.metrics.get("industry"),
        )
        for r in kanglong_results
    ]
    auctions = _auction_rows(cache, trade_date)
    daily_prev = _daily_rows(cache, prev_date)
    last_close = {c.code: (daily_prev[c.code].close if c.code in daily_prev else None) for c in candidates}
    last_volume = {c.code: (daily_prev[c.code].volume if c.code in daily_prev else None) for c in candidates}
    results, anomalies = evaluate_qianlong(
        candidates, auctions, last_close, last_volume, cfg.strategy
    )
    checks = _qianlong_checks(candidates, auctions, last_close, last_volume, cfg)
    return results, checks, anomalies, len(candidates)


def _persist_results(
    storage: Storage, cfg: Config, trade_date: str, snapshot_type: str, state: str, results: list
) -> tuple[str, int]:
    rows = [
        build_snapshot_row(
            trade_date=trade_date,
            state=state,
            code=r.code,
            name=r.name,
            state_date=trade_date,
            is_new_state=True,
            previous_state=States.FEILONG if state == States.KANGLONG else States.KANGLONG,
            reason=r.reason,
            metrics=r.metrics,
            source="tushare_jsonl",
        )
        for r in results
    ]
    return persist_snapshot(storage, cfg, trade_date, snapshot_type, rows)


def _finish_run(
    storage: Storage, task_name: str, trade_date: str, total: int, success: int, anomalies: list[str]
) -> None:
    run_id = storage.start_task_run(task_name, trade_date)
    status = TaskStatus.PARTIAL if anomalies else TaskStatus.SUCCESS
    storage.finish_task_run(
        run_id,
        status,
        total=total,
        success=success,
        error=len(anomalies),
        error_summary=" | ".join(anomalies[:20]),
    )


def _has_result(storage: Storage, trade_date: str, snapshot_type: str, task_name: str) -> bool:
    if storage.snapshot_exists(trade_date, snapshot_type):
        return True
    return any(
        r["task_name"] == task_name and r["status"] in (TaskStatus.SUCCESS, TaskStatus.PARTIAL)
        for r in storage.query_task_runs(trade_date)
    )


def _cached_backtest_counts(storage: Storage, trade_date: str) -> dict:
    kanglong = len(
        storage.query_snapshot(trade_date, States.KANGLONG, SnapshotType.KANGLONG)
    )
    qianlong = len(
        storage.query_snapshot(trade_date, States.QIANLONG, SnapshotType.QIANLONG)
    )
    anomalies = 0
    for r in storage.query_task_runs(trade_date):
        if r["task_name"] in (TaskName.KANGLONG, TaskName.QIANLONG):
            anomalies += int(r.get("error_count") or 0)
    return {
        "trade_date": trade_date,
        "kanglong": kanglong,
        "qianlong": qianlong,
        "anomalies": anomalies,
        "cached": True,
    }


def backtest_tushare_cache(
    storage: Storage, cfg: Config, start: str, end: str, refresh: bool = False
) -> dict:
    """用本地 Tushare JSONL 缓存回算区间内亢龙和潜龙。"""
    cache = TushareRawCache(cfg.tushare.raw_dir)
    dates = _trade_dates(cache, start, end)
    if len(dates) < 2:
        return {"status": TaskStatus.SKIPPED, "reason": "本地交易日缓存不足"}

    summary = []
    kanglong_by_date: dict[str, list] = {}
    totals = {"kanglong": 0, "qianlong": 0}
    for i, trade_date in enumerate(dates):
        if i == 0:
            continue
        prev_date = dates[i - 1]
        if (
            not refresh
            and _has_result(storage, trade_date, SnapshotType.KANGLONG, TaskName.KANGLONG)
            and _has_result(storage, trade_date, SnapshotType.QIANLONG, TaskName.QIANLONG)
        ):
            cached = _cached_backtest_counts(storage, trade_date)
            totals["kanglong"] += cached["kanglong"]
            totals["qianlong"] += cached["qianlong"]
            summary.append(cached)
            continue

        kl_results, kl_anomalies, kl_total = _kanglong_for_date(
            cache, cfg, trade_date, prev_date
        )
        kanglong_by_date[trade_date] = kl_results
        _, kl_written = _persist_results(
            storage, cfg, trade_date, SnapshotType.KANGLONG, States.KANGLONG, kl_results
        )
        _finish_run(
            storage, TaskName.KANGLONG, trade_date, kl_total, len(kl_results), kl_anomalies
        )

        ql_results, ql_checks, ql_anomalies, ql_total = _qianlong_for_date(
            cache, cfg, trade_date, prev_date, kanglong_by_date.get(prev_date, [])
        )
        storage.replace_qianlong_checks(
            trade_date, prev_date, ql_checks, source="tushare_jsonl"
        )
        _, ql_written = _persist_results(
            storage, cfg, trade_date, SnapshotType.QIANLONG, States.QIANLONG, ql_results
        )
        _finish_run(
            storage, TaskName.QIANLONG, trade_date, ql_total, len(ql_results), ql_anomalies
        )

        totals["kanglong"] += len(kl_results)
        totals["qianlong"] += len(ql_results)
        summary.append(
            {
                "trade_date": trade_date,
                "kanglong": len(kl_results),
                "qianlong": len(ql_results),
                "kanglong_snapshot_rows": kl_written,
                "qianlong_snapshot_rows": ql_written,
                "anomalies": len(kl_anomalies) + len(ql_anomalies),
            }
        )
        log.info(
            "回测 %s 完成：亢龙 %d，潜龙 %d",
            trade_date,
            len(kl_results),
            len(ql_results),
        )

    return {
        "status": TaskStatus.SUCCESS,
        "from": start,
        "to": end,
        "trade_days": len(dates),
        "kanglong": totals["kanglong"],
        "qianlong": totals["qianlong"],
        "summary": summary,
    }
