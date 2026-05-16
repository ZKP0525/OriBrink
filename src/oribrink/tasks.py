"""任务编排模块：亢龙有悔 / 潜龙在渊。

核心判断不再依赖 ``current_stock_state`` 取候选池：
- 亢龙有悔：用 T 日的昨日涨停池筛 T-1 飞龙，再用 T 日数据判断弱化放量。
- 潜龙在渊：先动态计算上一交易日亢龙，再用当天 09:25 竞价数据判断。

SQLite 仍用于缓存、快照、去重通知和任务审计。
"""

from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

from .config import Config
from .datasource import (
    DataSourceError,
    apply_config,
    fetch_auction,
    fetch_daily_hist,
    fetch_previous_zt_pool,
    fetch_zbgc_pool,
    fetch_zt_pool,
)
from .logging import get_logger
from .models import Candidate, SnapshotType, States, TaskName, TaskStatus
from .notifier import build_kanglong_email, build_qianlong_email, send_email
from .snapshot import build_snapshot_row, persist_snapshot
from .storage import Storage
from .strategy import (
    evaluate_kanglong,
    evaluate_qianlong,
    kanglong_triggered_codes,
    select_feilong,
)

log = get_logger("tasks")


def _window(trade_date: str, days: int = 25) -> tuple[str, str]:
    end = dt.date.fromisoformat(trade_date)
    return (end - dt.timedelta(days=days)).isoformat(), end.isoformat()


def _split_bars(bars: list, trade_date: str) -> tuple[object | None, object | None]:
    """返回 (今日 bar 或 None, 昨日 bar 或 None)。bars 已按日期升序。"""
    today = next((b for b in bars if b.date == trade_date), None)
    prev = None
    for b in bars:
        if b.date < trade_date:
            prev = b
    return today, prev


def _previous_weekday(date: str) -> str:
    d = dt.date.fromisoformat(date) - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def _nearest_weekday(date: str) -> str:
    d = dt.date.fromisoformat(date)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def _latest_detail_trade_date(now: dt.datetime | None = None) -> tuple[str, str | None]:
    """腾讯 3 秒成交明细 16:00 后才提供当日数据，返回当前可用交易日。"""
    now = now or dt.datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    else:
        now = now.astimezone(ZoneInfo("Asia/Shanghai"))

    today = now.date().isoformat()
    latest = _nearest_weekday(today)
    if latest == today and now.time() < dt.time(16, 0):
        latest = _previous_weekday(today)
        return latest, f"腾讯 3 秒成交明细 16:00 后更新，当前显示 {latest} 的潜龙数据"
    return latest, None


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


def _result_payload(results: list) -> list[dict]:
    rows = []
    for r in results:
        m = r.metrics
        rows.append(
            {
                "code": r.code,
                "name": r.name,
                "state": r.state,
                "industry": m.get("industry"),
                "prev_lianban_count": m.get("prev_lianban_count"),
                "free_market_cap": m.get("free_market_cap"),
                "volume_ratio": m.get("volume_ratio"),
                "gap_open_pct": m.get("gap_open_pct"),
                "auction_ratio": m.get("auction_ratio"),
                "quality": m.get("quality"),
                "reason": r.reason,
            }
        )
    return rows


def _snapshot_payload(
    rows: list[dict], metrics_by_code: dict[str, dict] | None = None
) -> list[dict]:
    payload = []
    metrics_by_code = metrics_by_code or {}
    for r in rows:
        m = metrics_by_code.get(r.get("code"), {})
        payload.append(
            {
                "code": r.get("code"),
                "name": r.get("name"),
                "state": r.get("state"),
                "industry": r.get("industry") or m.get("industry"),
                "prev_lianban_count": (
                    r.get("lianban_count") or m.get("prev_lianban_count")
                ),
                "free_market_cap": r.get("free_market_cap") or m.get("free_market_cap"),
                "volume_ratio": r.get("volume_ratio") or m.get("volume_ratio"),
                "gap_open_pct": r.get("gap_open_pct") or m.get("gap_open_pct"),
                "auction_ratio": r.get("auction_ratio") or m.get("auction_ratio"),
                "quality": r.get("quality") or m.get("quality"),
                "reason": r.get("reason"),
            }
        )
    return payload


