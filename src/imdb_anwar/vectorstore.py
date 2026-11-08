"""RAG: cari film yang maknanya mirip dengan pertanyaan user.

Alur `search`:  teks -> embedding -> Qdrant (id film) -> SQLite (data film) -> reranker
"""

import httpx

from . import age_rules, config, database


def embed(text: str) -> list[float]:
    """Ubah teks jadi vektor (1536 angka) lewat OpenRouter."""
    response = config.embeddings().embeddings.create(model=config.EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def search_ids(query: str, limit: int = 15) -> list[int]:
    """Cari di Qdrant. Payload hanya berisi `sqlite_id`; data lengkap diambil dari SQLite."""
    hits = config.qdrant().query_points(
        collection_name=config.QDRANT_COLLECTION,
        query=embed(query),
        limit=limit,
        with_payload=True,
    ).points
    return [hit.payload["sqlite_id"] for hit in hits]


def rerank(query: str, documents: list[str], top_n: int) -> tuple[list[int], str]:
    """Urutkan dokumen dengan model reranker. Mengembalikan (indeks terpilih, sumber urutan).

    Kalau reranker gagal (rate limit / diblokir provider), pakai urutan dari Qdrant.
    """
    try:
        response = httpx.post(
            f"{config.OPENROUTER_BASE_URL}/rerank",
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
            json={"model": config.RERANK_MODEL, "query": query, "documents": documents, "top_n": top_n},
            timeout=60,
        )
        response.raise_for_status()
        return [item["index"] for item in response.json()["results"]], "reranker"
    except Exception:
        return list(range(min(top_n, len(documents)))), "urutan-vektor"


def search(query: str, top_n: int = 5, candidates: int = 30, age: int | None = None) -> tuple[list[dict], str]:
    """Film paling relevan untuk `query` yang boleh untuk umur `age`. Mengembalikan (film, sumber urutan).

    Kandidat disaring umur SEBELUM reranker, dan jumlahnya diperbanyak (30) supaya
    setelah disaring masih cukup untuk `top_n`.
    """
    movies = [m for m in database.by_ids(search_ids(query, candidates)) if age_rules.allowed(m, age)]
    documents = [
        f"{m['Series_Title']} ({int(m['year']) if m['year'] else '?'}) - {m['genre']}: {m['overview']}"
        for m in movies
    ]
    order, source = rerank(query, documents, top_n)
    return [movies[i] for i in order], source
