"""RAG: cari film yang maknanya mirip dengan pertanyaan user.

Alur `search`:  teks -> embedding -> Qdrant (id film) -> SQLite (data film) -> reranker
Setiap langkahnya dicatat di Langfuse (lihat tracing.py), dan biayanya masuk ke total sesi.
"""

import httpx

from . import age_rules, config, database, tracing

QDRANT_CANDIDATES = 30  # film yang diambil dari Qdrant (lebih banyak dari RERANK_CANDIDATES, cadangan untuk filter umur)
RERANK_CANDIDATES = 15  # maksimal dokumen yang dikirim ke reranker (biaya reranker mengikuti jumlah ini)


def embed(text: str) -> list[float]:
    """Ubah teks jadi vektor (1536 angka) lewat OpenRouter."""
    with tracing.observe("embedding", "embedding", model=config.EMBEDDING_MODEL, input=text) as observation:
        response = config.embeddings().embeddings.create(model=config.EMBEDDING_MODEL, input=text)
        tokens = response.usage.total_tokens
        cost = getattr(response.usage, "cost", 0) or 0
        observation.update(usage_details={"input": tokens}, cost_details={"total": cost} if cost else None)
        tracing.add_cost("embedding", cost, tokens)
        return response.data[0].embedding


def search_ids(query: str, limit: int = 15) -> list[int]:
    """Cari di Qdrant. Payload hanya berisi `sqlite_id`; data lengkap diambil dari SQLite."""
    vector = embed(query)
    with tracing.observe("qdrant-search", "retriever", input={"query": query, "limit": limit},
                         metadata={"collection": config.QDRANT_COLLECTION}) as observation:
        hits = config.qdrant().query_points(
            collection_name=config.QDRANT_COLLECTION,
            query=vector,
            limit=limit,
            with_payload=True,
        ).points
        ids = [hit.payload["sqlite_id"] for hit in hits]
        observation.update(output={"ids": ids, "scores": [round(hit.score, 4) for hit in hits]})
        return ids


def rerank(query: str, documents: list[str], top_n: int) -> tuple[list[int], str]:
    """Urutkan dokumen dengan model reranker. Mengembalikan (indeks terpilih, sumber urutan).

    Kalau reranker gagal (rate limit / diblokir provider), pakai urutan dari Qdrant.
    """
    with tracing.observe("rerank", "span", input={"query": query, "documents": len(documents), "top_n": top_n},
                         metadata={"model": config.RERANK_MODEL}) as observation:
        try:
            response = httpx.post(
                f"{config.OPENROUTER_BASE_URL}/rerank",
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                json={"model": config.RERANK_MODEL, "query": query, "documents": documents, "top_n": top_n},
                timeout=60,
            )
            response.raise_for_status()
            body = response.json()
            order = [item["index"] for item in body["results"]]
            usage = body.get("usage") or {}
            tracing.add_cost("rerank", usage.get("cost", 0), usage.get("total_tokens", 0))
            observation.update(output={"order": order, "source": "reranker"}, metadata={"usage": usage})
            return order, "reranker"
        except Exception as error:
            order = list(range(min(top_n, len(documents))))
            observation.update(output={"order": order, "source": "urutan-vektor"}, level="WARNING",
                               status_message=f"reranker gagal: {type(error).__name__}")
            return order, "urutan-vektor"


def search(query: str, top_n: int = 5, age: int | None = None) -> tuple[list[dict], str]:
    """Film paling relevan untuk `query` yang boleh untuk umur `age`. Mengembalikan (film, sumber urutan).

    Qdrant mengembalikan 30 kandidat, disaring umur, lalu maksimal 15 teratas (urutan kemiripan Qdrant)
    dikirim ke reranker yang memilih `top_n`. Qdrant diminta 30 supaya setelah disaring umur
    masih cukup untuk mengisi 15.
    """
    movies = [m for m in database.by_ids(search_ids(query, QDRANT_CANDIDATES))
              if age_rules.allowed(m, age)][:RERANK_CANDIDATES]
    documents = [
        f"{m['Series_Title']} ({int(m['year']) if m['year'] else '?'}) - {m['genre']}: {m['overview']}"
        for m in movies
    ]
    order, source = rerank(query, documents, top_n)
    return [movies[i] for i in order], source
