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

    assert result["index"]["engine"] == "local_ollama_embedding"
    assert result["matches"][0]["source"] == "docs/alpha.md"

    monkeypatch.setenv("RAG_RETRIEVAL_MODE", "local_embedding")
    fallback_store = RagDocumentStore(project_root=tmp_path)
    monkeypatch.setattr(fallback_store, "_embed_many", lambda _values: (_ for _ in ()).throw(RuntimeError("offline")))
    fallback = fallback_store.query("alpha", top_k=1)

    assert fallback["index"]["engine"] == "local_lexical_cosine"
    assert fallback["index"]["embedding_fallback_reason"] == "RuntimeError"
