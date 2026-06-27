from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RagChunk:
    chunk_id: str
    source_path: str
    title: str
    text: str
    token_counts: Counter[str]
    norm: float


class RagDocumentStore:
    """Small local RAG store with deterministic lexical vectors.

    The class intentionally avoids heavyweight dependencies so the simulation
    remains runnable in a clean local environment. FAISS, Chroma, or local
    embedding models can replace the scoring internals without changing the
    query API used by agents.
    """

    def __init__(self, project_root: Path | None = None, chunk_size: int = 900, chunk_overlap: int = 140) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._chunks: list[RagChunk] = []
        self._signatures: dict[str, tuple[int, int]] = {}

    def query(self, query: str, top_k: int = 5, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_index()
        query_counts = Counter(_tokenize(query))
        query_norm = _counter_norm(query_counts)
        if not query_counts or query_norm == 0:
            return self._empty_result(query, top_k)

        scored: list[tuple[float, RagChunk]] = []
        for chunk in self._chunks:
            if filters and not self._matches_filters(chunk, filters):
                continue
            score = _cosine(query_counts, query_norm, chunk.token_counts, chunk.norm)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        matches = [
            {
                "chunk_id": chunk.chunk_id,
                "source": chunk.source_path,
                "title": chunk.title,
                "score": round(score, 4),
                "content_preview": _preview(chunk.text),
                "content": chunk.text,
            }
            for score, chunk in scored[: max(1, top_k)]
        ]
        return {
            "query": query,
            "top_k": top_k,
            "match_count": len(matches),
            "matches": matches,
            "index": self.stats(),
        }

    def reindex(self) -> dict[str, Any]:
        self._chunks = []
        self._signatures = {}
        for path in self._source_paths():
            self._index_path(path)
        return self.stats()

    def ensure_index(self) -> None:
        current = self._collect_signatures()
        if current != self._signatures:
            self.reindex()

    def stats(self) -> dict[str, Any]:
        sources = sorted({chunk.source_path for chunk in self._chunks})
        return {
            "source_count": len(sources),
            "chunk_count": len(self._chunks),
            "sources": sources,
            "engine": "local_lexical_cosine",
        }

    def sources(self) -> dict[str, Any]:
        self.ensure_index()
        return self.stats()

    def _source_paths(self) -> list[Path]:
        patterns = [
            "docs/*.md",
            "backend/app/config/*.yaml",
            "data/tasks/*.json",
        ]
        paths: list[Path] = []
        for pattern in patterns:
            paths.extend(sorted(self.project_root.glob(pattern)))
        return [path for path in paths if path.is_file()]

    def _collect_signatures(self) -> dict[str, tuple[int, int]]:
        signatures: dict[str, tuple[int, int]] = {}
        for path in self._source_paths():
            stat = path.stat()
            signatures[self._relative(path)] = (int(stat.st_mtime), int(stat.st_size))
        return signatures

    def _index_path(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        relative = self._relative(path)
        chunks = _split_text(text, self.chunk_size, self.chunk_overlap)
        for index, chunk_text in enumerate(chunks):
            counts = Counter(_tokenize(chunk_text))
            norm = _counter_norm(counts)
            if not counts or norm == 0:
                continue
            self._chunks.append(
                RagChunk(
                    chunk_id=f"{relative}#{index + 1}",
                    source_path=relative,
                    title=_title_for_chunk(path, chunk_text),
                    text=chunk_text,
                    token_counts=counts,
                    norm=norm,
                )
            )
        self._signatures = self._collect_signatures()

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.project_root).as_posix()

    def _matches_filters(self, chunk: RagChunk, filters: dict[str, Any]) -> bool:
        source_contains = filters.get("source_contains")
        if source_contains and str(source_contains) not in chunk.source_path:
            return False
        return True

    def _empty_result(self, query: str, top_k: int) -> dict[str, Any]:
        return {
            "query": query,
            "top_k": top_k,
            "match_count": 0,
            "matches": [],
            "index": self.stats(),
        }


def _tokenize(text: str) -> list[str]:
    normalized = text.lower()
    tokens = re.findall(r"[a-z0-9_]+", normalized)
    non_ascii_chars = [char for char in normalized if ord(char) > 127 and not char.isspace()]
    tokens.extend(non_ascii_chars)
    tokens.extend("".join(pair) for pair in zip(non_ascii_chars, non_ascii_chars[1:]))
    return tokens


def _counter_norm(counts: Counter[str]) -> float:
    return math.sqrt(sum(value * value for value in counts.values()))


def _cosine(left: Counter[str], left_norm: float, right: Counter[str], right_norm: float) -> float:
    if left_norm == 0 or right_norm == 0:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = sum(value * right.get(token, 0) for token, value in left.items())
    return dot / (left_norm * right_norm)


def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = paragraph
        while len(current) > chunk_size:
            chunks.append(current[:chunk_size])
            current = current[max(0, chunk_size - chunk_overlap) :]
    if current:
        chunks.append(current)
    return chunks


def _title_for_chunk(path: Path, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or path.stem
    return path.stem


def _preview(text: str, max_len: int = 360) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= max_len:
        return collapsed
    return f"{collapsed[: max_len - 3]}..."
