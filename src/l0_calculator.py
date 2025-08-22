# src/l0_calculator.py

from datetime import date, time
from typing import Any, Dict, Optional

import pandas as pd

# 导入config和data_loader
from . import config, data_loader

# --- 新增辅助函数 ---


def _get_previous_trading_day_data(code: str, current_date: date) -> Optional[Dict[str, pd.DataFrame]]:
    """
    获取指定股票在上一个交易日的所有数据。
    它通过读取日线历史来找到上一个交易日，然后加载该日的数据。
    """
    try:
        daily_file = config.DAILY_MARKET_DIR / f"{code.lower()}.csv"
        if not daily_file.exists():
            return None

        # 读取完整的日线数据来寻找上一个交易日
        df_history = pd.read_csv(daily_file, sep=",", encoding="gbk", usecols=["交易日期"])
        df_history["交易日期"] = pd.to_datetime(df_history["交易日期"]).dt.date

        # 筛选出早于当前日期的所有交易日
        previous_days = df_history[df_history["交易日期"] < current_date]
        if previous_days.empty:
            return None  # 没有更早的数据

        # 找到最近的一个交易日
        previous_trading_date = previous_days["交易日期"].max()

        # 加载这个上一个交易日的数据
        return data_loader.load_by_date_and_code(previous_trading_date, code)

    except Exception:
        # 任何错误都意味着无法获取数据
        return None


# --- 更新后的L0指标计算函数 ---


def calculate_auction_info(
    daily_df: pd.DataFrame, pre_market_df: pd.DataFrame, prev_day_data: Optional[Dict[str, pd.DataFrame]]
) -> Dict[str, Any]:
    """计算集合竞价相关指标，包括与昨日的对比"""
    result = {
        "竞价涨幅": "N/A",
        "竞价量能(元)": "N/A",
        "竞价量能/昨日竞价量能": "N/A",
        "竞价量能/昨日总量能": "N/A",
    }

    if pre_market_df.empty:
        return result

    df = pre_market_df.copy()
    df["trade_datetime"] = pd.to_datetime(df["trade_date"])
    auction_data = df[df["trade_datetime"].dt.time == time(9, 25, 0)]

    if auction_data.empty:
        return result

    auction_price = auction_data["current"].iloc[0]
    today_auction_amount = auction_data["amount"].iloc[0]
    prev_close = auction_data["prev_close"].iloc[0]

    if pd.notna(prev_close) and prev_close > 0:
        change_pct = (auction_price / prev_close - 1) * 100
        result["竞价涨幅"] = f"{change_pct:.2f}%"

    if pd.notna(today_auction_amount):
        result["竞价量能(元)"] = f"{today_auction_amount:,.0f}"

    # --- 新增：与昨日数据对比 ---
    if prev_day_data and not prev_day_data["pre_market_3s"].empty and not prev_day_data["daily_market"].empty:
        # 获取昨日竞价量能
        prev_pre_market_df = prev_day_data["pre_market_3s"].copy()
        prev_pre_market_df["trade_datetime"] = pd.to_datetime(prev_pre_market_df["trade_date"])
        prev_auction_data = prev_pre_market_df[prev_pre_market_df["trade_datetime"].dt.time == time(9, 25, 0)]

        if not prev_auction_data.empty:
            prev_auction_amount = prev_auction_data["amount"].iloc[0]
            if pd.notna(prev_auction_amount) and prev_auction_amount > 0:
                ratio = today_auction_amount / prev_auction_amount
                result["竞价量能/昨日竞价量能"] = f"{ratio:.2f}"

        # 获取昨日总量能
        prev_daily_df = prev_day_data["daily_market"]
        prev_total_amount = prev_daily_df["成交额"].iloc[0]
        if pd.notna(prev_total_amount) and prev_total_amount > 0:
            ratio = today_auction_amount / prev_total_amount
            result["竞价量能/昨日总量能"] = f"{ratio * 100:.2f}%"

    return result