def _transition_metrics_by_code(
    storage: Storage, trade_date: str, to_state: str
) -> dict[str, dict]:
    metrics = {}
    for row in storage.query_transitions(transition_date=trade_date, to_state=to_state):
        try:
            metrics[row["code"]] = json.loads(row.get("metrics_json") or "{}")
        except (TypeError, ValueError):
            metrics[row["code"]] = {}
    return metrics


def _send_task_email(
    storage: Storage,
    cfg: Config,
    send: bool,
    task_label: str,
    subject: str,
    html: str,
    has_content: bool,
    transitions: list[dict],
) -> None:
    if not send:
        log.info("%s邮件跳过：命令指定不发送", task_label)
        return
    if not has_content and not cfg.email.send_when_empty:
        log.info("%s邮件跳过：无新增信号且 send_when_empty=false", task_label)
        return

    log.info(
        "%s邮件进入发送流程：subject=%s，新增信号=%d，收件人=%d",
        task_label,
        subject,
        len(transitions),
        len(cfg.email.recipients),
    )
    if send_email(cfg.email, subject, html):
        storage.mark_notified([t["id"] for t in transitions])


def _send_cached_task_email(
    storage: Storage,
    cfg: Config,
    send: bool,
    task_label: str,
    trade_date: str,
    task_name: str,
    state: str,
    snapshot_status: str,
    anomalies: list[str],
    builder,
) -> None:
    transitions = storage.unnotified_transitions(trade_date, task_name, state)
    if not transitions:
        reason = (
            "命中缓存且无待通知新增信号"
            if send else "命令指定不发送"
        )
        log.info("%s邮件跳过：%s", task_label, reason)
        return
    subject, html, has_content = builder(
        trade_date, transitions, snapshot_status, anomalies
    )
    _send_task_email(
        storage, cfg, send, task_label, subject, html, has_content, transitions
    )


def _cached_signals(
    storage: Storage, trade_date: str, snapshot_type: str, state: str
) -> list[dict]:
    return storage.query_snapshot(trade_date, state, snapshot_type)


def _completed_task_run(storage: Storage, trade_date: str, task_name: str) -> dict | None:
    runs = [
        r for r in storage.query_task_runs(trade_date)
        if r["task_name"] == task_name
        and r["status"] in (TaskStatus.SUCCESS, TaskStatus.PARTIAL)
    ]
    return runs[-1] if runs else None


def _cached_result(
    storage: Storage,
    trade_date: str,
    snapshot_type: str,
    state: str,
    task_name: str,
    new_key: str,
) -> dict | None:
    cached = _cached_signals(storage, trade_date, snapshot_type, state)
    if cached:
        log.info("命中%s缓存 trade_date=%s，共 %d 条", state, trade_date, len(cached))
        return {
            "status": TaskStatus.SUCCESS,
            "cached": True,
            new_key: 0,
            "snapshot": f"命中 {snapshot_type} 快照，共 {len(cached)} 条",
            "signals": _snapshot_payload(
                cached, _transition_metrics_by_code(storage, trade_date, state)
            ),
            "anomalies": [],
        }

    run = _completed_task_run(storage, trade_date, task_name)
    if run:
        anomalies = [run["error_summary"]] if run.get("error_summary") else []
        log.info("命中%s空结果缓存 trade_date=%s", state, trade_date)
        return {
            "status": run["status"],
            "cached": True,
            new_key: 0,
            "snapshot": f"命中 {snapshot_type} 空结果缓存，共 0 条",
            "signals": [],
            "anomalies": anomalies,
        }
    return None


