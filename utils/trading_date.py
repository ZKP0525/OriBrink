from datetime import datetime, timedelta


def get_previous_trading_day(date_str):
    """date_str example: 20250310"""
    # 将字符串转换为日期对象
    date = datetime.strptime(date_str, "%Y%m%d")
    
    # 计算前一天的日期
    previous_day = date - timedelta(days=1)
    
    # 如果前一天是周六或周日，则继续向前推
    while previous_day.weekday() >= 5:  # 5是周六，6是周日
        previous_day -= timedelta(days=1)
    
    # 将日期对象转换回字符串格式
    previous_trading_day_str = previous_day.strftime("%Y%m%d")
    
    return previous_trading_day_str

def get_next_trading_day(date_str):
    """date_str example: 20250310"""
    # 将字符串转换为日期对象
    date = datetime.strptime(date_str, "%Y%m%d")
    
    # 计算下一个日期
    next_date = date + timedelta(days=1)
    
    # 检查是否是周末，如果是则继续加1天，直到找到下一个交易日
    while next_date.weekday() >= 5:  # 5是周六，6是周日
        next_date += timedelta(days=1)
    
    # 将日期对象转换回字符串格式
    return next_date.strftime("%Y%m%d")
