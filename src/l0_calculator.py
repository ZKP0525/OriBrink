# src/l0_calculator.py

from datetime import date, time
from typing import Any, Dict

import pandas as pd

from . import data_loader

# --- 辅助函数 ---


def _get_limit_up_price(code: str, prev_close: float) -> float:
    """根据股票代码和前收盘价计算涨停价"""
    if pd.isna(prev_close) or prev_close == 0:
        return 0.0

    code_prefix = code[:2].lower()
    code_number_prefix = code[2:5]

    rate = 0.10  # 默认主板
    if code_prefix == "bj":
        rate = 0.30
    elif code_number_prefix in ["300", "688"]:  # 创业板和科创板
        rate = 0.20

    # ST/*ST 股票为 5% (这里为简化，暂不处理)
    # 新股上市首日规则不同 (这里为简化，暂不处理)

    # 四舍五入到两位小数
    return round(prev_close * (1 + rate), 2)


# --- L0 指标计算函数 ---


def calculate_auction_info(daily_df: pd.DataFrame, pre_market_df: pd.DataFrame) -> Dict[str, Any]:
    """计算集合竞价涨幅和量能"""
    # 【修正1】: 更新字典键名以匹配前端
    result = {"竞价涨幅": "N/A", "竞价量能(元)": "N/A"}

    if pre_market_df.empty:
        return result

    # 【修正2】: 使用 .copy() 避免 SettingWithCopyWarning，并使逻辑更清晰
    df = pre_market_df.copy()
    df["trade_datetime"] = pd.to_datetime(df["trade_date"])

    # 集合竞价的最终结果在 09:25:00 这一刻产生
    # 直接定位到这个精确的时间点
    auction_data = df[df["trade_datetime"].dt.time == time(9, 25, 0)]

    if auction_data.empty:
        # 如果没有精确的 09:25:00 数据，则无法计算，直接返回默认值
        return result

    # 提取需要的值
    auction_price = auction_data["current"].iloc[0]
    auction_amount = auction_data["amount"].iloc[0]
    prev_close = auction_data["prev_close"].iloc[0]

    # 【修正3】: 增加对数据有效性的检查
    if pd.notna(prev_close) and prev_close > 0:
        change_pct = (auction_price / prev_close - 1) * 100
        result["竞价涨幅"] = f"{change_pct:.2f}%"

    if pd.notna(auction_amount):
        result["竞价量能(元)"] = f"{auction_amount:,.0f}"

    return result


def calculate_high_low_times(min1_df: pd.DataFrame) -> Dict[str, Any]:
    """计算全天、上午、下午的最高最低价及其时间"""
    result = {
        "全天最高": "N/A",
        "全天最高时间": "N/A",
        "全天最低": "N/A",
        "全天最低时间": "N/A",
        "上午最高": "N/A",
        "上午最高时间": "N/A",
        "上午最低": "N/A",
        "上午最低时间": "N/A",
        "下午最高": "N/A",
        "下午最高时间": "N/A",
        "下午最低": "N/A",
        "下午最低时间": "N/A",
    }
    if min1_df.empty:
        return result

    min1_df["time"] = pd.to_datetime(min1_df["日期"]).dt.time

    # 全天
    full_day_high_idx = min1_df["最高价"].idxmax()
    full_day_low_idx = min1_df["最低价"].idxmin()
    result["全天最高"] = min1_df.loc[full_day_high_idx, "最高价"]
    result["全天最高时间"] = min1_df.loc[full_day_high_idx, "time"].strftime("%H:%M")
    result["全天最低"] = min1_df.loc[full_day_low_idx, "最低价"]
    result["全天最低时间"] = min1_df.loc[full_day_low_idx, "time"].strftime("%H:%M")

    # 上午 (09:30 - 11:30)
    morning_df = min1_df[min1_df["time"] <= time(11, 30)]
    if not morning_df.empty:
        morning_high_idx = morning_df["最高价"].idxmax()
        morning_low_idx = morning_df["最低价"].idxmin()
        result["上午最高"] = morning_df.loc[morning_high_idx, "最高价"]
        result["上午最高时间"] = morning_df.loc[morning_high_idx, "time"].strftime("%H:%M")
        result["上午最低"] = morning_df.loc[morning_low_idx, "最低价"]
        result["上午最低时间"] = morning_df.loc[morning_low_idx, "time"].strftime("%H:%M")

    # 下午 (13:00 - 15:00)
    afternoon_df = min1_df[min1_df["time"] >= time(13, 0)]
    if not afternoon_df.empty:
        afternoon_high_idx = afternoon_df["最高价"].idxmax()
        afternoon_low_idx = afternoon_df["最低价"].idxmin()
        result["下午最高"] = afternoon_df.loc[afternoon_high_idx, "最高价"]
        result["下午最高时间"] = afternoon_df.loc[afternoon_high_idx, "time"].strftime("%H:%M")
        result["下午最低"] = afternoon_df.loc[afternoon_low_idx, "最低价"]
        result["下午最低时间"] = afternoon_df.loc[afternoon_low_idx, "time"].strftime("%H:%M")

    return result


