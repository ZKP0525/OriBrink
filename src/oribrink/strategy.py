"""状态识别模块（最重要的深模块，纯策略）。

不依赖 AkShare、不碰数据库、不发邮件：输入标准化领域对象 + 阈值配置，
输出 StateResult 列表与异常说明列表。便于离线单测各种边界。
"""

from __future__ import annotations

from .config import StrategyConfig
from .models import AuctionData, Candidate, Quality, States, StateResult, ZbRow, ZtRow


# --------------------------------------------------------------------------- #
# 飞龙在天：连板数 >= 阈值
# --------------------------------------------------------------------------- #
def select_feilong(
    zt_rows: list[ZtRow], cfg: StrategyConfig
) -> tuple[list[StateResult], list[str]]:
    results: list[StateResult] = []
    anomalies: list[str] = []
    for r in zt_rows:
        if r.lianban_count is None:
            anomalies.append(f"{r.code} {r.name}: 连板数字段缺失，跳过飞龙判断")
            continue
        if r.lianban_count < cfg.min_lianban_count:
            continue
        results.append(
            StateResult(
                code=r.code,
                name=r.name,
                state=States.FEILONG,
                reason=f"连板数 {r.lianban_count} >= {cfg.min_lianban_count}",
                metrics={
                    "lianban_count": r.lianban_count,
                    "free_market_cap": r.free_market_cap,
                    "total_market_cap": r.total_market_cap,
                    "industry": r.industry,
                    "first_limit_time": r.first_limit_time,
                    "last_limit_time": r.last_limit_time,
                    "break_board_count": r.break_board_count,
                    "seal_amount": r.seal_amount,
                    "turnover_rate": r.turnover_rate,
                    "amount": r.amount,
                    "latest_price": r.latest_price,
                    "pct_change": r.pct_change,
                },
            )
        )
    return results, anomalies


# --------------------------------------------------------------------------- #
# 亢龙有悔：曾飞龙在天 + 弱化形态 + 放量
# --------------------------------------------------------------------------- #
def _kanglong_triggers(
    c: Candidate,
    zt_by_code: dict[str, ZtRow],
    zb_by_code: dict[str, ZbRow],
) -> tuple[bool, bool, ZtRow | None, ZbRow | None]:
    """弱化形态判断，纯粹基于已抓取的涨停/炸板池，不需要任何额外网络请求。"""
    zt = zt_by_code.get(c.code)
    zb = zb_by_code.get(c.code)
    zhaban_no_refill = zb is not None
    lanban_refill = zt is not None and (zt.break_board_count or 0) > 0
    return zhaban_no_refill, lanban_refill, zt, zb


def kanglong_triggered_codes(
    feilong: list[Candidate],
    zt_by_code: dict[str, ZtRow],
    zb_by_code: dict[str, ZbRow],
    cfg: StrategyConfig,
) -> set[str]:
    """出现弱化形态的飞龙代码集合。

    任务侧据此只对这些股票拉历史日 K 算放量，避免对全部飞龙发起请求。
    """
    return {
        c.code
        for c in feilong
        if any(_kanglong_triggers(c, zt_by_code, zb_by_code)[:2])
    }


