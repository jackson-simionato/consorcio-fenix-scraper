from __future__ import annotations

from functools import cached_property
from urllib.parse import urljoin

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", populate_by_name=True)

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/consorcio_fenix"
    log_level: str = "INFO"
    base_url: str = Field(default="https://www.consorciofenix.com.br", validation_alias="CONSORCIO_FENIX_BASE_URL")
    route_index_path: str = Field(default="/horarios", validation_alias="CONSORCIO_FENIX_ROUTE_INDEX_PATH")
    user_agent: str = Field(
        default="consorcio-fenix-scraper/0.1 (+https://github.com/)",
        validation_alias="CONSORCIO_FENIX_USER_AGENT",
    )
    http_timeout_seconds: float = Field(default=20.0, validation_alias="CONSORCIO_FENIX_HTTP_TIMEOUT_SECONDS")
    http_retries: int = Field(default=2, validation_alias="CONSORCIO_FENIX_HTTP_RETRIES")
    http_rate_limit_seconds: float = Field(default=0.5, validation_alias="CONSORCIO_FENIX_HTTP_RATE_LIMIT_SECONDS")
    http_concurrency: int = Field(default=4, validation_alias="CONSORCIO_FENIX_HTTP_CONCURRENCY")

    @cached_property
    def route_index_url(self) -> str:
        return urljoin(f"{self.base_url.rstrip('/')}/", self.route_index_path.lstrip("/"))


def load_config() -> ProjectConfig:
    return ProjectConfig()
