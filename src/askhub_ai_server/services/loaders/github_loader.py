"""GitHub 리포지토리 코드 수집 로더."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from askhub_ai_server.services.chunker import detect_file_type
from askhub_ai_server.services.loaders.document_loader import (
    BINARY_EXTENSIONS,
    CONVERTIBLE_EXTENSIONS,
    convert_to_markdown,
)

logger = logging.getLogger(__name__)

# 건너뛸 디렉토리
SKIP_DIRS: set[str] = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "vendor", "dist", "build", ".next", ".nuxt", "target",
    ".idea", ".vscode", ".settings", "coverage", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

# 파일당 최대 크기 (500KB)
MAX_FILE_BYTES: int = 500_000


@dataclass(frozen=True)
class LoadedFile:
    """리포지토리에서 추출된 파일."""

    path: str
    content: str
    file_type: str
    commit_sha: str
    repo_url: str


def _validate_repo_url(repo_url: str) -> None:
    """HTTPS URL만 허용한다."""
    if not repo_url.startswith("https://"):
        raise ValueError(f"HTTPS URL만 지원합니다: {repo_url}")


def _clone_repo(repo_url: str, branch: str | None, target_dir: str) -> None:
    """Shallow clone (depth=1)으로 리포지토리를 복제한다."""
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([repo_url, target_dir])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone 실패: {result.stderr.strip()}")


def _get_head_sha(repo_dir: str) -> str:
    """현재 HEAD의 commit SHA를 반환한다."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=repo_dir,
        timeout=10,
    )
    return result.stdout.strip()


def _is_skippable(path: Path) -> bool:
    """건너뛸 파일/디렉토리인지 판별한다."""
    ext = path.suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return True
    # 파일 크기 제한
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return True
    except OSError:
        return True
    return False


def _should_skip_dir(dir_name: str) -> bool:
    """건너뛸 디렉토리인지 판별한다."""
    return dir_name in SKIP_DIRS or dir_name.startswith(".")


def load_repository(
    repo_url: str,
    branch: str | None = None,
) -> Iterator[LoadedFile]:
    """GitHub 리포지토리를 클론하고 코드 파일을 순회한다.

    Yields:
        LoadedFile — 각 파일의 경로, 내용, 타입, commit SHA
    """
    _validate_repo_url(repo_url)

    with tempfile.TemporaryDirectory(prefix="askhub-repo-") as tmp_dir:
        logger.info("리포지토리 클론 시작: %s (branch=%s)", repo_url, branch)
        _clone_repo(repo_url, branch, tmp_dir)
        commit_sha = _get_head_sha(tmp_dir)
        logger.info("클론 완료: commit=%s", commit_sha[:8])

        repo_path = Path(tmp_dir)
        file_count = 0

        for file_path in sorted(repo_path.rglob("*")):
            if not file_path.is_file():
                continue

            # 건너뛸 디렉토리 내부 파일 제외
            relative = file_path.relative_to(repo_path)
            if any(_should_skip_dir(part) for part in relative.parts[:-1]):
                continue

            if _is_skippable(file_path):
                continue

            ext = file_path.suffix.lower()

            # 마크다운 변환 대상 문서 파일 (DOCX, PPTX, XLSX, PDF 등)
            if ext in CONVERTIBLE_EXTENSIONS:
                try:
                    data = file_path.read_bytes()
                    content = convert_to_markdown(data, str(relative))
                except Exception:
                    logger.debug("문서 변환 실패: %s", relative)
                    continue
            else:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    logger.debug("파일 읽기 실패: %s", relative)
                    continue

                # 널 바이트가 있으면 바이너리로 간주
                if "\x00" in content[:8192]:
                    continue

            if not content.strip():
                continue

            file_count += 1
            yield LoadedFile(
                path=str(relative).replace("\\", "/"),
                content=content,
                file_type=detect_file_type(str(relative)),
                commit_sha=commit_sha,
                repo_url=repo_url,
            )

        logger.info("리포지토리 파일 수집 완료: %d개 파일", file_count)
