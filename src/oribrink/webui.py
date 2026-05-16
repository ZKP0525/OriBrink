"""轻量 WebUI：按状态时序展示 SQLite 中保存的亢龙/潜龙结果。"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
import urllib.parse

from .config import Config
from .models import SnapshotType, States, TaskName
from .storage import Storage


def _h(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _fmt_num(value: object, digits: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:.{digits}f}"


def _fmt_cap(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value / 1e8:.2f}亿"


def _fmt_pct(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value * 100:.2f}%"


def _badge(value: object, kind: str = "neutral") -> str:
    return f"<span class='badge {kind}'>{_h(value)}</span>"


def _date_bounds(storage: Storage) -> tuple[str | None, str | None]:
    row = storage.conn.execute(
        """
        SELECT MIN(d) AS start, MAX(d) AS end FROM (
          SELECT trade_date AS d FROM daily_state_snapshot
          UNION
          SELECT trade_date AS d FROM task_run_history
        )
        """
    ).fetchone()
    return (row["start"], row["end"]) if row else (None, None)


def _latest_runs(storage: Storage, start: str, end: str) -> dict[tuple[str, str], dict]:
    rows = storage.conn.execute(
        """
        SELECT * FROM task_run_history
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY id ASC
        """,
        (start, end),
    ).fetchall()
    latest: dict[tuple[str, str], dict] = {}
    for row in rows:
        r = dict(row)
        latest[(r["trade_date"], r["task_name"])] = r
    return latest


def _snapshot_counts(storage: Storage, start: str, end: str) -> dict[tuple[str, str], int]:
    rows = storage.conn.execute(
        """
        SELECT trade_date, snapshot_type, COUNT(*) AS n
        FROM daily_state_snapshot
        WHERE trade_date BETWEEN ? AND ?
          AND snapshot_type IN (?, ?)
        GROUP BY trade_date, snapshot_type
        """,
        (start, end, SnapshotType.KANGLONG, SnapshotType.QIANLONG),
    ).fetchall()
    return {(r["trade_date"], r["snapshot_type"]): int(r["n"]) for r in rows}


def _check_counts(storage: Storage, start: str, end: str) -> dict[str, int]:
    rows = storage.conn.execute(
        """
        SELECT trade_date, COUNT(*) AS n
        FROM qianlong_candidate_check
        WHERE trade_date BETWEEN ? AND ?
        GROUP BY trade_date
        """,
        (start, end),
    ).fetchall()
    return {r["trade_date"]: int(r["n"]) for r in rows}


def _summaries(storage: Storage, start: str, end: str) -> list[dict]:
    counts = _snapshot_counts(storage, start, end)
    check_counts = _check_counts(storage, start, end)
    runs = _latest_runs(storage, start, end)
    dates = {
        *[d for d, _ in counts],
        *[d for d, _ in runs],
    }
    base = []
    for date in sorted(dates):
        kl_run = runs.get((date, TaskName.KANGLONG))
        ql_run = runs.get((date, TaskName.QIANLONG))
        kl = counts.get((date, SnapshotType.KANGLONG))
        ql = counts.get((date, SnapshotType.QIANLONG))
        base.append(
            {
                "trade_date": date,
                "today_kanglong": kl if kl is not None else (kl_run or {}).get("success_count", 0),
                "today_qianlong": ql if ql is not None else (ql_run or {}).get("success_count", 0),
                "kanglong_status": (kl_run or {}).get("status", "-"),
                "qianlong_status": (ql_run or {}).get("status", "-"),
                "errors": int((kl_run or {}).get("error_count") or 0)
                + int((ql_run or {}).get("error_count") or 0),
                "check_count": check_counts.get(date),
            }
        )
    by_date = {r["trade_date"]: r for r in base}
    for i, row in enumerate(base):
        prev = base[i - 1] if i > 0 else None
        prev_count = int((prev or {}).get("today_kanglong") or 0)
        today_qianlong = int(row.get("today_qianlong") or 0)
        check_count = row.get("check_count")
        candidate_count = int(check_count) if check_count is not None else prev_count
        row["prev_date"] = (prev or {}).get("trade_date")
        row["yesterday_kanglong"] = prev_count
        row["failed_kanglong"] = max(candidate_count - today_qianlong, 0)
        by_date[row["trade_date"]] = row
    return base


def _table(headers: list[str], rows: list[list[Any]], empty: str = "暂无数据") -> str:
    if not rows:
        return f"<p class='empty'>{_h(empty)}</p>"
    head = "".join(f"<th>{_h(h)}</th>" for h in headers)
    body = "\n".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _filter_summaries(rows: list[dict], mode: str) -> list[dict]:
    if mode == "qianlong":
        return [r for r in rows if int(r.get("today_qianlong") or 0) > 0]
    if mode == "kanglong":
        return [r for r in rows if int(r.get("today_kanglong") or 0) > 0]
    if mode == "failed":
        return [r for r in rows if int(r.get("failed_kanglong") or 0) > 0]
    if mode in ("signal", "event"):
        return [
            r
            for r in rows
            if int(r.get("today_qianlong") or 0) > 0
            or int(r.get("today_kanglong") or 0) > 0
            or int(r.get("failed_kanglong") or 0) > 0
        ]
    return rows


def _summary_table(
    rows: list[dict], selected_date: str | None, start: str, end: str, mode: str
) -> str:
    table_rows = []
    card_rows = []
    for r in reversed(rows):
        date = r["trade_date"]
        url = (
            f"/?start={urllib.parse.quote(start)}&end={urllib.parse.quote(end)}"
            f"&mode={urllib.parse.quote(mode)}&date={date}"
        )
        cls = " class='selected'" if date == selected_date else ""
        qianlong = int(r["today_qianlong"] or 0)
        today_kanglong = int(r["today_kanglong"] or 0)
        failed = int(r["failed_kanglong"] or 0)
        table_rows.append(
            [
                f"<a{cls} href='{_h(url)}'>{_h(date)}</a>",
                _h(r["yesterday_kanglong"]),
                _badge(qianlong, "success" if qianlong else "neutral"),
                _badge(failed, "failed" if failed else "neutral"),
                _badge(today_kanglong, "watch" if today_kanglong else "neutral"),
                _h(r["errors"]),
            ]
        )
        card_cls = " summary-card selected" if date == selected_date else " summary-card"
        card_rows.append(
            f"""
            <a class='{card_cls}' href='{_h(url)}'>
              <span class='summary-card-date'>{_h(date)}</span>
              <span class='summary-card-grid'>
                <span class='metric prev'><b>{_h(r["yesterday_kanglong"])}</b><em>昨日亢龙</em></span>
                <span class='metric qianlong'><b>{qianlong}</b><em>今日潜龙</em></span>
                <span class='metric failed'><b>{failed}</b><em>失败</em></span>
                <span class='metric kanglong'><b>{today_kanglong}</b><em>今日亢龙</em></span>
              </span>
            </a>
            """
        )
    return (
        "<div class='summary-scroll'>"
        + _table(["日期", "昨日亢龙", "今日潜龙", "失败亢龙", "今日亢龙", "异常"], table_rows)
        + "</div><div class='summary-cards'>"
        + "".join(card_rows)
        + "</div>"
    )


def _kanglong_rows(rows: list[dict]) -> list[list[str]]:
    return [
        [
            _h(r.get("code")),
            _h(r.get("name")),
            _h(r.get("industry")),
            _h(r.get("lianban_count") or "-"),
            _fmt_cap(r.get("free_market_cap")),
            f"{_fmt_num(r.get('volume_ratio'))}倍" if r.get("volume_ratio") is not None else "-",
            _h(r.get("reason")),
        ]
        for r in rows
    ]


def _qianlong_rows(rows: list[dict]) -> list[list[str]]:
    return [
        [
            _h(r.get("code")),
            _h(r.get("name")),
            _h(r.get("industry")),
            _fmt_cap(r.get("free_market_cap")),
            _fmt_pct(r.get("gap_open_pct")),
            _fmt_pct(r.get("auction_ratio")),
            _badge(r.get("quality") or "-", "success" if r.get("quality") else "neutral"),
            _h(r.get("reason")),
        ]
        for r in rows
    ]


def _failed_rows(rows: list[dict], prev_kanglong: list[dict]) -> list[list[str]]:
    prev_by_code = {r.get("code"): r for r in prev_kanglong}
    return [
        [
            _h(r.get("code")),
            _h(r.get("name")),
            _h(r.get("industry")),
            _fmt_cap(r.get("free_market_cap")),
            f"{_fmt_num(prev_by_code.get(r.get('code'), {}).get('volume_ratio'))}倍"
            if prev_by_code.get(r.get("code"), {}).get("volume_ratio") is not None else "-",
            _h(prev_by_code.get(r.get("code"), {}).get("reason") or "-"),
            _fmt_pct(r.get("gap_open_pct")),
            _fmt_pct(r.get("auction_ratio")),
            _h(r.get("reason") or "未进化为潜龙"),
        ]
        for r in rows
    ]


def _fallback_failed(prev_kanglong: list[dict], today_qianlong: list[dict]) -> list[dict]:
    qianlong_codes = {r["code"] for r in today_qianlong}
    return [
        {
            "code": r.get("code"),
            "name": r.get("name"),
            "industry": r.get("industry"),
            "free_market_cap": r.get("free_market_cap"),
            "reason": "未进化为潜龙",
        }
        for r in prev_kanglong
        if r.get("code") not in qianlong_codes
    ]


STYLE = """
html,body{height:100%;overflow:hidden}
:root{--bg:#f7f9fc;--panel:#fff;--ink:#121826;--muted:#667085;--line:#e4e9f2;--soft:#f1f5fb;--blue:#2463eb;--blue-dark:#1d4ed8;--shadow:0 12px 32px rgba(18,24,38,.06)}
body{margin:0;background:linear-gradient(180deg,#fbfdff 0,#f5f8fc 240px,var(--bg) 100%);color:var(--ink);font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;display:grid;grid-template-rows:auto 1fr}
header{background:rgba(255,255,255,.86);border-bottom:1px solid var(--line);backdrop-filter:blur(12px);padding:14px 24px}
header h1{margin:0;font-size:18px;font-weight:760;letter-spacing:0}
main{min-height:0;padding:18px 24px;display:grid;grid-template-columns:minmax(500px,640px) minmax(0,1fr);grid-template-rows:auto 1fr;gap:18px;overflow:hidden}
section{background:rgba(255,255,255,.92);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:var(--shadow)}
h2{font-size:18px;margin:0 0 14px;font-weight:760;letter-spacing:0}
h3{font-size:14px;margin:20px 0 10px;color:#344054;font-weight:720}
ul{margin:8px 0 0 18px;padding:0;color:#344054;font-size:13px;line-height:1.75}
form{display:grid;grid-template-columns:minmax(112px,1fr) minmax(112px,1fr) minmax(96px,.72fr) 72px;gap:10px;align-items:end;margin-bottom:16px}
label{min-width:0;font-size:12px;color:var(--muted);display:grid;gap:7px;font-weight:650}
input,select{box-sizing:border-box;width:100%;min-width:0;height:42px;border:1px solid #cbd5e1;border-radius:12px;padding:0 12px;background:#fff;color:var(--ink);font-size:15px;outline:none;box-shadow:0 1px 0 rgba(18,24,38,.02)}
input:focus,select:focus{border-color:#8db2ff;box-shadow:0 0 0 4px rgba(36,99,235,.12)}
button{width:72px;height:42px;border:0;border-radius:12px;background:var(--blue);color:white;padding:0 12px;font-weight:760;font-size:15px;box-shadow:0 8px 18px rgba(36,99,235,.22);cursor:pointer}
button:hover{background:var(--blue-dark)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border-bottom:1px solid #edf1f6;padding:9px 10px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:700;background:#fbfcfe}
.summary-panel{min-height:0;overflow:hidden;display:flex;flex-direction:column}
.summary-scroll{min-height:0;overflow:auto;border:1px solid var(--line);border-radius:12px;background:white}
.summary-scroll table{border-collapse:separate;border-spacing:0}
.summary-scroll thead th{position:sticky;top:0;z-index:1}
.summary-cards{display:none}
a{color:var(--blue-dark);text-decoration:none}
a.selected{font-weight:700;color:#111827}
.muted,.empty{color:var(--muted);font-size:13px}
.detail{min-height:0;overflow:auto}
.detail section{min-height:min-content}
.wide{overflow:auto;border:1px solid var(--line);border-radius:12px;background:white}
.wide table{min-width:720px}
.wide td:last-child{max-width:560px}
.rule{grid-column:1 / -1}
.rule ul{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px 22px}
.split{height:1px;background:var(--line);margin:20px 0}
.chain-note{color:var(--muted);font-size:13px;margin:0 0 12px}
.badge{display:inline-block;min-width:22px;text-align:center;border-radius:999px;padding:3px 9px;font-weight:760;font-size:12px}
.badge.neutral{background:#eef1f5;color:#475467}
.badge.success{background:#dcfce7;color:#166534}
.badge.failed{background:#fee2e2;color:#991b1b}
.badge.watch{background:#fef3c7;color:#92400e}
@media(max-width:980px){
html,body{height:auto;min-height:100%;overflow:auto}
body{display:block}
header{position:sticky;top:0;z-index:10;padding:12px 14px}
header h1{font-size:16px}
main{display:block;padding:12px;overflow:visible}
section{border-radius:14px;padding:14px;box-shadow:0 8px 22px rgba(18,24,38,.05);margin-bottom:12px}
h2{font-size:16px;margin-bottom:10px}
h3{font-size:14px;margin:16px 0 8px}
ul{font-size:12px;line-height:1.65;margin-left:16px}
.rule ul{grid-template-columns:1fr}
form{grid-template-columns:1fr 1fr;gap:9px;margin-bottom:12px}
label{font-size:11px;gap:5px}
input,select{height:40px;border-radius:10px;font-size:14px;padding:0 10px}
button{width:100%}
.summary-panel{display:block;overflow:visible}
.summary-scroll{display:none}
.summary-cards{display:grid;grid-template-columns:1fr;gap:8px;max-height:46vh;overflow:auto;padding-right:2px}
.summary-card{display:block;border:1px solid var(--line);border-radius:12px;background:#fff;padding:10px 11px;color:var(--ink)}
.summary-card.selected{border-color:#8db2ff;box-shadow:0 0 0 3px rgba(36,99,235,.10)}
.summary-card-date{display:block;font-size:15px;font-weight:780;margin-bottom:8px;color:var(--blue-dark)}
.summary-card-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
.summary-card-grid .metric{display:grid;gap:3px;min-width:0;border-radius:12px;padding:8px 9px;background:#f3f6fa}
.summary-card-grid b{font-size:16px;line-height:1;color:var(--ink)}
.summary-card-grid em{font-style:normal;font-size:10px;color:var(--muted);white-space:nowrap}
.summary-card-grid .prev{background:#eef4ff}
.summary-card-grid .prev b{color:#1d4ed8}
.summary-card-grid .qianlong{background:#dcfce7}
.summary-card-grid .qianlong b{color:#166534}
.summary-card-grid .failed{background:#fee2e2}
.summary-card-grid .failed b{color:#991b1b}
.summary-card-grid .kanglong{background:#fef3c7}
.summary-card-grid .kanglong b{color:#92400e}
.detail{overflow:visible}
.detail section{padding-bottom:18px}
.wide{margin-left:-2px;margin-right:-2px;border-radius:10px}
.wide table{min-width:640px;font-size:12px}
th,td{padding:8px 8px}
.badge{min-width:18px;padding:2px 7px;font-size:11px}
@media(max-width:430px){
form{grid-template-columns:1fr}
button{height:40px}
.summary-card-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.wide table{min-width:600px}
}
}
"""


def _mode_options(mode: str) -> str:
    labels = {
        "event": "有事件",
        "all": "全部",
        "qianlong": "有潜龙",
        "failed": "有失败",
        "kanglong": "有亢龙",
    }
    if mode == "signal":
        mode = "event"
    return "".join(
        f"<option value='{_h(value)}'{' selected' if value == mode else ''}>{_h(label)}</option>"
        for value, label in labels.items()
    )


def _default_selected(summaries: list[dict]) -> str:
    for row in reversed(summaries):
        if int(row.get("today_qianlong") or 0) > 0:
            return row["trade_date"]
    for row in reversed(summaries):
        if int(row.get("today_kanglong") or 0) > 0:
            return row["trade_date"]
    return summaries[-1]["trade_date"] if summaries else ""


def render_dashboard(storage: Storage, cfg: Config, query: dict[str, list[str]]) -> str:
    min_date, max_date = _date_bounds(storage)
    start = (query.get("start") or [min_date or ""])[0]
    end = (query.get("end") or [max_date or ""])[0]
    summaries = _summaries(storage, start, end) if start and end else []
    mode = (query.get("mode") or ["all"])[0]
    visible_summaries = _filter_summaries(summaries, mode)
    summary_by_date = {r["trade_date"]: r for r in summaries}
    selected_date = (query.get("date") or [_default_selected(visible_summaries or summaries)])[0]
    prev_date = summary_by_date.get(selected_date, {}).get("prev_date")
    yesterday_kanglong = (
        storage.query_snapshot(prev_date, States.KANGLONG, SnapshotType.KANGLONG)
        if prev_date else []
    )
    today_qianlong = storage.query_snapshot(selected_date, States.QIANLONG, SnapshotType.QIANLONG)
    checks = storage.query_qianlong_checks(selected_date, prev_date) if selected_date else []
    failed_checks = [r for r in checks if not r.get("passed")]
    if not failed_checks:
        failed_checks = _fallback_failed(yesterday_kanglong, today_qianlong)
    today_kanglong = storage.query_snapshot(selected_date, States.KANGLONG, SnapshotType.KANGLONG)

    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>oribrink WebUI</title><style>{STYLE}</style></head>
<body>
<header><h1>oribrink 数据看板</h1></header>
<main>
  <section class="rule">
    <h2>筛选规则</h2>
    <ul>
      <li>状态时序：T-1 飞龙在天 → T 亢龙有悔 → T+1 潜龙在渊。</li>
      <li>亢龙有悔：昨日连板数 ≥ {cfg.strategy.min_lianban_count}，今日出现炸板未回封或烂板回封，且今日成交量 / 昨日成交量 ≥ {cfg.strategy.volume_ratio_threshold}。</li>
      <li>潜龙在渊：昨日亢龙，今日集合竞价高开 ≥ {_fmt_pct(cfg.strategy.gap_open_threshold)}；小票竞价量占比 &gt; {_fmt_pct(cfg.strategy.small_cap_auction_ratio_qualified)} 合格、&gt; {_fmt_pct(cfg.strategy.small_cap_auction_ratio_excellent)} 优质；大票 &gt; {_fmt_pct(cfg.strategy.large_cap_auction_ratio_qualified)} 合格。</li>
    </ul>
  </section>
  <section class="summary-panel">
    <h2>历史摘要</h2>
    <form method="get">
      <label>开始日期<input name="start" value="{_h(start)}" placeholder="YYYY-MM-DD"></label>
      <label>结束日期<input name="end" value="{_h(end)}" placeholder="YYYY-MM-DD"></label>
      <label>筛选<select name="mode">{_mode_options(mode)}</select></label>
      <button type="submit">查看</button>
    </form>
    {_summary_table(visible_summaries, selected_date, start, end, mode) if visible_summaries else "<p class='empty'>暂无匹配日期</p>"}
  </section>
  <div class="detail">
    <section>
      <h2>{_h(selected_date or "未选择日期")} 进化链路</h2>
      <p class="chain-note">昨日亢龙是今日潜龙候选；今日亢龙是明日潜龙候选。</p>
      <h3>{_h(prev_date or "-")} 昨日亢龙</h3>
      <div class="wide">{_table(["代码","名称","行业","原连板","流通市值","放量","原因"], _kanglong_rows(yesterday_kanglong))}</div>
      <h3>{_h(selected_date)} 今日潜龙</h3>
      <div class="wide">{_table(["代码","名称","行业","流通市值","高开","竞价占比","评级","原因"], _qianlong_rows(today_qianlong))}</div>
      <h3>进化失败的亢龙</h3>
      <div class="wide">{_table(["代码","名称","行业","流通市值","昨日放量","昨日亢龙原因","高开","竞价占比","今日检查"], _failed_rows(failed_checks, yesterday_kanglong))}</div>
      <div class="split"></div>
      <h3>{_h(selected_date)} 今日亢龙</h3>
      <div class="wide">{_table(["代码","名称","行业","原连板","流通市值","放量","原因"], _kanglong_rows(today_kanglong))}</div>
    </section>
  </div>
</main>
</body></html>"""


def make_handler(cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            query = urllib.parse.parse_qs(parsed.query)
            with Storage(cfg.storage.db_path) as storage:
                body = render_dashboard(storage, cfg, query).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    return Handler


def run_web_ui(cfg: Config, host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(cfg))
    try:
        server.serve_forever()
    finally:
        server.server_close()
