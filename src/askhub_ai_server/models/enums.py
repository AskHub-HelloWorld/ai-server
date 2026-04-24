"""도메인 상태/역할 Enum 정의."""

from enum import StrEnum


class MessageStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SourceStatus(StrEnum):
    REGISTERED = "registered"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"


class FilePurpose(StrEnum):
    CHAT_ATTACHMENT = "chat_attachment"
    RAG_SOURCE = "rag_source"


class SourceType(StrEnum):
    REPOSITORY = "repository"
    DOCUMENT = "document"


class JobMode(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class ResponseType(StrEnum):
    RAG = "rag"
    GENERAL = "general"
