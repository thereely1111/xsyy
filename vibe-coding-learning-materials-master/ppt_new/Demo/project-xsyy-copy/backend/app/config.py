import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "象数演易 (XSYY)"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    DATABASE_URL: str = "mysql+pymysql://xsyy:xsyy_secret@localhost:3306/xsyy"
    DATABASE_ECHO: bool = False

    REDIS_URL: str = "redis://localhost:6379/0"

    CHROMA_PATH: str = "./chroma_data"

    JWT_SECRET_KEY: str = "your-super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-pro"

    OPENAI_API_KEY: str = ""
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    CORS_ORIGINS: list = ["http://localhost:8000", "http://localhost:3000"]

    UPLOAD_DIR: str = "./uploads"
    GENERATED_APPS_DIR: str = "./generated_apps"
    MAX_UPLOAD_SIZE: int = 5 * 1024 * 1024

    AI_ANALYZE_TIMEOUT: int = 30
    AI_GENERATE_TIMEOUT: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
