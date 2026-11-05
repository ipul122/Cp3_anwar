"""Akses tabel `imdb_movies` di SQLite."""

import json
import sqlite3

from . import config

# Kolom yang dipakai aplikasi (sekaligus nama alias yang ramah dibaca).
FIELDS = (
    "id, Series_Title, Released_Year_numeric AS year, Genre AS genre, "
    "Director AS director, IMDB_Rating AS rating, Overview AS overview, "
    "Runtime_minutes AS runtime, Meta_score AS meta_score, PC1, PC2"
)


def query(sql: str, params=()) -> list[dict]:
    """Jalankan SQL dan kembalikan list of dict."""
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def by_ids(ids) -> list[dict]:
    """Ambil film berdasarkan id, urutannya mengikuti `ids`."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = {r["id"]: r for r in query(f"SELECT {FIELDS} FROM imdb_movies WHERE id IN ({placeholders})", tuple(ids))}
    return [rows[i] for i in ids if i in rows]


def random_movies(limit: int = 3) -> list[dict]:
    """Film acak, dipakai sebagai rekomendasi awal sebelum user memberi rating."""
    return query(f"SELECT {FIELDS} FROM imdb_movies ORDER BY RANDOM() LIMIT ?", (limit,))


def rating_center(ratings: dict) -> tuple[float, float] | None:
    """Titik tengah (PC1, PC2) dari film yang diberi rating, dibobot nilai ratingnya.

    Film dengan rating 10 menarik titik lebih kuat daripada rating 3.
    """
    if not ratings:
        return None
    placeholders = ",".join("?" * len(ratings))
    rows = query(f"SELECT id, PC1, PC2 FROM imdb_movies WHERE id IN ({placeholders})", tuple(ratings))
    rows = [r for r in rows if r["PC1"] is not None and r["PC2"] is not None]
    if not rows:
        return None
    total = sum(ratings[r["id"]] for r in rows)
    pc1 = sum(ratings[r["id"]] * r["PC1"] for r in rows) / total
    pc2 = sum(ratings[r["id"]] * r["PC2"] for r in rows) / total
    return pc1, pc2


def pca_neighbors(center: tuple[float, float], k: int = 3, exclude=()) -> list[dict]:
    """`k` film terdekat dari `center` di ruang PCA 2D (jarak euclidean)."""
    pc1, pc2 = center
    sql = (
        f"SELECT {FIELDS} FROM imdb_movies WHERE PC1 IS NOT NULL AND PC2 IS NOT NULL "
        "ORDER BY (PC1 - ?) * (PC1 - ?) + (PC2 - ?) * (PC2 - ?) ASC LIMIT ?"
    )
    # Ambil lebih banyak dari yang diminta supaya film yang sudah dirating bisa dibuang.
    rows = query(sql, (pc1, pc1, pc2, pc2, k + len(exclude)))
    skip = set(exclude)
    return [r for r in rows if r["id"] not in skip][:k]


def to_json(records: list[dict]) -> str:
    """Ubah baris hasil query jadi JSON, dipakai sebagai output tool dan konteks agent."""
    return json.dumps(records, ensure_ascii=False, default=str)


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
