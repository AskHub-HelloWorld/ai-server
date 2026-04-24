from askhub_ai_server.services.citation_normalizer import normalize_inline_citations


def test_normalize_inline_citations_reindexes_by_first_appearance() -> None:
    answer = "첫 근거 [2][99]. 다음은 [10]의 문제 풀이이며 반복 근거입니다 [2]. 문제 [99]."
    citations = [
        {"index": 1, "title": "unused"},
        {"index": 2, "title": "first used"},
        {"index": 10, "title": "second used"},
    ]

    normalized_answer, normalized_citations = normalize_inline_citations(answer, citations)

    assert normalized_answer == (
        "첫 근거 [1]. 다음은 [2]의 문제 풀이이며 반복 근거입니다 [1]. "
        "문제 [99]."
    )
    assert [citation["index"] for citation in normalized_citations] == [1, 2]
    assert [citation["original_index"] for citation in normalized_citations] == [2, 10]
    assert [citation["title"] for citation in normalized_citations] == [
        "first used",
        "second used",
    ]


def test_normalize_inline_citations_adds_fallback_when_no_inline_refs() -> None:
    answer = "참고자료를 바탕으로 답했습니다."
    citations = [{"index": 3, "title": "source"}]

    normalized_answer, normalized_citations = normalize_inline_citations(answer, citations)

    assert normalized_answer == "참고자료를 바탕으로 답했습니다. [1]"
    assert normalized_citations == [{"index": 1, "original_index": 3, "title": "source"}]


def test_normalize_inline_citations_preserves_standalone_unknown_brackets() -> None:
    answer = "문제 [6]을 먼저 읽고, 근거 문장에는 [2]를 붙였습니다."
    citations = [{"index": 2, "title": "source"}]

    normalized_answer, normalized_citations = normalize_inline_citations(answer, citations)

    assert normalized_answer == "문제 [6]을 먼저 읽고, 근거 문장에는 [1]를 붙였습니다."
    assert normalized_citations == [{"index": 1, "original_index": 2, "title": "source"}]


def test_normalize_inline_citations_preserves_space_after_valid_ref() -> None:
    answer = "근거 [2] 다음 문장입니다."
    citations = [{"index": 2, "title": "source"}]

    normalized_answer, normalized_citations = normalize_inline_citations(answer, citations)

    assert normalized_answer == "근거 [1] 다음 문장입니다."
    assert normalized_citations == [{"index": 1, "original_index": 2, "title": "source"}]
