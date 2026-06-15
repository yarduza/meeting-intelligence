from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    assemblyai_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-pro"
    gemini_transcription_model: str = "gemini-2.5-pro"
    hf_token: str = ""
    default_transcription_provider: str = "assemblyai"


settings = Settings()
