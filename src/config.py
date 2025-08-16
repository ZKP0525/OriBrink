# src/config.py

from pathlib import Path

# 项目根目录，这里我们假设 src 目录的父目录就是项目根目录
# Path(__file__) -> /path/to/project/src/config.py
# .parent -> /path/to/project/src
# .parent -> /path/to/project
PROJECT_ROOT = Path(__file__).parent.parent

# 数据根目录
DATA_DIR = PROJECT_ROOT / "data"
STOCK_RAW_DATA_DIR = DATA_DIR / "stock_raw_data"

# 各个数据源的详细路径
DAILY_MARKET_DIR = STOCK_RAW_DATA_DIR / "daily_market"
MARKET_TRADE_1MIN_DIR = STOCK_RAW_DATA_DIR / "market_trade_1min"
PRE_MARKET_3S_DIR = STOCK_RAW_DATA_DIR / "pre_market_3s"
