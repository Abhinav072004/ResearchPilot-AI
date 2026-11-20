from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RP_", extra="ignore")
    database_url: str = "sqlite:///./data/researchpilot.db"
    redis_url: str = ""
    local_objects: Path = Path("data/objects")
    s3_bucket: str = ""
    s3_endpoint: str | None = None
    secure_cookie: bool = False
    origin: str = ""
    upload_bytes: int = 15 * 1024 * 1024
    grobid_url: str = ""
    docling_url: str = ""
    ocr_languages: str = "eng"
    clamd_host: str = ""
    openalex_key: str = ""
    semantic_scholar_key: str = ""
    core_key: str = ""
    llm_url: str = ""
    llm_key: str = ""
    llm_model: str = ""
    llm_max_calls: int = 1
    llm_input_per_million: float = 0
    llm_output_per_million: float = 0
    environment: str = "development"


@lru_cache
def settings() -> Settings:
    config = Settings()
    if config.environment == "production" and (
        not config.secure_cookie or not config.origin.startswith("https://")
        or not config.database_url.startswith("postgresql+psycopg://")
        or not config.redis_url or not config.s3_bucket or not config.clamd_host
    ):
        raise ValueError("Production requires HTTPS origin, secure cookies, PostgreSQL, Redis, S3 and malware scanning")
    return config