def _collect_kanglong(
    cfg: Config, trade_date: str
) -> tuple[list, list[str], str | None, int]:
    """按日期动态计算亢龙结果，不读当前状态表。"""
    anomalies: list[str] = []

    zt_rows = fetch_zt_pool(trade_date)
    if not zt_rows:
        return [], anomalies, "涨停股池为空，疑似非交易日", 0

    prev_zt_rows = fetch_previous_zt_pool(trade_date)
    if not prev_zt_rows:
        return [], anomalies, "昨日涨停股池为空，无飞龙候选", 0

    try:
        zb_rows = fetch_zbgc_pool(trade_date)
    except DataSourceError as e:
        zb_rows = []
        anomalies.append(f"炸板股池获取失败：{e}")

    prev_feilong, a1 = select_feilong(prev_zt_rows, cfg.strategy)
    anomalies += a1
    prev_date = _previous_weekday(trade_date)
    candidates = [_candidate_from_feilong(r, prev_date) for r in prev_feilong]
    if not candidates:
        return [], anomalies, "昨日无飞龙候选", 0

    zt_by_code = {r.code: r for r in zt_rows}
    zb_by_code = {r.code: r for r in zb_rows}
    triggered = kanglong_triggered_codes(
        candidates, zt_by_code, zb_by_code, cfg.strategy
    )

    volumes: dict[str, tuple[float | None, float | None]] = {}
    start, end = _window(trade_date)
    if triggered:
        log.info("出现弱化形态的昨日飞龙 %d 只，拉取历史日 K 算放量", len(triggered))
    for c in candidates:
        if c.code not in triggered:
            continue
        try:
            bars = fetch_daily_hist(c.code, start, end)
            today_b, prev_b = _split_bars(bars, trade_date)
            volumes[c.code] = (
                today_b.volume if today_b else None,
                prev_b.volume if prev_b else None,
            )
        except DataSourceError as e:
            anomalies.append(f"{c.code} 历史日 K 获取失败：{e}")
            volumes[c.code] = (None, None)

    results, a2 = evaluate_kanglong(
        candidates, zt_by_code, zb_by_code, volumes, cfg.strategy
    )
    anomalies += a2
    return results, anomalies, None, len(candidates)


def _persist_kanglong(
    storage: Storage,
    cfg: Config,
    trade_date: str,
    results: list,
) -> tuple[set[str], str, int]:
    new_codes: set[str] = set()
    for r in results:
        cur = storage.get_current(r.code)
        inserted = storage.record_transition(
            r.code, r.name, States.FEILONG, States.KANGLONG,
            trade_date, TaskName.KANGLONG, r.reason, r.metrics,
        )
        if inserted:
            new_codes.add(r.code)
        m = r.metrics
        storage.upsert_current_state(
            code=r.code, name=r.name, state=States.KANGLONG, state_date=trade_date,
            previous_state=States.FEILONG,
            previous_state_date=m.get("prev_state_date"),
            lianban_count=m.get("prev_lianban_count"), industry=m.get("industry"),
            free_market_cap=m.get("free_market_cap"),
            total_market_cap=m.get("total_market_cap"),
            today_volume=m.get("today_volume"), last_volume=m.get("last_volume"),
            volume_ratio=m.get("volume_ratio"),
            break_board_count=m.get("break_board_count"),
            first_limit_time=m.get("first_limit_time"),
            last_limit_time=m.get("last_limit_time"),
            reason=r.reason, source_date=trade_date,
        )

    snap_rows = [
        build_snapshot_row(
            trade_date=trade_date, state=States.KANGLONG, code=r.code,
            name=r.name, state_date=trade_date,
            is_new_state=r.code in new_codes, previous_state=States.FEILONG,
            reason=r.reason, metrics=r.metrics, source="stock_zt_pool_previous_em/zt/zbgc",
        )
        for r in results
    ]
    snap_type, written = (SnapshotType.KANGLONG, 0)
    if cfg.snapshot.kanglong_enabled:
        snap_type, written = persist_snapshot(
            storage, cfg, trade_date, SnapshotType.KANGLONG, snap_rows
        )
    snap_status = (
        f"已生成 {snap_type} 快照，共 {written} 条"
        if cfg.snapshot.kanglong_enabled
        else "亢龙快照未启用"
    )
    return new_codes, snap_status, written