def analyze_limit_status(
    code: str, daily_df: pd.DataFrame, min1_df: pd.DataFrame, pre_market_df: pd.DataFrame
) -> Dict[str, Any]:
    """分析涨停、炸板、烂板情况"""
    result = {"是否涨停": "否", "是否炸板": "否", "是否烂板": "否", "封单额(元)": "N/A"}
    if daily_df.empty or pre_market_df.empty or min1_df.empty:
        return result

    close_price = daily_df["收盘价"].iloc[0]
    day_high = min1_df["最高价"].max()
    prev_close = pre_market_df["prev_close"].iloc[0]  # 从盘前数据获取更准确

    limit_up_price = _get_limit_up_price(code, prev_close)
    if limit_up_price == 0:
        return result

    # 检查是否涨停
    is_limit_up = abs(close_price - limit_up_price) < 0.01
    if is_limit_up:
        result["是否涨停"] = "是"
        # 尝试计算收盘时的封单额
        # 简化：假设收盘价=涨停价，可以看盘后挂单。但1分钟数据不含此信息。
        # 这里我们无法精确获取封单额，仅作标识。
        result["封单额(元)"] = "无法从1分钟数据获取"

    # 检查是否炸板 (最高价触及涨停，但收盘价未涨停)
    is_broken_limit = abs(day_high - limit_up_price) < 0.01 and not is_limit_up
    if is_broken_limit:
        result["是否炸板"] = "是"

    # 检查是否烂板 (涨停后曾开板)
    if is_limit_up:
        first_limit_up_time = None
        for _, row in min1_df.iterrows():
            if abs(row["最高价"] - limit_up_price) < 0.01:
                first_limit_up_time = pd.to_datetime(row["日期"]).time()
                break

        if first_limit_up_time:
            opened_after_limit = False
            # 检查首次封板后的时间里，是否有价格低于涨停价
            after_limit_df = min1_df[pd.to_datetime(min1_df["日期"]).dt.time > first_limit_up_time]
            if not after_limit_df[after_limit_df["最低价"] < limit_up_price].empty:
                opened_after_limit = True

            if opened_after_limit:
                result["是否烂板"] = "是"

    return result


def analyze_late_session_rush(min1_df: pd.DataFrame, daily_df: pd.DataFrame) -> Dict[str, Any]:
    """分析尾盘抢筹情况"""
    result = {"尾盘表现": "N/A"}
    if min1_df.empty or daily_df.empty:
        return result

    min1_df["datetime"] = pd.to_datetime(min1_df["日期"])

    # 定义尾盘时间：14:45 - 15:00
    late_session_start = time(14, 45)

    price_at_start = min1_df[min1_df["datetime"].dt.time <= late_session_start]
    if price_at_start.empty:
        return result

    start_price = price_at_start.iloc[-1]["收盘价"]
    close_price = daily_df["收盘价"].iloc[0]

    if start_price > 0:
        change_pct = (close_price / start_price - 1) * 100
        if change_pct > 1.0:
            result["尾盘表现"] = f"抢筹拉升 {change_pct:.2f}%"
        elif change_pct < -1.0:
            result["尾盘表现"] = f"尾盘跳水 {change_pct:.2f}%"
        else:
            result["尾盘表现"] = f"平稳 {change_pct:.2f}%"

    return result


def get_turnover_rate(daily_df: pd.DataFrame) -> Dict[str, Any]:
    """获取换手率"""
    result = {"换手率": "N/A"}
    if not daily_df.empty and "换手率" in daily_df.columns:
        turnover = daily_df["换手率"].iloc[0]
        result["换手率"] = f"{turnover * 100:.2f}%"  # 假设原始数据是小数
    return result


# --- 主计算函数 ---


def calculate_all_l0_metrics(day_date: date, code: str) -> Dict[str, Any]:
    """
    计算指定日期和代码的所有L0指标。
    """
    # 1. 加载所有需要的数据
    all_data = data_loader.load_by_date_and_code(day_date, code)
    daily_df = all_data[data_loader.DAILY_MARKET_KEY]
    min1_df = all_data[data_loader.MARKET_TRADE_1MIN_KEY]
    pre_market_df = all_data[data_loader.PRE_MARKET_3S_KEY]

    # 检查关键数据是否存在
    if daily_df.empty:
        return {"error": f"未找到 {day_date} 的日线数据"}
    if min1_df.empty:
        return {"error": f"未找到 {day_date} 的1分钟线数据"}
    if pre_market_df.empty:
        return {"error": f"未找到 {day_date} 的盘前3秒数据"}

    # 2. 调用各个计算函数
    l0_metrics = {}
    l0_metrics.update(calculate_auction_info(daily_df, pre_market_df))
    l0_metrics.update(calculate_high_low_times(min1_df))
    l0_metrics.update(analyze_limit_status(code, daily_df, min1_df, pre_market_df))
    l0_metrics.update(analyze_late_session_rush(min1_df, daily_df))
    l0_metrics.update(get_turnover_rate(daily_df))

    # 添加股票名称和日期信息
    l0_metrics["股票代码"] = code
    l0_metrics["股票名称"] = daily_df["股票名称"].iloc[0]
    l0_metrics["交易日期"] = day_date.isoformat()

    return l0_metrics
