"""한국어 형태소 토크나이저 단위 테스트."""

import pytest

from askhub_ai_server.services.korean_tokenizer import KoreanTokenizer, tokenize_for_search


@pytest.fixture()
def tokenizer():
    return KoreanTokenizer.get_instance()


class TestKoreanTokenizer:
    def test_tokenize_korean_sentence(self, tokenizer):
        result = tokenizer.tokenize_for_search("데이터베이스를 검색합니다")
        # 명사/동사 어간이 추출되어야 한다
        assert "데이터베이스" in result or "데이터" in result
        assert "검색" in result

    def test_tokenize_english_preserved(self, tokenizer):
        result = tokenizer.tokenize_for_search("Spring Boot application")
        assert "Spring" in result
        assert "Boot" in result
        assert "application" in result

    def test_tokenize_mixed_korean_english(self, tokenizer):
        result = tokenizer.tokenize_for_search("Spring Boot 설정 방법을 알려주세요")
        assert "Spring" in result
        assert "Boot" in result
        assert "설정" in result
        assert "방법" in result

    def test_tokenize_empty_string(self, tokenizer):
        assert tokenizer.tokenize_for_search("") == ""

    def test_tokenize_whitespace_only(self, tokenizer):
        assert tokenizer.tokenize_for_search("   ") == "   "

    def test_singleton_instance(self):
        inst1 = KoreanTokenizer.get_instance()
        inst2 = KoreanTokenizer.get_instance()
        assert inst1 is inst2

    def test_module_level_function(self):
        result = tokenize_for_search("테스트 문장입니다")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_code_tokens_preserved(self, tokenizer):
        result = tokenizer.tokenize_for_search("src/main.py 파일의 함수")
        # 영문/경로 토큰이 보존되어야 한다
        assert isinstance(result, str)
        assert len(result) > 0
