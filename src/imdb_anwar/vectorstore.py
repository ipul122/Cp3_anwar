"""RAG: embedding query, pencarian di Qdrant, lalu reranking."""

import json

import httpx

from . import config, data

# Sumber urutan yang terakhir dipakai: "reranker" atau "llm-fallback".
last_rerank = ""


def embed(text: str) -> list[float]:
    """Ubah teks jadi vektor (1536 dimensi) lewat OpenRouter."""
    response = config.embeddings().embeddings.create(model=config.EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def search_ids(query: str, limit: int = 15) -> list[int]:
    """Cari di Qdrant. Payload hanya berisi `sqlite_id`, data lengkapnya di SQLite."""
    hits = config.qdrant().query_points(
        collection_name=config.QDRANT_COLLECTION,
        query=embed(query),
        limit=limit,
        with_payload=True,
    ).points
    return [hit.payload["sqlite_id"] for hit in hits]


def _rerank_api(query: str, documents: list[str], top_n: int) -> list[int] | None:
    """Panggil model reranker di OpenRouter. None kalau tidak tersedia."""
    try:
        response = httpx.post(
            f"{config.OPENROUTER_BASE_URL}/rerank",
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
            json={
                "model": config.RERANK_MODEL,
                "query": query,
                "documents": documents,
                "top_n": top_n,
            },
            timeout=60,
        )
        response.raise_for_status()
        return [item["index"] for item in response.json()["results"]]
    except Exception:
        return None


def _rerank_llm(query: str, documents: list[str], top_n: int) -> list[int]:
    """Cadangan: minta LLM mengurutkan dokumen dan mengembalikan indeks paling relevan."""
    prompt = (
        f"Nilai relevansi setiap dokumen terhadap query: {query}\n\n"
        + "\n".join(f"{i}. {doc[:150]}" for i, doc in enumerate(documents))
        + f'\n\nBalas HANYA JSON: {{"urut": [indeks paling relevan, maksimal {top_n}]}}'
    )
    try:
        reply = config.llm().invoke(prompt).content
        order = json.loads(reply[reply.find("{") : reply.rfind("}") + 1])["urut"]
        order = [int(i) for i in order if 0 <= int(i) < len(documents)]
        return order[:top_n] or list(range(min(top_n, len(documents))))
    except Exception:
        return list(range(min(top_n, len(documents))))


def rerank(query: str, documents: list[str], top_n: int = 5) -> list[int]:
    """Urutkan dokumen dengan model reranker; kalau diblokir, pakai LLM sebagai cadangan."""
    global last_rerank
    if len(documents) <= top_n:
        last_rerank = "urutan-vektor"
        return list(range(len(documents)))
    order = _rerank_api(query, documents, top_n)
    last_rerank = "reranker" if order else "llm-fallback"
    return order or _rerank_llm(query, documents, top_n)


def search(query: str, top_n: int = 5, candidates: int = 15) -> list[dict]:
    """Ambil film paling relevan: Qdrant -> SQLite -> reranker."""
    movies = data.by_ids(search_ids(query, candidates))
    documents = [
        f"{m['Series_Title']} ({int(m['year']) if m['year'] else '?'}) - {m['genre']}: {m['overview']}"
        for m in movies
    ]
    return [movies[i] for i in rerank(query, documents, top_n)]

