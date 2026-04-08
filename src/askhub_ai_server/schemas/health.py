from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """서버 상태 확인 응답."""

    service: str = Field(description="서비스 이름")
    environment: str = Field(description="실행 환경 (local, dev, prod)")
    version: str = Field(description="서버 버전")
    status: str = Field(description="상태 (ok)")

