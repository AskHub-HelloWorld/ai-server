"""chunker 모듈 단위 테스트."""

from askhub_ai_server.services.chunker import (
    MAX_CHUNK_CHARS,
    chunk_code,
    chunk_document,
    chunk_text,
    detect_file_type,
    enforce_max_chunk_chars,
    is_code_file,
)


class TestIsCodeFile:
    def test_python_file(self):
        assert is_code_file("src/main.py") is True

    def test_typescript_file(self):
        assert is_code_file("app/index.tsx") is True

    def test_dockerfile(self):
        assert is_code_file("Dockerfile") is True

    def test_pdf_not_code(self):
        assert is_code_file("doc.pdf") is False

    def test_markdown_not_code(self):
        assert is_code_file("README.md") is False


class TestDetectFileType:
    def test_python(self):
        assert detect_file_type("main.py") == "python"

    def test_javascript(self):
        assert detect_file_type("index.js") == "javascript"

    def test_dockerfile(self):
        assert detect_file_type("Dockerfile") == "dockerfile"

    def test_markdown(self):
        assert detect_file_type("README.md") == "markdown"

    def test_unknown(self):
        assert detect_file_type("somefile") == "text"


class TestChunkCode:
    def test_small_file_single_chunk(self):
        content = "\n".join(f"line {i}" for i in range(10))
        chunks = chunk_code(content, "small.py")
        assert len(chunks) == 1
        assert chunks[0].line_start == 1
        assert chunks[0].line_end == 10
        assert chunks[0].file_type == "python"
        assert chunks[0].metadata["language"] == "python"

    def test_large_file_multiple_chunks(self):
        content = "\n".join(f"line {i}" for i in range(250))
        chunks = chunk_code(content, "big.py", window_lines=100, overlap_lines=20)
        assert len(chunks) > 1
        # 첫 번째 청크
        assert chunks[0].line_start == 1
        assert chunks[0].line_end == 100
        # 두 번째 청크는 overlap으로 시작
        assert chunks[1].line_start == 81
        assert chunks[1].chunk_index == 1

    def test_empty_content(self):
        chunks = chunk_code("", "empty.py")
        assert chunks == []

    def test_whitespace_only_skipped(self):
        content = "\n\n\n   \n"
        chunks = chunk_code(content, "blank.py")
        assert chunks == []

    def test_python_symbols_are_chunked_by_function_and_class(self):
        content = (
            "import fastapi\n\n"
            "class Service:\n"
            "    def run(self):\n"
            "        return True\n\n"
            "@router.get('/health')\n"
            "def health():\n"
            "    return {'ok': True}\n"
        )

        chunks = chunk_code(content, "src/api.py", source_title="backend")

        symbols = {chunk.metadata.get("symbol_name"): chunk for chunk in chunks}
        assert "Service" in symbols
        assert "health" in symbols
        assert symbols["Service"].metadata["symbol_type"] == "class"
        assert symbols["health"].metadata["route_path"] == "GET /health"
        assert "source title: backend" in symbols["health"].embedding_text
        assert "imports: fastapi" in symbols["health"].embedding_text


class TestChunkDocument:
    def test_short_document_single_chunk(self):
        content = "This is a short paragraph."
        chunks = chunk_document(content, "doc.txt", source_title="Guide", page=2)
        assert len(chunks) == 1
        assert chunks[0].line_start is None
        assert chunks[0].file_type == "text"
        assert chunks[0].content == content
        assert chunks[0].metadata["source_title"] == "Guide"
        assert chunks[0].metadata["page"] == 2
        assert "source title: Guide" in chunks[0].embedding_text
        assert "page: 2" in chunks[0].embedding_text

    def test_long_document_multiple_chunks(self):
        paragraphs = [f"Paragraph {i}. " + "word " * 200 for i in range(10)]
        content = "\n\n".join(paragraphs)
        chunks = chunk_document(content, "long.txt", target_tokens=300)
        assert len(chunks) > 1
        # chunk_index 순서 확인
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_empty_document(self):
        chunks = chunk_document("", "empty.txt")
        assert chunks == []

    def test_document_heading_and_summary_are_added_to_embedding_text_only(self):
        content = "## 설치\n\n패키지를 설치합니다."
        chunks = chunk_document(content, "README.md", document_summary="프로젝트 설치 안내")

        assert chunks[0].content == content
        assert chunks[0].metadata["heading"] == "설치"
        assert chunks[0].metadata["document_summary"] == "프로젝트 설치 안내"
        assert "heading: 설치" in chunks[0].embedding_text
        assert "document summary: 프로젝트 설치 안내" in chunks[0].embedding_text


class TestChunkText:
    def test_code_file_uses_code_chunker(self):
        content = "\n".join(f"x = {i}" for i in range(10))
        chunks = chunk_text(content, "script.py")
        assert len(chunks) >= 1
        assert chunks[0].file_type == "python"
        assert chunks[0].line_start is not None

    def test_text_file_uses_document_chunker(self):
        content = "Hello world"
        chunks = chunk_text(content, "readme.txt")
        assert len(chunks) == 1
        assert chunks[0].line_start is None

    def test_chunk_text_enforces_default_embedding_size(self):
        content = "const payload = '" + ("x" * (MAX_CHUNK_CHARS * 2)) + "';"
        chunks = chunk_text(content, "huge.js")

        assert len(chunks) > 1
        assert all(len(chunk.content) <= MAX_CHUNK_CHARS for chunk in chunks)

    def test_splits_oversized_single_line_code_chunk(self):
        content = "x = '" + ("a" * 120) + "'"
        chunks = enforce_max_chunk_chars(
            chunk_code(content, "large.py"),
            max_chars=50,
        )

        assert len(chunks) > 1
        assert all(len(chunk.content) <= 50 for chunk in chunks)
        assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
        assert {chunk.line_start for chunk in chunks} == {1}
        assert {chunk.line_end for chunk in chunks} == {1}

    def test_splits_oversized_document_chunk(self):
        content = "a" * 130
        chunks = enforce_max_chunk_chars(
            chunk_document(content, "large.txt"),
            max_chars=50,
        )

        assert len(chunks) == 3
        assert all(len(chunk.content) <= 50 for chunk in chunks)
        assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
