from pathlib import Path

from app.rag.document_store import RagDocumentStore


def test_local_embedding_mode_ranks_vectors_and_falls_back_to_lexical(monkeypatch, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text("alpha comfort reference", encoding="utf-8")
    (docs / "beta.md").write_text("beta device reference", encoding="utf-8")
    monkeypatch.setenv("RAG_RETRIEVAL_MODE", "local_embedding")
    store = RagDocumentStore(project_root=tmp_path)

    def embeddings(values: list[str]) -> list[tuple[float, ...]]:
        return [(1.0, 0.0) if "alpha" in value else (0.0, 1.0) for value in values]

    monkeypatch.setattr(store, "_embed_many", embeddings)
    result = store.query("alpha", top_k=1)

    assert result["index"]["engine"] == "local_ollama_embedding_hybrid"
    assert result["matches"][0]["source"] == "docs/alpha.md"

    monkeypatch.setenv("RAG_RETRIEVAL_MODE", "local_embedding")
    fallback_store = RagDocumentStore(project_root=tmp_path)
    monkeypatch.setattr(fallback_store, "_embed_many", lambda _values: (_ for _ in ()).throw(RuntimeError("offline")))
    fallback = fallback_store.query("alpha", top_k=1)

    assert fallback["index"]["engine"] == "local_lexical_cosine"
    assert fallback["index"]["embedding_fallback_reason"] == "RuntimeError"


def test_embedding_index_is_restored_from_a_checksum_validated_disk_cache(monkeypatch, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text("alpha comfort reference", encoding="utf-8")
    (docs / "beta.md").write_text("beta device reference", encoding="utf-8")
    monkeypatch.setenv("RAG_RETRIEVAL_MODE", "local_embedding")
    monkeypatch.setenv("RAG_INDEX_CACHE_PATH", ".runtime/test-rag-index.json")
    first_store = RagDocumentStore(project_root=tmp_path)
    first_calls: list[list[str]] = []

    def first_embeddings(values: list[str]) -> list[tuple[float, ...]]:
        first_calls.append(values)
        return [(1.0, 0.0) if "alpha" in value else (0.0, 1.0) for value in values]

    monkeypatch.setattr(first_store, "_embed_many", first_embeddings)
    first_store.ensure_index()
    assert len(first_calls) == 1
    assert first_store.stats()["cache_status"] == "written"

    restored_store = RagDocumentStore(project_root=tmp_path)
    restored_calls: list[list[str]] = []
    monkeypatch.setattr(restored_store, "_embed_many", lambda values: restored_calls.append(values) or [(1.0, 0.0)])
    restored_store.ensure_index()

    assert restored_store.stats()["cache_status"] == "restored"
    assert restored_store.stats()["engine"] == "local_ollama_embedding_hybrid"
    assert restored_calls == []


def test_corrupt_embedding_cache_rebuilds_instead_of_trusting_tampered_chunks(monkeypatch, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text("alpha comfort reference", encoding="utf-8")
    monkeypatch.setenv("RAG_RETRIEVAL_MODE", "lexical")
    monkeypatch.setenv("RAG_INDEX_CACHE_PATH", ".runtime/test-rag-index.json")
    first_store = RagDocumentStore(project_root=tmp_path)
    first_store.ensure_index()
    cache_path = tmp_path / ".runtime" / "test-rag-index.json"
    cache_path.write_text('{"schema_version":"rag_index_v1","index_sha256":"tampered"}', encoding="utf-8")

    restored_store = RagDocumentStore(project_root=tmp_path)
    restored_store.ensure_index()

    assert restored_store.stats()["cache_status"] == "written"
    assert restored_store.query("alpha", top_k=1)["matches"][0]["source"] == "docs/alpha.md"


def test_query_prefers_distinct_sources_before_repeating_chunks(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text("alpha alpha alpha\n\nalpha alpha alpha", encoding="utf-8")
    (docs / "beta.md").write_text("alpha reference", encoding="utf-8")
    store = RagDocumentStore(project_root=tmp_path, chunk_size=16, chunk_overlap=0)

    sources = [match["source"] for match in store.query("alpha", top_k=2)["matches"]]

    assert sources == ["docs/alpha.md", "docs/beta.md"]
