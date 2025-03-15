from abc import ABC, abstractmethod
import pandas as pd


class StockDataProvider(ABC):
    """股票数据提供者的抽象基类"""

    @abstractmethod
    def get_zb_stocks_pool(self, date: str) -> pd.DataFrame:
        """获取炸板股池的抽象方法"""
        pass

    @abstractmethod
    def get_stock_day_data(
        self, stock_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取股票日数据的抽象方法"""
        pass

    @abstractmethod
    def get_stock_minute_data(
        self, stock_code: str, start_date_time: str, end_date_time: str, period: str
    ) -> pd.DataFrame:
        """获取股票分时数据的抽象方法"""
        pass

    @abstractmethod
    def get_stock_individual_info(self, stock_code: str) -> pd.DataFrame:
        """获取股票基本信息的抽象方法"""
        pass

    @abstractmethod
    def get_stock_volume_day_data(self, stock_code: str, date: str):
        """获取股票日成交量的抽象方法"""
        pass

    @abstractmethod
    def get_stock_code_from_pool(self, pool: pd.DataFrame) -> list:
        """从股票池中获取股票代码的抽象方法"""
        pass

    @abstractmethod
    def get_stock_market_capitalization(self, stock_code: str) -> float:
        """获取股票流通市值的抽象方法"""
        pass

    @abstractmethod
    def get_stock_auction_volume(self, stock_code: str, date: str):
        """获取股票竞价成交量的抽象方法"""
        pass
