"""Akses tabel `imdb_movies` di SQLite + pemformatan film untuk LLM dan UI.

Dibaca dari bawah ke atas: `query` (dasar) -> `by_ids` / `random_movies`
-> fungsi format (`to_json`, `for_llm`, `imdb_url`).
"""

import json
import sqlite3
from urllib.parse import quote_plus

from . import age_rules, config

# Kolom yang dipakai aplikasi, dengan alias yang ramah dibaca.
FIELDS = (
    "id, Series_Title, Certificate AS certificate, Released_Year_numeric AS year, Genre AS genre, "
    "Director AS director, IMDB_Rating AS rating, Overview AS overview, "
    "Runtime_minutes AS runtime, Meta_score AS meta_score, Poster_Link, PC1, PC2"
)

# Kolom yang dikirim ke LLM (tanpa poster/PC, supaya hemat token).
LLM_FIELDS = ("id", "Series_Title", "year", "genre", "director", "rating", "overview")
OVERVIEW_CHARS = 200  # overview dipotong supaya konteks tidak boros token


# --- Query dasar -------------------------------------------------------------

def query(sql: str, params=()) -> list[dict]:
    """Jalankan SQL (database dibuka read-only) dan kembalikan list of dict."""
    with sqlite3.connect(config.DB_URI, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def by_ids(ids) -> list[dict]:
    """Ambil film berdasarkan id, urutannya mengikuti `ids`."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = query(f"SELECT {FIELDS} FROM imdb_movies WHERE id IN ({placeholders})", tuple(ids))
    by_id = {row["id"]: row for row in rows}
    return [by_id[i] for i in ids if i in by_id]


def random_movies(limit: int = 3, exclude=(), age: int | None = None) -> list[dict]:
    """Film acak yang boleh untuk `age` (rekomendasi awal & card acak); `exclude` = id yang dilewati."""
    conditions = [age_rules.sql_condition(age)]
    params = list(exclude)
    if params:
        conditions.append(f"id NOT IN ({','.join('?' * len(params))})")
    sql = f"SELECT {FIELDS} FROM imdb_movies WHERE {' AND '.join(conditions)} ORDER BY RANDOM() LIMIT ?"
    return query(sql, params + [limit])


def visible_count(age: int | None) -> int:
    """Jumlah film yang boleh dilihat user berumur `age`."""
    sql = f"SELECT COUNT(*) AS n FROM imdb_movies WHERE {age_rules.sql_condition(age)}"
    return query(sql)[0]["n"]


def run_select(sql: str, age: int | None = None) -> list[dict]:
    """Jalankan SELECT buatan LLM. Dengan `age`, tabel `imdb_movies` yang terlihat oleh SQL
    hanyalah film yang boleh untuk umur itu (lewat view sementara bernama sama; SQLite
    mencari objek TEMP lebih dulu daripada tabel asli)."""
    with sqlite3.connect(config.DB_URI, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        if age is not None:
            conn.execute("CREATE TEMP VIEW imdb_movies AS SELECT * FROM main.imdb_movies "
                         f"WHERE {age_rules.sql_condition(age)}")
        return [dict(row) for row in conn.execute(sql)]


def schema_text() -> str:
    """Deskripsi tabel untuk prompt yang menyusun SQL."""
    return (
        "Tabel `imdb_movies` (1 baris = 1 film):\n"
        "id INTEGER, Series_Title TEXT, Certificate TEXT, Genre TEXT, "
        "IMDB_Rating REAL, Overview TEXT, Meta_score REAL, Director TEXT, "
        "Star1 TEXT, Star2 TEXT, Star3 TEXT, Star4 TEXT, No_of_Votes INTEGER, "
        "Released_Year_numeric REAL, Runtime_minutes REAL, Gross_cleaned REAL, "
        "PC1 REAL, PC2 REAL"
    )


# --- Format keluaran ---------------------------------------------------------

def imdb_url(movie: dict) -> str:
    """Link pencarian IMDb (judul + tahun). Dipakai UI dan konteks LLM."""
    year = int(movie["year"]) if movie.get("year") else ""
    return f"https://www.imdb.com/find/?q={quote_plus(str(movie['Series_Title']).title())}+{year}"


def to_json(records) -> str:
    """Ubah hasil query jadi JSON (keluaran tool)."""
    return json.dumps(records, ensure_ascii=False, default=str)


def for_llm(movies: list[dict]) -> str:
    """JSON ringkas film untuk konteks LLM: kolom terpilih + link, overview dipotong."""
    compact = []
    for movie in movies:
        item = {key: movie.get(key) for key in LLM_FIELDS}
        item["link"] = imdb_url(movie)
        item["overview"] = str(movie.get("overview") or "")[:OVERVIEW_CHARS]
        compact.append(item)
    return json.dumps(compact, ensure_ascii=False, default=str)
