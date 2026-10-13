import secrets

from typing import Optional
from pydantic import Field, HttpUrl, field_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  

    BOT_TOKEN: str = Field(..., description="Telegram Bot API token")
    BACKEND_URL: HttpUrl = Field(..., description="Base URL of the FastAPI backend")
    BOT_PUBLIC_URL: Optional[HttpUrl] = Field(None, description="Public URL of this bot for Telegram webhooks")
    BACKEND_SECRET: str = Field(
        ...,
        validation_alias=AliasChoices("BACKEND_SECRET", "TELEGRAM_WEBHOOK_SECRET"),
        description="Secret key for authenticating with the backend",
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
    
    PRO_PRICE_BIRR: int = Field(300, description="Price of PRO in Birr, shown in every upgrade message")

    ENVIRONMENT: str = Field("development", description="Environment mode: 'development' or 'production'")
    REDIS_URL: Optional[str] = Field(None, description="Prod Redis URL for FSM storage.")
    DEV_REDIS_URL: str = Field("redis://localhost:6379/1", description="Dev Redis URL for FSM storage fallback.")


    @field_validator("BACKEND_SECRET")
    @classmethod
    def _require_strong_secret(cls, v: str) -> str:
        if not v or len(v.strip()) < 16:
            raise ValueError('BACKEND_SECRET is too short (minimum 16 characters required)')
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra fields in .env not defined in Settings
        hide_input_in_errors=True,  # never print secret values in startup errors
    )


# Initialize settings
settings = Settings()
