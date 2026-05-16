"""ob 命令行入口。

只保留两个命令：

  ob kanglong  [--date] [--no-send]
  ob qianlong  [--date] [--no-send]
  ob collect   --from YYYY-MM-DD --to YYYY-MM-DD
  ob backtest  --from YYYY-MM-DD --to YYYY-MM-DD
  ob web       [--host] [--port]
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .storage import open_storage
from .tasks import run_kanglong_task, run_qianlong_task
from .tushare_cache import backtest_tushare_cache, collect_tushare_raw
from .webui import run_web_ui

app = typer.Typer(add_completion=False, help="A 股亢龙有悔 / 潜龙在渊识别系统")
console = Console()

_TODAY = dt.date.today().isoformat()


def _cap(v: object) -> str:
    return f"{v / 1e8:.2f}亿" if isinstance(v, (int, float)) else "-"


def _pct(v: object) -> str:
    return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else "-"


def _x(v: object) -> str:
    return f"{v:.2f}倍" if isinstance(v, (int, float)) else "-"


def _cell(v: object) -> str:
    if v is None or v == "":
        return "-"
    s = str(v)
    return s if len(s) <= 80 else s[:77] + "..."


def _print_result(result: dict, title: str) -> None:
    console.print(
        {
            k: v
            for k, v in result.items()
            if k not in {"signals", "checks"} and (k != "anomalies" or v)
        }
    )
    rows = result.get("signals") or []
    if not rows:
        checks = result.get("checks") or []
        if checks:
            _print_qianlong_checks(checks, f"{title} 候选检查")
        return

    is_qianlong = any(r.get("state") == "潜龙在渊" for r in rows)
    table = Table(title=title, header_style="bold cyan", show_lines=False)
    if is_qianlong:
        for col in ["代码", "名称", "行业", "流通市值", "高开", "竞价占比", "评级", "原因"]:
            table.add_column(col)
        for r in rows:
            table.add_row(
                _cell(r.get("code")),
                _cell(r.get("name")),
                _cell(r.get("industry")),
                _cap(r.get("free_market_cap")),
                _pct(r.get("gap_open_pct")),
                _pct(r.get("auction_ratio")),
                _cell(r.get("quality")),
                _cell(r.get("reason")),
            )
    else:
        for col in ["代码", "名称", "行业", "原连板", "流通市值", "放量", "原因"]:
            table.add_column(col)
        for r in rows:
            table.add_row(
                _cell(r.get("code")),
                _cell(r.get("name")),
                _cell(r.get("industry")),
                _cell(r.get("prev_lianban_count")),
                _cap(r.get("free_market_cap")),
                _x(r.get("volume_ratio")),
                _cell(r.get("reason")),
            )
    console.print(table)

    checks = result.get("checks") or []
    if checks:
        _print_qianlong_checks(checks, f"{title} 候选检查")


def _print_qianlong_checks(rows: list[dict], title: str) -> None:
    table = Table(title=title, header_style="bold magenta", show_lines=False)
    for col in ["代码", "名称", "流通市值", "竞价价", "昨收", "高开", "竞价占比", "评级", "结果"]:
        table.add_column(col)
    for r in rows:
        table.add_row(
            _cell(r.get("code")),
            _cell(r.get("name")),
            _cap(r.get("free_market_cap")),
            _cell(r.get("auction_price")),
            _cell(r.get("last_close")),
            _pct(r.get("gap_open_pct")),
            _pct(r.get("auction_ratio")),
            _cell(r.get("quality")),
            _cell(r.get("reason")),
        )
    console.print(table)


def _print_backtest_summary(result: dict) -> None:
    console.print({k: v for k, v in result.items() if k != "summary"})
    rows = result.get("summary") or []
    if not rows:
        return
    table = Table(title="历史回测摘要", header_style="bold green", show_lines=False)
    for col in ["日期", "亢龙", "潜龙", "异常", "缓存"]:
        table.add_column(col)
    for r in rows:
        table.add_row(
            _cell(r.get("trade_date")),
            _cell(r.get("kanglong")),
            _cell(r.get("qianlong")),
            _cell(r.get("anomalies")),
            "是" if r.get("cached") else "-",
        )
    console.print(table)


@app.command("kanglong")
def run_kanglong(
    date: str = typer.Option(_TODAY, "--date", "-d", help="交易日 YYYY-MM-DD"),
    no_send: bool = typer.Option(False, "--no-send", help="不发送邮件"),
    refresh: bool = typer.Option(False, "--refresh", help="忽略缓存，重新查询数据源"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """亢龙有悔：用昨日涨停连板数据生成候选，再用当日数据判断。"""
    cfg = load_config(config)
    with open_storage(cfg.storage.db_path) as st:
        result = run_kanglong_task(st, cfg, date, send=not no_send, refresh=refresh)
    _print_result(result, f"{result.get('trade_date', date)} 亢龙有悔")


@app.command("qianlong")
def run_qianlong(
    date: str = typer.Option(_TODAY, "--date", "-d", help="交易日 YYYY-MM-DD"),
    no_send: bool = typer.Option(False, "--no-send", help="不发送邮件"),
    refresh: bool = typer.Option(False, "--refresh", help="忽略缓存，重新查询数据源"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """潜龙在渊：支持已缓存日期；未缓存历史日期暂不回算。"""
    cfg = load_config(config)
    with open_storage(cfg.storage.db_path) as st:
        result = run_qianlong_task(st, cfg, date, send=not no_send, refresh=refresh)
    _print_result(result, f"{result.get('trade_date', date)} 潜龙在渊")


@app.command("collect")
def collect(
    from_date: str = typer.Option(..., "--from", help="开始日期 YYYY-MM-DD"),
    to_date: str = typer.Option(..., "--to", help="结束日期 YYYY-MM-DD"),
    refresh: bool = typer.Option(False, "--refresh", help="忽略 JSONL 缓存，重新请求"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """采集必要 Tushare 原始数据到 JSONL。"""
    cfg = load_config(config)
    result = collect_tushare_raw(cfg, from_date, to_date, refresh=refresh)
    console.print(result)


@app.command("backtest")
def backtest(
    from_date: str = typer.Option(..., "--from", help="开始日期 YYYY-MM-DD"),
    to_date: str = typer.Option(..., "--to", help="结束日期 YYYY-MM-DD"),
    refresh: bool = typer.Option(False, "--refresh", help="忽略已生成快照，重新回算"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """只读本地 Tushare JSONL，回算历史亢龙/潜龙并写快照。"""
    cfg = load_config(config)
    with open_storage(cfg.storage.db_path) as st:
        result = backtest_tushare_cache(st, cfg, from_date, to_date, refresh=refresh)
    _print_backtest_summary(result)


@app.command("web")
def web(
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址"),
    port: int = typer.Option(8000, "--port", help="监听端口"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """启动本地 WebUI，展示已保存的快照、任务记录和原始缓存。"""
    cfg = load_config(config)
    console.print(f"WebUI 已启动：http://{host}:{port}")
    run_web_ui(cfg, host, port)


if __name__ == "__main__":
    app()
