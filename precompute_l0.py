# precompute_l0_final.py

import concurrent.futures
import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Tuple

import pandas as pd
from src import config, l0_calculator
from tqdm import tqdm


# 任务函数 process_stock_file 保持不变
def process_stock_file(stock_file: Path, target_year: int, position: int) -> Tuple[str, str, Any]:
    """
    处理单个股票文件的函数，返回一个包含状态、代码和消息的元组。
    增加了内存优化和垃圾回收。
    """
    code = stock_file.stem
    try:
        df_daily = pd.read_csv(stock_file, usecols=["交易日期"], encoding="gbk", dtype={"交易日期": str})
        df_daily["交易日期_dt"] = pd.to_datetime(df_daily["交易日期"]).dt.date

        all_trading_dates = sorted(df_daily["交易日期_dt"].unique())
        dates_to_process = [d for d in all_trading_dates if d.year == target_year]

        if not dates_to_process:
            return "SKIPPED", code, f"在 {target_year} 年没有交易数据"

        stock_metrics = {}

        inner_bar_desc = f"计算 {code:<8}"
        for trade_date in tqdm(dates_to_process, desc=inner_bar_desc, position=position, leave=False, mininterval=1.0):
            metrics = l0_calculator.calculate_all_l0_metrics(trade_date, code)
            if "error" not in metrics:
                stock_metrics[date_str := trade_date.isoformat()] = metrics

        if stock_metrics:
            output_path = config.L0_METRICS_DIR / f"{code}.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(stock_metrics, f, ensure_ascii=False, indent=4)

        return "SUCCESS", code, None

    except Exception as e:
        return "FAILED", code, str(e)
    finally:
        gc.collect()


def run_parallel_precomputation(target_year: int = 2024):
    config.L0_METRICS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 获取所有股票文件
    all_files = list(config.DAILY_MARKET_DIR.glob("*.csv"))

    # --- 核心修改点：过滤掉北交所的股票 ---
    # 我们只保留文件名不以 'bj' 开头的股票文件
    stock_files = sorted([f for f in all_files if not f.name.lower().startswith("bj")])

    # 打印过滤信息
    print(f"从总共 {len(all_files)} 个文件中筛选出 {len(stock_files)} 个非北交所股票。")

    if not stock_files:
        print("错误：筛选后没有找到任何需要处理的股票文件。")
        return

    total_cores = os.cpu_count() or 1
    num_workers = max(1, total_cores // 2)

    print(f"为 {target_year} 年进行并行计算...")
    print(f"警告：将使用 {num_workers} / {total_cores} 个CPU核心以降低内存压力。")
    print("按 Ctrl+C 可以随时中断任务。")
    time.sleep(2)

    executor = concurrent.futures.ProcessPoolExecutor(max_workers=num_workers)
    main_pbar = tqdm(total=len(stock_files), desc="总体进度 ", position=num_workers)

    successful_stocks = []
    skipped_stocks = []
    failed_stocks = []

    try:
        futures = {}
        for i, stock_file in enumerate(stock_files):
            worker_position = i % num_workers
            tqdm.write(f"[提交任务] -> {stock_file.name}")
            future = executor.submit(process_stock_file, stock_file, target_year, worker_position)
            futures[future] = stock_file.name

        for future in concurrent.futures.as_completed(futures):
            stock_name = futures[future]
            try:
                status, code, message = future.result()
                if status == "SUCCESS":
                    successful_stocks.append(code)
                elif status == "SKIPPED":
                    skipped_stocks.append(code)
                elif status == "FAILED":
                    failed_stocks.append({"code": code, "reason": message})
            except concurrent.futures.process.BrokenProcessPool:
                tqdm.write(f"\n!!!!!! 严重错误: 处理 {stock_name} 的进程池已损坏 !!!!!!")
                failed_stocks.append({"code": stock_name, "reason": "进程意外终止 (很可能是内存耗尽 OOM)"})
                raise
            except Exception as exc:
                failed_stocks.append({"code": stock_name, "reason": f"任务执行框架错误: {exc}"})

            main_pbar.update(1)

    except (KeyboardInterrupt, concurrent.futures.process.BrokenProcessPool):
        # 捕获异常的逻辑保持不变
        exc_info = sys.exc_info()
        if isinstance(exc_info[1], KeyboardInterrupt):
            tqdm.write("\n\n捕获到 Ctrl+C, 正在强制关闭所有子进程...")
        else:
            tqdm.write("\n\n检测到进程池损坏，正在强制关闭剩余子进程...")

        for process in executor._processes.values():
            process.kill()

    finally:
        # 总结报告的逻辑保持不变
        executor.shutdown(wait=False)
        main_pbar.close()

        print("\n" * (num_workers + 2))
        print("=" * 50)
        print("任务已结束。")
        print(f"总计任务: {len(stock_files)}")
        print(f"  - 成功: {len(successful_stocks)}")
        print(f"  - 跳过: {len(skipped_stocks)}")
        print(f"  - 失败: {len(failed_stocks)}")
        print("=" * 50)

        if failed_stocks:
            print("\n失败的股票列表及原因:")
            for item in failed_stocks:
                reason_lines = str(item["reason"]).split("\n")
                print(f"  - 代码: {item['code']}")
                print(f"    原因: {reason_lines[0]}")
                for line in reason_lines[1:]:
                    print(f"          {line}")
        print("\n")


if __name__ == "__main__":
    run_parallel_precomputation(target_year=2024)
