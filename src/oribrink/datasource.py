"""AkShare 数据源模块（深模块）。

对外暴露简单接口，内部隐藏 AkShare 的字段差异、时间/日期格式、空数据与异常。
- 原始抓取函数 ``_raw_*`` 单独封装，方便测试 monkeypatch；
- 标准化函数 ``normalize_*`` 为纯函数，吃 DataFrame 吐领域对象，可离线单测。
"""

from __future__ import annotations

import datetime as dt
import math
import time
from typing import Any, Callable

from .logging import get_logger
from .models import AuctionData, DailyBar, ZbRow, ZtRow

log = get_logger("datasource")


class DataSourceError(RuntimeError):
    """数据源相关异常（接口失败、字段缺失等），不静默吞掉。"""


# --------------------------------------------------------------------------- #
# 日期 / 时间 / 数值 标准化
# --------------------------------------------------------------------------- #
def to_akshare_date(date: str) -> str:
    """``YYYY-MM-DD`` 或 ``YYYYMMDD`` -> ``YYYYMMDD``。"""
    s = str(date).strip()
    return s.replace("-", "") if "-" in s else s


def to_iso_date(date: str) -> str:
    """``YYYYMMDD`` 或 ``YYYY-MM-DD`` -> ``YYYY-MM-DD``。"""
    s = str(date).strip()
    if "-" in s:
        return s[:10]
    if len(s) >= 8:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    raise ValueError(f"无法解析日期: {date!r}")


def normalize_time(value: Any) -> str | None:
    """把封板时间标准化为 ``HH:MM:SS``。

    兼容 ``"09:25:00"`` / ``"092500"`` / ``141354`` / ``93000`` / ``93000.0``，
    以及带日期前缀的 ``"2026-05-15 09:25:00"`` / ``"2026-05-15T09:25:00"``。
    空或异常返回 None。
    """
    if value is None:
        return None
    s = str(value).strip()
    if s.lower() in ("", "nan", "none", "nat", "-", "0", "0.0", "00:00:00"):
        return None
    # 去掉日期前缀，只留时间部分
    if " " in s:
        s = s.split(" ")[-1]
    elif "T" in s and "-" in s:
        s = s.split("T")[-1]
    if ":" in s:
        parts = [p for p in s.split(":") if p != ""]
        try:
            nums = [int(float(p)) for p in parts]
        except ValueError:
            log.warning("无法解析时间字段: %r", value)
            return None
        while len(nums) < 3:
            nums.append(0)
        h, m, sec = nums[:3]
        return f"{h:02d}:{m:02d}:{sec:02d}"
    if s.endswith(".0"):
        s = s[:-2]
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits or len(digits) > 6:
        log.warning("无法解析时间字段: %r", value)
        return None
    digits = digits.zfill(6)
    return f"{digits[0:2]}:{digits[2:4]}:{digits[4:6]}"


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    s = str(value).strip()
    return s == "" or s.lower() in ("nan", "none", "-", "--")


def _num(value: Any) -> float | None:
    """转 float，失败/缺失返回 None。容忍千分位逗号与百分号。"""
    if _is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def _pick(row: dict, *names: str) -> Any:
    """按候选列名取第一个存在的值（应对 AkShare 字段改名）。"""
    for n in names:
        if n in row:
            return row[n]
    return None


def _records(df: Any) -> list[dict]:
    """DataFrame -> list[dict]，空表返回 []。"""
    if df is None:
        return []
    if hasattr(df, "empty"):
        if df.empty:
            return []
        return df.to_dict("records")
    return list(df)