def analyze_late_session_rush(min1_df: pd.DataFrame, daily_df: pd.DataFrame) -> Dict[str, Any]:
    """分析尾盘抢筹情况，并计算尾盘成交额占比"""
    result = {"尾盘表现": "N/A", "尾盘成交占比": "N/A"}
    if min1_df.empty or daily_df.empty:
        return result

    min1_df["datetime"] = pd.to_datetime(min1_df["日期"])

    # 价格表现
    late_session_start_time = time(14, 45)
    price_at_start_df = min1_df[min1_df["datetime"].dt.time <= late_session_start_time]
    if not price_at_start_df.empty:
        start_price = price_at_start_df.iloc[-1]["收盘价"]
        close_price = daily_df["收盘价"].iloc[0]
        if start_price > 0:
            change_pct = (close_price / start_price - 1) * 100
            if change_pct > 1.0:
                result["尾盘表现"] = f"抢筹拉升 {change_pct:.2f}%"
            elif change_pct < -1.0:
                result["尾盘表现"] = f"尾盘跳水 {change_pct:.2f}%"
            else:
                result["尾盘表现"] = f"平稳 {change_pct:.2f}%"

    # --- 新增：成交额占比 ---
    late_session_df = min1_df[min1_df["datetime"].dt.time >= late_session_start_time]
    late_session_amount = late_session_df["成交额（元）"].sum()
    full_day_amount = daily_df["成交额"].iloc[0]

    if pd.notna(full_day_amount) and full_day_amount > 0:
        ratio = late_session_amount / full_day_amount
        result["尾盘成交占比"] = f"{ratio * 100:.2f}%"

    return result


def get_turnover_rate_and_total_amount(daily_df: pd.DataFrame) -> Dict[str, Any]:
    """获取换手率和全天成交额"""
    result = {"换手率": "N/A", "全天成交额": "N/A"}
    if not daily_df.empty:
        if "换手率" in daily_df.columns:
            turnover = daily_df["换手率"].iloc[0]
            result["换手率"] = f"{turnover * 100:.2f}%"
        if "成交额" in daily_df.columns:
            amount = daily_df["成交额"].iloc[0]
            if amount > 1_0000_0000:
                result["全天成交额"] = f"{amount / 1_0000_0000:.2f}亿"
            else:
                result["全天成交额"] = f"{amount / 1_0000:.2f}万"
    return result


# --- calculate_high_low_times 和 analyze_limit_status 函数保持不变 ---
def calculate_high_low_times(min1_df: pd.DataFrame) -> Dict[str, Any]:
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

    full_day_high_idx = min1_df["最高价"].idxmax()
    full_day_low_idx = min1_df["最低价"].idxmin()
    result["全天最高"] = min1_df.loc[full_day_high_idx, "最高价"]
    result["全天最高时间"] = min1_df.loc[full_day_high_idx, "time"].strftime("%H:%M")
    result["全天最低"] = min1_df.loc[full_day_low_idx, "最低价"]
    result["全天最低时间"] = min1_df.loc[full_day_low_idx, "time"].strftime("%H:%M")

    morning_df = min1_df[min1_df["time"] <= time(11, 30)]
    if not morning_df.empty:
        morning_high_idx = morning_df["最高价"].idxmax()
        morning_low_idx = morning_df["最低价"].idxmin()
        result["上午最高"] = morning_df.loc[morning_high_idx, "最高价"]
        result["上午最高时间"] = morning_df.loc[morning_high_idx, "time"].strftime("%H:%M")
        result["上午最低"] = morning_df.loc[morning_low_idx, "最低价"]
        result["上午最低时间"] = morning_df.loc[morning_low_idx, "time"].strftime("%H:%M")

    afternoon_df = min1_df[min1_df["time"] >= time(13, 0)]
    if not afternoon_df.empty:
        afternoon_high_idx = afternoon_df["最高价"].idxmax()
        afternoon_low_idx = afternoon_df["最低价"].idxmin()
        result["下午最高"] = afternoon_df.loc[afternoon_high_idx, "最高价"]
        result["下午最高时间"] = afternoon_df.loc[afternoon_high_idx, "time"].strftime("%H:%M")
        result["下午最低"] = afternoon_df.loc[afternoon_low_idx, "最低价"]
        result["下午最低时间"] = afternoon_df.loc[afternoon_low_idx, "time"].strftime("%H:%M")

    return result


