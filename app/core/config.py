"""Application configuration using environment-driven settings.

This module exposes the central :class:`Settings` object plus the cached
``get_settings()`` accessor. The original (foundation) fields used by existing
code -- ``database_url``, ``secret_key``, ``access_token_expire_minutes``,
``token_algorithm`` and ``bcrypt_work_factor`` -- are preserved verbatim. The
additional fields below add observability, caching, Celery, JWT, database-pool
and CORS configuration. Every new field carries a safe default so the
application keeps booting without an ``.env`` file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings loaded from environment.

    Fields are grouped by concern. All additions are env-driven via
    pydantic-settings v2 and default to development-friendly values.
    """

    # ------------------------------------------------------------------
    # Core / pre-existing fields (DO NOT change names or semantics).
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/logistics",
        description="SQLAlchemy-compatible database URL.",
    )
    secret_key: str = Field(
        default="change-this-secret-key",
        min_length=32,
        description="JWT signing secret; must be strong and rotated in production.",
    )
    access_token_expire_minutes: int = Field(
        default=60,
        ge=5,
        le=24 * 60,
        description="Access token lifetime in minutes.",
    )
    token_algorithm: Literal["HS256"] = Field(
        default="HS256",
        description="JWT signing algorithm.",
    )
    bcrypt_work_factor: int = Field(
        default=12,
        ge=8,
        le=16,
        description="bcrypt rounds for password hashing.",
    )

    # ------------------------------------------------------------------
    # Application / environment metadata.
    # ------------------------------------------------------------------
    environment: Literal["development", "staging", "production", "test"] = Field(
        default="development",
        description="Deployment environment name; drives behavioral toggles.",
    )
    app_name: str = Field(
        default="Mesaar Logistics Operations API",
        description="Human-readable application/service name.",
    )
    app_version: str = Field(
        default="1.0.0",
        description="Semantic version of the running application.",
    )
    debug: bool = Field(
        default=False,
        description="Enable verbose debug behavior; never enable in production.",
    )
    api_v1_prefix: str = Field(
        default="/v1",
        description="URL prefix for versioned API routes (ADR-005).",
    )

    # ------------------------------------------------------------------
    # CORS.
    # ------------------------------------------------------------------
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins; accepts a comma-separated env string.",
    )

    # ------------------------------------------------------------------
    # Logging / observability.
    # ------------------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        description="Root log level (e.g. DEBUG, INFO, WARNING, ERROR).",
    )
    log_json: bool = Field(
        default=True,
        description="Emit structured JSON logs when True, else pretty console logs.",
    )
    request_id_header: str = Field(
        default="X-Request-ID",
        description="HTTP header carrying the per-request correlation id.",
    )
    tenant_header: str = Field(
        default="X-Tenant-ID",
        description="HTTP header carrying the tenant id for multi-tenant scoping.",
    )
    prometheus_enabled: bool = Field(
        default=True,
        description="Mount Prometheus metrics middleware and /metrics endpoint.",
    )

    # ------------------------------------------------------------------
    # Redis / cache.
    # ------------------------------------------------------------------
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL used for caching and token denylists.",
    )
    cache_ttl_seconds: int = Field(
        default=300,
        ge=0,
        description="Default cache entry time-to-live in seconds.",
    )

    # ------------------------------------------------------------------
    # Celery.
    # ------------------------------------------------------------------
    celery_broker_url: str = Field(
        default="redis://localhost:6379/1",
        description="Celery broker connection URL.",
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2",
        description="Celery result backend connection URL.",
    )
    celery_task_max_retries: int = Field(
        default=3,
        ge=0,
        description="Default maximum retry attempts for Celery tasks.",
    )
    celery_task_default_retry_delay: int = Field(
        default=5,
        ge=0,
        description="Default delay (seconds) before retrying a failed Celery task.",
    )

    # ------------------------------------------------------------------
    # JWT / refresh tokens.
    # ------------------------------------------------------------------
    refresh_token_expire_minutes: int = Field(
        default=60 * 24 * 14,
        ge=1,
        description="Refresh token lifetime in minutes (default 14 days).",
    )
    jwt_issuer: str = Field(
        default="mesaar",
        description="Expected 'iss' claim for issued/validated JWTs.",
    )
    jwt_audience: str = Field(
        default="mesaar-clients",
        description="Expected 'aud' claim for issued/validated JWTs.",
    )

    # ------------------------------------------------------------------
    # Database connection pool.
    # ------------------------------------------------------------------
    db_pool_size: int = Field(
        default=5,
        ge=1,
        description="SQLAlchemy connection pool size.",
    )
    db_max_overflow: int = Field(
        default=10,
        ge=0,
        description="Maximum overflow connections beyond the pool size.",
    )
    db_pool_timeout: int = Field(
        default=30,
        ge=1,
        description="Seconds to wait for a connection from the pool before failing.",
    )
    db_pool_recycle_seconds: int = Field(
        default=1800,
        ge=-1,
        description="Recycle pooled connections older than this many seconds.",
    )
    db_echo: bool = Field(
        default=False,
        description="Echo SQL statements to logs; useful only for debugging.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Validators.
    # ------------------------------------------------------------------
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: Any) -> Any:
        """Allow CORS origins to be supplied as a comma-separated string.

        Environment variables are always strings, so an operator may set
        ``CORS_ORIGINS=https://a.com,https://b.com``. We split such a value
        into a clean list. A native list (e.g. from code/JSON) passes through
        unchanged.
        """
        if isinstance(value, str):
            # Empty / whitespace-only string means "no explicit origins".
            stripped = value.strip()
            if not stripped:
                return []
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    # ------------------------------------------------------------------
    # Computed properties.
    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        """Return True when running in the production environment."""
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
