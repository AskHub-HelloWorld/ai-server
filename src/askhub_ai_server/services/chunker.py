"""문서/코드 청킹 로직 — RAG 인덱싱용 텍스트 분할."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 코드 파일 확장자 매핑
CODE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".cpp", ".c",
    ".h", ".hpp", ".cs", ".rb", ".kt", ".swift", ".scala", ".sh", ".bash",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".sql", ".r", ".m", ".lua",
    ".pl", ".php", ".dart", ".vue", ".svelte",
    "dockerfile", "makefile",
}

# Titan Embed v2 rejects inputs above 8,192 tokens. We do not have the exact
# Bedrock tokenizer locally, so keep the character cap conservative; minified
# code can tokenize much denser than normal prose.
MAX_CHUNK_CHARS: int = 8_000

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
_JS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+default\s+|export\s+)?(?:(async)\s+)?"
    r"(?:(class|function)\s+([A-Za-z_$][\w$]*)|"
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>)",
)
_JS_ROUTE_RE = re.compile(
    r"\b(?P<receiver>app|router|server)\.(?P<method>get|post|put|patch|delete|options|head)"
    r"\s*\(\s*['\"](?P<path>[^'\"]+)['\"]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Chunk:
    """분할된 텍스트 청크.

    ``content``는 citation과 LLM context에 쓰는 원문이다.
    ``embedding_text``/``search_text``는 path, heading, symbol 같은 검색 힌트를
    붙인 인덱싱 입력이다.
    """

    content: str
    file_path: str
    file_type: str
    chunk_index: int
    line_start: int | None = None
    line_end: int | None = None
    embedding_text: str | None = None
    search_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def is_code_file(file_path: str) -> bool:
    """파일 경로로 코드 파일 여부를 판별한다."""
    lower = file_path.lower()
    # 확장자 없는 특수 파일 (Dockerfile, Makefile)
    basename = lower.rsplit("/", 1)[-1] if "/" in lower else lower
    if basename in CODE_EXTENSIONS:
        return True
    # 확장자 기반 판별
    dot_idx = lower.rfind(".")
    if dot_idx == -1:
        return False
    return lower[dot_idx:] in CODE_EXTENSIONS


def detect_file_type(file_path: str) -> str:
    """파일 경로에서 파일 타입을 추론한다."""
    lower = file_path.lower()
    basename = lower.rsplit("/", 1)[-1] if "/" in lower else lower

    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".jsx": "javascript", ".tsx": "typescript", ".java": "java",
        ".go": "go", ".rs": "rust", ".cpp": "cpp", ".c": "c",
        ".h": "c", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby",
        ".kt": "kotlin", ".swift": "swift", ".scala": "scala",
        ".sh": "shell", ".bash": "shell", ".yaml": "yaml", ".yml": "yaml",
        ".toml": "toml", ".json": "json", ".xml": "xml", ".sql": "sql",
        ".md": "markdown", ".txt": "text", ".pdf": "pdf", ".docx": "docx",
        ".pptx": "pptx", ".csv": "csv", ".html": "html",
        ".vue": "vue", ".svelte": "svelte", ".dart": "dart",
        ".php": "php", ".lua": "lua", ".r": "r", ".pl": "perl",
    }
    basename_map = {"dockerfile": "dockerfile", "makefile": "makefile"}

    if basename in basename_map:
        return basename_map[basename]
    dot_idx = lower.rfind(".")
    if dot_idx != -1:
        return ext_map.get(lower[dot_idx:], "text")
    return "text"


def chunk_code(
    content: str,
    file_path: str,
    *,
    window_lines: int = 100,
    overlap_lines: int = 20,
    source_title: str | None = None,
) -> list[Chunk]:
    """코드 파일을 함수/클래스/route 단위로 우선 분할한다.

    파서가 지원하지 못하는 언어 또는 심볼이 없는 파일은 기존 슬라이딩 윈도우
    방식으로 fallback한다.
    """
    file_type = detect_file_type(file_path)
    lines = content.splitlines(keepends=True)
    if not lines:
        return []

    base_metadata = _base_code_metadata(content, file_path, file_type, source_title)
    symbol_chunks: list[Chunk] = []
    if file_type == "python":
        symbol_chunks = _chunk_python_symbols(content, file_path, file_type, base_metadata)
    elif file_type in {"javascript", "typescript", "vue", "svelte"}:
        symbol_chunks = _chunk_javascript_symbols(content, file_path, file_type, base_metadata)

    if symbol_chunks:
        return _reindex_chunks(symbol_chunks)

    chunks: list[Chunk] = []
    step = max(window_lines - overlap_lines, 1)
    chunk_index = 0

    for start in range(0, len(lines), step):
        end = min(start + window_lines, len(lines))
        chunk_content = "".join(lines[start:end])
        if chunk_content.strip():
            metadata = {
                **base_metadata,
                "symbol_type": "file_window",
            }
            chunks.append(_make_chunk(
                content=chunk_content,
                file_path=file_path,
                file_type=file_type,
                chunk_index=chunk_index,
                line_start=start + 1,
                line_end=end,
                metadata=metadata,
            ))
            chunk_index += 1
        if end >= len(lines):
            break

    return chunks


def chunk_document(
    content: str,
    file_path: str,
    *,
    target_tokens: int = 500,
    overlap_sentences: int = 2,
    source_title: str | None = None,
    page: int | None = None,
    document_summary: str | None = None,
) -> list[Chunk]:
    """문서 텍스트를 단락/heading 기반으로 분할한다.

    원문 ``content``는 그대로 보존하고, embedding/BM25용 입력에만 page,
    heading, section, document summary, source title을 붙인다.
    """
    file_type = detect_file_type(file_path)
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    if not paragraphs:
        return []

    title = source_title or _source_title_from_path(file_path)
    summary = _short_summary(document_summary or content)
    chunks: list[Chunk] = []
    current_parts: list[str] = []
    current_word_count = 0
    current_heading: str | None = None
    current_section: str | None = None
    chunk_heading: str | None = None
    chunk_section: str | None = None
    chunk_index = 0

    def flush() -> None:
        nonlocal current_parts, current_word_count, chunk_heading, chunk_section, chunk_index
        if not current_parts:
            return
        chunk_content = "\n\n".join(current_parts)
        metadata = {
            "chunk_kind": "document",
            "source_title": title,
            "page": page,
            "heading": chunk_heading,
            "section": chunk_section,
            "document_summary": summary,
        }
        chunks.append(_make_chunk(
            content=chunk_content,
            file_path=file_path,
            file_type=file_type,
            chunk_index=chunk_index,
            metadata=metadata,
        ))
        chunk_index += 1

    for para in paragraphs:
        detected_heading = _detect_heading(para)
        if detected_heading:
            current_heading = detected_heading
            current_section = detected_heading

        word_count = len(para.split())
        if current_word_count + word_count > target_tokens and current_parts:
            flush()
            if overlap_sentences > 0 and len(current_parts) > overlap_sentences:
                current_parts = current_parts[-overlap_sentences:]
                current_word_count = sum(len(p.split()) for p in current_parts)
                chunk_heading = current_heading
                chunk_section = current_section
            else:
                current_parts = []
                current_word_count = 0
                chunk_heading = None
                chunk_section = None

        if not current_parts:
            chunk_heading = current_heading
            chunk_section = current_section
        current_parts.append(para)
        current_word_count += word_count

    flush()
    return chunks


def chunk_markdown(
    content: str,
    file_path: str,
    *,
    target_tokens: int = 500,
    source_title: str | None = None,
    page: int | None = None,
    document_summary: str | None = None,
) -> list[Chunk]:
    """마크다운 구조를 인식하여 청킹한다.

    전략:
    1. heading 라인(``^#{1,6}\\s+``)으로 섹션 분할
    2. heading 계층 추적 → breadcrumb (예: ``"설치 가이드 > 사전 요구사항"``)
    3. 테이블(``|...|``)과 코드 블록(````` ``` `````)은 원자 단위로 보존
    4. 섹션이 target_tokens 이하면 단일 청크, 초과하면 단락 경계에서 분할
    5. 각 청크의 metadata에 heading_breadcrumb 포함
    """
    file_type = detect_file_type(file_path)
    title = source_title or _source_title_from_path(file_path)
    summary = _short_summary(document_summary or content)

    sections = _split_markdown_sections(content)
    if not sections:
        return chunk_document(
            content, file_path, target_tokens=target_tokens,
            source_title=source_title, page=page, document_summary=document_summary,
        )

    chunks: list[Chunk] = []
    chunk_index = 0

    for section in sections:
        section_tokens = _estimate_word_count(section.content)
        if section_tokens <= target_tokens:
            # 섹션이 타겟 이하면 단일 청크
            if section.content.strip():
                metadata = _markdown_chunk_metadata(
                    title, page, section.breadcrumb, summary,
                )
                chunks.append(_make_chunk(
                    content=section.content,
                    file_path=file_path,
                    file_type=file_type,
                    chunk_index=chunk_index,
                    metadata=metadata,
                ))
                chunk_index += 1
        else:
            # 섹션이 타겟 초과면 블록 단위로 분할
            blocks = _split_section_into_blocks(section.content)
            current_parts: list[str] = []
            current_word_count = 0

            for block in blocks:
                block_words = _estimate_word_count(block)

                # 단일 블록이 타겟을 크게 초과하면 문장 단위로 분할
                is_atomic = _is_table_block(block) or block.strip().startswith("```")
                if block_words > target_tokens and not is_atomic:
                    if current_parts:
                        chunk_content = "\n\n".join(current_parts)
                        if chunk_content.strip():
                            metadata = _markdown_chunk_metadata(
                                title, page, section.breadcrumb, summary,
                            )
                            chunks.append(_make_chunk(
                                content=chunk_content,
                                file_path=file_path,
                                file_type=file_type,
                                chunk_index=chunk_index,
                                metadata=metadata,
                            ))
                            chunk_index += 1
                        current_parts = []
                        current_word_count = 0

                    sentences = re.split(r"(?<=[.!?。])\s+", block)
                    for sent in sentences:
                        sent_words = _estimate_word_count(sent)
                        if current_word_count + sent_words > target_tokens and current_parts:
                            chunk_content = " ".join(current_parts)
                            if chunk_content.strip():
                                metadata = _markdown_chunk_metadata(
                                    title, page, section.breadcrumb, summary,
                                )
                                chunks.append(_make_chunk(
                                    content=chunk_content,
                                    file_path=file_path,
                                    file_type=file_type,
                                    chunk_index=chunk_index,
                                    metadata=metadata,
                                ))
                                chunk_index += 1
                            current_parts = []
                            current_word_count = 0
                        current_parts.append(sent)
                        current_word_count += sent_words
                    continue

                if current_word_count + block_words > target_tokens and current_parts:
                    chunk_content = "\n\n".join(current_parts)
                    if chunk_content.strip():
                        metadata = _markdown_chunk_metadata(
                            title, page, section.breadcrumb, summary,
                        )
                        chunks.append(_make_chunk(
                            content=chunk_content,
                            file_path=file_path,
                            file_type=file_type,
                            chunk_index=chunk_index,
                            metadata=metadata,
                        ))
                        chunk_index += 1
                    current_parts = []
                    current_word_count = 0

                current_parts.append(block)
                current_word_count += block_words

            if current_parts:
                chunk_content = "\n\n".join(current_parts)
                if chunk_content.strip():
                    metadata = _markdown_chunk_metadata(
                        title, page, section.breadcrumb, summary,
                    )
                    chunks.append(_make_chunk(
                        content=chunk_content,
                        file_path=file_path,
                        file_type=file_type,
                        chunk_index=chunk_index,
                        metadata=metadata,
                    ))
                    chunk_index += 1

    return chunks


@dataclass(frozen=True)
class _MarkdownSection:
    """마크다운 heading으로 구분된 섹션."""

    content: str
    breadcrumb: str | None


def _split_markdown_sections(content: str) -> list[_MarkdownSection]:
    """마크다운 heading으로 섹션을 분할하고 heading 계층을 추적한다."""
    lines = content.split("\n")
    heading_re = re.compile(r"^(#{1,6})\s+(.+)$")

    sections: list[_MarkdownSection] = []
    heading_stack: list[tuple[int, str]] = []  # (level, text)
    current_lines: list[str] = []

    def _breadcrumb() -> str | None:
        if not heading_stack:
            return None
        return " > ".join(text for _, text in heading_stack)

    def flush() -> None:
        nonlocal current_lines
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(_MarkdownSection(content=text, breadcrumb=_breadcrumb()))
        current_lines = []

    for line in lines:
        match = heading_re.match(line)
        if match:
            flush()
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            # heading 스택 관리: 현재 레벨 이상의 항목 제거
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))
            current_lines.append(line)
        else:
            current_lines.append(line)

    flush()
    return sections


