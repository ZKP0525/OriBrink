import json
import os
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "OriBrink API"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "oribrink"
    postgres_user: str = "oribrink"
    postgres_password: str = "oribrink"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    scheduler_heartbeat_seconds: int = 60
    rqdata_market: str = "cn"
    rqdata_auth_mode: str = "auto"
    rqdata_uri: str = ""
    rqdata_license: str = ""
    rqdata_host: str = "rqdatad-pro.ricequant.com"
    rqdata_port: int = 16011
    rqdata_init_kwargs_json: str = "{}"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def postgres_dsn(self) -> str:
        return (
            "postgresql+psycopg://"
            f"{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_dsn(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def rqdata_init_kwargs(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.rqdata_init_kwargs_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("RQDATA_INIT_KWARGS_JSON must be a valid JSON object") from exc

        if not isinstance(parsed, dict):
            raise ValueError("RQDATA_INIT_KWARGS_JSON must parse to a JSON object")

        return parsed

    @property
    def rqdata_resolved_uri(self) -> str:
        if self.rqdata_uri:
            return self.rqdata_uri
        if self.rqdata_license:
            return f"rqdata://license:{self.rqdata_license}@{self.rqdata_host}:{self.rqdata_port}"
        return ""

    def apply_rqdata_runtime_env(self) -> None:
        """
        Export runtime env used by rqdatac when uri/license auth is selected.
        """
        uri = self.rqdata_resolved_uri
        if uri:
            os.environ["RQDATAC2_CONF"] = uri


settings = Settings()