def run_kanglong_task(
    storage: Storage,
    cfg: Config,
    trade_date: str,
    send: bool = True,
    refresh: bool = False,
) -> dict:
    apply_config(cfg.datasource)
    requested_date = trade_date
    trade_date = _nearest_weekday(trade_date)
    if not refresh:
        cached = _cached_result(
            storage, trade_date, SnapshotType.KANGLONG, States.KANGLONG,
            TaskName.KANGLONG, "new_kanglong",
        )
        if cached:
            cached["trade_date"] = trade_date
            _send_cached_task_email(
                storage, cfg, send, "亢龙有悔", trade_date, TaskName.KANGLONG,
                States.KANGLONG, cached["snapshot"], cached.get("anomalies", []),
                build_kanglong_email,
            )
            return cached

    run_id = storage.start_task_run(TaskName.KANGLONG, trade_date)
    log.info("亢龙有悔任务开始 trade_date=%s", trade_date)
    if trade_date != requested_date:
        log.info("输入日期 %s 非交易日，已回退到最近交易日 %s", requested_date, trade_date)

    try:
        results, anomalies, skip_reason, candidate_count = _collect_kanglong(
            cfg, trade_date
        )
    except DataSourceError as e:
        storage.finish_task_run(run_id, TaskStatus.FAILED, error=1, error_summary=str(e))
        log.error("亢龙有悔任务失败：%s", e)
        return {"status": TaskStatus.FAILED, "error": str(e)}

    if skip_reason and skip_reason == "涨停股池为空，疑似非交易日":
        storage.finish_task_run(run_id, TaskStatus.SKIPPED, error_summary=skip_reason)
        log.info("亢龙有悔任务跳过：%s", skip_reason)
        return {"status": TaskStatus.SKIPPED, "trade_date": trade_date, "reason": skip_reason}
    if skip_reason:
        storage.finish_task_run(
            run_id, TaskStatus.SUCCESS, total=0, success=0,
            error=len(anomalies), error_summary=" | ".join(anomalies[:20]),
        )
        log.info("亢龙有悔任务完成：%s，结果 0 条", skip_reason)
        return {
            "status": TaskStatus.SUCCESS, "trade_date": trade_date,
            "new_kanglong": 0, "snapshot": "已生成 kanglong 快照，共 0 条",
            "signals": [], "anomalies": anomalies,
        }

    _, snap_status, written = _persist_kanglong(storage, cfg, trade_date, results)

    new_kl = storage.unnotified_transitions(
        trade_date, TaskName.KANGLONG, States.KANGLONG
    )
    subject, html, has = build_kanglong_email(trade_date, new_kl, snap_status, anomalies)
    _send_task_email(storage, cfg, send, "亢龙有悔", subject, html, has, new_kl)

    status = TaskStatus.PARTIAL if anomalies else TaskStatus.SUCCESS
    storage.finish_task_run(
        run_id, status, total=candidate_count, success=len(results),
        error=len(anomalies), error_summary=" | ".join(anomalies[:20]),
    )
    log.info("亢龙有悔任务完成：新增亢龙 %d，快照 %d 条", len(new_kl), written)
    return {
        "status": status, "trade_date": trade_date, "new_kanglong": len(new_kl),
        "snapshot": snap_status, "signals": _result_payload(results),
        "anomalies": anomalies,
    }


def _previous_kanglong_for_qianlong(
    storage: Storage, cfg: Config, trade_date: str, refresh: bool = False
) -> tuple[str | None, list, list[str], str | None]:
    """找到上一交易日并动态计算亢龙，最多向前探 10 个自然日。"""
    d = dt.date.fromisoformat(trade_date) - dt.timedelta(days=1)
    anomalies: list[str] = []
    checked = 0
    while checked < 10:
        if d.weekday() >= 5:
            d -= dt.timedelta(days=1)
            continue
        day = d.isoformat()
        if not refresh:
            cached_rows = _cached_signals(storage, day, SnapshotType.KANGLONG, States.KANGLONG)
            if cached_rows:
                log.info("命中上一交易日亢龙缓存 trade_date=%s，共 %d 条", day, len(cached_rows))
                return day, [
                    Candidate(
                        code=r["code"], name=r["name"], prev_state=States.KANGLONG,
                        prev_state_date=day, free_market_cap=r["free_market_cap"],
                        industry=r["industry"],
                    )
                    for r in cached_rows
                ], anomalies, None
            if _completed_task_run(storage, day, TaskName.KANGLONG):
                log.info("命中上一交易日亢龙空结果缓存 trade_date=%s", day)
                return day, [], anomalies, None
        try:
            results, a, skip_reason, _ = _collect_kanglong(cfg, day)
        except DataSourceError as e:
            anomalies.append(f"{day} 亢龙预计算失败：{e}")
            d -= dt.timedelta(days=1)
            checked += 1
            continue
        anomalies += a
        if skip_reason == "涨停股池为空，疑似非交易日":
            d -= dt.timedelta(days=1)
            checked += 1
            continue
        _persist_kanglong(storage, cfg, day, results)
        return day, results, anomalies, None
    return None, [], anomalies, "未找到上一交易日亢龙数据"


