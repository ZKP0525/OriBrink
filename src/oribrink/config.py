"""配置模块。

用 pydantic 做类型化 + 校验的配置模型（默认值与 PRD 10.8 一致），
用 stdlib tomllib 读 TOML 文件。TOML 按节覆盖默认值，未知键忽略。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class StrategyConfig(BaseModel):
    min_lianban_count: int = 3
    volume_ratio_threshold: float = 1.5
    gap_open_threshold: float = 0.03
    small_cap_threshold: float = 8_000_000_000.0
    small_cap_auction_ratio_qualified: float = 0.05
    small_cap_auction_ratio_excellent: float = 0.10
    large_cap_auction_ratio_qualified: float = 0.025


class SnapshotConfig(BaseModel):
    kanglong_enabled: bool = True
    qianlong_enabled: bool = True
    overwrite_on_rerun: bool = False


class StorageConfig(BaseModel):
    db_path: str = "data/oribrink.db"


class DataSourceConfig(BaseModel):
    retry_attempts: int = 2          # akshare 调用最大尝试次数（含首次）
    retry_backoff: float = 1.0       # 重试退避基数（秒），第 n 次睡 n*backoff
    request_interval: float = 0.3    # 逐股请求（日 K / 竞价）之间的间隔（秒）


class TushareConfig(BaseModel):
    token: str = ""
    endpoint: str = "http://tsy.xiaodefa.cn"
    raw_dir: str = "data/tushare/raw"
    request_interval: float = 0.65
    timeout: float = 30.0
    retry_attempts: int = 3
    retry_backoff: float = 10.0


class ExportConfig(BaseModel):
    default_format: str = "csv"
    dir: str = "exports"


class EmailConfig(BaseModel):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    use_ssl: bool = True
    username: str = ""
    password: str = ""
    sender: str = ""
    recipients: list[str] = Field(default_factory=list)
    send_when_empty: bool = False


class Config(BaseModel):
    storage: StorageConfig = Field(default_factory=StorageConfig)
    datasource: DataSourceConfig = Field(default_factory=DataSourceConfig)
    tushare: TushareConfig = Field(default_factory=TushareConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    snapshot: SnapshotConfig = Field(default_factory=SnapshotConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)


def _resolve_path(path: str | os.PathLike | None) -> Path | None:
    """显式 path > 环境变量 OB_CONFIG > ./config.toml > None（全默认）。"""
    if path:
        return Path(path)
    if os.environ.get("OB_CONFIG"):
        return Path(os.environ["OB_CONFIG"])
    if Path("config.toml").exists():
        return Path("config.toml")
    return None


def load_config(path: str | os.PathLike | None = None) -> Config:
    """加载并校验配置，文件不存在或类型错误均显式报错。"""
    candidate = _resolve_path(path)
    if candidate is None:
        return Config()
    if not candidate.exists():
        raise FileNotFoundError(f"配置文件不存在: {candidate}")
    raw = tomllib.loads(candidate.read_text(encoding="utf-8"))
    return Config.model_validate(raw)
