"""Tool yang dieksekusi oleh agent."""

import json
import re
import sqlite3

from langchain_core.tools import tool

from . import config, data, prompts, vectorstore


def _is_safe_select(sql: str) -> bool:
    """Cek sederhana sebelum SQL dari LLM dijalankan."""
    lowered = sql.lower().strip()
    forbidden = ("insert", "update", "delete", "drop", "alter", "create", "attach", "pragma", "replace")
    return lowered.startswith("select") and not any(word in lowered for word in forbidden)


@tool
def search_movies(query: str) -> str:
    """Cari film yang paling relevan dengan deskripsi atau preferensi user.

    Memakai pencarian semantik di vector database lalu diurutkan ulang dengan
    reranker. Isi `query` dengan deskripsi, misal "film perang yang menyedihkan".
    """
    return data.to_json(vectorstore.search(query, top_n=5))


@tool
def movie_stats(question: str) -> str:
    """Jawab pertanyaan angka atau statistik tentang koleksi film lewat SQL ke SQLite.

    Contoh: "rata-rata rating film genre drama", "5 sutradara dengan film terbanyak",
    "film tahun 1990-an dengan pendapatan tertinggi".
    """
    sql_prompt = prompts.get(config.PROMPT_SQL, question=question, schema=data.schema_text())
    raw = config.llm().invoke(sql_prompt).content.strip()
    sql = re.sub(r"^```(?:sql)?|```$", "", raw, flags=re.IGNORECASE).strip()
    if not _is_safe_select(sql):
        return "Pertanyaan ini tidak bisa dijawab dengan query yang aman ke database."
    with sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(sql)]
    if not rows:
        return f"Query tidak mengembalikan baris. SQL: {sql}"
    return json.dumps({"sql": sql, "rows": rows[:50]}, ensure_ascii=False, default=str)
