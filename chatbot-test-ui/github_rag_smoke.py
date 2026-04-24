from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request

DEFAULT_REPO_URL = "https://github.com/hkuds/lightrag"
DEFAULT_QUESTIONS = [
    "LightRAG 프로젝트의 목적과 핵심 기능을 설명해라.",
    "LightRAG를 설치하고 기본 실행하는 방법을 레포 근거로 요약해라.",
    "LightRAG에서 지원하는 query mode나 검색 모드는 무엇인지 설명해라.",
    "LightRAG의 주요 Python 패키지 구조나 핵심 모듈은 어떻게 구성되어 있는가?",
]


def _source_name_from_repo_url(repo_url: str) -> str:
    normalized = repo_url.rstrip("/").removesuffix(".git")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else "GitHub Repository"


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    data: bytes | None = None,
) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
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


def _wait_for_job(
    base_url: str,
    headers: dict[str, str],
    job_id: str,
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
        print(
            json.dumps(
                {
                    "job_id": job_id,
                    "status": last_job["status"],
                    "indexed_object_count": last_job["indexed_object_count"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
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


def _create_session(base_url: str, headers: dict[str, str]) -> dict:
    return _json_request("POST", f"{base_url}/v1/chat/sessions", headers=headers, body={})


def _ask_question(
    base_url: str,
    headers: dict[str, str],
    session_id: str,
    question: str,
) -> dict:
    stream_raw = _request(
        "POST",
        f"{base_url}/v1/chat/sessions/{session_id}/messages/stream",
        headers={**headers, "Content-Type": "application/json"},
        data=json.dumps(
            {"message": question, "file_ids": []},
            ensure_ascii=False,
        ).encode("utf-8"),
    ).decode("utf-8", errors="replace")
    return _extract_done_event(stream_raw)


def _citation_indexes_are_sequential(citations: list[dict]) -> bool:
    indexes = [citation.get("index") for citation in citations]
    return indexes == list(range(1, len(indexes) + 1))


def _github_urls_are_valid(citations: list[dict], repo_url: str) -> bool:
    normalized_repo_url = repo_url.rstrip("/").removesuffix(".git").lower()
    for citation in citations:
        url = (citation.get("url") or "").lower()
        if not url.startswith(normalized_repo_url):
            return False
        if "/blob/" not in url:
            return False
    return True


def _check_answer(question: str, done: dict, repo_url: str) -> dict:
    answer = done.get("full_response", "")
    citations = done.get("citations", [])
    inline_refs = re.findall(r"\[(\d+)\]", answer)
    citation_indexes = [citation.get("index") for citation in citations]
    checks = {
        "answer_present": bool(answer.strip()),
        "inline_refs_present": bool(inline_refs),
        "citations_present": bool(citations),
        "citation_indexes_sequential": _citation_indexes_are_sequential(citations),
        "inline_refs_have_citations": all(int(ref) in citation_indexes for ref in inline_refs),
        "repository_citations_only": all(
            citation.get("source_type") == "repository" for citation in citations
        ),
        "github_urls_present": _github_urls_are_valid(citations, repo_url),
        "no_adjacent_citation_number": not re.search(r"\[\d+\]\d", answer),
    }
    return {
        "question": question,
        "answer_preview": answer[:700],
        "inline_refs": inline_refs,
        "citation_indexes": citation_indexes,
        "citation_urls": [citation.get("url") for citation in citations],
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/api")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--team-id", type=int, default=60601)
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    parser.add_argument("--source-name", default=None)
    parser.add_argument("--branch", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--question", action="append", default=[])
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    repo_url = args.repo_url.rstrip("/")
    source_name = args.source_name or _source_name_from_repo_url(repo_url)
    headers = {
        "X-Test-User-Id": str(args.user_id),
        "X-Test-Team-Id": str(args.team_id),
    }

    source = _json_request(
        "POST",
        f"{base_url}/v1/sources",
        headers=headers,
        body={
            "source_type": "repository",
            "name": source_name,
            "repo_url": repo_url,
            "default_branch": args.branch,
        },
    )
    job = _json_request(
        "POST",
        f"{base_url}/v1/ingestion-jobs",
        headers=headers,
        body={"source_id": source["source_id"], "mode": "full"},
    )
    indexed_job = _wait_for_job(
        base_url,
        headers,
        job["job_id"],
        args.timeout_seconds,
    )

    session = _create_session(base_url, headers)
    questions = args.question or DEFAULT_QUESTIONS
    question_results = [
        _check_answer(
            question,
            _ask_question(base_url, headers, session["session_id"], question),
            repo_url,
        )
        for question in questions
    ]

    checks = {
        "job_succeeded": indexed_job["status"] == "succeeded",
        "chunks_indexed": indexed_job["indexed_object_count"] > 0,
        "all_questions_passed": all(
            all(result["checks"].values()) for result in question_results
        ),
    }
    result = {
        "source_id": source["source_id"],
        "job_id": job["job_id"],
        "session_id": session["session_id"],
        "repo_url": repo_url,
        "job_status": indexed_job["status"],
        "indexed_object_count": indexed_job["indexed_object_count"],
        "checks": checks,
        "questions": question_results,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    failed = [name for name, passed in checks.items() if not passed]
    failed.extend(
        f"{idx}:{name}"
        for idx, question_result in enumerate(question_results, 1)
        for name, passed in question_result["checks"].items()
        if not passed
    )
    if failed:
        raise SystemExit(f"github RAG smoke failed: {failed}")


if __name__ == "__main__":
    main()
