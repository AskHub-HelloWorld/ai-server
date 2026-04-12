from askhub_ai_server.schemas.chat import ChatAttachment, ChatRequest, HistoryMessage
from askhub_ai_server.services.llm import build_converse_messages


def test_build_converse_messages_includes_image_block() -> None:
    request = ChatRequest(
        message="이 이미지에 뭐라고 써져 있나요?",
        history=[HistoryMessage(role="assistant", content="이전 답변입니다.")],
        attachments=[
            ChatAttachment(
                filename="image.png",
                content_type="image/png",
                data=b"png-bytes",
            )
        ],
    )

    messages = build_converse_messages(request)

    assert messages[0] == {"role": "assistant", "content": [{"text": "이전 답변입니다."}]}
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == [
        {"image": {"format": "png", "source": {"bytes": b"png-bytes"}}},
        {"text": "이 이미지에 뭐라고 써져 있나요?"},
    ]