def evaluate_kanglong(
    feilong: list[Candidate],
    zt_by_code: dict[str, ZtRow],
    zb_by_code: dict[str, ZbRow],
    volumes: dict[str, tuple[float | None, float | None]],
    cfg: StrategyConfig,
) -> tuple[list[StateResult], list[str]]:
    """volumes: code -> (今日成交量, 昨日成交量)，单位手。

    放量数据只需对有弱化形态的股票提供（其余在判定弱化时即被跳过）。
    """
    results: list[StateResult] = []
    anomalies: list[str] = []

    for c in feilong:
        zhaban_no_refill, lanban_refill, zt, zb = _kanglong_triggers(
            c, zt_by_code, zb_by_code
        )
        if not (zhaban_no_refill or lanban_refill):
            continue  # 仍是飞龙在天，无弱化

        today_vol, last_vol = volumes.get(c.code, (None, None))
        if last_vol is None or last_vol == 0:
            anomalies.append(f"{c.code} {c.name}: 昨日成交量缺失或为 0，不升级亢龙有悔")
            continue
        if today_vol is None:
            anomalies.append(f"{c.code} {c.name}: 今日成交量缺失，不升级亢龙有悔")
            continue
        volume_ratio = today_vol / last_vol
        if volume_ratio < cfg.volume_ratio_threshold:
            continue  # 未放量，不视为有效分歧

        triggers = []
        if zhaban_no_refill:
            triggers.append("炸板未回封")
        if lanban_refill:
            triggers.append(f"烂板回封(炸板{zt.break_board_count}次)")
        reason = (
            "曾飞龙在天；"
            + "、".join(triggers)
            + f"；放量 {volume_ratio:.2f} 倍 >= {cfg.volume_ratio_threshold}"
        )
        ref = zt or zb
        results.append(
            StateResult(
                code=c.code,
                name=c.name,
                state=States.KANGLONG,
                reason=reason,
                metrics={
                    "prev_lianban_count": c.lianban_count,
                    "prev_state_date": c.prev_state_date,
                    "industry": c.industry or (ref.industry if ref else None),
                    "free_market_cap": ref.free_market_cap if ref else None,
                    "total_market_cap": ref.total_market_cap if ref else None,
                    "break_board_count": (zt.break_board_count if zt else None),
                    "first_limit_time": (zt.first_limit_time if zt else None),
                    "last_limit_time": (zt.last_limit_time if zt else None),
                    "today_volume": today_vol,
                    "last_volume": last_vol,
                    "volume_ratio": round(volume_ratio, 4),
                    "zhaban_no_refill": zhaban_no_refill,
                    "lanban_refill": lanban_refill,
                },
            )
        )
    return results, anomalies


# --------------------------------------------------------------------------- #
# 潜龙在渊：当前亢龙有悔 + 高开 + 竞价爆量
# --------------------------------------------------------------------------- #
def evaluate_qianlong(
    kanglong: list[Candidate],
    auctions: dict[str, AuctionData | None],
    last_close: dict[str, float | None],
    last_volume: dict[str, float | None],
    cfg: StrategyConfig,
) -> tuple[list[StateResult], list[str]]:
    results: list[StateResult] = []
    anomalies: list[str] = []

    for c in kanglong:
        au = auctions.get(c.code)
        if au is None:
            anomalies.append(f"{c.code} {c.name}: 09:25 竞价数据缺失，不升级潜龙在渊")
            continue
        lc = last_close.get(c.code)
        if lc is None or lc == 0:
            anomalies.append(f"{c.code} {c.name}: 昨日收盘价缺失或为 0，不升级")
            continue
        lv = last_volume.get(c.code)
        if lv is None or lv == 0:
            anomalies.append(f"{c.code} {c.name}: 昨日成交量缺失或为 0，不升级")
            continue
        if au.price is None or au.volume is None:
            anomalies.append(f"{c.code} {c.name}: 竞价价格或成交量缺失，不升级")
            continue
        if c.free_market_cap is None:
            anomalies.append(f"{c.code} {c.name}: 流通市值缺失，无法判定竞价标准")
            continue

        gap = au.price / lc - 1.0
        if gap < cfg.gap_open_threshold:
            continue
        ratio = au.volume / lv

        is_small = c.free_market_cap < cfg.small_cap_threshold
        quality: str | None = None
        if is_small:
            if ratio > cfg.small_cap_auction_ratio_excellent:
                quality = Quality.EXCELLENT
            elif ratio > cfg.small_cap_auction_ratio_qualified:
                quality = Quality.QUALIFIED
        else:
            if ratio > cfg.large_cap_auction_ratio_qualified:
                quality = Quality.QUALIFIED
        if quality is None:
            continue  # 竞价量未达标

        cap_kind = "小票" if is_small else "大票"
        reason = (
            f"曾亢龙有悔；高开 {gap * 100:.2f}% >= {cfg.gap_open_threshold * 100:.0f}%；"
            f"{cap_kind}竞价量占比 {ratio * 100:.2f}% -> {quality}"
        )
        results.append(
            StateResult(
                code=c.code,
                name=c.name,
                state=States.QIANLONG,
                reason=reason,
                quality=quality,
                metrics={
                    "industry": c.industry,
                    "free_market_cap": c.free_market_cap,
                    "last_close": lc,
                    "last_volume": lv,
                    "auction_price": au.price,
                    "auction_volume": au.volume,
                    "auction_amount": au.amount,
                    "auction_ratio": round(ratio, 6),
                    "gap_open_pct": round(gap, 6),
                    "quality": quality,
                    "prev_state_date": c.prev_state_date,
                },
            )
        )
    return results, anomalies
