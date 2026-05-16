"""领域模型与常量。

datasource 把 AkShare 的 DataFrame 标准化成这里的对象，strategy / storage /
notifier 只依赖这些对象，从而与数据源、邮件解耦。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


class States:
    """三种核心状态。"""

    FEILONG: Final = "飞龙在天"
    KANGLONG: Final = "亢龙有悔"
    QIANLONG: Final = "潜龙在渊"
    ALL: Final = ("飞龙在天", "亢龙有悔", "潜龙在渊")
    # 状态升级路径：key 的下一步是 value
    NEXT: Final = {"飞龙在天": "亢龙有悔", "亢龙有悔": "潜龙在渊"}


class SnapshotType:
    KANGLONG: Final = "kanglong"
    QIANLONG: Final = "qianlong"
    MANUAL: Final = "manual"
    ALL: Final = ("kanglong", "qianlong", "manual")


class TaskName:
    KANGLONG: Final = "kanglong_task"
    QIANLONG: Final = "qianlong_task"
    MANUAL_QUERY: Final = "manual_query"


class TaskStatus:
    SUCCESS: Final = "success"
    PARTIAL: Final = "partial_success"
    FAILED: Final = "failed"
    SKIPPED: Final = "skipped"


class Quality:
    QUALIFIED: Final = "合格"
    EXCELLENT: Final = "优质"


@dataclass(slots=True)
class ZtRow:
    """涨停股池一行（stock_zt_pool_em 标准化）。"""

    code: str
    name: str
    pct_change: float | None = None
    latest_price: float | None = None
    amount: float | None = None
    free_market_cap: float | None = None
    total_market_cap: float | None = None
    turnover_rate: float | None = None
    seal_amount: float | None = None
    first_limit_time: str | None = None
    last_limit_time: str | None = None
    break_board_count: int | None = None
    lianban_count: int | None = None
    industry: str | None = None


@dataclass(slots=True)
class ZbRow:
    """炸板股池一行（stock_zt_pool_zbgc_em 标准化）。"""

    code: str
    name: str
    pct_change: float | None = None
    latest_price: float | None = None
    limit_price: float | None = None
    amount: float | None = None
    free_market_cap: float | None = None
    total_market_cap: float | None = None
    turnover_rate: float | None = None
    first_limit_time: str | None = None
    break_board_count: int | None = None
    amplitude: float | None = None
    industry: str | None = None


@dataclass(slots=True)
class DailyBar:
    """历史日 K 一行（stock_zh_a_hist 标准化）。成交量单位：手。"""

    date: str
    code: str
    open: float | None = None
    close: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    amplitude: float | None = None
    pct_change: float | None = None
    change: float | None = None
    turnover_rate: float | None = None


@dataclass(slots=True)
class AuctionData:
    """09:25 集合竞价数据。成交量单位：手。"""

    code: str
    time: str | None = None
    price: float | None = None
    volume: float | None = None
    amount: float | None = None


@dataclass(slots=True)
class Candidate:
    """状态升级的候选股票（来自当前状态表）。

    feilong -> 亢龙有悔 时携带连板数；亢龙有悔 -> 潜龙在渊 时携带流通市值。
    """

    code: str
    name: str
    prev_state: str
    prev_state_date: str | None = None
    lianban_count: int | None = None
    free_market_cap: float | None = None
    industry: str | None = None


@dataclass(slots=True)
class StateResult:
    """strategy 输出的一条状态结论。

    metrics 存关键指标快照（写入 state_transition_history.metrics_json 与
    daily_state_snapshot 对应列），reason 为人类可读的入选原因。
    """

    code: str
    name: str
    state: str
    reason: str
    metrics: dict = field(default_factory=dict)
    quality: str | None = None
