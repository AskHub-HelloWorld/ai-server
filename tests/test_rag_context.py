"""rag_context 모듈 단위 테스트 — CitationBuilder, RagContextBuilder."""

import uuid

from askhub_ai_server.services.rag_context import CitationBuilder, RagContextBuilder
from askhub_ai_server.services.retriever import RetrievedChunk


def _make_chunk(
    *,
    file_path: str = "src/main.py",
    file_type: str = "python",
    source_name: str = "backend",
    source_type: str = "repository",
    line_start: int | None = 1,
    line_end: int | None = 50,
    commit_sha: str | None = "abc1234",
    repo_url: str | None = "https://github.com/org/repo",
    source_id: uuid.UUID | None = None,
    source_file_id: uuid.UUID | None = None,
    content: str = "def hello():\n    print('hi')",
    chunk_index: int = 0,
    similarity: float = 0.85,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        content=content,
        file_path=file_path,
        file_type=file_type,
        line_start=line_start,
        line_end=line_end,
        chunk_index=chunk_index,
        metadata={},
        commit_sha=commit_sha,
        repo_url=repo_url,
        source_id=source_id or uuid.uuid4(),
        source_name=source_name,
        source_type=source_type,
        source_file_id=source_file_id,
        similarity=similarity,
    )


class FakeRetriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.queries = []

    def search(self, query, team_id):
        self.queries.append((query, team_id))
        return self.chunks


class QueryMappedRetriever:
    def __init__(self, chunks_by_query):
        self.chunks_by_query = chunks_by_query
        self.queries = []

    def search(self, query, team_id):
        self.queries.append((query, team_id))
        return self.chunks_by_query.get(query, [])


class FakeQueryRewriter:
    def __init__(self, rewritten: str) -> None:
        self.rewritten = rewritten

    def rewrite_for_retrieval(self, query: str) -> str:
        return self.rewritten


class TestCitationBuilder:
    def test_builds_code_citation_with_github_url(self):
        chunk = _make_chunk()
        citations = CitationBuilder.build([chunk])
        assert len(citations) == 1
        c = citations[0]
        assert c["index"] == 1
        assert c["source_type"] == "repository"
        assert c["path"] == "src/main.py"
        assert c["commit_sha"] == "abc1234"
        assert "blob/abc1234/src/main.py#L1-L50" in c["url"]

    def test_builds_document_citation_with_download_url(self):
        file_id = uuid.uuid4()
        chunk = _make_chunk(
            file_path="docs/guide.pdf",
            file_type="pdf",
            source_type="document",
            commit_sha=None,
            repo_url=None,
            source_file_id=file_id,
            line_start=None,
            line_end=None,
        )
        citations = CitationBuilder.build([chunk])
        assert len(citations) == 1
        c = citations[0]
        assert c["source_type"] == "document"
        assert c["file_id"] == str(file_id)
        assert c["url"] == f"/v1/files/{file_id}/download"
        assert c["line_start"] is None

    def test_deduplicates_same_file_range(self):
        chunk1 = _make_chunk(file_path="a.py", line_start=1, line_end=50)
        # 같은 source_id를 만들기 위해 동일 객체를 두 번 넣는다
        citations = CitationBuilder.build([chunk1, chunk1])
        # frozen dataclass이므로 같은 key → 1개만
        assert len(citations) == 1

    def test_strips_git_suffix_from_repo_url(self):
        chunk = _make_chunk(repo_url="https://github.com/org/repo.git")
        citations = CitationBuilder.build([chunk])
        assert ".git" not in citations[0]["url"]

    def test_does_not_dedupe_different_document_chunks_without_lines(self):
        source_id = uuid.uuid4()
        file_id = uuid.uuid4()
        chunk1 = _make_chunk(
            file_path="guide.pdf",
            source_type="document",
            source_id=source_id,
            source_file_id=file_id,
            line_start=None,
            line_end=None,
            chunk_index=0,
        )
        chunk2 = _make_chunk(
            file_path="guide.pdf",
            source_type="document",
            source_id=source_id,
            source_file_id=file_id,
            line_start=None,
            line_end=None,
            chunk_index=1,
        )

        citations = CitationBuilder.build([chunk1, chunk2])

        assert [citation["index"] for citation in citations] == [1, 2]

    def test_empty_chunks(self):
        assert CitationBuilder.build([]) == []


class TestRagContextBuilder:
    def test_returns_empty_when_team_id_is_none(self):
        # retriever는 호출되지 않아야 하므로 None을 전달해도 OK
        builder = RagContextBuilder(retriever=None)  # type: ignore[arg-type]
        ctx = builder.build("질문", team_id=None)
        assert ctx.text == ""
        assert ctx.citations == []
        assert ctx.chunks == []

    def test_context_and_citations_share_deduped_numbering(self):
        chunk = _make_chunk()
        retriever = FakeRetriever([chunk, chunk])
        builder = RagContextBuilder(
            retriever=retriever,  # type: ignore[arg-type]
            max_context_tokens=200,
        )

        ctx = builder.build("질문", team_id=10)

        assert ctx.text.count("[참고자료 1]") == 1
        assert "[참고자료 2]" not in ctx.text
        assert [citation["index"] for citation in ctx.citations] == [1]
        assert retriever.queries == [("질문", 10)]

    def test_rewrites_query_before_retrieval(self):
        chunk = _make_chunk()
        retriever = FakeRetriever([chunk])
        builder = RagContextBuilder(
            retriever=retriever,  # type: ignore[arg-type]
            max_context_tokens=200,
            query_rewriter=FakeQueryRewriter("베이즈 정리 조건부 확률 전확률 역확률"),
        )

        ctx = builder.build("베이즈 정리가 무엇인가?", team_id=10)

        assert ctx.citations
        assert retriever.queries == [
            ("베이즈 정리가 무엇인가?", 10),
            ("베이즈 정리 조건부 확률 전확률 역확률", 10),
        ]

    def test_original_query_result_survives_bad_rewrite(self):
        chunk = _make_chunk(file_path="README", content="Hello World!", similarity=0.86)
        retriever = QueryMappedRetriever({
            "Hello World! 문구가 들어 있는 파일 이름": [chunk],
            "저장소 README 설명 설치 방법 사용법": [],
        })
        builder = RagContextBuilder(
            retriever=retriever,  # type: ignore[arg-type]
            max_context_tokens=200,
            query_rewriter=FakeQueryRewriter("저장소 README 설명 설치 방법 사용법"),
        )

        ctx = builder.build("Hello World! 문구가 들어 있는 파일 이름", team_id=10)

        assert ctx.citations
        assert "Hello World!" in ctx.text
        assert retriever.queries == [
            ("Hello World! 문구가 들어 있는 파일 이름", 10),
            ("저장소 README 설명 설치 방법 사용법", 10),
        ]

    def test_applies_max_context_tokens(self):
        chunks = [
            _make_chunk(file_path="a.md", content="one two", chunk_index=0),
            _make_chunk(file_path="b.md", content=" ".join(["word"] * 200), chunk_index=1),
            _make_chunk(file_path="c.md", content="three four", chunk_index=2),
        ]
        builder = RagContextBuilder(
            retriever=FakeRetriever(chunks),  # type: ignore[arg-type]
            max_context_tokens=50,
        )

        ctx = builder.build("질문", team_id=10)

        assert "[참고자료 1]" in ctx.text
        assert "[참고자료 2]" not in ctx.text
        assert len(ctx.citations) == 1
