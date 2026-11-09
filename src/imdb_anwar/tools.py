"""Tiga tool yang dipakai agent. Semuanya mengembalikan JSON (string).

| Tool                  | Dipakai agent | Sumber data                     |
|-----------------------|---------------|---------------------------------|
| search_movies         | retrieve      | Qdrant -> SQLite -> reranker    |
| find_movies_by_title  | lookup        | SQLite (cocok judul)            |
| movie_stats           | analytics     | LLM menulis SQL -> SQLite       |
"""

import json
import re

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from . import config, database, prompts, titles, tracing, vectorstore

SQL_MAX_ROWS = 50  # batas baris hasil SQL
FORBIDDEN_SQL = ("insert", "update", "delete", "drop", "alter", "create", "attach", "pragma", "replace")
# `main.imdb_movies` / "main"."imdb_movies" = jalan pintas melewati filter umur (lihat database.run_select).
BYPASS_SCHEMA = re.compile(r"\b(main|temp)\W*\.")


def _is_safe_select(sql: str) -> bool:
    """Lapis pengaman kedua (lapis pertama: database dibuka read-only): hanya SELECT,
    dan tidak boleh menyebut schema `main`/`temp` secara langsung."""
    lowered = sql.lower().strip()
    return (lowered.startswith("select")
            and not any(word in lowered for word in FORBIDDEN_SQL)
            and not BYPASS_SCHEMA.search(lowered))


# Parameter `age` diisi oleh workflow (dari input umur di UI), bukan oleh LLM.

@tool
def search_movies(query: str, age: int | None = None) -> str:
    """Cari film yang paling relevan dengan deskripsi atau preferensi user.

    Memakai pencarian semantik di vector database lalu diurutkan ulang dengan
    reranker. Isi `query` dengan deskripsi, misal "film perang yang menyedihkan".
    Hanya film yang boleh untuk umur `age` yang dikembalikan.

    Hasil: JSON `{"movies": [...], "ranked_by": "reranker" | "urutan-vektor"}`.
    """
    with tracing.observe("search_movies", "tool", input={"query": query, "age": age}) as observation:
        movies, ranked_by = vectorstore.search(query, top_n=5, age=age)
        observation.update(output={"films": [m["Series_Title"] for m in movies], "ranked_by": ranked_by})
        return json.dumps({"movies": movies, "ranked_by": ranked_by}, ensure_ascii=False, default=str)


@tool
def find_movies_by_title(titles_text: str, age: int | None = None) -> str:
    """Ambil detail film dari daftar JUDUL (bukan deskripsi).

    Pakai tool ini kalau user minta menampilkan/membuka film yang sudah disebut
    sebelumnya, atau menyebut judul film secara langsung. Isi `titles_text` dengan
    satu judul per baris. Salah ketik kecil ditoleransi ("Discable Me" -> "Despicable Me").

    Hasil: JSON `{"found": [film...], "restricted": [{"title", "min_age"}], "not_found": [judul]}`.
    `restricted` = film ADA tapi dibatasi usia untuk `age`; "film X tidak ada" hanya boleh
    disimpulkan dari `not_found`.
    """
    names = [t.strip() for t in titles_text.replace(";", "\n").split("\n") if t.strip()]
    with tracing.observe("find_movies_by_title", "tool", input={"titles": names, "age": age}) as observation:
        found, restricted, not_found = titles.match_titles(names, age)
        observation.update(output={"found": [m["Series_Title"] for m in found],
                                   "restricted": restricted, "not_found": not_found})
        return json.dumps({"found": found, "restricted": restricted, "not_found": not_found},
                          ensure_ascii=False, default=str)


@tool
def movie_stats(question: str, age: int | None = None) -> str:
    """Jawab pertanyaan angka atau statistik tentang koleksi film lewat SQL ke SQLite.

    Contoh: "rata-rata rating film genre drama", "5 sutradara dengan film terbanyak",
    "film tahun 1990-an dengan pendapatan tertinggi". Hitungannya hanya atas film
    yang boleh untuk umur `age`.

    Hasil: JSON `{"sql": ..., "rows": [...]}`, atau pesan teks kalau SQL tidak aman / kosong.
    """
    with tracing.observe("movie_stats", "tool", input={"question": question, "age": age}) as observation:
        # LLM penulis SQL ikut dihitung token dan biayanya di trace sesi (generation "sql").
        sql_prompt, prompt = prompts.load(config.PROMPT_SQL, question=question, schema=database.schema_text())
        reply = tracing.call_llm(tracing.current_trace() or tracing.new_trace(), "sql",
                                 [HumanMessage(sql_prompt)], prompt=prompt)
        sql = re.sub(r"^```(?:sql)?|```$", "", reply.content.strip(), flags=re.IGNORECASE).strip()  # buang pagar ```sql
        if not _is_safe_select(sql):
            observation.update(output="ditolak: SQL tidak aman", level="WARNING")
            return "Pertanyaan ini tidak bisa dijawab dengan query yang aman ke database."
        with tracing.observe("sqlite-query", "span", input={"sql": sql, "age": age}) as query_span:
            rows = database.run_select(sql, age)
            query_span.update(output={"rows": len(rows)})
        observation.update(output={"sql": sql, "rows": len(rows)})
        if not rows:
            return f"Query tidak mengembalikan baris. SQL: {sql}"
        return json.dumps({"sql": sql, "rows": rows[:SQL_MAX_ROWS]}, ensure_ascii=False, default=str)
