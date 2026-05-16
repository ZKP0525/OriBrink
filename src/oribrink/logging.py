"""日志模块。

直接用 rich 的 RichHandler（rich 已是依赖），获得彩色、对齐、带时间的
结构化输出，无需自己拼格式串。便于定位"哪个接口/哪只股票/哪步"出错。
"""

from __future__ import annotations

import logging

from rich.logging import RichHandler

_CONFIGURED = False


def setup_logging(level: int | str = logging.INFO) -> None:
    """配置 oribrink 根 logger（幂等）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = RichHandler(
        rich_tracebacks=True, show_path=False, log_time_format="%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger("oribrink")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """获取带 oribrink 前缀的 logger，未配置时自动配置。"""
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(f"oribrink.{name}")
