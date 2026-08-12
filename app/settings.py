from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MeuCV.pro ATS"
    database_url: str = "postgresql+psycopg://meucv:meucv@postgres:5432/meucv"
    cache_ttl_seconds: int = 300
    auth_token_ttl_seconds: int = 60 * 60 * 24 * 7
    frontend_cache_seconds: int = 300

    model_config = SettingsConfigDict(env_file=".env", env_prefix="MEUCV_")