def _log_qianlong_candidates(kl_date: str | None, candidates: list) -> None:
    if not candidates:
        log.info("%s 亢龙候选池为空", kl_date or "上一交易日")
        return
    labels = []
    for c in candidates:
        code = getattr(c, "code", "")
        name = getattr(c, "name", "")
        labels.append(f"{code} {name}".strip())
    log.info("%s 亢龙候选 %d 只：%s", kl_date, len(candidates), "，".join(labels))


def _qianlong_checks(
    candidates: list[Candidate],
    auctions: dict[str, object | None],
    last_close: dict[str, float | None],
    last_volume: dict[str, float | None],
    cfg: Config,
) -> list[dict]:
    checks = []
    for c in candidates:
        row = {
            "code": c.code,
            "name": c.name,
            "industry": c.industry,
            "free_market_cap": c.free_market_cap,
            "quality": None,
        }
        au = auctions.get(c.code)
        lc = last_close.get(c.code)
        lv = last_volume.get(c.code)
        if au is None:
            row["reason"] = "09:25 竞价数据缺失"
            checks.append(row)
            continue
        row.update(
            {
                "auction_price": au.price,
                "auction_volume": au.volume,
                "auction_amount": au.amount,
                "last_close": lc,
                "last_volume": lv,
            }
        )
        if lc is None or lc == 0:
            row["reason"] = "昨日收盘价缺失或为 0"
            checks.append(row)
            continue
        if lv is None or lv == 0:
            row["reason"] = "昨日成交量缺失或为 0"
            checks.append(row)
            continue
        if au.price is None or au.volume is None:
            row["reason"] = "竞价价格或成交量缺失"
            checks.append(row)
            continue
        if c.free_market_cap is None:
            row["reason"] = "流通市值缺失，无法判定竞价标准"
            checks.append(row)
            continue

        gap = au.price / lc - 1.0
        ratio = au.volume / lv
        row["gap_open_pct"] = round(gap, 6)
        row["auction_ratio"] = round(ratio, 6)
        if gap < cfg.strategy.gap_open_threshold:
            row["reason"] = (
                f"高开 {gap * 100:.2f}% < "
                f"{cfg.strategy.gap_open_threshold * 100:.2f}%"
            )
            checks.append(row)
            continue

        is_small = c.free_market_cap < cfg.strategy.small_cap_threshold
        if is_small:
            if ratio > cfg.strategy.small_cap_auction_ratio_excellent:
                row["quality"] = "优质"
                row["reason"] = (
                    f"入选：小票竞价成交量占比 {ratio * 100:.2f}% > "
                    f"{cfg.strategy.small_cap_auction_ratio_excellent * 100:.2f}%"
                )
            elif ratio > cfg.strategy.small_cap_auction_ratio_qualified:
                row["quality"] = "合格"
                row["reason"] = (
                    f"入选：小票竞价成交量占比 {ratio * 100:.2f}% > "
                    f"{cfg.strategy.small_cap_auction_ratio_qualified * 100:.2f}%"
                )
            else:
                row["reason"] = (
                    f"小票竞价成交量占比 {ratio * 100:.2f}% <= "
                    f"{cfg.strategy.small_cap_auction_ratio_qualified * 100:.2f}%"
                )
        elif ratio > cfg.strategy.large_cap_auction_ratio_qualified:
            row["quality"] = "合格"
            row["reason"] = (
                f"入选：大票竞价成交量占比 {ratio * 100:.2f}% > "
                f"{cfg.strategy.large_cap_auction_ratio_qualified * 100:.2f}%"
            )
        else:
            row["reason"] = (
                f"大票竞价成交量占比 {ratio * 100:.2f}% <= "
                f"{cfg.strategy.large_cap_auction_ratio_qualified * 100:.2f}%"
            )
        checks.append(row)
    return checks


