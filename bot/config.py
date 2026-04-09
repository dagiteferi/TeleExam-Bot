import secrets

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings for the TeleExam AI Telegram Bot.

    Settings are loaded from environment variables, with defaults provided
    where appropriate. This ensures sensitive information is not hardcoded
    and configuration is flexible.
    """

    BOT_TOKEN: str = Field(..., description="Telegram Bot API token")
    BACKEND_URL: HttpUrl = Field(..., description="Base URL of the FastAPI backend")
    BACKEND_SECRET: str = Field(
        ..., description="Secret key for authenticating with the backend"
    )
    WEBHOOK_PATH: str = Field(
        "/webhook", description="Path for the Telegram webhook endpoint"
    )
    WEBHOOK_SECRET: str = Field(
        default_factory=lambda: secrets.token_hex(32),
        description="Secret token for webhook validation",
    )
    HOST: str = Field("0.0.0.0", description="Host address for the aiohttp server")
    PORT: int = Field(8080, description="Port for the aiohttp server")
    REDIS_URL: str = "redis://localhost:6379/1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra fields in .env not defined in Settings
    )


# Initialize settings
settings = Settings()
