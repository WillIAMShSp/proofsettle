from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROOFSETTLE_", env_file=".env")

    # Any SQLAlchemy URL; swap for the Supabase Postgres URL later.
    database_url: str = "sqlite:///./proofsettle.db"


settings = Settings()
