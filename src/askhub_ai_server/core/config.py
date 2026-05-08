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
    bedrock_model_id: str = "amazon.nova-lite-v1:0"
    bedrock_embed_model_id: str = "amazon.titan-embed-text-v2:0"

    # RAG retrieval
    rag_embedding_dimensions: int = 1024
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.3
    rag_answerable_threshold: float = 0.5
    rag_max_context_tokens: int = 4000

    # Hybrid search (vector + BM25)
    rag_bm25_enabled: bool = True
    rag_rrf_k: int = 60
    rag_retrieval_k: int = 20

    # Korean morphological analysis for BM25
    korean_tokenizer_enabled: bool = True

    # Neighbor chunk expansion (contextual retrieval)
    rag_neighbor_chunks_enabled: bool = True
    rag_neighbor_window: int = 1

    # Previous turn RAG context preservation
    rag_context_preservation_enabled: bool = True

    # Query routing / intent classification
    query_routing_enabled: bool = True

    # Conversation history summarization
    history_summarize_enabled: bool = True
    history_summarize_threshold: int = 14
    history_recent_count: int = 10

    # Database
    database_url: str
    db_schema: str = "ai"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 10
    db_pool_recycle: int = 1800
    file_storage_backend: str = "s3"
    s3_bucket: str = ""
    s3_region: str = "ap-northeast-2"
    s3_prefix: str = "ai-server/user-files"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_file_context_bytes: int = 50 * 1024
    max_files_per_message: int = 5
    allowed_upload_content_types_raw: str = Field(
        default=(
            "text/plain,text/markdown,application/json,application/xml,text/csv,"
            "image/png,image/jpeg,image/jpg,image/gif,image/webp,"
            "application/pdf,"
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        alias="ALLOWED_UPLOAD_CONTENT_TYPES",
    )
    max_history_messages: int = 20

    # Pagination
    default_page_limit: int = 20
    max_page_limit: int = 100

    # LLM resilience
    llm_timeout_seconds: int = 60
    llm_circuit_failure_threshold: int = 5
    llm_circuit_recovery_seconds: int = 30

    # Service-to-service authentication. Backend must sign requests to ai-server.
    service_auth_enabled: bool = True
    service_auth_secret: str = ""
    service_auth_timestamp_tolerance_seconds: int = 300

    backend_base_url: str = "http://localhost:8080"
    allowed_origins_raw: str = Field(default="", alias="ALLOWED_ORIGINS")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        if not self.allowed_origins_raw:
            return ["http://localhost:3000", "http://localhost:5173"]
        return [origin.strip() for origin in self.allowed_origins_raw.split(",") if origin.strip()]

    @property
    def allowed_upload_content_types(self) -> set[str]:
        return {
            content_type.strip().lower()
            for content_type in self.allowed_upload_content_types_raw.split(",")
            if content_type.strip()
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