# --------------------------------------------------------------------------- #
# 纯标准化函数（可离线单测）
# --------------------------------------------------------------------------- #
def normalize_zt_pool(df: Any) -> list[ZtRow]:
    rows: list[ZtRow] = []
    for r in _records(df):
        code = _pick(r, "代码", "股票代码")
        if _is_missing(code):
            continue
        rows.append(
            ZtRow(
                code=str(code).strip().zfill(6),
                name=str(_pick(r, "名称", "股票简称") or "").strip(),
                pct_change=_num(_pick(r, "涨跌幅")),
                latest_price=_num(_pick(r, "最新价")),
                amount=_num(_pick(r, "成交额")),
                free_market_cap=_num(_pick(r, "流通市值")),
                total_market_cap=_num(_pick(r, "总市值")),
                turnover_rate=_num(_pick(r, "换手率")),
                seal_amount=_num(_pick(r, "封板资金")),
                first_limit_time=normalize_time(_pick(r, "首次封板时间", "昨日封板时间")),
                last_limit_time=normalize_time(_pick(r, "最后封板时间", "昨日封板时间")),
                break_board_count=_int(_pick(r, "炸板次数")),
                lianban_count=_int(_pick(r, "连板数", "昨日连板数")),
                industry=(str(_pick(r, "所属行业")).strip() or None)
                if not _is_missing(_pick(r, "所属行业"))
                else None,
            )
        )
    return rows


def normalize_zbgc_pool(df: Any) -> list[ZbRow]:
    rows: list[ZbRow] = []
    for r in _records(df):
        code = _pick(r, "代码", "股票代码")
        if _is_missing(code):
            continue
        rows.append(
            ZbRow(
                code=str(code).strip().zfill(6),
                name=str(_pick(r, "名称", "股票简称") or "").strip(),
                pct_change=_num(_pick(r, "涨跌幅")),
                latest_price=_num(_pick(r, "最新价")),
                limit_price=_num(_pick(r, "涨停价")),
                amount=_num(_pick(r, "成交额")),
                free_market_cap=_num(_pick(r, "流通市值")),
                total_market_cap=_num(_pick(r, "总市值")),
                turnover_rate=_num(_pick(r, "换手率")),
                first_limit_time=normalize_time(_pick(r, "首次封板时间")),
                break_board_count=_int(_pick(r, "炸板次数")),
                amplitude=_num(_pick(r, "振幅")),
                industry=(str(_pick(r, "所属行业")).strip() or None)
                if not _is_missing(_pick(r, "所属行业"))
                else None,
            )
        )
    return rows


def normalize_daily_hist(df: Any) -> list[DailyBar]:
    bars: list[DailyBar] = []
    for r in _records(df):
        date = _pick(r, "日期", "date")
        if _is_missing(date):
            continue
        bars.append(
            DailyBar(
                date=to_iso_date(str(date).replace("/", "-")),
                code=str(_pick(r, "股票代码", "代码") or "").strip().zfill(6),
                open=_num(_pick(r, "开盘")),
                close=_num(_pick(r, "收盘")),
                high=_num(_pick(r, "最高")),
                low=_num(_pick(r, "最低")),
                volume=_num(_pick(r, "成交量")),  # 东财: 手
                amount=_num(_pick(r, "成交额")),
                amplitude=_num(_pick(r, "振幅")),
                pct_change=_num(_pick(r, "涨跌幅")),
                change=_num(_pick(r, "涨跌额")),
                turnover_rate=_num(_pick(r, "换手率")),
            )
        )
    bars.sort(key=lambda b: b.date)
    return bars


def normalize_daily_hist_tx(df: Any, code: str) -> list[DailyBar]:
    """腾讯回退源标准化（英文列）。

    腾讯 ``amount`` 为成交量，当前 AkShare 返回口径与成交明细 ``成交量`` 一致，
    均按「手」处理，竞价量占比才正确。
    """
    bars: list[DailyBar] = []
    for r in _records(df):
        date = _pick(r, "date", "日期")
        if _is_missing(date):
            continue
        volume = _num(_pick(r, "amount", "成交量"))
        bars.append(
            DailyBar(
                date=to_iso_date(str(date).replace("/", "-")),
                code=str(code).strip().zfill(6),
                open=_num(_pick(r, "open")),
                close=_num(_pick(r, "close")),
                high=_num(_pick(r, "high")),
                low=_num(_pick(r, "low")),
                volume=volume,
            )
        )
    bars.sort(key=lambda b: b.date)
    return bars


