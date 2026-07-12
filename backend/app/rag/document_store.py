from __future__ import annotations

import hashlib
import math
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class RagChunk:
    chunk_id: str
    source_path: str
    title: str
    text: str
    token_counts: Counter[str]
    norm: float
    embedding: tuple[float, ...] | None = None


class RagDocumentStore:
    """Local RAG with optional Ollama embeddings and a deterministic fallback."""

    def __init__(self, project_root: Path | None = None, chunk_size: int = 900, chunk_overlap: int = 140) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._chunks: list[RagChunk] = []
        self._signatures: dict[str, str] = {}
        self.embedding_mode = os.getenv("RAG_RETRIEVAL_MODE", "lexical").lower()
        self.embedding_model = os.getenv("RAG_EMBEDDING_MODEL", "qwen3-embedding:0.6b")
        self.embedding_base_url = os.getenv("RAG_EMBEDDING_BASE_URL", "http://127.0.0.1:11434/v1")
        self.embedding_timeout_seconds = float(os.getenv("RAG_EMBEDDING_TIMEOUT_SECONDS", "30"))
        self.embedding_model_revision = os.getenv("RAG_EMBEDDING_MODEL_REVISION", "")
        self.embedding_lexical_weight = _bounded_float(os.getenv("RAG_EMBEDDING_LEXICAL_WEIGHT", "0.55"))
        configured_cache_path = os.getenv("RAG_INDEX_CACHE_PATH", ".runtime/rag_index.json").strip()
        self.cache_path = (
            Path(configured_cache_path)
            if Path(configured_cache_path).is_absolute()
            else self.project_root / configured_cache_path
        ) if configured_cache_path else None
        self._embedding_active = False
        self._embedding_fallback_reason: str | None = None
        self._cache_status = "not_loaded"

    def query(self, query: str, top_k: int = 5, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_index()
        query_counts = Counter(_tokenize(query))
        query_norm = _counter_norm(query_counts)
        if not query_counts or query_norm == 0:
            return self._empty_result(query, top_k)

        embedded_query = self._embed_text(query) if self._embedding_active else None
        scored: list[tuple[float, RagChunk]] = []
        for chunk in self._chunks:
            if filters and not self._matches_filters(chunk, filters):
                continue
            lexical_score = _lexical_score(query_counts, query_norm, chunk.token_counts, chunk.norm)
            score = lexical_score
            if embedded_query is not None and chunk.embedding is not None:
                vector_score = _vector_cosine(embedded_query, chunk.embedding)
                score = (
                    self.embedding_lexical_weight * lexical_score
                    + (1 - self.embedding_lexical_weight) * vector_score
                )
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = _diverse_top_chunks(scored, max(1, top_k))
        matches = [
            {
                "chunk_id": chunk.chunk_id,
                "source": chunk.source_path,
                "title": chunk.title,
                "score": round(score, 4),
                "content_preview": _preview(chunk.text),
                "content": chunk.text,
            }
            for score, chunk in selected
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
        self._attach_embeddings_if_requested()
        self._signatures = self._collect_signatures()
        self._write_persistent_index()
        return self.stats()

    def ensure_index(self) -> None:
        current = self._collect_signatures()
        if current != self._signatures:
            if self._load_persistent_index(current):
                return
            self.reindex()

    def stats(self) -> dict[str, Any]:
        sources = sorted({chunk.source_path for chunk in self._chunks})
        return {
            "source_count": len(sources),
            "chunk_count": len(self._chunks),
            "sources": sources,
            "engine": "local_ollama_embedding_hybrid" if self._embedding_active else "local_lexical_cosine",
            "embedding_model": self.embedding_model if self._embedding_active else None,
            "embedding_lexical_weight": self.embedding_lexical_weight if self._embedding_active else None,
            "embedding_fallback_reason": self._embedding_fallback_reason,
            "index_persistence": "disk_cache" if self.cache_path else "disabled",
            "cache_status": self._cache_status,
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
        signatures: dict[str, str] = {}
        for path in self._source_paths():
            try:
                signatures[self._relative(path)] = _file_sha256(path)
            except OSError:
                continue
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

    def _cache_config(self) -> dict[str, object]:
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "embedding_mode": self.embedding_mode,
            "embedding_model": self.embedding_model,
            "embedding_model_revision": self.embedding_model_revision,
            "embedding_lexical_weight": self.embedding_lexical_weight,
        }

    def _load_persistent_index(self, current_signatures: dict[str, str]) -> bool:
        if self.cache_path is None or not self.cache_path.is_file():
            self._cache_status = "missing"
            return False
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            checksum = payload.pop("index_sha256")
            if checksum != _stable_sha256(payload):
                raise ValueError("index checksum does not match")
            if payload.get("schema_version") != "rag_index_v1":
                raise ValueError("unsupported index schema")
            if payload.get("config") != self._cache_config():
                raise ValueError("index configuration does not match")
            if payload.get("source_fingerprints") != current_signatures:
                raise ValueError("source fingerprints do not match")
            restored = [_chunk_from_cache(item) for item in payload.get("chunks", [])]
            if not restored:
                raise ValueError("index has no chunks")
            embedding_active = bool(payload.get("embedding_active"))
            if embedding_active and any(chunk.embedding is None for chunk in restored):
                raise ValueError("embedding index is incomplete")
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            self._cache_status = "invalid"
            return False
        self._chunks = restored
        self._signatures = current_signatures
        self._embedding_active = embedding_active
        self._embedding_fallback_reason = payload.get("embedding_fallback_reason")
        self._cache_status = "restored"
        return True

    def _write_persistent_index(self) -> None:
        if self.cache_path is None:
            self._cache_status = "disabled"
            return
        try:
            payload: dict[str, object] = {
                "schema_version": "rag_index_v1",
                "config": self._cache_config(),
                "source_fingerprints": self._signatures,
                "embedding_active": self._embedding_active,
                "embedding_fallback_reason": self._embedding_fallback_reason,
                "chunks": [_chunk_to_cache(chunk) for chunk in self._chunks],
            }
            payload["index_sha256"] = _stable_sha256(payload)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.cache_path.with_suffix(f"{self.cache_path.suffix}.tmp")
            temporary_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            temporary_path.replace(self.cache_path)
            self._cache_status = "written"
        except OSError:
            self._cache_status = "unavailable"

    def _attach_embeddings_if_requested(self) -> None:
        self._embedding_active = False
        self._embedding_fallback_reason = None
        if self.embedding_mode != "local_embedding":
            return
        try:
            vectors = self._embed_many([chunk.text for chunk in self._chunks])
            if len(vectors) != len(self._chunks) or not vectors:
                raise RuntimeError("embedding response count does not match indexed chunks")
            self._chunks = [replace(chunk, embedding=vector) for chunk, vector in zip(self._chunks, vectors)]
            self._embedding_active = True
        except (OSError, RuntimeError, ValueError) as exc:
            self._embedding_fallback_reason = type(exc).__name__

    def _embed_text(self, text: str) -> tuple[float, ...] | None:
        try:
            return self._embed_many([text])[0]
        except (OSError, RuntimeError, ValueError) as exc:
            self._embedding_active = False
            self._embedding_fallback_reason = type(exc).__name__
            return None

    def _embed_many(self, inputs: list[str]) -> list[tuple[float, ...]]:
        parsed = urlsplit(self.embedding_base_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("RAG_EMBEDDING_BASE_URL must be an absolute URL")
        base_path = parsed.path.rstrip("/")
        if base_path.endswith("/v1"):
            base_path = base_path[:-3]
        endpoint = urlunsplit((parsed.scheme, parsed.netloc, f"{base_path}/api/embed", "", ""))
        payload = json.dumps({"model": self.embedding_model, "input": inputs}, ensure_ascii=False).encode("utf-8")
        request = Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.embedding_timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        raw_vectors = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(raw_vectors, list) or not raw_vectors:
            raise RuntimeError("embedding response is missing embeddings")
        vectors = [tuple(float(value) for value in vector) for vector in raw_vectors if isinstance(vector, list)]
        if len(vectors) != len(inputs) or any(not vector for vector in vectors):
            raise RuntimeError("embedding response contains invalid vectors")
        return vectors

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


def _lexical_score(left: Counter[str], left_norm: float, right: Counter[str], right_norm: float) -> float:
    cosine = _cosine(left, left_norm, right, right_norm)
    coverage = sum(1 for token in left if token in right) / len(left)
    return cosine + 0.35 * coverage


def _vector_cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _diverse_top_chunks(scored: list[tuple[float, RagChunk]], top_k: int) -> list[tuple[float, RagChunk]]:
    """Prefer distinct source files before returning multiple chunks from one file."""
    selected: list[tuple[float, RagChunk]] = []
    selected_ids: set[str] = set()
    seen_sources: set[str] = set()
    for score, chunk in scored:
        if chunk.source_path in seen_sources:
            continue
        selected.append((score, chunk))
        selected_ids.add(chunk.chunk_id)
        seen_sources.add(chunk.source_path)
        if len(selected) == top_k:
            return selected
    for score, chunk in scored:
        if chunk.chunk_id in selected_ids:
            continue
        selected.append((score, chunk))
        if len(selected) == top_k:
            break
    return selected


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_sha256(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        return 0.55
    return min(1.0, max(0.0, value))


def _chunk_to_cache(chunk: RagChunk) -> dict[str, object]:
    return {
        "chunk_id": chunk.chunk_id,
        "source_path": chunk.source_path,
        "title": chunk.title,
        "text": chunk.text,
        "embedding": list(chunk.embedding) if chunk.embedding is not None else None,
    }


def _chunk_from_cache(value: object) -> RagChunk:
    if not isinstance(value, dict):
        raise ValueError("cached chunk is not an object")
    required = ("chunk_id", "source_path", "title", "text")
    if any(not isinstance(value.get(key), str) or not value[key] for key in required):
        raise ValueError("cached chunk has invalid text fields")
    embedding_value = value.get("embedding")
    if embedding_value is not None and not isinstance(embedding_value, list):
        raise ValueError("cached chunk has invalid embedding")
    embedding = tuple(float(item) for item in embedding_value) if embedding_value is not None else None
    counts = Counter(_tokenize(value["text"]))
    norm = _counter_norm(counts)
    if not counts or norm == 0 or embedding == ():
        raise ValueError("cached chunk is empty")
    return RagChunk(
        chunk_id=value["chunk_id"],
        source_path=value["source_path"],
        title=value["title"],
        text=value["text"],
        token_counts=counts,
        norm=norm,
        embedding=embedding,
    )


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
