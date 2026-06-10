"""Application settings.

Single, typed source of truth for configuration. Values come from environment
variables and the local `.env` file. If a required variable is missing the app
fails fast at startup instead of breaking later at runtime.

Django equivalent: `settings.py` + django-environ.
"""

from functools import lru_cache

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "dev"
    sql_echo: bool = False  # set true to log every SQL query (debugging only)

    # Auth / JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # CORS — comma-separated list in the .env (the Expo app origins)
    cors_origins: str = "http://localhost:8081"

    # Database (async driver)
    database_url: str

    # SAP (DEV) — credentials live ONLY here, never in the repo
    sap_base_url: str
    sap_user: str
    sap_password: str = ""
    sap_timeout_seconds: float = 30.0

    @field_validator("jwt_algorithm")
    @classmethod
    def _validate_jwt_algorithm(cls, value: str) -> str:
        allowed = {"HS256", "HS384", "HS512"}
        if value not in allowed:
            raise ValueError(f"JWT_ALGORITHM debe ser uno de {sorted(allowed)}.")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret(cls, value: str, info: ValidationInfo) -> str:
        # Fail fast if the example placeholder is still in use: a public, committed
        # string would let anyone forge a valid token for any user/role.
        if value.startswith("change-me"):
            raise ValueError(
                "JWT_SECRET sigue siendo el placeholder de ejemplo. Genera uno real con "
                '`python -c "import secrets; print(secrets.token_urlsafe(32))"`.'
            )
        # Enforce real entropy outside dev (token_urlsafe(32) yields ~43 chars).
        if info.data.get("app_env", "dev") != "dev" and len(value) < 32:
            raise ValueError("JWT_SECRET debe tener al menos 32 caracteres fuera de 'dev'.")
        return value

    @field_validator("sap_base_url")
    @classmethod
    def _validate_sap_base_url(cls, value: str, info: ValidationInfo) -> str:
        # Basic Auth over plain HTTP exposes the technical user's credentials in transit.
        # The DEV endpoint is http by external imposition; require TLS everywhere else.
        if info.data.get("app_env", "dev") != "dev" and not value.startswith("https://"):
            raise ValueError("SAP_BASE_URL debe usar https:// fuera de 'dev'.")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    # Cached so the .env is read once per process. Required fields without a value
    # raise a validation error here at startup (fail fast).
    return Settings()
