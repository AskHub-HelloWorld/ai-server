"""히스토리 요약 단위 테스트."""

from askhub_ai_server.schemas.chat import HistoryMessage
from askhub_ai_server.services.history_summarizer import HistorySummarizer


def _make_history(n: int) -> list[HistoryMessage]:
    """user/assistant 교대로 n개의 히스토리 메시지 생성."""
    messages = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(HistoryMessage(role=role, content=f"메시지 {i}"))
    return messages


class TestHistorySummarizer:
    def test_below_threshold_no_summary(self):
        history = _make_history(10)
        summarizer = HistorySummarizer(lambda text: "요약")
        summary, result = summarizer.summarize_if_needed(history, threshold=14)
        assert summary is None
        assert result == history

    def test_at_threshold_no_summary(self):
        history = _make_history(14)
        summarizer = HistorySummarizer(lambda text: "요약")
        summary, result = summarizer.summarize_if_needed(history, threshold=14)
        assert summary is None
        assert result == history

    def test_above_threshold_summarizes(self):
        history = _make_history(20)
        summarizer = HistorySummarizer(lambda text: "이전 대화 요약입니다")
        summary, recent = summarizer.summarize_if_needed(
            history, max_recent=10, threshold=14,
        )
        assert summary == "이전 대화 요약입니다"
        assert len(recent) == 10
        assert recent == history[-10:]

    def test_recent_count_preserved(self):
        history = _make_history(30)
        summarizer = HistorySummarizer(lambda text: "요약")
        summary, recent = summarizer.summarize_if_needed(
            history, max_recent=5, threshold=10,
        )
        assert summary is not None
        assert len(recent) == 5
        assert recent == history[-5:]

    def test_summarize_fn_receives_older_messages(self):
        history = _make_history(16)
        received_text = []

        def capture_summarize(text):
            received_text.append(text)
            return "요약"

        summarizer = HistorySummarizer(capture_summarize)
        summarizer.summarize_if_needed(history, max_recent=10, threshold=14)
        assert len(received_text) == 1
        # older = history[:-10] = 6개 메시지
        assert "메시지 0" in received_text[0]
        assert "메시지 5" in received_text[0]

    def test_summarize_fn_exception_fallback(self):
        history = _make_history(20)

        def raise_error(text):
            raise RuntimeError("LLM 실패")

        summarizer = HistorySummarizer(raise_error)
        summary, result = summarizer.summarize_if_needed(
            history, max_recent=10, threshold=14,
        )
        assert summary is None
        assert result == history

    def test_disabled_no_summary(self):
        history = _make_history(20)
        summarizer = HistorySummarizer(lambda text: "요약", enabled=False)
        summary, result = summarizer.summarize_if_needed(
            history, max_recent=10, threshold=14,
        )
        assert summary is None
        assert result == history
