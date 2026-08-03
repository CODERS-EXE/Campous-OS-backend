from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "CampusOS"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "campusos"

    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    ALLOWED_ORIGINS: str = "http://localhost:3000,https://campous-os-frontend.vercel.app,https://campous-os-frontend-eiv93he0h-team-poonam.vercel.app"

    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    REDIS_URL: str = ""

    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    AI_RATE_LIMIT_PER_MINUTE: int = 10
    
    SETUP_KEY: str = ""  # Optional: Set to secure the seed endpoint

    @property
    def allowed_origins_list(self) -> List[str]:
        origins = [o.strip() for o in self.ALLOWED_ORIGINS.replace('\n', '').split(",") if o.strip()]
        # Always include the main Vercel URL
        vercel_urls = [
            "https://campous-os-frontend.vercel.app",
            "https://campous-os-frontend-eiv93he0h-team-poonam.vercel.app"
        ]
        for vercel_url in vercel_urls:
            if vercel_url not in origins:
                origins.append(vercel_url)
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
