"""GitHub Repo Loader 통합 테스트 — 실제 리포지토리 클론."""

import pytest

from askhub_ai_server.services.loaders.github_loader import load_repository


class TestGitHubLoaderIntegration:
    """실제 GitHub 리포지토리를 클론하여 파일 수집을 검증한다.

    이 테스트는 네트워크와 git이 필요하다.
    """

    def test_load_real_repository(self):
        """LightRAG 리포지토리에서 파일을 정상적으로 수집하는지 확인."""
        repo_url = "https://github.com/HKUDS/LightRAG.git"
        files = list(load_repository(repo_url, branch="main"))

        # 파일이 수집되었는지 기본 확인
        assert len(files) > 0, "리포지토리에서 파일이 하나도 수집되지 않았습니다"

        # 모든 파일이 필수 필드를 가지고 있는지 확인
        for f in files:
            assert f.path, "file_path가 비어 있음"
            assert f.content, "content가 비어 있음"
            assert f.file_type, "file_type이 비어 있음"
            assert len(f.commit_sha) == 40, f"commit_sha 길이 이상: {f.commit_sha}"
            assert f.repo_url == repo_url

        # .git 디렉토리 파일이 포함되지 않았는지 확인
        git_files = [f for f in files if ".git/" in f.path or f.path == ".git"]
        assert len(git_files) == 0, ".git 디렉토리 파일이 포함됨"

        # node_modules 파일이 포함되지 않았는지 확인
        node_files = [f for f in files if "node_modules/" in f.path]
        assert len(node_files) == 0, "node_modules 파일이 포함됨"

        # Python 파일이 포함되어 있는지 확인 (LightRAG는 Python 프로젝트)
        py_files = [f for f in files if f.path.endswith(".py")]
        assert len(py_files) > 0, "Python 파일이 하나도 없음"

        # 경로에 백슬래시가 없는지 확인 (Unix 형식)
        for f in files:
            assert "\\" not in f.path, f"경로에 백슬래시: {f.path}"

        print(f"\n수집된 파일 수: {len(files)}")
        print(f"Python 파일 수: {len(py_files)}")
        print(f"commit SHA: {files[0].commit_sha}")
        print(f"샘플 파일: {[f.path for f in files[:5]]}")

    def test_rejects_non_https_url(self):
        """HTTPS가 아닌 URL을 거부하는지 확인."""
        with pytest.raises(ValueError, match="HTTPS"):
            list(load_repository("git@github.com:HKUDS/LightRAG.git"))

    def test_invalid_repo_url_raises(self):
        """존재하지 않는 리포지토리 URL이 에러를 발생시키는지 확인."""
        with pytest.raises(RuntimeError, match="git clone 실패"):
            list(load_repository("https://github.com/nonexistent/repo-12345.git"))
