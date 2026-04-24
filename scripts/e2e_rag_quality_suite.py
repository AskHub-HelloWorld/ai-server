from __future__ import annotations

import argparse
import json
import mimetypes
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QualityQuestion:
    question: str
    expected_source_type: str
    expected_terms: tuple[str, ...] = ()


QUESTIONS: tuple[QualityQuestion, ...] = (
    QualityQuestion(
        "RAG-Anything README 기준으로 이 프로젝트의 핵심 기능을 5가지로 요약해라.",
        "repository",
        ("multimodal", "LightRAG"),
    ),
    QualityQuestion(
        "RAG-Anything을 PyPI로 설치하는 기본 명령과 모든 optional dependency를 포함하는 명령을 알려줘.",
        "repository",
        ("pip install raganything", "all"),
    ),
    QualityQuestion(
        "README의 Query Options에서 지원하는 text query mode 네 가지를 모두 나열해라.",
        "repository",
        ("hybrid", "local", "global", "naive"),
    ),
    QualityQuestion(
        "README 예제에서 RAGAnythingConfig의 parser, parse_method, image/table/equation processing 설정값은 무엇인가?",
        "repository",
        ("mineru", "auto"),
    ),
    QualityQuestion(
        "Office 문서 처리를 위해 README가 요구하는 외부 프로그램과 OS별 설치 예시는 무엇인가?",
        "repository",
        ("LibreOffice",),
    ),
    QualityQuestion(
        "논문 초록 기준으로 기존 RAG 프레임워크의 핵심 한계와 RAG-Anything의 해결 방향을 설명해라.",
        "document",
        ("textual content", "dual-graph"),
    ),
    QualityQuestion(
        "논문 Introduction의 Technical Challenges 세 가지를 각각 짧게 설명해라.",
        "document",
        ("unified multimodal representation", "structure-aware", "cross-modal retrieval"),
    ),
    QualityQuestion(
        "논문 Table 1에 나온 DocBench와 MMLongBench의 문서 수, 평균 페이지 수, 질문 수를 비교해라.",
        "document",
        ("DocBench", "MMLongBench", "229", "135"),
    ),
    QualityQuestion(
        "논문 Table 2와 Table 3에서 RAGAnything의 overall accuracy는 각각 얼마인가?",
        "document",
        ("63.4", "42.8"),
    ),
    QualityQuestion(
        "논문 Table 4의 ablation study에서 Chunk-only, w/o Reranker, RAGAnything의 overall 점수를 비교하고 의미를 설명해라.",
        "document",
        ("60.0", "62.4", "63.4"),
    ),
)


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    data: bytes | None = None,
) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc


def _json_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict | None = None,
) -> dict:
    request_headers = {**headers}
    data = None
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    raw = _request(method, url, headers=request_headers, data=data)
    return json.loads(raw.decode("utf-8"))


def _multipart_body(file_path: Path, *, purpose: str) -> tuple[bytes, str]:
    boundary = f"----AskHubQuality{uuid.uuid4().hex}"
    file_bytes = file_path.read_bytes()
    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="purpose"\r\n\r\n'
        f"{purpose}\r\n",
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n",
    ]
    body = "".join(parts).encode("utf-8") + file_bytes
    body += f"\r\n--{boundary}--\r\n".encode()
    return body, boundary


def _upload_file(base_url: str, headers: dict[str, str], file_path: Path) -> dict:
    body, boundary = _multipart_body(file_path, purpose="rag_source")
    return json.loads(_request(
        "POST",
        f"{base_url}/v1/files/upload",
        headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        data=body,
    ).decode("utf-8"))


