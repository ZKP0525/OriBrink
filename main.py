# main.py

from datetime import date, time

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from src import data_loader, l0_calculator

# --- FastAPI 应用设置 ---
app = FastAPI(title="L0 Stock Data Analyzer")

# 设置模板目录
templates = Jinja2Templates(directory="templates")

# 如果未来有静态文件(CSS, JS)，可以这样挂载
# app.mount("/static", StaticFiles(directory="static"), name="static")


# --- 路由 ---


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """渲染主页面"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/l0-data")
async def get_l0_data(code: str, date_str: str):
    """
    API端点，用于获取L0指标和分时图数据。
    - code: 股票代码, e.g., sz000001
    - date_str: 日期字符串, e.g., 2024-01-02
    """
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD 格式") from e

    # 计算L0指标
    l0_metrics = l0_calculator.calculate_all_l0_metrics(target_date, code)
    if "error" in l0_metrics:
        raise HTTPException(status_code=404, detail=l0_metrics["error"])

    # --- 开始修改 ---

    # 获取绘图所需的所有数据
    all_data = data_loader.load_by_date_and_code(target_date, code)
    min1_df = all_data[data_loader.MARKET_TRADE_1MIN_KEY]
    pre_market_df = all_data[data_loader.PRE_MARKET_3S_KEY]  # 新增获取盘前数据

    chart_data = []

    # 1. 添加集合竞价数据点 (09:25)
    if not pre_market_df.empty:
        pre_market_df["trade_datetime"] = pd.to_datetime(pre_market_df["trade_date"])
        # 找到 09:25:00 或之前的最后一条记录作为最终竞价结果
        auction_time_point = time(9, 25, 0)
        final_auction_data = pre_market_df[pre_market_df["trade_datetime"].dt.time <= auction_time_point].tail(1)

        if not final_auction_data.empty:
            auction_price = final_auction_data["current"].iloc[0]
            chart_data.append({"time": "09:25", "price": auction_price})

    # 2. 添加1分钟交易数据
    if not min1_df.empty:
        min1_df["日期"] = pd.to_datetime(min1_df["日期"])
        minute_chart_data = [
            {"time": row["日期"].strftime("%H:%M"), "price": row["收盘价"]} for index, row in min1_df.iterrows()
        ]
        chart_data.extend(minute_chart_data)

    # --- 修改结束 ---

    return {"metrics": l0_metrics, "chart_data": chart_data}


# --- 运行服务器 ---
if __name__ == "__main__":
    # 使用 uvicorn 启动服务器
    # reload=True 可以在代码更改时自动重启服务，方便开发
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
