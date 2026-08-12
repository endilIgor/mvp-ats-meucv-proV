from app.settings import Settings


def test_settings_default_to_postgres_and_cache_ttl():
    settings = Settings()

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.cache_ttl_seconds == 300
