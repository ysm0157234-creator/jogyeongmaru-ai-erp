from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "조경마루 AI ERP API"
    database_url: str = "sqlite:///./jogyeongmaru-local.db"
    secret_key: str = "development-secret-change-me"
    access_token_expire_minutes: int = 720

    admin_email: str = "admin@jogyeongmaru.co.kr"
    admin_password: str = "ChangeMe123!"
    cors_origins: str = "*"

    # Google Drive
    google_service_account_json: str = ""
    shipment_overview_file_id: str = ""
    import_2025_folder_id: str = ""

    # Google Programmable Search
    google_search_api_key: str = ""
    google_search_engine_id: str = ""

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
