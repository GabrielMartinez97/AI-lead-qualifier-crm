from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "NexusLead AI — Agente Cualificador de Leads & CRM"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = (
        "Plataforma backend de automatización comercial con IA (Gemini + BANT Scoring), "
        "ingesta multi-canal por Webhooks/APIs/CSV, CRM Pipeline y secuencias de seguimiento."
    )
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str = "sqlite:///./ai_lead_crm.db"

    # Gemini API Configuration (falls back to deterministic BANT AI engine if empty)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"

    # Security / Webhook verification
    WEBHOOK_SECRET: str = "whsec_nexus_lead_demo_2026"
    OUTBOUND_WEBHOOK_URL: str = ""

    # Automation flags
    AUTO_QUALIFY_ON_INGEST: bool = True
    AUTO_ENROLL_SEQUENCE_ON_QUALIFY: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
