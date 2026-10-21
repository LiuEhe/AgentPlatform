"""读取并校验应用环境配置。"""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_INSTITUTION_REVIEW_CONCURRENCY = 3


class Settings(BaseSettings):
    """服务运行所需的环境配置。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    log_level: str = "INFO"
    langfuse_enabled: bool = False
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "http://127.0.0.1:3000"
    langfuse_capture_content: bool = False
    langfuse_sample_rate: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)
    langfuse_timeout_seconds: int = Field(default=2, gt=0)
    langfuse_prompts_enabled: bool = False
    langfuse_prompt_label: str = "production"
    langfuse_prompt_cache_ttl_seconds: int = Field(default=60, ge=0)
    langfuse_cost_model: str | None = None
    langfuse_input_cny_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    langfuse_output_cny_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    langfuse_cached_input_cny_per_million: Decimal | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    max_review_chars: int = Field(default=50_000, ge=1_000, le=200_000)
    max_upload_bytes: int = Field(default=20_971_520, ge=1)
    document_export_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    document_export_concurrency: int = Field(default=2, gt=0)
    document_export_max_chars: int = Field(default=200000, gt=0, le=200000)
    document_export_max_body_bytes: int = Field(default=1048576, gt=0)
    document_export_max_output_bytes: int = Field(default=10485760, gt=0)
    institution_review_concurrency: int = Field(
        default=DEFAULT_INSTITUTION_REVIEW_CONCURRENCY,
        ge=1,
    )
    conversation_idle_seconds: float = Field(default=7200, gt=0, allow_inf_nan=False)
    conversation_lifetime_seconds: float = Field(default=28800, gt=0, allow_inf_nan=False)
    conversation_max_sessions: int = Field(default=100, gt=0)
    conversation_max_bytes: int = Field(default=134217728, gt=0)
    conversation_concurrency: int = Field(default=3, gt=0)
    conversation_queue_size: int = Field(default=6, ge=0)
    conversation_run_timeout_seconds: float = Field(default=600, gt=0, allow_inf_nan=False)
    conversation_queue_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)

    llm_provider: str = "openai_compatible"
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_timeout_seconds: int = Field(default=180, ge=30, le=600)

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

    @field_validator("llm_base_url", "ragflow_base_url", "langfuse_base_url")
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
        return self.model_issues()

    def model_issues(self) -> list[str]:
        """检查聊天模型配置，不要求知识库可用。"""
        issues: list[str] = []
        if self.llm_provider != "openai_compatible":
            issues.append("LLM_PROVIDER 当前只支持 openai_compatible")
        if not self.llm_model:
            issues.append("缺少 LLM_MODEL")
        if not self.llm_api_key:
            issues.append("缺少 LLM_API_KEY")
        return issues

    def ragflow_issues(self) -> list[str]:
        """检查仅知识库审核需要的配置。"""
        issues: list[str] = []
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
