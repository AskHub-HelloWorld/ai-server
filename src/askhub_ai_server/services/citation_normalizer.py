"""Citation normalization for LLM answers."""

from __future__ import annotations

import re

_CITATION_CLUSTER_RE = re.compile(r"\[\d+\](?:\s*\[\d+\])*")
_INLINE_CITATION_RE = re.compile(r"\[(\d+)\]")


def normalize_inline_citations(answer: str, citations: list[dict]) -> tuple[str, list[dict]]:
    """Renumber cited sources by first appearance in the answer.

    The retriever may pass many context chunks to the LLM, so the model can
    legitimately cite sparse source indexes such as [2] and [10]. This function
    keeps the source mapping but exposes only the used citations as [1], [2], ...
    in first-appearance order.

    Invalid bracketed numbers are only removed from citation clusters that also
    contain a valid citation. Standalone bracketed numbers are preserved because
    they may be problem numbers, equation numbers, or ordinary document text.
    """
    if not answer or not citations:
        return answer, citations

    citation_by_original_index = _index_citations(citations)
    if not citation_by_original_index:
        return answer, []

    remapped_by_original_index: dict[int, dict] = {}
    remapped_citations: list[dict] = []

    def remap_index(original_index: int) -> dict | None:
        citation = citation_by_original_index.get(original_index)
        if citation is None:
            return None

        display_citation = remapped_by_original_index.get(original_index)
        if display_citation is None:
            display_citation = {
                **citation,
                "original_index": original_index,
                "index": len(remapped_citations) + 1,
            }
            remapped_by_original_index[original_index] = display_citation
            remapped_citations.append(display_citation)
        return display_citation

    def replace_cluster(match: re.Match[str]) -> str:
        cluster = match.group(0)
        refs = [int(raw) for raw in _INLINE_CITATION_RE.findall(cluster)]
        if not any(ref in citation_by_original_index for ref in refs):
            return cluster

        rendered_refs: list[str] = []
        seen_display_indexes: set[int] = set()
        for ref in refs:
            display_citation = remap_index(ref)
            if display_citation is None:
                continue
            display_index = display_citation["index"]
            if display_index in seen_display_indexes:
                continue
            seen_display_indexes.add(display_index)
            rendered_refs.append(f"[{display_index}]")
        return "".join(rendered_refs)

    normalized_answer = _CITATION_CLUSTER_RE.sub(replace_cluster, answer)
    normalized_answer = re.sub(r"\s+([.,!?])", r"\1", normalized_answer)
    if remapped_citations:
        return normalized_answer, remapped_citations

    original_index, citation = next(iter(citation_by_original_index.items()))
    fallback_citation = {**citation, "original_index": original_index, "index": 1}
    return f"{normalized_answer.rstrip()} [1]", [fallback_citation]


def _index_citations(citations: list[dict]) -> dict[int, dict]:
    citation_by_original_index: dict[int, dict] = {}
    for citation in citations:
        try:
            index = int(citation.get("index"))
        except (TypeError, ValueError):
            continue
        if index > 0 and index not in citation_by_original_index:
            citation_by_original_index[index] = citation
    return citation_by_original_index
