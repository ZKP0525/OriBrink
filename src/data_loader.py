# src/data_loader.py

from datetime import date
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from . import config

# --- 定义常量以避免魔术字符串 ---
DAILY_MARKET_KEY = "daily_market"
MARKET_TRADE_1MIN_KEY = "market_trade_1min"
PRE_MARKET_3S_KEY = "pre_market_3s"


def _find_pre_market_3s_file(target_date: date) -> Optional[Path]:
    """在 pre_market_3s 目录中查找包含指定日期的文件"""
    year_dir = config.PRE_MARKET_3S_DIR / str(target_date.year)
    if not year_dir.exists():
        return None

    for file_path in year_dir.glob("*.csv"):
        try:
            parts = file_path.stem.split("_")
            start_date_str = parts[2]
            end_date_str = parts[3]

            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)

            if start_date <= target_date <= end_date:
                return file_path
        except (IndexError, ValueError):
            # 忽略格式不正确的文件名
            continue
    return None


def _load_daily_market(day_date: date, code: str) -> pd.DataFrame:
    """加载日线行情数据 (daily_market)"""
    try:
        daily_file = config.DAILY_MARKET_DIR / f"{code.lower()}.csv"
        if not daily_file.exists():
            return pd.DataFrame()

        df = pd.read_csv(daily_file, sep=",", encoding="gbk")
        df["交易日期"] = pd.to_datetime(df["交易日期"]).dt.date

        filtered_data = df[df["交易日期"] == day_date]
        return filtered_data
    except Exception as e:
        print(f"Error loading daily_market data for {code} on {day_date}: {e}")
        return pd.DataFrame()


def _load_market_trade_1min(day_date: date, code: str) -> pd.DataFrame:
    """加载1分钟线数据 (market_trade_1min)"""
    try:
        prefix = code[:2].upper()
        number = code[2:]
        code_1min = f"{prefix}.{number}"

        min1_file = config.MARKET_TRADE_1MIN_DIR / str(day_date.year) / f"{code_1min}.csv"
        if not min1_file.exists():
            return pd.DataFrame()

        df = pd.read_csv(min1_file)
        df["日期"] = pd.to_datetime(df["日期"])

        filtered_data = df[df["日期"].dt.date == day_date]
        return filtered_data
    except Exception as e:
        print(f"Error loading market_trade_1min data for {code} on {day_date}: {e}")
        return pd.DataFrame()


def _load_pre_market_3s(day_date: date, code: str) -> pd.DataFrame:
    """加载盘前3秒数据 (pre_market_3s)"""
    try:
        pre_market_file = _find_pre_market_3s_file(day_date)
        if not pre_market_file:
            return pd.DataFrame()

        prefix = code[:2].upper()
        number = code[2:]
        code_3s = f"{number}.{prefix}"  # 注意格式与其他数据源不同

        df = pd.read_csv(pre_market_file, sep=",", encoding="gbk")
        df["trade_date_dt"] = pd.to_datetime(df["trade_date"]).dt.date

        filtered_data = df[(df["code"] == code_3s) & (df["trade_date_dt"] == day_date)].drop(columns=["trade_date_dt"])

        return filtered_data
    except Exception as e:
        print(f"Error loading pre_market_3s data for {code} on {day_date}: {e}")
        return pd.DataFrame()


def load_by_date_and_code(day_date: date, code: str) -> Dict[str, pd.DataFrame]:
    """
    根据日期和股票代码，加载该股票当天的所有相关数据。

    此函数保证返回一个包含固定键的字典，即使某个数据源没有找到数据，
    对应的值也会是一个空的 DataFrame。

    Args:
        day_date (datetime.date): 需要查询的日期.
        code (str): 股票代码 (格式如: 'sh600000', 'sz000001', 'bj430017').

    Returns:
        Dict[str, pd.DataFrame]: 一个字典，包含以下固定的键:
            - "daily_market": 日线行情数据
            - "market_trade_1min": 1分钟线数据
            - "pre_market_3s": 盘前3秒快照数据
    """
    return {
        DAILY_MARKET_KEY: _load_daily_market(day_date, code),
        MARKET_TRADE_1MIN_KEY: _load_market_trade_1min(day_date, code),
        PRE_MARKET_3S_KEY: _load_pre_market_3s(day_date, code),
    }


# --- 使用示例 ---
if __name__ == "__main__":
    # 示例1: 使用您提供的 sz301063 日期
    test_date_1 = date(2024, 7, 31)
    test_code_1 = "sz301063"
    print(f"--- Loading data for {test_code_1} on {test_date_1} ---")
    data_1 = load_by_date_and_code(day_date=test_date_1, code=test_code_1)

    # 现在返回的字典总是包含所有键
    for source, df in data_1.items():
        print(f"\n[+] Data from '{source}':")
        if not df.empty:
            print(f"Found {len(df)} rows.")
            print(df.head())
        else:
            print("No data found.")

    print("\n" + "=" * 50 + "\n")

    # 示例2: 使用您提供的 BJ.430017 和 tick_3s 数据日期
    test_date_2 = date(2024, 1, 8)
    test_code_2 = "bj430017"

    # 假设一个不存在的数据，来验证空DataFrame的返回
    test_code_3 = "sz999999"  # 一个不存在的股票代码

    print(f"--- Loading data for {test_code_2} on {test_date_2} ---")
    data_2 = load_by_date_and_code(day_date=test_date_2, code=test_code_2)
    for source, df in data_2.items():
        print(f"\n[+] Data from '{source}':")
        if not df.empty:
            print(f"Found {len(df)} rows.")
            print(df.head())
        else:
            print("No data found.")

    print("\n" + "=" * 50 + "\n")

    print(f"--- Loading data for non-existent code {test_code_3} on {test_date_2} ---")
    data_3 = load_by_date_and_code(day_date=test_date_2, code=test_code_3)
    for source, df in data_3.items():
        print(f"\n[+] Data from '{source}':")
        if not df.empty:
            print(f"Found {len(df)} rows.")
            print(df.head())
        else:
            print("No data found.")