def normalize_auction(df: Any, code: str) -> AuctionData | None:
    """取腾讯 3 秒成交明细中 09:25 的集合竞价成交量与价格。"""
    target = None
    for r in _records(df):
        t = normalize_time(_pick(r, "成交时间"))
        if t is not None and t.startswith("09:25:"):
            target = r
            break
    if target is None:
        log.warning("股票 %s 缺失 09:25 竞价数据，跳过升级", code)
        return None
    return AuctionData(
        code=str(code).strip().zfill(6),
        time=normalize_time(_pick(target, "成交时间")),
        price=_num(_pick(target, "成交价格")),
        volume=_num(_pick(target, "成交量")),
        amount=_num(_pick(target, "成交金额")),
    )


# --------------------------------------------------------------------------- #
# 原始抓取（lazy import akshare；测试可 monkeypatch 这些 _raw_* 函数）
# --------------------------------------------------------------------------- #
def _akshare():
    try:
        import akshare as ak  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - 取决于运行环境
        raise DataSourceError(
            "未安装 akshare。运行采集任务需要：uv sync"
        ) from e
    return ak


# 可被配置覆盖的运行期设置（apply_config 注入；默认与 DataSourceConfig 一致）
_SETTINGS = {"attempts": 2, "backoff": 1.0, "interval": 0.3}


def apply_config(ds_cfg) -> None:
    """把 [datasource] 配置注入数据源运行期设置。"""
    _SETTINGS["attempts"] = max(1, int(ds_cfg.retry_attempts))
    _SETTINGS["backoff"] = float(ds_cfg.retry_backoff)
    _SETTINGS["interval"] = max(0.0, float(ds_cfg.request_interval))


def _retry(fn: Callable):
    """对 akshare 调用做有限重试，缓解偶发的连接中断/限流。

    中间重试用 DEBUG 记录避免刷屏，仅最终失败由上层转 DataSourceError。
    """
    attempts = _SETTINGS["attempts"]
    backoff = _SETTINGS["backoff"]
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - 统一重试后再上抛
            last = e
            if i + 1 < attempts:
                log.debug("数据源调用失败，第 %d/%d 次重试：%s", i + 1, attempts, e)
                time.sleep(backoff * (i + 1))
    raise last  # type: ignore[misc]


def _throttle() -> None:
    """逐股请求间的节流，降低 eastmoney 限流概率。"""
    if _SETTINGS["interval"] > 0:
        time.sleep(_SETTINGS["interval"])


def _raw_zt_pool(date_yyyymmdd: str):
    return _retry(lambda: _akshare().stock_zt_pool_em(date=date_yyyymmdd))


def _raw_zbgc_pool(date_yyyymmdd: str):
    return _retry(lambda: _akshare().stock_zt_pool_zbgc_em(date=date_yyyymmdd))


def _raw_previous_zt_pool(date_yyyymmdd: str):
    return _retry(lambda: _akshare().stock_zt_pool_previous_em(date=date_yyyymmdd))


def _market_prefix(code: str) -> str:
    """腾讯接口需要带市场前缀的代码。"""
    c = str(code).zfill(6)
    if c[0] == "6":
        return f"sh{c}"
    if c[0] in ("4", "8"):
        return f"bj{c}"
    return f"sz{c}"


def _raw_daily_hist(symbol: str, start: str, end: str):
    _throttle()
    return _retry(
        lambda: _akshare().stock_zh_a_hist(
            symbol=symbol, period="daily", start_date=start, end_date=end, adjust=""
        )
    )


