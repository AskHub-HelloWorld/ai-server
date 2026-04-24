from __future__ import annotations

import argparse
import json
import mimetypes
import re
import time
from pathlib import Path

from fastapi.testclient import TestClient

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.core.security import build_service_signature
from askhub_ai_server.main import create_app
from askhub_ai_server.services.embedding import get_embedding_service
from askhub_ai_server.worker import _claim_next_job, _process_job


CONTENT_TYPES_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _auth_headers(method: str, path: str, *, user_id: int, team_id: int) -> dict[str, str]:
    settings = get_settings()
    timestamp, signature = build_service_signature(
        secret=settings.service_auth_secret,
        method=method,
        path=path,
        query="",
        user_id=user_id,
        team_id=team_id,
        timestamp=int(time.time()),
    )
    return {
        "X-AskHub-User-Id": str(user_id),
        "X-AskHub-Team-Id": str(team_id),
        "X-AskHub-Timestamp": timestamp,
        "X-AskHub-Signature": signature,
    }


def _request(client: TestClient, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} failed: {response.status_code} {response.text}")
    return response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path")
    parser.add_argument(
        "--question",
        default="베이즈 정리가 무엇인가? 실제 예시를 들어 설명해라",
    )
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--team-id", type=int, default=10)
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    content_type = (
        CONTENT_TYPES_BY_SUFFIX.get(pdf_path.suffix.lower())
        or mimetypes.guess_type(pdf_path.name)[0]
        or "application/octet-stream"
    )

    settings = get_settings()
    print(
        json.dumps(
            {
                "event": "settings",
                "app_env": settings.app_env,
                "db_schema": settings.db_schema,
                "s3_bucket": settings.s3_bucket,
            },
            ensure_ascii=False,
        )
    )

    client = TestClient(create_app())

    upload_path = "/v1/files/upload"
    with pdf_path.open("rb") as pdf:
        upload = _request(
            client,
            "POST",
            upload_path,
            headers=_auth_headers("POST", upload_path, user_id=args.user_id, team_id=args.team_id),
            files={"file": (pdf_path.name, pdf, content_type)},
            data={"purpose": "rag_source"},
        ).json()

    source_path = "/v1/sources"
    source = _request(
        client,
        "POST",
        source_path,
        headers=_auth_headers("POST", source_path, user_id=args.user_id, team_id=args.team_id),
        json={
            "source_type": "document",
            "name": pdf_path.name,
            "file_id": upload["id"],
        },
    ).json()

    job_path = "/v1/ingestion-jobs"
    job = _request(
        client,
        "POST",
        job_path,
        headers=_auth_headers("POST", job_path, user_id=args.user_id, team_id=args.team_id),
        json={"source_id": source["source_id"], "mode": "full"},
    ).json()

    claimed = _claim_next_job()
    if claimed is None:
        raise RuntimeError("worker did not claim any queued ingestion job")
    if str(claimed.id) != job["job_id"]:
        raise RuntimeError(f"worker claimed unexpected job: {claimed.id}")
    _process_job(claimed, get_embedding_service(), settings)

    get_job_path = f"/v1/ingestion-jobs/{job['job_id']}"
    indexed_job = _request(
        client,
        "GET",
        get_job_path,
        headers=_auth_headers("GET", get_job_path, user_id=args.user_id, team_id=args.team_id),
    ).json()

    source_list = _request(
        client,
        "GET",
        source_path,
        headers=_auth_headers("GET", source_path, user_id=args.user_id, team_id=args.team_id),
    ).json()

    session_path = "/v1/chat/sessions"
    session = _request(
        client,
        "POST",
        session_path,
        headers=_auth_headers("POST", session_path, user_id=args.user_id, team_id=args.team_id),
        json={},
    ).json()

    message_path = f"/v1/chat/sessions/{session['session_id']}/messages"
    answer = _request(
        client,
        "POST",
        message_path,
        headers=_auth_headers("POST", message_path, user_id=args.user_id, team_id=args.team_id),
        json={"message": args.question, "file_ids": []},
    ).json()

    citations = answer.get("citations", [])
    inline_refs = sorted(set(re.findall(r"\[(\d+)\]", answer.get("answer", ""))))
    checks = {
        "job_succeeded": indexed_job["status"] == "succeeded",
        "chunks_indexed": indexed_job["indexed_object_count"] > 0,
        "citations_present": bool(citations),
        "inline_refs_present": bool(inline_refs),
        "download_url_present": any(
            citation.get("url", "").startswith("/v1/files/")
            and citation.get("url", "").endswith("/download")
            for citation in citations
        ),
    }

    result = {
        "upload": upload,
        "source": source,
        "indexed_job": indexed_job,
        "sources": source_list["sources"],
        "question": args.question,
        "answer": answer.get("answer"),
        "citations": citations,
        "inline_refs": inline_refs,
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SystemExit(f"E2E PDF RAG smoke failed checks: {failed}")


if __name__ == "__main__":
    main()
