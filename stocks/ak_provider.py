import akshare as ak
from stocks.base_provider import StockDataProvider
import pandas as pd


class AkshareProvider(StockDataProvider):
    """使用 Akshare 实现的数据提供者"""

    def get_zb_stocks_pool(self, date: str) -> pd.DataFrame:
        """
        获取指定日期的炸板股池
        Args:
            date: 日期字符串，格式：YYYYMMDD
        Returns:
            DataFrame: 炸板股票数据
        """
        return ak.stock_zt_pool_zbgc_em(date=date)

    def get_stock_day_data(
        self, stock_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取股票日数据

        Args:
            stock_code (str): 股票代码,如'603777',可以通过 ak.stock_zh_a_spot_em() 获取
            start_date (str): 开始日期,格式为'YYYYMMDD'
            end_date (str): 结束日期,格式为'YYYYMMDD'

        Returns:
            DataFrame: 包含股票历史数据的DataFrame

        Notes:
            - 默认返回不复权的数据
            - 可以通过adjust参数设置复权方式:
                - qfq: 前复权
                - hfq: 后复权
        """
        return ak.stock_zh_a_hist(
            symbol=stock_code, period="daily", start_date=start_date, end_date=end_date
        )

    def get_stock_minute_data(
        self, stock_code: str, start_date_time: str, end_date_time: str, period: str
    ) -> pd.DataFrame:
        """
        获取股票分时数据

        Args:
            stock_code (str): 股票代码,如'603777',可以通过 ak.stock_zh_a_spot_em() 获取
            start_date_time (str): 开始日期时间,格式为'YYYYMMDDHHMM'
            end_date_time (str): 结束日期时间,格式为'YYYYMMDDHHMM'
            period (str): 数据周期,可选值为 '1min'(1分钟), '5min'(5分钟), '15min'(15分钟), '30min'(30分钟), '60min'(60分钟)

        Returns:
            DataFrame: 包含股票分时数据的DataFrame
        """
        return ak.stock_intraday_em(symbol=stock_code)

    def get_stock_individual_info(self, stock_code: str) -> pd.DataFrame:
        """
        获取股票基本信息
        """
        return ak.stock_individual_info_em(symbol=stock_code)

    def get_stock_volume_day_data(self, stock_code: str, date: str) -> pd.DataFrame:
        """
        获取股票日成交量数据
        """
        # TODO: 某些股票数据获取失败，如20250312的688339
        stock_day_daty = self.get_stock_day_data(
            stock_code=stock_code, start_date=date, end_date=date
        )
        return stock_day_daty.iloc[0]["成交量"]

    def get_stock_code_from_pool(self, pool: pd.DataFrame) -> list:
        """
        从股票池中获取股票代码
        """
        return pool["代码"]

    def get_stock_market_capitalization(self, stock_code: str) -> float:
        """
        获取股票流通市值
        """
        stock_individual_info = self.get_stock_individual_info(stock_code=stock_code)
        return stock_individual_info.loc[
            stock_individual_info["item"] == "流通市值", "value"
        ].values[0]

    def get_stock_auction_volume(self, stock_code: str, date: str):
        """
        获取股票竞价成交量
        """
        start_date_time = date + "0820"
        end_date_time = date + "0830"

        # TODO: Akshare只能获取最近一天的分时数据，用于获取竞价成交量，因此无法回测

        # 获取当天的分时交易数据
        df = self.get_stock_minute_data(
            stock_code=stock_code,
            start_date_time=start_date_time,
            end_date_time=end_date_time,
            period="1",
        )

        # 将时间列转换为时间类型
        df["时间"] = pd.to_datetime(df["时间"], format="%H:%M:%S")

        # 筛选出 9:15:00 到 9:25:00 之间的数据
        start_time = pd.to_datetime("09:15:00", format="%H:%M:%S")
        end_time = pd.to_datetime("09:25:00", format="%H:%M:%S")
        filtered_df = df[(df["时间"] >= start_time) & (df["时间"] <= end_time)]

        # 计算总手数
        total_volume = filtered_df["手数"].sum()

        return total_volume
