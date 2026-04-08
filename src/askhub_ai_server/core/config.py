from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AskHub AI Server"
    app_env: str = "local"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # AWS Bedrock
    aws_region: str = "ap-southeast-2"
    aws_bearer_token_bedrock: str = ""
    bedrock_model_id: str = "amazon.nova-micro-v1:0"
    use_bedrock: bool = False  # EC2 IAM Role 환경에서 True로 설정

    # Database and file storage
    database_url: str = "postgresql+psycopg://askhub:askhub@postgres:5432/askhub"
    db_schema: str = "ai"
    upload_dir: str = "/app/uploads"

    backend_base_url: str = "http://localhost:8080"
    allowed_origins_raw: str = Field(default="", alias="ALLOWED_ORIGINS")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        if not self.allowed_origins_raw:
            return ["http://localhost:3000", "http://localhost:5173"]
        return [origin.strip() for origin in self.allowed_origins_raw.split(",") if origin.strip()]

    @property
    def bedrock_available(self) -> bool:
        return self.use_bedrock or bool(self.aws_bearer_token_bedrock)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