def run_qianlong_task(
    storage: Storage,
    cfg: Config,
    trade_date: str,
    send: bool = True,
    refresh: bool = False,
    latest_date: str | None = None,
    latest_now: dt.datetime | None = None,
) -> dict:
    apply_config(cfg.datasource)
    requested_date = trade_date
    trade_date = _nearest_weekday(trade_date)

    latest_trade_date, data_note = (
        (_nearest_weekday(latest_date), None)
        if latest_date
        else _latest_detail_trade_date(latest_now)
    )
    if trade_date > latest_trade_date:
        log.info(
            "输入日期 %s 的腾讯 3 秒成交明细暂未更新，已回退到 %s",
            trade_date, latest_trade_date,
        )
        trade_date = latest_trade_date
        data_note = data_note or f"腾讯 3 秒成交明细暂未更新，当前显示 {trade_date} 的潜龙数据"

    if not refresh:
        cached = _cached_result(
            storage, trade_date, SnapshotType.QIANLONG, States.QIANLONG,
            TaskName.QIANLONG, "new_qianlong",
        )
        if cached:
            cached["trade_date"] = trade_date
            if data_note:
                cached["data_note"] = data_note
            _send_cached_task_email(
                storage, cfg, send, "潜龙在渊", trade_date, TaskName.QIANLONG,
                States.QIANLONG, cached["snapshot"], cached.get("anomalies", []),
                build_qianlong_email,
            )
            return cached

    if trade_date != latest_trade_date:
        reason = (
            f"{trade_date} 潜龙历史回算暂不支持；仅支持最近交易日 "
            f"{latest_trade_date} 或已缓存日期"
        )
        log.info(reason)
        return {"status": TaskStatus.SKIPPED, "trade_date": trade_date, "reason": reason}

    run_id = storage.start_task_run(TaskName.QIANLONG, trade_date)
    anomalies: list[str] = []
    log.info("潜龙在渊任务开始 trade_date=%s", trade_date)
    if trade_date != requested_date:
        log.info("输入日期 %s 非交易日，已回退到最近交易日 %s", requested_date, trade_date)
    if data_note:
        log.info(data_note)

    kl_date, kanglong_results, a0, skip = _previous_kanglong_for_qianlong(
        storage, cfg, trade_date, refresh=refresh
    )
    anomalies += a0
    if skip:
        storage.finish_task_run(run_id, TaskStatus.SKIPPED, error_summary=skip)
        log.info("潜龙在渊任务跳过：%s", skip)
        return {"status": TaskStatus.SKIPPED, "trade_date": trade_date, "reason": skip}
    if not kanglong_results:
        reason = f"{kl_date} 无亢龙有悔股票，无需扫描"
        _log_qianlong_candidates(kl_date, kanglong_results)
        storage.finish_task_run(run_id, TaskStatus.SUCCESS, total=0, success=0)
        log.info("潜龙在渊任务完成：%s，结果 0 条", reason)
        return {
            "status": TaskStatus.SUCCESS, "trade_date": trade_date,
            "kanglong_date": kl_date, "new_qianlong": 0,
            "snapshot": "已生成 qianlong 快照，共 0 条",
            "signals": [], "anomalies": [], "data_note": data_note,
        }
    _log_qianlong_candidates(kl_date, kanglong_results)

    candidates = [
        Candidate(
            code=r.code, name=r.name, prev_state=States.KANGLONG,
            prev_state_date=kl_date,
            free_market_cap=(
                r.metrics.get("free_market_cap")
                if hasattr(r, "metrics") else r.free_market_cap
            ),
            industry=(r.metrics.get("industry") if hasattr(r, "metrics") else r.industry),
        )
        for r in kanglong_results
    ]

    auctions: dict[str, object | None] = {}
    last_close: dict[str, float | None] = {}
    last_volume: dict[str, float | None] = {}
    start, end = _window(trade_date)
    for c in candidates:
        auctions[c.code] = fetch_auction(c.code)
        try:
            bars = fetch_daily_hist(c.code, start, end)
            _, prev_b = _split_bars(bars, trade_date)
            last_close[c.code] = prev_b.close if prev_b else None
            last_volume[c.code] = prev_b.volume if prev_b else None
        except DataSourceError as e:
            anomalies.append(f"{c.code} 历史日 K 获取失败：{e}")
            last_close[c.code] = None
            last_volume[c.code] = None

    results, a1 = evaluate_qianlong(
        candidates, auctions, last_close, last_volume, cfg.strategy
    )
    anomalies += a1
    checks = _qianlong_checks(candidates, auctions, last_close, last_volume, cfg)
    storage.replace_qianlong_checks(
        trade_date, kl_date, checks, source="stock_zh_a_tick_tx_js"
    )

    new_codes: set[str] = set()
    for r in results:
        cur = storage.get_current(r.code)
        inserted = storage.record_transition(
            r.code, r.name, States.KANGLONG, States.QIANLONG,
            trade_date, TaskName.QIANLONG, r.reason, r.metrics,
        )
        if inserted:
            new_codes.add(r.code)
        m = r.metrics
        storage.upsert_current_state(
            code=r.code, name=r.name, state=States.QIANLONG, state_date=trade_date,
            previous_state=States.KANGLONG,
            previous_state_date=(cur["state_date"] if cur else None),
            free_market_cap=m.get("free_market_cap"), industry=m.get("industry"),
            last_close=m.get("last_close"), last_volume=m.get("last_volume"),
            auction_price=m.get("auction_price"),
            auction_volume=m.get("auction_volume"),
            auction_amount=m.get("auction_amount"),
            auction_ratio=m.get("auction_ratio"), gap_open_pct=m.get("gap_open_pct"),
            quality=m.get("quality"), reason=r.reason, source_date=trade_date,
        )

    snap_rows = [
        build_snapshot_row(
            trade_date=trade_date, state=States.QIANLONG, code=r.code,
            name=r.name, state_date=trade_date,
            is_new_state=r.code in new_codes, previous_state=States.KANGLONG,
            reason=r.reason, metrics=r.metrics, source="stock_zh_a_tick_tx_js",
        )
        for r in results
    ]
    snap_type, written = (SnapshotType.QIANLONG, 0)
    if cfg.snapshot.qianlong_enabled:
        snap_type, written = persist_snapshot(
            storage, cfg, trade_date, SnapshotType.QIANLONG, snap_rows
        )
    snap_status = (
        f"已生成 {snap_type} 快照，共 {written} 条"
        if cfg.snapshot.qianlong_enabled
        else "潜龙快照未启用"
    )

    new_ql = storage.unnotified_transitions(
        trade_date, TaskName.QIANLONG, States.QIANLONG
    )
    subject, html, has = build_qianlong_email(trade_date, new_ql, snap_status, anomalies)
    _send_task_email(storage, cfg, send, "潜龙在渊", subject, html, has, new_ql)

    status = TaskStatus.PARTIAL if anomalies else TaskStatus.SUCCESS
    storage.finish_task_run(
        run_id, status, total=len(candidates), success=len(results),
        error=len(anomalies), error_summary=" | ".join(anomalies[:20]),
    )
    log.info("潜龙在渊任务完成：新增潜龙 %d，快照 %d 条", len(new_ql), written)
    return {
        "status": status, "trade_date": trade_date, "kanglong_date": kl_date,
        "new_qianlong": len(new_ql), "snapshot": snap_status,
        "signals": _result_payload(results),
        "checks": checks,
        "data_note": data_note,
        "anomalies": anomalies,
    }
