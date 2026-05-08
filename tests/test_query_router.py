"""쿼리 라우터 단위 테스트."""

from askhub_ai_server.services.query_router import QueryIntent, QueryRouter


class TestQueryRouter:
    def test_classify_rag(self):
        router = QueryRouter(lambda q: "rag")
        assert router.classify("Spring Boot 설정 방법") == QueryIntent.RAG_NEEDED

    def test_classify_chat(self):
        router = QueryRouter(lambda q: "chat")
        assert router.classify("안녕하세요") == QueryIntent.GENERAL_CHAT

    def test_classify_followup_with_history(self):
        router = QueryRouter(lambda q: "followup")
        assert router.classify("방금 말한 코드에서", has_history=True) == QueryIntent.FOLLOW_UP

    def test_classify_followup_without_history_falls_back_to_rag(self):
        router = QueryRouter(lambda q: "followup")
        assert router.classify("방금 말한 코드에서", has_history=False) == QueryIntent.RAG_NEEDED

    def test_classify_unknown_defaults_to_rag(self):
        router = QueryRouter(lambda q: "unknown_label")
        assert router.classify("테스트") == QueryIntent.RAG_NEEDED

    def test_classify_exception_defaults_to_rag(self):
        def raise_error(q):
            raise RuntimeError("LLM 호출 실패")

        router = QueryRouter(raise_error)
        assert router.classify("테스트") == QueryIntent.RAG_NEEDED

    def test_disabled_returns_rag(self):
        router = QueryRouter(lambda q: "chat", enabled=False)
        assert router.classify("안녕하세요") == QueryIntent.RAG_NEEDED

    def test_classify_strips_whitespace(self):
        router = QueryRouter(lambda q: "  chat  \n")
        assert router.classify("안녕") == QueryIntent.GENERAL_CHAT
