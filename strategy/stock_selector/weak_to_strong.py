from stocks import StockDataProvider, create_stock_provider
from strategy.stock_selector.base_selector import StockSelector
import pandas as pd
from utils import get_previous_trading_day, get_next_trading_day


class WeakToStrongSelector(StockSelector):
    """弱转强选股策略"""

    def __init__(self):
        self.params = {
            "market_capitalization_threshold": 8000000000,
            "small_good_trading_volume_expansion_threshold": 0.05,
            "small_excellent_trading_volume_expansion_threshold": 0.1,
            "large_good_trading_volume_expansion_threshold": 0.025,
        }

    def select_stocks(self, stock_provider: StockDataProvider, date: str):
        """
        从股票池中选择股票
        Args:
            stock_provider: 股票数据提供者
            date: 日期
        """
        prev_date = get_previous_trading_day(date)  # 前一个交易日
        next_date = get_next_trading_day(date)  # 次日交易日

        # TODO: 添加烂板股票池

        # 炸板股票池
        zb_stocks_pool = stock_provider.get_zb_stocks_pool(date)
        # 炸板放量池流通市值小于80亿
        stock_zbfl_pool_small = []
        # 炸板放量池流通市值大于等于80亿
        stock_zbfl_pool_big = []

        for stock in stock_provider.get_stock_code_from_pool(zb_stocks_pool):
            yesterday_volume = stock_provider.get_stock_volume_day_data(
                stock_code=stock, date=prev_date
            )
            today_volume = stock_provider.get_stock_volume_day_data(
                stock_code=stock, date=date
            )
            if today_volume > yesterday_volume:
                market_capitalization = stock_provider.get_stock_market_capitalization(
                    stock_code=stock
                )
                if (
                    market_capitalization
                    >= self.params["market_capitalization_threshold"]
                ):
                    stock_zbfl_pool_big.append(stock)
                else:
                    stock_zbfl_pool_small.append(stock)

        def get_auction_ratio(stock_code):
            """获取竞价比例"""
            date_volume = stock_provider.get_stock_volume_day_data(
                stock_code=stock_code, date=date
            )
            next_date_auction_volume = stock_provider.get_stock_auction_volume(
                stock_code=stock_code, date=next_date
            )
            ratio = next_date_auction_volume / date_volume
            return ratio

        excellent_poll = []
        good_poll = []

        for stock in stock_zbfl_pool_small:
            ratio = get_auction_ratio(stock)
            if (
                ratio
                > self.params["small_excellent_trading_volume_expansion_threshold"]
            ):
                excellent_poll.append(stock)
            elif ratio > self.params["small_good_trading_volume_expansion_threshold"]:
                good_poll.append(stock)

        for stock in stock_zbfl_pool_big:
            ratio = get_auction_ratio(stock)
            if ratio > self.params["large_good_trading_volume_expansion_threshold"]:
                good_poll.append(stock)

        return {"excellent_poll": excellent_poll, "good_poll": good_poll}


if __name__ == "__main__":
    stock_provider = create_stock_provider(provider_type="akshare")
    selector = WeakToStrongSelector()
    res = selector.select_stocks(stock_provider, "20250310")
    print(res)
