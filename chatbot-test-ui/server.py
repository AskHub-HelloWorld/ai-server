from __future__ import annotations

import hmac
import os
import time
from hashlib import sha256
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
USER_ID_HEADER = "X-AskHub-User-Id"
TEAM_ID_HEADER = "X-AskHub-Team-Id"
TIMESTAMP_HEADER = "X-AskHub-Timestamp"
SIGNATURE_HEADER = "X-AskHub-Signature"
TEST_USER_ID_HEADER = "X-Test-User-Id"
TEST_TEAM_ID_HEADER = "X-Test-Team-Id"
TEST_USER_ID_QUERY = "test_user_id"
TEST_TEAM_ID_QUERY = "test_team_id"


def build_service_signature(
    *,
    secret: str,
    method: str,
    path: str,
    query: str,
    user_id: int,
    team_id: int | None,
) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    payload = "\n".join(
        [
            timestamp,
            method.upper(),
            path,
            query,
            str(user_id),
            "" if team_id is None else str(team_id),
        ]
    )
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    return timestamp, signature


class ChatbotTestUiHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, directory: str | None = None, **kwargs) -> None:
        super().__init__(*args, directory=directory or os.getenv("STATIC_ROOT", "."), **kwargs)

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self.proxy_request()
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            self.proxy_request()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        if self.path.startswith("/api/"):
            self.proxy_request()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        if self.path.startswith("/api/"):
            self.proxy_request()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def proxy_request(self) -> None:
        try:
            target_path, query = self.resolve_target_path()
            upstream_url = self.build_upstream_url(target_path, query)
            request = self.build_upstream_request(upstream_url, target_path, query)
            with urlopen(request, timeout=600) as upstream:
                self.write_upstream_response(upstream.status, upstream.headers, upstream)
        except HTTPError as exc:
            self.write_upstream_response(exc.code, exc.headers, exc)
        except ValueError as exc:
            self.write_text_response(HTTPStatus.BAD_REQUEST, str(exc))
        except RuntimeError as exc:
            self.write_text_response(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        except URLError as exc:
            self.write_text_response(
                HTTPStatus.BAD_GATEWAY,
                f"ai-server proxy request failed: {exc.reason}",
            )

    def resolve_target_path(self) -> tuple[str, str]:
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/api/"):
            raise ValueError("proxy path must start with /api/")
        target_path = parsed.path.removeprefix("/api")
        if not target_path.startswith("/"):
            target_path = f"/{target_path}"

        auth_params: dict[str, str] = {}
        upstream_query_pairs: list[tuple[str, str]] = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key in {TEST_USER_ID_QUERY, TEST_TEAM_ID_QUERY}:
                auth_params[key] = value
            else:
                upstream_query_pairs.append((key, value))
        self._test_auth_query = auth_params
        return target_path, urlencode(upstream_query_pairs)

    def build_upstream_url(self, target_path: str, query: str) -> str:
        base_url = os.getenv("AI_SERVER_BASE_URL", "http://host.docker.internal:8000").rstrip("/")
        parsed_base = urlsplit(base_url)
        if not parsed_base.scheme or not parsed_base.netloc:
            raise RuntimeError("AI_SERVER_BASE_URL must include scheme and host")
        return urlunsplit(
            (
                parsed_base.scheme,
                parsed_base.netloc,
                f"{parsed_base.path.rstrip('/')}{target_path}",
                query,
                "",
            )
        )

    def build_upstream_request(self, upstream_url: str, target_path: str, query: str) -> Request:
        method = self.command.upper()
        body = self.read_request_body()
        headers = self.forward_headers()
        if target_path not in {"/health", "/ready"}:
            headers.update(self.service_auth_headers(method, target_path, query))
        return Request(upstream_url, data=body, headers=headers, method=method)

    def read_request_body(self) -> bytes | None:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return None
        return self.rfile.read(content_length)

    def forward_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            lower_key = key.lower()
            if lower_key in HOP_BY_HOP_HEADERS:
                continue
            if lower_key in {"host", "content-length"}:
                continue
            if lower_key.startswith("x-test-"):
                continue
            headers[key] = value
        return headers

    def service_auth_headers(self, method: str, target_path: str, query: str) -> dict[str, str]:
        secret = os.getenv("SERVICE_AUTH_SECRET", "")
        if not secret:
            raise RuntimeError("SERVICE_AUTH_SECRET is not configured in the test UI container")

        user_id = self.parse_int_header(TEST_USER_ID_HEADER, required=True)
        team_id = self.parse_int_header(TEST_TEAM_ID_HEADER, required=False)
        timestamp, signature = build_service_signature(
            secret=secret,
            method=method,
            path=target_path,
            query=query,
            user_id=user_id,
            team_id=team_id,
        )
        headers = {
            USER_ID_HEADER: str(user_id),
            TIMESTAMP_HEADER: timestamp,
            SIGNATURE_HEADER: signature,
        }
        if team_id is not None:
            headers[TEAM_ID_HEADER] = str(team_id)
        return headers

    def parse_int_header(self, name: str, *, required: bool) -> int | None:
        value = self.headers.get(name, "").strip()
        if not value:
            query_name = {
                TEST_USER_ID_HEADER: TEST_USER_ID_QUERY,
                TEST_TEAM_ID_HEADER: TEST_TEAM_ID_QUERY,
            }.get(name)
            if query_name:
                value = getattr(self, "_test_auth_query", {}).get(query_name, "").strip()
        if not value:
            if required:
                raise ValueError(f"{name} header is required")
            return None
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if parsed < 1:
            raise ValueError(f"{name} must be greater than 0")
        return parsed

    def write_upstream_response(self, status: int, headers, upstream) -> None:
        self.send_response(status)
        self.send_header("Connection", "close")
        for key, value in headers.items():
            if key.lower() in HOP_BY_HOP_HEADERS or key.lower() == "content-length":
                continue
            self.send_header(key, value)
        self.end_headers()
        while True:
            chunk = upstream.read(8192)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()
        self.close_connection = True

    def write_text_response(self, status: HTTPStatus, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    static_root = Path(os.getenv("STATIC_ROOT", ".")).resolve()

    def handler(*args, **kwargs) -> ChatbotTestUiHandler:
        return ChatbotTestUiHandler(*args, directory=str(static_root), **kwargs)

    with ThreadingHTTPServer(("0.0.0.0", port), handler) as server:
        print(f"serving chatbot test ui on 0.0.0.0:{port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
