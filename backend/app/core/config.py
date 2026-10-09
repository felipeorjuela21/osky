from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # SQLite by default so the project runs without Docker.
    # Set DATABASE_URL to postgresql+psycopg://... to use PostgreSQL.
    database_url: str = "sqlite:///./data/enterprise_agent.db"
    app_env: str = "development"  # "production" on the server
    log_level: str = "INFO"
    agent_name: str = "Osky"
    company_name: str = "CeluWeb"
    website_url: str = "https://www.celuweb.com/"
    # Demo customers/sales tables. Keep disabled until real company data is loaded,
    # otherwise the agent would answer with fake figures.
    enable_demo_data: bool = False

    # Groq (free tier): speech-to-text with Whisper and natural answers with Llama.
    groq_api_key: str = ""
    groq_stt_model: str = "whisper-large-v3-turbo"
    llm_model: str = "llama-3.3-70b-versatile"
    # Natural answers: "groq" rewrites the retrieved company text conversationally
    # (never adding facts); "none" reads the extracts. "auto" = groq if a key exists.
    llm_provider: str = "auto"

    # Text-to-speech: "azure" (official, free F0 tier), "edge" (free, unofficial),
    # "browser" (speechSynthesis only). "auto" = azure if a key exists, else edge.
    tts_provider: str = "auto"
    tts_voice: str = "es-CO-GonzaloNeural"
    tts_rate: str = "+6%"
    azure_speech_key: str = ""
    azure_speech_region: str = "eastus"

    # Speech-to-text: "groq" (cloud), "whisper" (local faster-whisper), "browser".
    # "auto" = groq if a key exists, else local whisper if installed, else browser.
    stt_provider: str = "auto"
    stt_model: str = "base"  # local whisper model

    # Security for the public deployment.
    admin_token: str = ""  # required for /api/knowledge/refresh in production
    rate_limit_per_minute: int = 30  # per visitor IP, for ask/tts/stt
    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174,https://localhost:5175"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def effective_llm(self) -> str:
        if self.llm_provider == "auto":
            return "groq" if self.groq_api_key else "none"
        return self.llm_provider

    @property
    def effective_tts(self) -> str:
        if self.tts_provider == "auto":
            return "azure" if self.azure_speech_key else "edge"
        return self.tts_provider

    @property
    def effective_stt(self) -> str:
        if self.stt_provider == "auto":
            if self.groq_api_key:
                return "groq"
            try:
                import faster_whisper  # noqa: F401
            except ImportError:
                return "browser"
            return "whisper"
        return self.stt_provider

settings = Settings()
