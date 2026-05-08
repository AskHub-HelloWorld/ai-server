"""DOCX + PDF RAG 통합 E2E 테스트 스위트.

10개 이커머스 플랫폼 문서(DOCX 5 + PDF 5)를 test-docs에서 직접 읽어
업로드·인제스트한 뒤 청킹 → 임베딩 → 검색 → Q&A → 인용 → 스트리밍까지
전 파이프라인을 검증한다.

실행:
    docker compose run --rm \\
        -v ../test-docs:/test-docs \\
        api-test python scripts/e2e_docx_pdf_rag_suite.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from askhub_ai_server.core.config import Settings, get_settings
from askhub_ai_server.core.database import SessionLocal, engine
from askhub_ai_server.core.security import build_service_signature
from askhub_ai_server.main import create_app
from askhub_ai_server.models.document import DocumentChunk, RagSource
from askhub_ai_server.services.embedding import get_embedding_service
from askhub_ai_server.services.retriever import PgVectorRetriever
from askhub_ai_server.worker import _claim_next_job, _process_job

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

USER_ID = 1
TEAM_ID = 10
MAX_CHUNK_CHARS = 8_000

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

DOCX_FILES = [
    "이커머스_플랫폼_API명세서_v1.3.docx",
    "이커머스_플랫폼_DB설계서_v2.1.docx",
    "이커머스_플랫폼_개발표준가이드_v1.0.docx",
    "이커머스_플랫폼_릴리즈노트_v1.0-v3.5.docx",
    "이커머스_플랫폼_보안점검보고서_v1.0.docx",
]

PDF_FILES = [
    "이커머스_플랫폼_성능테스트보고서_v1.2.pdf",
    "이커머스_플랫폼_아키텍처설계서_v3.0.pdf",
    "이커머스_플랫폼_요구사항명세서_v2.0.pdf",
    "이커머스_플랫폼_운영가이드_v1.5.pdf",
    "이커머스_플랫폼_장애보고서_모음_2024.pdf",
]


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityQuestion:
    question: str
    expected_terms: tuple[str, ...]
    category: str  # single_doc, cross_doc, korean_bm25, numeric, deep_analysis
    target_doc_keywords: tuple[str, ...] = ()
    difficulty: str = "medium"  # "easy", "medium", "hard"


QUESTIONS: tuple[QualityQuestion, ...] = (
    # =========================================================================
    # A. 단일문서 사실 확인 (single_doc) — 10개
    # =========================================================================
    QualityQuestion(
        "API 명세서에서 상품 목록 조회 API의 엔드포인트, HTTP 메서드, 주요 쿼리 파라미터를 설명해줘.",
        ("GET", "/products"),
        "single_doc", ("API명세서",), "easy",
    ),
    QualityQuestion(
        "DB 설계서에서 주문(ORDER) 관련 주요 테이블과 역할을 설명해줘.",
        ("orders",),
        "single_doc", ("DB설계서",), "easy",
    ),
    QualityQuestion(
        "아키텍처 설계서에서 서비스 간 통신 방식과 기술 스택을 설명해줘.",
        ("gRPC",),
        "single_doc", ("아키텍처",), "easy",
    ),
    QualityQuestion(
        "운영 가이드에서 카나리 배포 절차를 단계별로 설명해줘.",
        ("카나리", "배포"),
        "single_doc", ("운영가이드",), "medium",
    ),
    QualityQuestion(
        "개발 표준에서 서비스별 기술 스택과 Recommendation Service의 Python 선택 근거를 설명해줘.",
        ("Recommendation", "Python"),
        "single_doc", ("개발표준",), "easy",
    ),
    QualityQuestion(
        "보안점검 보고서에서 발견된 긴급 등급 취약점과 조치 방안을 설명해줘.",
        ("취약점",),
        "single_doc", ("보안점검",), "medium",
    ),
    QualityQuestion(
        "성능 테스트 보고서에서 Checkout Service의 P99 응답시간과 병목 원인을 설명해줘.",
        ("P99", "Checkout"),
        "single_doc", ("성능테스트",), "medium",
    ),
    QualityQuestion(
        "장애 보고서에서 P1 등급 장애의 원인과 복구 과정을 설명해줘.",
        ("장애",),
        "single_doc", ("장애보고서",), "medium",
    ),
    QualityQuestion(
        "DB 설계서에서 전체 데이터베이스의 논리 스키마 구성과 각 스키마의 담당 서비스를 설명해줘.",
        ("PRODUCT", "ORDER", "PAYMENT"),
        "single_doc", ("DB설계서",), "medium",
    ),
    QualityQuestion(
        "API 명세서에서 JWT 인증 방식과 Access Token, Refresh Token의 유효기간을 설명해줘.",
        ("JWT", "15"),
        "single_doc", ("API명세서",), "easy",
    ),
    # =========================================================================
    # B. 교차문서 종합 (cross_doc) — 6개
    # =========================================================================
    QualityQuestion(
        "Checkout Service에 대해 아키텍처, 성능, 장애 관점을 종합하여 설명해줘.",
        ("Checkout",),
        "cross_doc", (), "hard",
    ),
    QualityQuestion(
        "Astronomy Shop의 관측가능성(Observability) 전략을 아키텍처, 운영가이드, 개발표준에서 종합해줘.",
        ("OpenTelemetry",),
        "cross_doc", (), "hard",
    ),
    QualityQuestion(
        "보안점검 보고서에서 JWT 토큰 만료시간 24시간 문제가 지적되었는데, API 명세서에서 권장하는 토큰 유효기간과 비교하여 설명해줘.",
        ("JWT", "24"),
        "cross_doc", (), "hard",
    ),
    QualityQuestion(
        "INC-2024-001 장애에서 인덱스 누락이 원인이었는데, DB 설계서의 인덱스 전략과 비교하여 어떤 교훈을 얻을 수 있는지 설명해줘.",
        ("인덱스", "orders", "user_id"),
        "cross_doc", (), "hard",
    ),
    QualityQuestion(
        "요구사항 명세서의 성능 SLO 목표와 성능테스트 보고서의 실측 결과를 비교하여 달성 여부를 설명해줘.",
        ("SLO", "P99"),
        "cross_doc", (), "hard",
    ),
    QualityQuestion(
        "릴리즈노트 v3.5.0에서 도입된 Fraud Detection Service의 아키텍처와 기술 스택을 아키텍처 설계서와 종합하여 설명해줘.",
        ("Fraud Detection", "Kotlin"),
        "cross_doc", (), "medium",
    ),
    # =========================================================================
    # C. 한국어 BM25 키워드 (korean_bm25) — 4개
    # =========================================================================
    QualityQuestion(
        "릴리즈 노트에서 v3.0 메이저 릴리즈의 Breaking Changes를 나열해줘.",
        ("v3.0",),
        "korean_bm25", ("릴리즈노트",), "medium",
    ),
    QualityQuestion(
        "요구사항 명세서에서 비기능 요구사항 중 가용성과 성능 SLO 목표를 설명해줘.",
        ("가용성",),
        "korean_bm25", ("요구사항",), "medium",
    ),
    QualityQuestion(
        "운영 가이드에서 LogQL을 사용한 로그 조회 방법과 Grafana 연동 방식을 설명해줘.",
        ("LogQL", "Grafana"),
        "korean_bm25", ("운영가이드",), "medium",
    ),
    QualityQuestion(
        "보안점검 보고서에서 사용된 점검 방법론과 OWASP Top 10 기반 점검 항목을 설명해줘.",
        ("OWASP",),
        "korean_bm25", ("보안점검",), "easy",
    ),
    # =========================================================================
    # D. 수치/데이터 정확성 (numeric) — 5개
    # =========================================================================
    QualityQuestion(
        "보안점검 보고서에서 발견된 전체 취약점 수와 심각도별(Critical, High, Medium, Low) 분포를 알려줘.",
        ("42", "Critical"),
        "numeric", ("보안점검",), "easy",
    ),
    QualityQuestion(
        "성능 테스트에서 블랙프라이데이 급증 시나리오의 최대 가상 사용자(VU) 수와 사용된 부하 테스트 도구를 알려줘.",
        ("5,000", "k6"),
        "numeric", ("성능테스트",), "easy",
    ),
    QualityQuestion(
        "2024년 장애보고서에서 P1 등급 장애의 평균 MTTR과 연간 총 장애 건수를 알려줘.",
        ("49", "6"),
        "numeric", ("장애보고서",), "medium",
    ),
    QualityQuestion(
        "아키텍처 설계서에서 gRPC 서버의 기본 포트 번호와 최대 동시 스트림 수, 요청 타임아웃을 알려줘.",
        ("8080", "100"),
        "numeric", ("아키텍처",), "easy",
    ),
    QualityQuestion(
        "보안점검 보고서에서 SQL Injection 취약점의 CVSS 점수와 영향받는 서비스를 알려줘.",
        ("9.1", "Product Catalog"),
        "numeric", ("보안점검",), "medium",
    ),
    # =========================================================================
    # E. 심층 분석 (deep_analysis) — 5개
    # =========================================================================
    QualityQuestion(
        "아키텍처 설계서에서 Saga 패턴과 Circuit Breaker 패턴이 어떤 문제를 해결하며, 각각의 동작 방식을 설명해줘.",
        ("Saga", "Circuit Breaker"),
        "deep_analysis", ("아키텍처",), "hard",
    ),
    QualityQuestion(
        "아키텍처 설계서의 Kafka 토픽 설계에서 order 관련 토픽의 파티션 수와 구독 서비스들의 역할을 설명해줘.",
        ("order", "Kafka"),
        "deep_analysis", ("아키텍처",), "hard",
    ),
    QualityQuestion(
        "운영 가이드에서 프로덕션 Kubernetes 클러스터의 노드 그룹 구성과 각 그룹의 인스턴스 타입을 설명해줘.",
        ("m6i.xlarge", "r6i"),
        "deep_analysis", ("운영가이드",), "hard",
    ),
    QualityQuestion(
        "운영 가이드의 CI/CD 파이프라인에서 GitHub Actions부터 ArgoCD까지의 전체 배포 흐름을 설명해줘.",
        ("GitHub Actions", "ArgoCD"),
        "deep_analysis", ("운영가이드",), "medium",
    ),
    QualityQuestion(
        "장애보고서 INC-2024-001에서 gRPC 커넥션 풀 고갈과 인덱스 누락이 동시에 발생한 복합 장애의 근본 원인과 재발 방지 대책을 분석해줘.",
        ("gRPC", "인덱스", "user_id"),
        "deep_analysis", ("장애보고서",), "hard",
    ),
)


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _auth_headers(method: str, path: str) -> dict[str, str]:
    settings = get_settings()
    timestamp, signature = build_service_signature(
        secret=settings.service_auth_secret,
        method=method,
        path=path,
        query="",
        user_id=USER_ID,
        team_id=TEAM_ID,
        timestamp=int(time.time()),
    )
    return {
        "X-AskHub-User-Id": str(USER_ID),
        "X-AskHub-Team-Id": str(TEAM_ID),
        "X-AskHub-Timestamp": timestamp,
        "X-AskHub-Signature": signature,
    }


def _request(client: TestClient, method: str, path: str, **kwargs) -> Any:
    resp = client.request(method, path, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"{method} {path} → {resp.status_code}: {resp.text[:500]}")
    return resp


def _setup_db() -> Settings:
    """테스트 DB 스키마 마이그레이션 + 테이블 클린."""
    settings = get_settings()
    if settings.app_env != "test" or "test" not in settings.db_schema.lower():
        raise SystemExit(f"테스트 환경이 아닙니다: env={settings.app_env}, schema={settings.db_schema}")

    root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(root / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    tables = [
        "document_chunks", "ingestion_jobs", "rag_sources",
        "user_files", "messages", "chat_sessions",
    ]
    with engine.begin() as conn:
        for t in tables:
            conn.execute(text(f'DELETE FROM "{settings.db_schema}".{t}'))

    return settings


def _parse_sse_events(raw: str) -> list[tuple[str, dict]]:
    """SSE 스트림을 (event_name, data_dict) 리스트로 파싱한다."""
    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            try:
                data = json.loads("\n".join(data_lines))
                events.append((event_name, data))
            except json.JSONDecodeError:
                pass
    return events


# ---------------------------------------------------------------------------
# Phase 1: 문서 수집 (Ingestion)
# ---------------------------------------------------------------------------


def phase_1_ingest(
    client: TestClient,
    settings: Settings,
    test_docs_dir: Path,
) -> dict:
    """10개 문서를 업로드 → 소스 등록 → 인제스트 → 워커 실행."""
    embedding_service = get_embedding_service()
    results: list[dict] = []

    files_to_ingest: list[tuple[str, bytes, str]] = []

    # DOCX 파일
    for name in DOCX_FILES:
        path = test_docs_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"DOCX 파일 없음: {path}")
        files_to_ingest.append((name, path.read_bytes(), CONTENT_TYPES[".docx"]))

    # PDF 파일
    for name in PDF_FILES:
        path = test_docs_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"PDF 파일 없음: {path}")
        files_to_ingest.append((name, path.read_bytes(), CONTENT_TYPES[".pdf"]))

    for filename, data, content_type in files_to_ingest:
        print(f"  수집 중: {filename}", flush=True)

        upload_path = "/v1/files/upload"
        upload = _request(
            client, "POST", upload_path,
            headers=_auth_headers("POST", upload_path),
            files={"file": (filename, data, content_type)},
            data={"purpose": "rag_source"},
        ).json()

        source_path = "/v1/sources"
        source = _request(
            client, "POST", source_path,
            headers=_auth_headers("POST", source_path),
            json={"source_type": "document", "name": filename, "file_id": upload["id"]},
        ).json()

        job_path = "/v1/ingestion-jobs"
        job = _request(
            client, "POST", job_path,
            headers=_auth_headers("POST", job_path),
            json={"source_id": source["source_id"], "mode": "full"},
        ).json()

        claimed = _claim_next_job()
        if claimed is None:
            raise RuntimeError(f"워커가 잡을 클레임하지 못함: {filename}")
        _process_job(claimed, embedding_service, settings)

        get_path = f"/v1/ingestion-jobs/{job['job_id']}"
        indexed = _request(
            client, "GET", get_path,
            headers=_auth_headers("GET", get_path),
        ).json()

        results.append({
            "filename": filename,
            "file_id": upload["id"],
            "source_id": source["source_id"],
            "job_id": job["job_id"],
            "status": indexed["status"],
            "indexed_object_count": indexed["indexed_object_count"],
        })

    docx_results = [r for r in results if r["filename"].endswith(".docx")]
    pdf_results = [r for r in results if r["filename"].endswith(".pdf")]

    checks = {
        "all_10_jobs_succeeded": all(r["status"] == "succeeded" for r in results),
        "docx_5_jobs_succeeded": all(r["status"] == "succeeded" for r in docx_results),
        "pdf_5_jobs_succeeded": all(r["status"] == "succeeded" for r in pdf_results),
        "all_chunks_indexed": all(r["indexed_object_count"] > 0 for r in results),
        "min_3_chunks_per_doc": all(r["indexed_object_count"] >= 3 for r in results),
    }

    return {"checks": checks, "documents": results}


# ---------------------------------------------------------------------------
# Phase 2: 청킹 품질
# ---------------------------------------------------------------------------


def phase_2_chunking(settings: Settings) -> dict:
    """document_chunks 테이블에서 청킹 품질을 검증한다."""
    korean_re = re.compile(r"[\uAC00-\uD7AF]")

    with SessionLocal() as db:
        chunks = db.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.content,
                DocumentChunk.metadata_json,
                DocumentChunk.source_id,
            ).where(DocumentChunk.team_id == TEAM_ID)
        ).all()

        total = len(chunks)
        too_long = sum(1 for c in chunks if len(c.content) > MAX_CHUNK_CHARS)
        empty = sum(1 for c in chunks if not c.content.strip())
        has_korean = sum(1 for c in chunks if korean_re.search(c.content))
        has_heading = sum(
            1 for c in chunks
            if c.metadata_json and (
                c.metadata_json.get("heading") or c.metadata_json.get("heading_breadcrumb")
            )
        )

        source_counts = {}
        for c in chunks:
            source_counts[c.source_id] = source_counts.get(c.source_id, 0) + 1
        count_ok = all(3 <= v <= 500 for v in source_counts.values())

    checks = {
        "all_chunks_within_8000_chars": too_long == 0,
        "no_empty_content": empty == 0,
        "korean_text_ratio_gte_80pct": total > 0 and (has_korean / total) >= 0.8,
        "metadata_has_headings_gte_30pct": total > 0 and (has_heading / total) >= 0.3,
        "chunk_count_per_source_reasonable": count_ok,
    }
    stats = {
        "total_chunks": total,
        "too_long": too_long,
        "empty": empty,
        "korean_ratio": round(has_korean / total, 3) if total else 0,
        "heading_ratio": round(has_heading / total, 3) if total else 0,
        "source_chunk_counts": {str(k): v for k, v in source_counts.items()},
    }
    return {"checks": checks, "stats": stats}


# ---------------------------------------------------------------------------
# Phase 3: 임베딩 & DB 저장
# ---------------------------------------------------------------------------


def phase_3_embedding(settings: Settings) -> dict:
    """임베딩 벡터 저장 상태를 검증한다."""
    with SessionLocal() as db:
        total = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.team_id == TEAM_ID
            )
        )

        null_embedding = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.team_id == TEAM_ID,
                DocumentChunk.embedding.is_(None),
            )
        )

        null_embedding_text = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.team_id == TEAM_ID,
                DocumentChunk.embedding_text.is_(None),
            )
        )

        wrong_team = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.team_id != TEAM_ID,
            )
        )

        # 벡터 차원 샘플 확인
        sample = db.execute(
            select(DocumentChunk.embedding).where(
                DocumentChunk.team_id == TEAM_ID,
                DocumentChunk.embedding.isnot(None),
            ).limit(1)
        ).scalar()
        dim_ok = sample is not None and len(sample) == 1024

    checks = {
        "embedding_not_null": null_embedding == 0,
        "embedding_dimensions_1024": dim_ok,
        "team_id_correct": wrong_team == 0,
        "total_chunks_gte_50": total >= 50,
        "embedding_text_populated": null_embedding_text == 0,
    }
    return {"checks": checks, "total": total, "null_embedding": null_embedding}


# ---------------------------------------------------------------------------
# Phase 4: 검색 품질
# ---------------------------------------------------------------------------


def phase_4_retrieval(settings: Settings) -> dict:
    """PgVectorRetriever를 직접 호출하여 검색 품질을 검증한다."""
    embedding_service = get_embedding_service()
    checks: dict[str, bool] = {}

    with SessionLocal() as db:
        retriever = PgVectorRetriever(db, embedding_service, settings)

        # 벡터 검색
        vec_results = retriever.search("Checkout Service 결제 처리 아키텍처", TEAM_ID)
        checks["vector_search_returns_results"] = len(vec_results) > 0
        if vec_results:
            checks["top_result_similarity_above_threshold"] = vec_results[0].similarity >= 0.3

        # BM25 + 하이브리드 (기본적으로 hybrid)
        hybrid_results = retriever.search("Kubernetes 카나리 배포 절차", TEAM_ID)
        checks["hybrid_search_returns_results"] = len(hybrid_results) > 0

        # 교차 문서 검색
        cross_results = retriever.search("Checkout Service 성능 장애 아키텍처", TEAM_ID)
        if cross_results:
            source_ids = {r.source_id for r in cross_results}
            checks["cross_doc_retrieval"] = len(source_ids) > 1
        else:
            checks["cross_doc_retrieval"] = False

        # 이웃 청크 확장
        if vec_results:
            neighbors = retriever.fetch_neighbor_chunks(vec_results[:3], window=1)
            checks["neighbor_expansion_works"] = len(neighbors) > 0
        else:
            checks["neighbor_expansion_works"] = False

    return {
        "checks": checks,
        "vector_count": len(vec_results),
        "hybrid_count": len(hybrid_results),
        "cross_sources": len(source_ids) if cross_results else 0,
    }


# ---------------------------------------------------------------------------
# Phase 5: 챗봇 Q&A 품질
# ---------------------------------------------------------------------------


def phase_5_qa(client: TestClient) -> dict:
    """30개 도메인 질문으로 Q&A 품질을 검증한다."""
    question_results: list[dict] = []

    for q in QUESTIONS:
        print(f"  질문: {q.question[:40]}...", flush=True)

        session_path = "/v1/chat/sessions"
        session = _request(
            client, "POST", session_path,
            headers=_auth_headers("POST", session_path),
            json={},
        ).json()

        msg_path = f"/v1/chat/sessions/{session['session_id']}/messages"
        answer_resp = _request(
            client, "POST", msg_path,
            headers=_auth_headers("POST", msg_path),
            json={"message": q.question, "file_ids": []},
        ).json()

        answer_text = answer_resp.get("answer", "")
        citations = answer_resp.get("citations", [])
        inline_refs = re.findall(r"\[(\d+)\]", answer_text)
        citation_indexes = [c.get("index") for c in citations]

        qchecks: dict[str, bool] = {
            "answer_present": bool(answer_text.strip()),
            "inline_refs_present": bool(inline_refs),
            "citations_present": bool(citations),
        }

        # 기대 용어 검증
        for i, term in enumerate(q.expected_terms, 1):
            qchecks[f"expected_term_{i}"] = term.casefold() in answer_text.casefold()

        # 인용 소스 타입
        if citations:
            qchecks["citation_source_type_document"] = all(
                c.get("source_type") == "document" for c in citations
            )
        else:
            qchecks["citation_source_type_document"] = False

        # 단일 문서 질문: 대상 문서가 인용에 포함되는지
        if q.target_doc_keywords and citations:
            paths = " ".join(c.get("path", "") or c.get("name", "") for c in citations)
            qchecks["target_doc_in_citations"] = any(
                kw in paths for kw in q.target_doc_keywords
            )

        question_results.append({
            "question": q.question,
            "category": q.category,
            "difficulty": q.difficulty,
            "answer_preview": answer_text[:500],
            "inline_refs": inline_refs,
            "citation_count": len(citations),
            "citations": citations,
            "checks": qchecks,
        })

    all_checks = sum(all(r["checks"].values()) for r in question_results)
    with_citations = sum(1 for r in question_results if r["checks"]["citations_present"])

    return {
        "questions": question_results,
        "summary": {
            "total_questions": len(question_results),
            "all_checks_passed": all_checks,
            "with_citations": with_citations,
        },
    }


# ---------------------------------------------------------------------------
# Phase 6: 인용 품질
# ---------------------------------------------------------------------------


def phase_6_citations(qa_results: dict) -> dict:
    """Phase 5 결과에서 인용 구조를 종합 검증한다."""
    questions = qa_results["questions"]

    seq_ok = 0
    ref_match_ok = 0
    no_adjacent = 0
    total_with_citations = 0

    for q in questions:
        answer = q["answer_preview"]
        citations_count = q["citation_count"]
        if not q["checks"]["citations_present"]:
            continue
        total_with_citations += 1

        # 인용 인덱스 순차 검증 (preview에서는 전체 citations 접근 불가하므로 inline_refs 기반)
        refs = sorted(set(int(r) for r in q["inline_refs"]))
        if refs == list(range(refs[0], refs[0] + len(refs))) if refs else True:
            seq_ok += 1

        # inline refs가 citations 범위 내인지
        if all(1 <= int(r) <= citations_count for r in q["inline_refs"]):
            ref_match_ok += 1

        # 인접 인용 번호 오류
        if not re.search(r"\[\d+\]\d", answer):
            no_adjacent += 1

    checks = {
        "inline_refs_within_citation_range": total_with_citations > 0
        and ref_match_ok == total_with_citations,
        "no_adjacent_citation_number": total_with_citations > 0
        and no_adjacent == total_with_citations,
        "sequential_refs_pattern": total_with_citations > 0
        and seq_ok >= total_with_citations * 0.8,
    }
    return {
        "checks": checks,
        "total_with_citations": total_with_citations,
        "sequential_ok": seq_ok,
        "ref_match_ok": ref_match_ok,
    }


# ---------------------------------------------------------------------------
# Phase 7: SSE 스트리밍
# ---------------------------------------------------------------------------


def phase_7_streaming(client: TestClient) -> dict:
    """SSE 스트리밍 엔드포인트를 검증한다."""
    session_path = "/v1/chat/sessions"
    session = _request(
        client, "POST", session_path,
        headers=_auth_headers("POST", session_path),
        json={},
    ).json()

    stream_path = f"/v1/chat/sessions/{session['session_id']}/messages/stream"
    resp = _request(
        client, "POST", stream_path,
        headers={
            **_auth_headers("POST", stream_path),
            "Accept": "text/event-stream",
        },
        json={
            "message": "Checkout Service에 대해 아키텍처와 성능을 종합하여 설명해줘.",
            "file_ids": [],
        },
    )

    raw = resp.text
    events = _parse_sse_events(raw)
    event_names = [e[0] for e in events]

    done_data: dict = {}
    for name, data in events:
        if name == "done":
            done_data = data
            break

    checks = {
        "metadata_event_present": "metadata" in event_names,
        "token_events_present": event_names.count("token") >= 1,
        "done_event_present": "done" in event_names,
        "done_has_full_response": bool(done_data.get("full_response", "").strip()),
        "done_has_citations": bool(done_data.get("citations")),
        "response_type_is_rag": done_data.get("response_type") == "rag",
    }

    return {
        "checks": checks,
        "event_count": len(events),
        "token_count": event_names.count("token"),
        "response_preview": done_data.get("full_response", "")[:300],
    }


# ---------------------------------------------------------------------------
# 차트 생성
# ---------------------------------------------------------------------------


def _phase_check_stats(phase_data: dict) -> tuple[int, int, int]:
    """phase 데이터에서 (total, passed, failed) 체크 통계를 계산한다."""
    total = passed = 0
    if "checks" in phase_data:
        for v in phase_data["checks"].values():
            total += 1
            passed += 1 if v else 0
    if "questions" in phase_data:
        for q in phase_data["questions"]:
            for v in q.get("checks", {}).values():
                total += 1
                passed += 1 if v else 0
    return total, passed, total - passed


def _generate_charts(result: dict, chart_dir: Path) -> None:
    """matplotlib으로 품질 평가 차트 5종을 생성한다."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
    except ImportError:
        print("  matplotlib 미설치 — 차트 생성 건너뜀", flush=True)
        return

    # 한국어 폰트 탐색 (Docker: Noto Sans CJK, Windows: Malgun Gothic, Mac: AppleGothic)
    fm._load_fontmanager(try_read_cache=False)  # 새 폰트 설치 후 캐시 갱신
    font_candidates = [
        "Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Sans CJK",
        "NanumGothic", "Malgun Gothic", "AppleGothic",
    ]
    for font_name in font_candidates:
        if any(font_name in f.name for f in fm.fontManager.ttflist):
            plt.rcParams["font.family"] = font_name
            print(f"  차트 폰트: {font_name}", flush=True)
            break
    else:
        print("  경고: 한국어 폰트 미발견 — 차트 텍스트가 깨질 수 있음", flush=True)
    plt.rcParams["axes.unicode_minus"] = False

    chart_dir.mkdir(parents=True, exist_ok=True)
    phases = result.get("phases", {})
    questions = phases.get("phase_5_qa", {}).get("questions", [])

    # --- Chart 1: Phase별 Pass Rate ---
    phase_names = [
        "1.수집", "2.청킹", "3.임베딩", "4.검색", "5.Q&A", "6.인용", "7.스트리밍",
    ]
    phase_keys = [
        "phase_1_ingestion", "phase_2_chunking", "phase_3_embedding",
        "phase_4_retrieval", "phase_5_qa", "phase_6_citations", "phase_7_streaming",
    ]
    rates = []
    for pk in phase_keys:
        t, p, _ = _phase_check_stats(phases.get(pk, {}))
        rates.append(p / t * 100 if t > 0 else 0)

    colors = ["#2ecc71" if r == 100 else "#f39c12" if r >= 80 else "#e74c3c" for r in rates]
    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(phase_names, rates, color=colors, edgecolor="white")
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{rate:.0f}%", ha="center", va="bottom", fontsize=9)
    ax.set_ylim(0, 110)
    ax.set_ylabel("Pass Rate (%)")
    ax.set_title("Phase별 Pass Rate")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(chart_dir / "phase_pass_rate.png", dpi=150, bbox_inches="tight")
    plt.close()

    # --- Chart 2: 카테고리별 Q&A 성능 ---
    if questions:
        categories = ["single_doc", "cross_doc", "korean_bm25", "numeric", "deep_analysis"]
        cat_labels = ["단일문서", "교차문서", "한국어BM25", "수치정확성", "심층분석"]
        answer_rates, citation_rates, term_rates = [], [], []
        for cat in categories:
            cat_qs = [q for q in questions if q["category"] == cat]
            n = len(cat_qs) or 1
            answer_rates.append(sum(1 for q in cat_qs if q["checks"].get("answer_present")) / n * 100)
            citation_rates.append(sum(1 for q in cat_qs if q["checks"].get("citations_present")) / n * 100)
            # 기대용어: expected_term_N 키들의 평균
            term_pass = 0
            term_total = 0
            for q in cat_qs:
                for k, v in q["checks"].items():
                    if k.startswith("expected_term_"):
                        term_total += 1
                        term_pass += 1 if v else 0
            term_rates.append(term_pass / term_total * 100 if term_total > 0 else 0)

        x = range(len(categories))
        width = 0.25
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.bar([i - width for i in x], answer_rates, width, label="응답률", color="#3498db")
        ax.bar(list(x), citation_rates, width, label="인용률", color="#2ecc71")
        ax.bar([i + width for i in x], term_rates, width, label="기대용어 매칭률", color="#e67e22")
        ax.set_xticks(list(x))
        ax.set_xticklabels(cat_labels)
        ax.set_ylim(0, 115)
        ax.set_ylabel("%")
        ax.set_title("카테고리별 Q&A 성능")
        ax.legend()
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        plt.savefig(chart_dir / "category_performance.png", dpi=150, bbox_inches="tight")
        plt.close()

    # --- Chart 3: 질문별 스코어카드 ---
    if questions:
        labels = [f"Q{i+1}: {q['question'][:25]}..." for i, q in enumerate(questions)]
        passed_counts = [sum(1 for v in q["checks"].values() if v) for q in questions]
        failed_counts = [sum(1 for v in q["checks"].values() if not v) for q in questions]

        fig, ax = plt.subplots(figsize=(12, max(8, len(questions) * 0.35)))
        y = range(len(questions))
        ax.barh(y, passed_counts, color="#2ecc71", label="통과", edgecolor="white")
        ax.barh(y, failed_counts, left=passed_counts, color="#e74c3c", label="실패", edgecolor="white")
        ax.set_yticks(list(y))
        ax.set_yticklabels(labels, fontsize=7)
        ax.invert_yaxis()
        ax.set_xlabel("체크 항목 수")
        ax.set_title("질문별 검증 결과 (30개)")
        ax.legend(loc="lower right")
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        plt.savefig(chart_dir / "question_scorecard.png", dpi=150, bbox_inches="tight")
        plt.close()

    # --- Chart 4: 난이도별 Pass Rate ---
    if questions:
        diff_order = ["easy", "medium", "hard"]
        diff_labels = ["Easy", "Medium", "Hard"]
        diff_rates = []
        diff_counts = []
        for d in diff_order:
            d_qs = [q for q in questions if q.get("difficulty") == d]
            n_checks = sum(len(q["checks"]) for q in d_qs) or 1
            n_pass = sum(sum(1 for v in q["checks"].values() if v) for q in d_qs)
            diff_rates.append(n_pass / n_checks * 100)
            diff_counts.append(len(d_qs))

        colors = ["#2ecc71", "#f39c12", "#e74c3c"]
        fig, ax = plt.subplots(figsize=(7, 5))
        bars = ax.bar(diff_labels, diff_rates, color=colors, edgecolor="white")
        for bar, rate, cnt in zip(bars, diff_rates, diff_counts):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f"{rate:.0f}% (n={cnt})", ha="center", va="bottom", fontsize=10)
        ax.set_ylim(0, 115)
        ax.set_ylabel("Pass Rate (%)")
        ax.set_title("난이도별 Pass Rate")
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        plt.savefig(chart_dir / "difficulty_pass_rate.png", dpi=150, bbox_inches="tight")
        plt.close()

    # --- Chart 5: 인용 품질 레이더 ---
    if questions:
        n_q = len(questions)
        metrics = {
            "응답존재": sum(1 for q in questions if q["checks"].get("answer_present")) / n_q,
            "인용존재": sum(1 for q in questions if q["checks"].get("citations_present")) / n_q,
            "인라인참조": sum(1 for q in questions if q["checks"].get("inline_refs_present")) / n_q,
            "소스타입정확": sum(1 for q in questions if q["checks"].get("citation_source_type_document")) / n_q,
        }
        # 기대용어 매칭률
        t_total = t_pass = 0
        for q in questions:
            for k, v in q["checks"].items():
                if k.startswith("expected_term_"):
                    t_total += 1
                    t_pass += 1 if v else 0
        metrics["기대용어매칭"] = t_pass / t_total if t_total > 0 else 0

        labels_r = list(metrics.keys())
        values = list(metrics.values())
        n = len(labels_r)
        angles = [i / n * 2 * math.pi for i in range(n)]
        values_closed = values + values[:1]
        angles_closed = angles + angles[:1]

        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw={"polar": True})
        ax.plot(angles_closed, values_closed, "o-", linewidth=2, color="#3498db")
        ax.fill(angles_closed, values_closed, alpha=0.25, color="#3498db")
        ax.set_xticks(angles)
        ax.set_xticklabels(labels_r, fontsize=9)
        ax.set_ylim(0, 1.05)
        ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
        ax.set_yticklabels(["20%", "40%", "60%", "80%", "100%"], fontsize=7)
        ax.set_title("인용 품질 Radar", y=1.08)
        plt.tight_layout()
        plt.savefig(chart_dir / "citation_radar.png", dpi=150, bbox_inches="tight")
        plt.close()

    print(f"  차트 5종 생성 완료: {chart_dir}", flush=True)


