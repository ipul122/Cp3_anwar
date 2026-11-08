"""Tiga tool yang dipakai agent. Semuanya mengembalikan JSON (string).

| Tool                  | Dipakai agent | Sumber data                     |
|-----------------------|---------------|---------------------------------|
| search_movies         | retrieve      | Qdrant -> SQLite -> reranker    |
| find_movies_by_title  | lookup        | SQLite (cocok judul)            |
| movie_stats           | analytics     | LLM menulis SQL -> SQLite       |
"""

import json
import re
import sqlite3

from langchain_core.tools import tool

from . import config, database, prompts, titles, vectorstore

SQL_MAX_ROWS = 50  # batas baris hasil SQL
FORBIDDEN_SQL = ("insert", "update", "delete", "drop", "alter", "create", "attach", "pragma", "replace")


def _is_safe_select(sql: str) -> bool:
    """Lapis pengaman kedua (lapis pertama: database dibuka read-only): hanya SELECT."""
    lowered = sql.lower().strip()
    return lowered.startswith("select") and not any(word in lowered for word in FORBIDDEN_SQL)


@tool
def search_movies(query: str) -> str:
    """Cari film yang paling relevan dengan deskripsi atau preferensi user.

    Memakai pencarian semantik di vector database lalu diurutkan ulang dengan
    reranker. Isi `query` dengan deskripsi, misal "film perang yang menyedihkan".

    Hasil: JSON `{"movies": [...], "ranked_by": "reranker" | "urutan-vektor"}`.
    """
    movies, ranked_by = vectorstore.search(query, top_n=5)
    return json.dumps({"movies": movies, "ranked_by": ranked_by}, ensure_ascii=False, default=str)


@tool
def find_movies_by_title(titles_text: str) -> str:
    """Ambil detail film dari daftar JUDUL (bukan deskripsi).

    Pakai tool ini kalau user minta menampilkan/membuka film yang sudah disebut
    sebelumnya, atau menyebut judul film secara langsung. Isi `titles_text` dengan
    satu judul per baris. Salah ketik kecil ditoleransi ("Discable Me" -> "Despicable Me").

    Hasil: JSON `{"found": [film...], "not_found": [judul yang tidak ada di database]}`,
    jadi "film X tidak ada" hanya boleh disimpulkan dari `not_found`.
    """
    names = [t.strip() for t in titles_text.replace(";", "\n").split("\n") if t.strip()]
    found, not_found = titles.match_titles(names)
    return json.dumps({"found": found, "not_found": not_found}, ensure_ascii=False, default=str)


@tool
def movie_stats(question: str) -> str:
    """Jawab pertanyaan angka atau statistik tentang koleksi film lewat SQL ke SQLite.

    Contoh: "rata-rata rating film genre drama", "5 sutradara dengan film terbanyak",
    "film tahun 1990-an dengan pendapatan tertinggi".

    Hasil: JSON `{"sql": ..., "rows": [...]}`, atau pesan teks kalau SQL tidak aman / kosong.
    """
    sql_prompt = prompts.get(config.PROMPT_SQL, question=question, schema=database.schema_text())
    raw = config.llm().invoke(sql_prompt).content.strip()
    sql = re.sub(r"^```(?:sql)?|```$", "", raw, flags=re.IGNORECASE).strip()  # buang pagar ```sql
    if not _is_safe_select(sql):
        return "Pertanyaan ini tidak bisa dijawab dengan query yang aman ke database."
    with sqlite3.connect(config.DB_URI, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(sql)]
    if not rows:
        return f"Query tidak mengembalikan baris. SQL: {sql}"
    return json.dumps({"sql": sql, "rows": rows[:SQL_MAX_ROWS]}, ensure_ascii=False, default=str)
