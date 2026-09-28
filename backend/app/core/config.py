"""读取并校验应用环境配置。"""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服务运行所需的环境配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    log_level: str = "INFO"
    max_review_chars: int = Field(default=50_000, ge=1_000, le=200_000)

    llm_provider: str = "openai_compatible"
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None

    ragflow_base_url: str | None = "http://localhost:9380"
    ragflow_api_key: str | None = None
    ragflow_dataset_id: str | None = None

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """确保 API 前缀以单个斜线开头且不以斜线结尾。"""
        normalized = "/" + value.strip("/")
        return normalized if normalized != "/" else "/api/v1"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """只允许标准日志级别。"""
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL 必须是 DEBUG、INFO、WARNING、ERROR 或 CRITICAL")
        return normalized

    @field_validator("llm_base_url", "ragflow_base_url")
    @classmethod
    def validate_optional_http_url(cls, value: str | None) -> str | None:
        """配置了服务地址时校验 HTTP 协议和主机名。"""
        if value is None or not value.strip():
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("服务地址必须是有效的 HTTP 或 HTTPS URL")
        return value.rstrip("/")

    def readiness_issues(self) -> list[str]:
        """返回就绪检查中缺失或不受支持的配置项名称。"""
        issues: list[str] = []
        if self.llm_provider != "openai_compatible":
            issues.append("LLM_PROVIDER 当前只支持 openai_compatible")
        if not self.llm_model:
            issues.append("缺少 LLM_MODEL")
        if not self.llm_api_key:
            issues.append("缺少 LLM_API_KEY")
        if not self.ragflow_base_url:
            issues.append("缺少 RAGFLOW_BASE_URL")
        if not self.ragflow_api_key:
            issues.append("缺少 RAGFLOW_API_KEY")
        if not self.ragflow_dataset_id:
            issues.append("缺少 RAGFLOW_DATASET_ID")
        return issues


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取进程级缓存的应用配置。"""
    return Settings()
