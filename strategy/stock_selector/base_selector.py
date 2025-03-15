from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import pandas as pd
from datetime import datetime
from stocks.base_provider import StockDataProvider
class StockSelector(ABC):
    @abstractmethod
    def select_stocks(self, stock_provider: StockDataProvider, date: str):
        """
        从股票池中选择股票
        Args:
            stock_provider: 股票数据提供者
            date: 日期
        """         
        pass