# ---------------------------------------------------------------------------
# MD 리포트 생성
# ---------------------------------------------------------------------------


def generate_report(result: dict, report_dir: Path) -> None:
    """테스트 결과를 마크다운 리포트 + 차트로 생성한다."""
    report_dir.mkdir(parents=True, exist_ok=True)
    chart_dir = report_dir / "charts"

    # 차트 생성 (실패해도 리포트는 계속 생성)
    try:
        _generate_charts(result, chart_dir)
    except Exception as exc:
        print(f"  차트 생성 실패: {exc}", flush=True)

    phases = result.get("phases", {})
    overall = result.get("overall", {})
    questions = phases.get("phase_5_qa", {}).get("questions", [])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []
    w = lines.append

    # 헤더
    w("# E2E RAG 품질 테스트 리포트\n")
    w(f"- **테스트 일시**: {now}")
    w(f"- **문서**: 10개 (DOCX 5 + PDF 5)")
    w(f"- **질문**: {len(questions)}개\n")
    w("---\n")

    # 1. 종합 요약
    w("## 1. 종합 요약\n")
    w("| 지표 | 값 |")
    w("|------|-----|")
    w(f"| 전체 체크 | {overall.get('total_checks', 0)}개 |")
    w(f"| 통과 | {overall.get('passed', 0)}개 |")
    w(f"| 실패 | {overall.get('failed', 0)}개 |")
    w(f"| **Pass Rate** | **{overall.get('pass_rate', '0%')}** |\n")
    w("---\n")

    # 2. Phase별 결과
    w("## 2. Phase별 결과\n")
    w("| Phase | 설명 | 체크 | 통과 | 실패 | Pass Rate |")
    w("|-------|------|------|------|------|-----------|")
    phase_info = [
        ("phase_1_ingestion", "1", "문서 수집"),
        ("phase_2_chunking", "2", "청킹 품질"),
        ("phase_3_embedding", "3", "임베딩 저장"),
        ("phase_4_retrieval", "4", "검색 품질"),
        ("phase_5_qa", "5", "Q&A 품질"),
        ("phase_6_citations", "6", "인용 품질"),
        ("phase_7_streaming", "7", "SSE 스트리밍"),
    ]
    for pk, num, desc in phase_info:
        t, p, f_ = _phase_check_stats(phases.get(pk, {}))
        rate = f"{p / t * 100:.0f}%" if t > 0 else "N/A"
        w(f"| {num} | {desc} | {t} | {p} | {f_} | {rate} |")
    w("")
    w("![Phase별 Pass Rate](charts/phase_pass_rate.png)\n")
    w("---\n")

    # 3. Q&A 상세 결과
    w(f"## 3. Q&A 상세 결과 ({len(questions)}개 질문)\n")
    w("| # | 질문 | 카테고리 | 난이도 | 응답 | 인용수 | 기대용어 | 결과 |")
    w("|---|------|----------|--------|------|--------|----------|------|")
    for i, q in enumerate(questions, 1):
        q_text = q["question"][:40] + "..." if len(q["question"]) > 40 else q["question"]
        ans = "O" if q["checks"].get("answer_present") else "X"
        cit_count = q.get("citation_count", 0)
        # 기대용어 통과 / 전체
        term_checks = {k: v for k, v in q["checks"].items() if k.startswith("expected_term_")}
        term_str = f"{sum(term_checks.values())}/{len(term_checks)}" if term_checks else "-"
        all_pass = "PASS" if all(q["checks"].values()) else "FAIL"
        result_icon = all_pass
        w(f"| {i} | {q_text} | {q['category']} | {q.get('difficulty', '-')} | {ans} | {cit_count} | {term_str} | {result_icon} |")
    w("")
    w("![카테고리별 성능](charts/category_performance.png)\n")
    w("![질문별 스코어카드](charts/question_scorecard.png)\n")
    w("---\n")

    # 4. 카테고리별 집계
    w("## 4. 카테고리별 집계\n")
    w("| 카테고리 | 질문수 | 응답률 | 인용률 | 기대용어 매칭률 | 종합 Pass Rate |")
    w("|----------|--------|--------|--------|-----------------|----------------|")
    categories = ["single_doc", "cross_doc", "korean_bm25", "numeric", "deep_analysis"]
    cat_display = {"single_doc": "단일문서", "cross_doc": "교차문서", "korean_bm25": "한국어BM25",
                   "numeric": "수치정확성", "deep_analysis": "심층분석"}
    for cat in categories:
        cat_qs = [q for q in questions if q["category"] == cat]
        n = len(cat_qs) or 1
        ans_r = sum(1 for q in cat_qs if q["checks"].get("answer_present")) / n * 100
        cit_r = sum(1 for q in cat_qs if q["checks"].get("citations_present")) / n * 100
        t_total = t_pass = 0
        for q in cat_qs:
            for k, v in q["checks"].items():
                if k.startswith("expected_term_"):
                    t_total += 1
                    t_pass += 1 if v else 0
        term_r = t_pass / t_total * 100 if t_total > 0 else 0
        all_checks = sum(len(q["checks"]) for q in cat_qs) or 1
        all_pass = sum(sum(1 for v in q["checks"].values() if v) for q in cat_qs)
        overall_r = all_pass / all_checks * 100
        w(f"| {cat_display.get(cat, cat)} | {len(cat_qs)} | {ans_r:.0f}% | {cit_r:.0f}% | {term_r:.0f}% | {overall_r:.0f}% |")
    w("\n---\n")

    # 5. 난이도별 집계
    w("## 5. 난이도별 집계\n")
    w("| 난이도 | 질문수 | Pass Rate |")
    w("|--------|--------|-----------|")
    for d, d_label in [("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")]:
        d_qs = [q for q in questions if q.get("difficulty") == d]
        n_checks = sum(len(q["checks"]) for q in d_qs) or 1
        n_pass = sum(sum(1 for v in q["checks"].values() if v) for q in d_qs)
        w(f"| {d_label} | {len(d_qs)} | {n_pass / n_checks * 100:.0f}% |")
    w("")
    w("![난이도별 Pass Rate](charts/difficulty_pass_rate.png)\n")
    w("---\n")

    # 6. 인용 품질
    w("## 6. 인용 품질\n")
    w("![인용 품질 레이더](charts/citation_radar.png)\n")
    w("---\n")

    # 7. 실패 항목
    failed = overall.get("failed_names", [])
    w("## 7. 실패 항목 목록\n")
    if failed:
        for name in failed:
            w(f"- `{name}`")
    else:
        w("모든 체크를 통과했습니다.")
    w("\n---\n")

    # 8. 실패 질문 상세 분석
    failed_qs = [
        (i, q) for i, q in enumerate(questions)
        if not all(q.get("checks", {}).values())
    ]
    w("## 8. 실패 질문 상세 분석\n")
    if not failed_qs:
        w("모든 질문이 통과했습니다.\n")
    else:
        w(f"총 {len(failed_qs)}개 질문에서 실패가 발생했습니다.\n")
        for idx, q in failed_qs:
            q_obj = QUESTIONS[idx] if idx < len(QUESTIONS) else None
            q_num = idx + 1
            failed_checks = [k for k, v in q["checks"].items() if not v]

            w(f"### Q{q_num}. {q['question']}\n")
            w(f"- **카테고리**: {q['category']} | **난이도**: {q.get('difficulty', '-')}")
            if q_obj:
                w(f"- **기대 용어**: `{'`, `'.join(q_obj.expected_terms)}`")
            w(f"- **실패 항목**: {', '.join(f'`{c}`' for c in failed_checks)}")
            w(f"- **인용 수**: {q.get('citation_count', 0)}개")
            w("")

            # LLM 응답 요약
            preview = q.get("answer_preview", "")
            if preview:
                # 500자까지 표시, 마크다운 코드블록으로 감싸기
                display = preview[:800]
                if len(preview) > 800:
                    display += " ..."
                w("<details>")
                w(f"<summary>LLM 응답 (처음 800자)</summary>\n")
                w(f"```\n{display}\n```\n")
                w("</details>\n")

            # 인용 정보
            citations = q.get("citations", [])
            if citations:
                cit_titles = [c.get("title", c.get("path", "?")) for c in citations]
                w(f"- **인용 소스**: {', '.join(cit_titles)}")
            else:
                w("- **인용 소스**: 없음")
            w("")

    report_path = report_dir / "e2e_rag_quality_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 결과 집계 + 메인
