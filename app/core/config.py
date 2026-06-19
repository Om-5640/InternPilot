from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str  # postgresql+asyncpg://...

    # JWT
    JWT_SECRET: str
    JWT_ALG: str = "HS256"
    ACCESS_TTL: int = 3600       # seconds
    REFRESH_TTL: int = 604800    # seconds (7 d)

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""

    # GitHub — optional; raises rate limit from 60 to 5000 req/hr
    GITHUB_TOKEN: str = ""

    # LLM providers — all optional so missing key = provider skipped
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    OLLAMA_URL: str = ""

    # Aggregation — when True only ingest postings whose title contains "intern"
    INTERNSHIP_FILTER: bool = True

    # USAJobs API — federal internships across ALL fields (optional)
    # Register free at https://developer.usajobs.gov/
    USAJOBS_API_KEY: str = ""
    USAJOBS_EMAIL: str = ""     # the email used to register

    # Adzuna API — cross-industry aggregator (optional)
    # Register free at https://developer.adzuna.com/
    ADZUNA_APP_ID: str = ""
    ADZUNA_APP_KEY: str = ""
    ADZUNA_COUNTRY: str = "us"

    # Firecrawl — research program portal scraper (optional)
    # Register free at https://firecrawl.dev — 500 scrapes/month on free tier
    FIRECRAWL_API_KEY: str = ""  # us | gb | de | au | in | ca

    # CORS — comma-separated string in env, parsed to list
    CORS_ORIGINS: str = "http://localhost:3000"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors(cls, v: object) -> object:
        # allow list[str] passed directly in tests
        if isinstance(v, list):
            return ",".join(v)
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
