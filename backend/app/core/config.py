from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "mysql+pymysql://jobapply:change-me@localhost:3306/jobapply"
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    fernet_key: str = ""
    # Which LLM does resume parsing, job scoring and form-field mapping:
    # gemini (free tier) | groq (free tier) | ollama (local, free) | anthropic (paid API)
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:7b"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    cors_origins: str = "http://localhost:5173"
    storage_dir: str = "./storage"
    indeed_base_url: str = "https://in.indeed.com"  # use your country's Indeed domain
    playwright_headless: bool = True
    playwright_executable: str = ""  # optional path to chrome/chromium
    apply_gap_min_s: float = 20.0  # human-like pause between application attempts
    apply_gap_max_s: float = 60.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
