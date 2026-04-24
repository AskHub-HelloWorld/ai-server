from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_QUESTION = "베이즈 정리가 무엇인가? 실제 예시를 들어 설명해라"


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
    test_headers: dict[str, str],
    body: dict | None = None,
) -> dict:
    headers = {**test_headers}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    raw = _request(method, url, headers=headers, data=data)
    return json.loads(raw.decode("utf-8"))


def _multipart_body(file_path: Path) -> tuple[bytes, str]:
    boundary = f"----AskHubSmoke{uuid.uuid4().hex}"
    file_bytes = file_path.read_bytes()
    filename = file_path.name
    parts = [
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="purpose"\r\n\r\n'
        "rag_source\r\n",
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n",
    ]
    body = "".join(parts).encode("utf-8") + file_bytes
    body += f"\r\n--{boundary}--\r\n".encode()
    return body, boundary


def _upload_pdf(base_url: str, test_headers: dict[str, str], file_path: Path) -> dict:
    body, boundary = _multipart_body(file_path)
    headers = {
        **test_headers,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    raw = _request("POST", f"{base_url}/v1/files/upload", headers=headers, data=body)
    return json.loads(raw.decode("utf-8"))


def _wait_for_job(base_url: str, test_headers: dict[str, str], job_id: str) -> dict:
    deadline = time.monotonic() + 180
    last_job: dict | None = None
    while time.monotonic() < deadline:
        last_job = _json_request(
            "GET",
            f"{base_url}/v1/ingestion-jobs/{job_id}",
            test_headers=test_headers,
        )
        if last_job["status"] in {"succeeded", "failed"}:
            return last_job
        time.sleep(2)
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


def _citation_indexes_are_sequential(citations: list[dict]) -> bool:
    indexes = [citation.get("index") for citation in citations]
    return indexes == list(range(1, len(indexes) + 1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/api")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--team-id", type=int, default=50502)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument(
        "--expect-text",
        action="append",
        default=[],
        help="Expected substring in the final answer. Can be passed multiple times.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)

    base_url = args.base_url.rstrip("/")
    test_headers = {
        "X-Test-User-Id": str(args.user_id),
        "X-Test-Team-Id": str(args.team_id),
    }

    upload = _upload_pdf(base_url, test_headers, pdf_path)
    source = _json_request(
        "POST",
        f"{base_url}/v1/sources",
        test_headers=test_headers,
        body={
            "source_type": "document",
            "name": upload["filename"],
            "file_id": upload["id"],
        },
    )
    job = _json_request(
        "POST",
        f"{base_url}/v1/ingestion-jobs",
        test_headers=test_headers,
        body={"source_id": source["source_id"], "mode": "full"},
    )
    indexed_job = _wait_for_job(base_url, test_headers, job["job_id"])

    session = _json_request(
        "POST",
        f"{base_url}/v1/chat/sessions",
        test_headers=test_headers,
        body={},
    )
    stream_raw = _request(
        "POST",
        f"{base_url}/v1/chat/sessions/{session['session_id']}/messages/stream",
        headers={**test_headers, "Content-Type": "application/json"},
        data=json.dumps(
            {"message": args.question, "file_ids": []},
            ensure_ascii=False,
        ).encode("utf-8"),
    ).decode("utf-8", errors="replace")

    done = _extract_done_event(stream_raw)
    answer = done.get("full_response", "")
    citations = done.get("citations", [])
    checks = {
        "job_succeeded": indexed_job["status"] == "succeeded",
        "chunks_indexed": indexed_job["indexed_object_count"] > 0,
        "inline_refs_present": bool(re.search(r"\[\d+\]", answer)),
        "citations_present": bool(citations),
        "citation_indexes_sequential": _citation_indexes_are_sequential(citations),
        "no_adjacent_citation_number": not re.search(r"\[\d+\]\d", answer),
        "download_url_present": any(
            re.search(r"/v1/files/[0-9a-f-]+/download", citation.get("url") or "")
            for citation in citations
        ),
    }
    expected_texts = args.expect_text
    if not expected_texts and args.question == DEFAULT_QUESTION:
        expected_texts = ["흡연자", "남학생"]
    for idx, expected_text in enumerate(expected_texts, 1):
        checks[f"expected_text_{idx}_present"] = expected_text in answer

    result = {
        "upload_id": upload["id"],
        "source_id": source["source_id"],
        "job_id": job["job_id"],
        "job_status": indexed_job["status"],
        "indexed_object_count": indexed_job["indexed_object_count"],
        "answer_preview": answer[:500],
        "citation_indexes": [citation.get("index") for citation in citations],
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SystemExit(f"chatbot-test-ui proxy RAG smoke failed: {failed}")


if __name__ == "__main__":
    main()