def _wait_for_job(
    base_url: str,
    headers: dict[str, str],
    job_id: str,
    *,
    timeout_seconds: int,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_job: dict | None = None
    while time.monotonic() < deadline:
        last_job = _json_request(
            "GET",
            f"{base_url}/v1/ingestion-jobs/{job_id}",
            headers=headers,
        )
        print(json.dumps({
            "job_id": job_id,
            "status": last_job["status"],
            "indexed_object_count": last_job["indexed_object_count"],
        }, ensure_ascii=False), flush=True)
        if last_job["status"] in {"succeeded", "failed"}:
            return last_job
        time.sleep(5)
    raise RuntimeError(f"ingestion timeout: {last_job}")


def _extract_done_event(stream_raw: str) -> dict:
    for raw_event in stream_raw.split("\n\n"):
        event_name = "message"
        data_lines: list[str] = []
        for line in raw_event.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if event_name == "done" and data_lines:
            return json.loads("\n".join(data_lines))
    raise RuntimeError(f"SSE done event not found: {stream_raw[:500]}")


def _ask_question(
    base_url: str,
    headers: dict[str, str],
    session_id: str,
    question: str,
) -> dict:
    raw = _request(
        "POST",
        f"{base_url}/v1/chat/sessions/{session_id}/messages/stream",
        headers={**headers, "Content-Type": "application/json"},
        data=json.dumps({"message": question, "file_ids": []}, ensure_ascii=False).encode("utf-8"),
    ).decode("utf-8", errors="replace")
    return _extract_done_event(raw)


def _citation_indexes_are_sequential(citations: list[dict]) -> bool:
    indexes = [citation.get("index") for citation in citations]
    return indexes == list(range(1, len(indexes) + 1))


def _evaluate_question(question: QualityQuestion, done: dict) -> dict:
    answer = done.get("full_response", "")
    citations = done.get("citations", [])
    inline_refs = re.findall(r"\[(\d+)\]", answer)
    citation_indexes = [citation.get("index") for citation in citations]
    citation_source_types = [citation.get("source_type") for citation in citations]
    checks = {
        "answer_present": bool(answer.strip()),
        "inline_refs_present": bool(inline_refs),
        "citations_present": bool(citations),
        "citation_indexes_sequential": _citation_indexes_are_sequential(citations),
        "inline_refs_have_citations": all(int(ref) in citation_indexes for ref in inline_refs),
        "expected_source_type_used": question.expected_source_type in citation_source_types,
        "no_adjacent_citation_number": not re.search(r"\[\d+\]\d", answer),
    }
    for index, term in enumerate(question.expected_terms, 1):
        checks[f"expected_term_{index}_present"] = term.casefold() in answer.casefold()

    return {
        "question": question.question,
        "expected_source_type": question.expected_source_type,
        "answer_preview": answer[:1200],
        "inline_refs": inline_refs,
        "citation_indexes": citation_indexes,
        "citation_source_types": citation_source_types,
        "citation_paths": [citation.get("path") for citation in citations],
        "citation_urls": [citation.get("url") for citation in citations],
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173/api")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--team-id", type=int, default=92510)
    parser.add_argument("--pdf-path", required=True)
    parser.add_argument("--repo-url", required=True)
    parser.add_argument("--branch", default=None)
    parser.add_argument("--ask-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    pdf_path = Path(args.pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)

    headers = {
        "X-Test-User-Id": str(args.user_id),
        "X-Test-Team-Id": str(args.team_id),
    }

    upload: dict = {}
    document_source: dict = {}
    repository_source: dict = {}
    document_job: dict = {}
    repository_job: dict = {}
    document_job_result: dict = {"status": "skipped", "indexed_object_count": None}
    repository_job_result: dict = {"status": "skipped", "indexed_object_count": None}

    if not args.ask_only:
        upload = _upload_file(base_url, headers, pdf_path)
        document_source = _json_request(
            "POST",
            f"{base_url}/v1/sources",
            headers=headers,
            body={
                "source_type": "document",
                "name": pdf_path.name,
                "file_id": upload["id"],
            },
        )
        repository_source = _json_request(
            "POST",
            f"{base_url}/v1/sources",
            headers=headers,
            body={
                "source_type": "repository",
                "name": "HKUDS/RAG-Anything",
                "repo_url": args.repo_url.rstrip("/"),
                "default_branch": args.branch,
            },
        )

        document_job = _json_request(
            "POST",
            f"{base_url}/v1/ingestion-jobs",
            headers=headers,
            body={"source_id": document_source["source_id"], "mode": "full"},
        )
        repository_job = _json_request(
            "POST",
            f"{base_url}/v1/ingestion-jobs",
            headers=headers,
            body={"source_id": repository_source["source_id"], "mode": "full"},
        )

        document_job_result = _wait_for_job(
            base_url,
            headers,
            document_job["job_id"],
            timeout_seconds=args.timeout_seconds,
        )
        repository_job_result = _wait_for_job(
            base_url,
            headers,
            repository_job["job_id"],
            timeout_seconds=args.timeout_seconds,
        )

    question_results = [
        _evaluate_question(
            question,
            _ask_question(
                base_url,
                headers,
                _json_request(
                    "POST",
                    f"{base_url}/v1/chat/sessions",
                    headers=headers,
                    body={},
                )["session_id"],
                question.question,
            ),
        )
        for question in QUESTIONS
    ]

    result = {
        "team_id": args.team_id,
        "fresh_session_per_question": True,
        "document": {
            "file_id": upload.get("id"),
            "source_id": document_source.get("source_id"),
            "job_id": document_job.get("job_id"),
            "job_status": document_job_result["status"],
            "indexed_object_count": document_job_result["indexed_object_count"],
        },
        "repository": {
            "source_id": repository_source.get("source_id"),
            "job_id": repository_job.get("job_id"),
            "job_status": repository_job_result["status"],
            "indexed_object_count": repository_job_result["indexed_object_count"],
        },
        "questions": question_results,
        "summary_checks": {
            "document_job_succeeded": args.ask_only or document_job_result["status"] == "succeeded",
            "repository_job_succeeded": args.ask_only
            or repository_job_result["status"] == "succeeded",
            "document_chunks_indexed": args.ask_only
            or document_job_result["indexed_object_count"] > 0,
            "repository_chunks_indexed": args.ask_only
            or repository_job_result["indexed_object_count"] > 0,
            "questions_with_citations": sum(
                1 for item in question_results if item["checks"]["citations_present"]
            ),
            "questions_all_checks_passed": sum(
                1 for item in question_results if all(item["checks"].values())
            ),
        },
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
