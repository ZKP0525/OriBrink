from stocks.base_provider import StockDataProvider
from stocks.ak_provider import AkshareProvider


def create_stock_provider(provider_type: str = "akshare") -> StockDataProvider:
    """
    工厂函数，用于创建股票数据提供者实例
    Args:
        provider_type: 提供者类型，默认为 "akshare"
    Returns:
        StockDataProvider: 数据提供者实例
    """
    providers = {
        "akshare": AkshareProvider(),
        # 未来可以在这里添加其他提供者
        # "tushare": TushareProvider(),
    }

    if provider_type not in providers:
        raise ValueError(f"不支持的数据提供者类型: {provider_type}")

    return providers[provider_type]


# 使用示例
def get_zb_stocks_pool(date: str, provider_type: str = "akshare"):
    """
    获取指定日期的炸板股池
    Args:
        date: 日期字符串，格式：YYYYMMDD
        provider_type: 数据提供者类型，默认为 "akshare"
    Returns:
        DataFrame: 炸板股票数据
    """
    provider = create_stock_provider(provider_type)
    return provider.get_zb_stocks_pool(date)
