from stocks.provider_factory import create_stock_provider
from strategy.stock_selector.weak_to_strong import WeakToStrongSelector


def main():
    test_date = "20250310"
    stock_provider = create_stock_provider(provider_type="akshare")
    selector = WeakToStrongSelector()
    res = selector.select_stocks(stock_provider, test_date)
    print(res)


if __name__ == "__main__":
    main()