# ---------------------------------------------------------------------------


def _collect_all_checks(phases: dict) -> dict:
    """모든 phase에서 checks를 수집하여 전체 요약을 만든다."""
    all_checks: dict[str, bool] = {}

    for phase_name, phase_data in phases.items():
        if "checks" in phase_data:
            for k, v in phase_data["checks"].items():
                all_checks[f"{phase_name}.{k}"] = v
        # phase_5_qa는 questions 안에 개별 checks가 있음
        if "questions" in phase_data:
            for i, q in enumerate(phase_data["questions"]):
                for k, v in q.get("checks", {}).items():
                    all_checks[f"{phase_name}.q{i+1}.{k}"] = v

    passed = sum(1 for v in all_checks.values() if v)
    failed_names = [k for k, v in all_checks.items() if not v]

    return {
        "total_checks": len(all_checks),
        "passed": passed,
        "failed": len(all_checks) - passed,
        "pass_rate": f"{passed / len(all_checks) * 100:.1f}%" if all_checks else "0%",
        "failed_names": failed_names,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="DOCX + PDF RAG 통합 E2E 테스트")
    parser.add_argument(
        "--test-docs-dir",
        default="/test-docs",
        help="DOCX 파일 디렉토리 (기본: /test-docs, docker volume mount)",
    )
    parser.add_argument("--output", default=None, help="결과 JSON 저장 경로")
    parser.add_argument(
        "--report-dir",
        default=str(Path(__file__).resolve().parent.parent / "test-results"),
        help="리포트 출력 디렉토리 (기본: ai-server/test-results/)",
    )
    args = parser.parse_args()

    test_docs_dir = Path(args.test_docs_dir)

    print("=" * 60)
    print("DOCX + PDF RAG 통합 E2E 테스트")
    print("=" * 60)

    # DB 설정
    print("\n[설정] DB 마이그레이션 + 클린...", flush=True)
    settings = _setup_db()
    client = TestClient(create_app())

    phases: dict[str, Any] = {}

    # Phase 1
    print("\n[Phase 1] 문서 수집 (10개 파일)...", flush=True)
    try:
        phases["phase_1_ingestion"] = phase_1_ingest(client, settings, test_docs_dir)
    except Exception as exc:
        print(f"  ✗ Phase 1 실패: {exc}", flush=True)
        phases["phase_1_ingestion"] = {"checks": {"phase_completed": False}, "error": str(exc)}

    # Phase 2
    print("\n[Phase 2] 청킹 품질 검증...", flush=True)
    try:
        phases["phase_2_chunking"] = phase_2_chunking(settings)
    except Exception as exc:
        print(f"  ✗ Phase 2 실패: {exc}", flush=True)
        phases["phase_2_chunking"] = {"checks": {"phase_completed": False}, "error": str(exc)}

    # Phase 3
    print("\n[Phase 3] 임베딩 & DB 저장 검증...", flush=True)
    try:
        phases["phase_3_embedding"] = phase_3_embedding(settings)
    except Exception as exc:
        print(f"  ✗ Phase 3 실패: {exc}", flush=True)
        phases["phase_3_embedding"] = {"checks": {"phase_completed": False}, "error": str(exc)}

    # Phase 4
    print("\n[Phase 4] 검색 품질 검증...", flush=True)
    try:
        phases["phase_4_retrieval"] = phase_4_retrieval(settings)
    except Exception as exc:
        print(f"  ✗ Phase 4 실패: {exc}", flush=True)
        phases["phase_4_retrieval"] = {"checks": {"phase_completed": False}, "error": str(exc)}

    # Phase 5
    print("\n[Phase 5] 챗봇 Q&A 품질 (30개 질문)...", flush=True)
    try:
        phases["phase_5_qa"] = phase_5_qa(client)
    except Exception as exc:
        print(f"  ✗ Phase 5 실패: {exc}", flush=True)
        phases["phase_5_qa"] = {"checks": {"phase_completed": False}, "error": str(exc)}

    # Phase 6
    print("\n[Phase 6] 인용 품질 검증...", flush=True)
    try:
        phases["phase_6_citations"] = phase_6_citations(phases.get("phase_5_qa", {}))
    except Exception as exc:
        print(f"  ✗ Phase 6 실패: {exc}", flush=True)
        phases["phase_6_citations"] = {"checks": {"phase_completed": False}, "error": str(exc)}

    # Phase 7
    print("\n[Phase 7] SSE 스트리밍 검증...", flush=True)
    try:
        phases["phase_7_streaming"] = phase_7_streaming(client)
    except Exception as exc:
        print(f"  ✗ Phase 7 실패: {exc}", flush=True)
        phases["phase_7_streaming"] = {"checks": {"phase_completed": False}, "error": str(exc)}

    # 결과 집계
    overall = _collect_all_checks(phases)

    result = {
        "test_summary": {"total_documents": 10, "docx_count": 5, "pdf_count": 5},
        "phases": phases,
        "overall": overall,
    }

    output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    print("\n" + "=" * 60)
    print(output)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"\n결과 저장: {args.output}")

    # 리포트 생성
    print("\n[Report] 마크다운 리포트 + 차트 생성 중...", flush=True)
    try:
        report_dir = Path(args.report_dir)
        generate_report(result, report_dir)
        # JSON도 리포트 디렉토리에 저장
        (report_dir / "e2e_result.json").write_text(output, encoding="utf-8")
        print(f"  리포트: {report_dir / 'e2e_rag_quality_report.md'}")
        print(f"  JSON:   {report_dir / 'e2e_result.json'}")
    except Exception as exc:
        print(f"  리포트 생성 실패: {exc}", flush=True)

    print(f"\n총 {overall['total_checks']}개 검증 → 통과 {overall['passed']}, 실패 {overall['failed']} ({overall['pass_rate']})")
    if overall["failed_names"]:
        print("실패 항목:")
        for name in overall["failed_names"]:
            print(f"  - {name}")

    if overall["failed"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