def _raw_daily_hist_tx(symbol: str, start: str, end: str):
    """腾讯日 K 回退源（东财 push2his 被限流时使用）。"""
    _throttle()
    return _retry(
        lambda: _akshare().stock_zh_a_hist_tx(
            symbol=_market_prefix(symbol), start_date=start, end_date=end, adjust=""
        )
    )


def _raw_tx_detail(symbol: str):
    _throttle()
    return _retry(
        lambda: _akshare().stock_zh_a_tick_tx_js(symbol=_market_prefix(symbol))
    )


# --------------------------------------------------------------------------- #
# 对外接口
# --------------------------------------------------------------------------- #
def fetch_zt_pool(date: str) -> list[ZtRow]:
    """涨停股池。"""
    try:
        df = _raw_zt_pool(to_akshare_date(date))
    except Exception as e:  # noqa: BLE001 - 统一转 DataSourceError
        raise DataSourceError(f"获取涨停股池失败 ({date}): {e}") from e
    rows = normalize_zt_pool(df)
    log.info("涨停股池 %s: %d 条", date, len(rows))
    return rows


def fetch_zbgc_pool(date: str) -> list[ZbRow]:
    """炸板股池。"""
    try:
        df = _raw_zbgc_pool(to_akshare_date(date))
    except Exception as e:  # noqa: BLE001
        raise DataSourceError(f"获取炸板股池失败 ({date}): {e}") from e
    rows = normalize_zbgc_pool(df)
    log.info("炸板股池 %s: %d 条", date, len(rows))
    return rows


def fetch_previous_zt_pool(date: str) -> list[ZtRow]:
    """昨日涨停股池（预留，复用 ZtRow 结构）。"""
    try:
        df = _raw_previous_zt_pool(to_akshare_date(date))
    except Exception as e:  # noqa: BLE001
        raise DataSourceError(f"获取昨日涨停股池失败 ({date}): {e}") from e
    return normalize_zt_pool(df)


def fetch_daily_hist(code: str, start: str, end: str) -> list[DailyBar]:
    """历史日 K（不复权）。start/end 接受 ISO 或 YYYYMMDD。

    东财 push2his 被限流时自动回退到腾讯源。两源成交量单位均为手，
    放量倍数为比值与单位无关，竞价量占比也用手，保持一致。
    """
    sym = str(code).zfill(6)
    s, e = to_akshare_date(start), to_akshare_date(end)
    try:
        return normalize_daily_hist(_raw_daily_hist(sym, s, e))
    except Exception as em_err:  # noqa: BLE001 - 东财失败则回退
        log.debug("东财日 K 失败 (%s)，回退腾讯源：%s", code, em_err)
    try:
        bars = normalize_daily_hist_tx(_raw_daily_hist_tx(sym, s, e), sym)
    except Exception as tx_err:  # noqa: BLE001
        raise DataSourceError(
            f"获取历史日 K 失败 ({code})，东财与腾讯源均不可用: {tx_err}"
        ) from tx_err
    log.info("历史日 K %s 已回退腾讯源，%d 条", code, len(bars))
    return bars


def fetch_auction(code: str) -> AuctionData | None:
    """09:25 集合竞价数据；腾讯 3 秒成交明细每个交易日 16:00 后提供当日数据。"""
    try:
        df = _raw_tx_detail(str(code).zfill(6))
    except Exception as e:  # noqa: BLE001
        log.error("获取竞价数据失败 (%s): %s", code, e)
        return None
    return normalize_auction(df, code)


def is_trading_day(date: str) -> bool:
    """MVP：用涨停股池是否为空粗判交易日（PRD 第 15 节）。"""
    iso = to_iso_date(date) if "-" not in str(date) else str(date)[:10]
    try:
        weekday = dt.date.fromisoformat(iso).weekday()
    except ValueError:
        return False
    if weekday >= 5:  # 周六/周日
        return False
    try:
        return len(fetch_zt_pool(date)) > 0
    except DataSourceError:
        return False
