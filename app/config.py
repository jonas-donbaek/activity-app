from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    strava_client_id: str = ""
    strava_client_secret: str = ""
    webhook_verify_token: str = "default-verify-token"
    secret_key: str = "change-me-in-production"
    base_url: str = "http://localhost:8000"
    database_url: str = "sqlite+aiosqlite:///./data/coach.db"

    # Runner profile
    max_heart_rate: int = 188
    zone1_ceiling: int = 113
    zone2_ceiling: int = 141
    zone3_ceiling: int = 150
    zone4_ceiling: int = 169

    # Race info
    race_date: str = "2026-06-14"
    race_name: str = "BESTSELLER Aarhus City Half Marathon"
    target_hm_time_minutes: int = 120  # target half marathon time in minutes

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