def _get_limit_up_price(code: str, prev_close: float) -> float:
    if pd.isna(prev_close) or prev_close == 0:
        return 0.0
    code_prefix = code[:2].lower()
    code_number_prefix = code[2:5]
    rate = 0.10
    if code_prefix == "bj":
        rate = 0.30
    elif code_number_prefix in ["300", "688"]:
        rate = 0.20
    return round(prev_close * (1 + rate), 2)


def analyze_limit_status(
    code: str, daily_df: pd.DataFrame, min1_df: pd.DataFrame, pre_market_df: pd.DataFrame
) -> Dict[str, Any]:
    result = {"是否涨停": "否", "是否炸板": "否", "是否烂板": "否"}
    if daily_df.empty or pre_market_df.empty or min1_df.empty:
        return result

    close_price = daily_df["收盘价"].iloc[0]
    day_high = min1_df["最高价"].max()
    prev_close = pre_market_df["prev_close"].iloc[0]
    limit_up_price = _get_limit_up_price(code, prev_close)
    if limit_up_price == 0:
        return result

    is_limit_up = abs(close_price - limit_up_price) < 0.01
    if is_limit_up:
        result["是否涨停"] = "是"

    is_broken_limit = abs(day_high - limit_up_price) < 0.01 and not is_limit_up
    if is_broken_limit:
        result["是否炸板"] = "是"

    if is_limit_up:
        first_limit_up_time = None
        for _, row in min1_df.iterrows():
            if abs(row["最高价"] - limit_up_price) < 0.01:
                first_limit_up_time = pd.to_datetime(row["日期"]).time()
                break

        if first_limit_up_time:
            after_limit_df = min1_df[pd.to_datetime(min1_df["日期"]).dt.time > first_limit_up_time]
            if not after_limit_df[after_limit_df["最低价"] < limit_up_price].empty:
                result["是否烂板"] = "是"

    return result


# --- 更新主计算函数 ---


def calculate_all_l0_metrics(day_date: date, code: str) -> Dict[str, Any]:
    """计算指定日期和代码的所有L0指标，包括与上一交易日对比的指标。"""
    # 1. 加载当天和上一个交易日的数据
    today_data = data_loader.load_by_date_and_code(day_date, code)
    prev_day_data = _get_previous_trading_day_data(code, day_date)

    daily_df = today_data[data_loader.DAILY_MARKET_KEY]
    min1_df = today_data[data_loader.MARKET_TRADE_1MIN_KEY]
    pre_market_df = today_data[data_loader.PRE_MARKET_3S_KEY]

    if daily_df.empty:
        return {"error": f"未找到 {day_date} 的日线数据"}
    if min1_df.empty:
        return {"error": f"未找到 {day_date} 的1分钟线数据"}
    if pre_market_df.empty:
        return {"error": f"未找到 {day_date} 的盘前3秒数据"}

    # 2. 调用各个计算函数
    l0_metrics = {}
    # 传入昨日数据
    l0_metrics.update(calculate_auction_info(daily_df, pre_market_df, prev_day_data))
    l0_metrics.update(calculate_high_low_times(min1_df))
    l0_metrics.update(analyze_limit_status(code, daily_df, min1_df, pre_market_df))
    # 更新函数调用
    l0_metrics.update(analyze_late_session_rush(min1_df, daily_df))
    l0_metrics.update(get_turnover_rate_and_total_amount(daily_df))  # 调用合并后的新函数

    # 添加股票名称和日期信息
    l0_metrics["股票代码"] = code
    l0_metrics["股票名称"] = daily_df["股票名称"].iloc[0]
    l0_metrics["交易日期"] = day_date.isoformat()

    return l0_metrics