def _split_section_into_blocks(content: str) -> list[str]:
    """섹션을 원자 블록(테이블, 코드 블록, 단락) 단위로 분할한다.

    코드 블록과 테이블은 내부에서 분할하지 않는다.
    """
    lines = content.split("\n")
    blocks: list[str] = []
    current: list[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        # 코드 블록 토글
        if stripped.startswith("```"):
            if in_code_block:
                # 코드 블록 종료
                current.append(line)
                blocks.append("\n".join(current))
                current = []
                in_code_block = False
                continue
            else:
                # 코드 블록 시작: 이전 내용 flush
                if current:
                    blocks.append("\n".join(current))
                    current = []
                current.append(line)
                in_code_block = True
                continue

        if in_code_block:
            current.append(line)
            continue

        # 빈 줄 = 단락 경계
        if not stripped:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue

        current.append(line)

    if current:
        blocks.append("\n".join(current))

    # 테이블 블록 병합: 연속된 | 라인을 하나의 블록으로
    merged: list[str] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if _is_table_block(block):
            table_parts = [block]
            while i + 1 < len(blocks) and _is_table_block(blocks[i + 1]):
                i += 1
                table_parts.append(blocks[i])
            merged.append("\n\n".join(table_parts))
        else:
            merged.append(block)
        i += 1

    return [b for b in merged if b.strip()]


def _is_table_block(block: str) -> bool:
    """블록이 마크다운 테이블인지 판별한다."""
    lines = [line for line in block.strip().split("\n") if line.strip()]
    if len(lines) < 2:
        return False
    return all(line.strip().startswith("|") for line in lines)


def _estimate_word_count(text: str) -> int:
    return len(text.split())


def _markdown_chunk_metadata(
    title: str,
    page: int | None,
    breadcrumb: str | None,
    summary: str,
) -> dict[str, Any]:
    return {
        "chunk_kind": "document",
        "source_title": title,
        "page": page,
        "heading_breadcrumb": breadcrumb,
        "heading": breadcrumb.split(" > ")[-1] if breadcrumb else None,
        "section": breadcrumb,
        "document_summary": summary,
    }


def _looks_like_markdown(content: str) -> bool:
    """텍스트가 마크다운 형식인지 간단히 판별한다."""
    indicators = 0
    sample = content[:4000]  # 처음 4000자만 검사

    if re.search(r"^#{1,6}\s+", sample, re.MULTILINE):
        indicators += 1
    if re.search(r"^\|.+\|$", sample, re.MULTILINE):
        indicators += 1
    if re.search(r"^```", sample, re.MULTILINE):
        indicators += 1
    if re.search(r"^[-*+]\s+", sample, re.MULTILINE):
        indicators += 1
    if re.search(r"\[.+\]\(.+\)", sample):
        indicators += 1

    return indicators >= 2


def estimate_tokens(text: str) -> int:
    """UTF-8 바이트 기반 토큰 수 추정 (BPE 근사).

    ``len(text.split())`` 는 한국어 등 교착어에서 토큰 수를 극심하게
    과소평가한다. UTF-8 바이트 길이를 4로 나누면 BPE 토크나이저와
    유사한 근사값을 얻을 수 있다.
    """
    return max(1, len(text.encode("utf-8")) // 4)


def chunk_text(
    content: str,
    file_path: str,
    *,
    source_title: str | None = None,
    page: int | None = None,
    document_summary: str | None = None,
    is_markdown: bool = False,
) -> list[Chunk]:
    """파일 종류에 따라 적절한 청킹 전략을 선택한다."""
    if is_code_file(file_path):
        return enforce_max_chunk_chars(chunk_code(
            content,
            file_path,
            source_title=source_title,
        ))
    if is_markdown or _looks_like_markdown(content):
        return enforce_max_chunk_chars(chunk_markdown(
            content,
            file_path,
            source_title=source_title,
            page=page,
            document_summary=document_summary,
        ))
    return enforce_max_chunk_chars(chunk_document(
        content,
        file_path,
        source_title=source_title,
        page=page,
        document_summary=document_summary,
    ))


def enforce_max_chunk_chars(
    chunks: list[Chunk],
    *,
    max_chars: int = MAX_CHUNK_CHARS,
) -> list[Chunk]:
    """Bedrock embedding 입력 제한을 넘는 청크를 더 작은 청크로 나눈다."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")

    resized: list[Chunk] = []
    for chunk in chunks:
        resized.extend(_split_chunk_by_chars(chunk, max_chars=max_chars))

    return [_replace_chunk_index(chunk, index) for index, chunk in enumerate(resized)]


def _chunk_python_symbols(
    content: str,
    file_path: str,
    file_type: str,
    base_metadata: dict[str, Any],
) -> list[Chunk]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    lines = content.splitlines(keepends=True)
    chunks: list[Chunk] = []
    ranges: list[tuple[int, int]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        line_start = node.lineno
        line_end = getattr(node, "end_lineno", node.lineno)
        route_path = _extract_python_route_path(node)
        symbol_type = "class" if isinstance(node, ast.ClassDef) else "function"
        if isinstance(node, ast.AsyncFunctionDef):
            symbol_type = "async_function"
        metadata = {
            **base_metadata,
            "symbol_name": node.name,
            "symbol_type": symbol_type,
            "route_path": route_path,
        }
        chunks.append(_make_chunk(
            content="".join(lines[line_start - 1 : line_end]),
            file_path=file_path,
            file_type=file_type,
            chunk_index=len(chunks),
            line_start=line_start,
            line_end=line_end,
            metadata=metadata,
        ))
        ranges.append((line_start, line_end))

    chunks.extend(_module_gap_chunks(lines, ranges, file_path, file_type, base_metadata))
    return sorted(chunks, key=lambda chunk: chunk.line_start or 0)


def _chunk_javascript_symbols(
    content: str,
    file_path: str,
    file_type: str,
    base_metadata: dict[str, Any],
) -> list[Chunk]:
    lines = content.splitlines(keepends=True)
    starts: list[tuple[int, dict[str, Any]]] = []
    for idx, line in enumerate(lines, 1):
        route = _JS_ROUTE_RE.search(line)
        match = _JS_SYMBOL_RE.search(line)
        if route:
            metadata = {
                **base_metadata,
                "symbol_name": f"{route.group('method').lower()} {route.group('path')}",
                "symbol_type": "route",
                "route_path": f"{route.group('method').upper()} {route.group('path')}",
            }
            starts.append((idx, metadata))
            continue
        if match:
            symbol_type = match.group(2) or "function"
            symbol_name = match.group(3) or match.group(4)
            if match.group(1):
                symbol_type = f"async_{symbol_type}"
            metadata = {
                **base_metadata,
                "symbol_name": symbol_name,
                "symbol_type": symbol_type,
            }
            starts.append((idx, metadata))

    if not starts:
        return []

    chunks: list[Chunk] = []
    for index, (line_start, metadata) in enumerate(starts):
        next_start = starts[index + 1][0] if index + 1 < len(starts) else len(lines) + 1
        line_end = max(line_start, next_start - 1)
        chunk_content = "".join(lines[line_start - 1 : line_end])
        if chunk_content.strip():
            chunks.append(_make_chunk(
                content=chunk_content,
                file_path=file_path,
                file_type=file_type,
                chunk_index=len(chunks),
                line_start=line_start,
                line_end=line_end,
                metadata=metadata,
            ))
    return chunks


def _module_gap_chunks(
    lines: list[str],
    ranges: list[tuple[int, int]],
    file_path: str,
    file_type: str,
    base_metadata: dict[str, Any],
) -> list[Chunk]:
    if not ranges:
        return []

    chunks: list[Chunk] = []
    cursor = 1
    for start, end in sorted(ranges):
        if cursor < start:
            chunks.extend(_make_module_chunk(
                lines,
                cursor,
                start - 1,
                file_path,
                file_type,
                base_metadata,
            ))
        cursor = max(cursor, end + 1)
    if cursor <= len(lines):
        chunks.extend(_make_module_chunk(
            lines,
            cursor,
            len(lines),
            file_path,
            file_type,
            base_metadata,
        ))
    return chunks


def _make_module_chunk(
    lines: list[str],
    start: int,
    end: int,
    file_path: str,
    file_type: str,
    base_metadata: dict[str, Any],
) -> list[Chunk]:
    chunk_content = "".join(lines[start - 1 : end])
    if not chunk_content.strip():
        return []
    metadata = {
        **base_metadata,
        "symbol_type": "module",
    }
    return [_make_chunk(
        content=chunk_content,
        file_path=file_path,
        file_type=file_type,
        chunk_index=0,
        line_start=start,
        line_end=end,
        metadata=metadata,
    )]


def _extract_python_route_path(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        method = _decorator_method_name(decorator.func)
        if method not in _HTTP_METHODS or not decorator.args:
            continue
        first_arg = decorator.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            return f"{method.upper()} {first_arg.value}"
    return None


def _decorator_method_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr.lower()
    if isinstance(node, ast.Name):
        return node.id.lower()
    return None


def _base_code_metadata(
    content: str,
    file_path: str,
    file_type: str,
    source_title: str | None,
) -> dict[str, Any]:
    return {
        "chunk_kind": "code",
        "source_title": source_title or _source_title_from_path(file_path),
        "file_path": file_path,
        "language": file_type,
        "imports": _extract_imports(content, file_type),
    }


def _extract_imports(content: str, file_type: str) -> list[str]:
    if file_type == "python":
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return _extract_import_lines(content)
        imports: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.extend(
                    f"{module}.{alias.name}" if module else alias.name
                    for alias in node.names
                )
        return imports[:20]
    return _extract_import_lines(content)


def _extract_import_lines(content: str) -> list[str]:
    imports: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if (
            lower.startswith(("import ", "from ", "require(", "include ", "use "))
            or " require(" in lower
        ):
            imports.append(stripped[:160])
        if len(imports) >= 20:
            break
    return imports


def _split_chunk_by_chars(chunk: Chunk, *, max_chars: int) -> list[Chunk]:
    if len(chunk.content) <= max_chars:
        return [chunk]

    if chunk.line_start is not None:
        return _split_code_chunk_by_chars(chunk, max_chars=max_chars)

    return [
        _replace_chunk_content(
            chunk,
            chunk.content[start : start + max_chars],
        )
        for start in range(0, len(chunk.content), max_chars)
        if chunk.content[start : start + max_chars].strip()
    ]


def _split_code_chunk_by_chars(chunk: Chunk, *, max_chars: int) -> list[Chunk]:
    lines = chunk.content.splitlines(keepends=True)
    if not lines:
        return []

    split_chunks: list[Chunk] = []
    current_lines: list[str] = []
    current_start_line = chunk.line_start or 1
    current_len = 0

    def flush(end_line: int) -> None:
        nonlocal current_lines, current_len, current_start_line
        if not current_lines:
            return
        content = "".join(current_lines)
        if content.strip():
            split_chunks.append(_replace_chunk_content(
                chunk,
                content,
                line_start=current_start_line,
                line_end=end_line,
            ))
        current_lines = []
        current_len = 0

    for offset, line in enumerate(lines):
        line_number = (chunk.line_start or 1) + offset
        if len(line) > max_chars:
            flush(line_number - 1)
            for start in range(0, len(line), max_chars):
                part = line[start : start + max_chars]
                if part.strip():
                    split_chunks.append(_replace_chunk_content(
                        chunk,
                        part,
                        line_start=line_number,
                        line_end=line_number,
                    ))
            current_start_line = line_number + 1
            continue

        if current_lines and current_len + len(line) > max_chars:
            flush(line_number - 1)
            current_start_line = line_number

        if not current_lines:
            current_start_line = line_number
        current_lines.append(line)
        current_len += len(line)

    flush((chunk.line_start or 1) + len(lines) - 1)
    return split_chunks


def _make_chunk(
    *,
    content: str,
    file_path: str,
    file_type: str,
    chunk_index: int,
    metadata: dict[str, Any],
    line_start: int | None = None,
    line_end: int | None = None,
) -> Chunk:
    metadata = _clean_metadata(metadata)
    embedding_text = _build_contextualized_text(
        content=content,
        file_path=file_path,
        file_type=file_type,
        line_start=line_start,
        line_end=line_end,
        metadata=metadata,
    )
    return Chunk(
        content=content,
        file_path=file_path,
        file_type=file_type,
        chunk_index=chunk_index,
        line_start=line_start,
        line_end=line_end,
        embedding_text=embedding_text,
        search_text=embedding_text,
        metadata=metadata,
    )


def _replace_chunk_content(
    chunk: Chunk,
    content: str,
    *,
    line_start: int | None = None,
    line_end: int | None = None,
) -> Chunk:
    return _make_chunk(
        content=content,
        file_path=chunk.file_path,
        file_type=chunk.file_type,
        chunk_index=chunk.chunk_index,
        line_start=chunk.line_start if line_start is None else line_start,
        line_end=chunk.line_end if line_end is None else line_end,
        metadata=chunk.metadata,
    )


def _replace_chunk_index(chunk: Chunk, chunk_index: int) -> Chunk:
    return Chunk(
        content=chunk.content,
        file_path=chunk.file_path,
        file_type=chunk.file_type,
        chunk_index=chunk_index,
        line_start=chunk.line_start,
        line_end=chunk.line_end,
        embedding_text=chunk.embedding_text,
        search_text=chunk.search_text,
        metadata=chunk.metadata,
    )


def _reindex_chunks(chunks: list[Chunk]) -> list[Chunk]:
    return [_replace_chunk_index(chunk, index) for index, chunk in enumerate(chunks)]


def _build_contextualized_text(
    *,
    content: str,
    file_path: str,
    file_type: str,
    line_start: int | None,
    line_end: int | None,
    metadata: dict[str, Any],
) -> str:
    fields: list[str] = [
        f"source title: {metadata.get('source_title') or _source_title_from_path(file_path)}",
        f"file path: {file_path}",
        f"file type: {file_type}",
    ]
    if line_start is not None:
        line_range = str(line_start) if line_end is None else f"{line_start}-{line_end}"
        fields.append(f"line range: {line_range}")

    for key in (
        "page",
        "heading",
        "section",
        "document_summary",
        "language",
        "symbol_name",
        "symbol_type",
        "route_path",
    ):
        value = metadata.get(key)
        if value:
            fields.append(f"{key.replace('_', ' ')}: {value}")

    imports = metadata.get("imports")
    if isinstance(imports, list) and imports:
        fields.append("imports: " + ", ".join(str(item) for item in imports[:20]))

    fields.append("content:")
    fields.append(content)
    return "\n".join(fields).strip()


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            value = [item for item in value if item]
            if not value:
                continue
        cleaned[key] = value
    return cleaned


def _source_title_from_path(file_path: str) -> str:
    return Path(file_path).name or file_path


def _detect_heading(paragraph: str) -> str | None:
    text = " ".join(paragraph.strip().split())
    if not text or len(text) > 120:
        return None
    markdown_heading = text.lstrip("#").strip() if text.startswith("#") else None
    if markdown_heading:
        return markdown_heading
    if text.endswith((".", "?", "!", "다", "요")) and not re.match(r"^\d+(?:\.\d+)*\s+", text):
        return None
    if re.match(r"^(?:제\s*\d+\s*[장절]|[0-9]+(?:\.[0-9]+)*\.?|[IVX]+\.)\s+", text):
        return text
    if len(text.split()) <= 8 and not any(ch in text for ch in ",;:"):
        return text
    return None


def _short_summary(text: str, *, max_chars: int = 500) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "..."
