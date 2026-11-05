"""Akses tabel `imdb_movies` di SQLite."""

import json
import sqlite3

from . import config

# Kolom yang dipakai aplikasi (sekaligus nama alias yang ramah dibaca).
FIELDS = (
    "id, Series_Title, Released_Year_numeric AS year, Genre AS genre, "
    "Director AS director, IMDB_Rating AS rating, Overview AS overview, "
    "Runtime_minutes AS runtime, Meta_score AS meta_score, Poster_Link, PC1, PC2"
)

# Kolom yang perlu dikirim ke LLM sebagai konteks (tanpa poster/PC agar hemat token).
LLM_FIELDS = ("id", "Series_Title", "year", "genre", "director", "rating", "overview")

PUSH_AWAY = 0.5  # seberapa kuat film yang tidak disukai mendorong titik selera


def query(sql: str, params=()) -> list[dict]:
    """Jalankan SQL (read-only) dan kembalikan list of dict."""
    with sqlite3.connect(config.DB_URI, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def by_ids(ids) -> list[dict]:
    """Ambil film berdasarkan id, urutannya mengikuti `ids`."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = {r["id"]: r for r in query(f"SELECT {FIELDS} FROM imdb_movies WHERE id IN ({placeholders})", tuple(ids))}
    return [rows[i] for i in ids if i in rows]


def random_movies(limit: int = 3, exclude=()) -> list[dict]:
    """Film acak (rekomendasi awal & card acak), boleh membuang film yang sudah dirating."""
    sql = f"SELECT {FIELDS} FROM imdb_movies"
    params = list(exclude)
    if params:
        sql += f" WHERE id NOT IN ({','.join('?' * len(params))})"
    sql += " ORDER BY RANDOM() LIMIT ?"
    return query(sql, params + [limit])


def _primary_mean(column: str) -> float:
    """Rata-rata sebuah kolom PC di seluruh katalog (dipakai kalau belum ada film disukai)."""
    return query(f"SELECT AVG({column}) AS mean FROM imdb_movies")[0]["mean"]


def rating_center(ratings: dict) -> tuple[float, float] | None:
    """Titik selera user di ruang PCA 2D (PC1, PC2).

    Perlakukan rating bagus dan jelek berbeda:

    - rating >= 6 (disukai)  : menarik titik selera, bobotnya nilai rating.
    - rating <= 5 (tidak suka): mendorong titik selera ke arah BERLAWANAN; makin
      rendah ratingnya makin kuat dorongannya (rating 5 = 20%, rating 1 = 100% dari
      PUSH_AWAY). Jadi film yang dibenci tidak menarik rekomendasi, tapi menolaknya.
    - belum ada film disukai : mulai dari pusat katalog, lalu didorong menjauh
      dari film yang tidak disukai.
    """
    if not ratings:
        return None
    placeholders = ",".join("?" * len(ratings))
    rows = query(f"SELECT id, PC1, PC2 FROM imdb_movies WHERE id IN ({placeholders})", tuple(ratings))
    rows = [r for r in rows if r["PC1"] is not None and r["PC2"] is not None]
    if not rows:
        return None

    liked = [(r, ratings[r["id"]]) for r in rows if ratings[r["id"]] >= 6]
    disliked = [(r, ratings[r["id"]]) for r in rows if ratings[r["id"]] <= 5]

    if liked:
        total = sum(weight for _, weight in liked)
        center = [sum(weight * r["PC1"] for r, weight in liked) / total,
                  sum(weight * r["PC2"] for r, weight in liked) / total]
    else:  # semua yang dirating tidak disukai
        center = [_primary_mean("PC1"), _primary_mean("PC2")]

    if disliked:
        total = sum(6 - weight for _, weight in disliked)
        away = [sum((6 - weight) * r["PC1"] for r, weight in disliked) / total,
                sum((6 - weight) * r["PC2"] for r, weight in disliked) / total]
        # makin rendah ratingnya makin kuat dorongannya: rating 5 = 20%, rating 1 = 100%
        push = PUSH_AWAY * total / (len(disliked) * 5)
        center = [center[0] - push * (away[0] - center[0]),
                  center[1] - push * (away[1] - center[1])]

    return center[0], center[1]


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


def band_movies(center: tuple[float, float], radius: float, limit: int = 3, exclude=(),
                low: float = 2.0, high: float = 5.0) -> list[dict]:
    """Film pada jarak low*radius s/d high*radius dari pusat selera (eksplorasi).

    Dipakai card acak: jauh dari jangkauan rekomendasi, tapi masih satu wilayah
    dengan selera user - bukan film dari ujung katalog yang tidak nyambung.
    """
    pc1, pc2 = center
    squared = "(PC1 - ?) * (PC1 - ?) + (PC2 - ?) * (PC2 - ?)"
    sql = (
        f"SELECT {FIELDS} FROM imdb_movies WHERE PC1 IS NOT NULL AND PC2 IS NOT NULL "
        f"AND {squared} BETWEEN ? AND ?"
    )
    params = [pc1, pc1, pc2, pc2, (low * radius) ** 2, (high * radius) ** 2]
    if exclude:
        exclude = list(exclude)
        sql += f" AND id NOT IN ({','.join('?' * len(exclude))})"
        params += exclude
    sql += " ORDER BY RANDOM() LIMIT ?"
    return query(sql, params + [limit])


def pca_points() -> list[dict]:
    """Semua titik (PC1, PC2) untuk visualisasi sebaran film."""
    return query(
        "SELECT id, Series_Title, IMDB_Rating AS rating, PC1, PC2 "
        "FROM imdb_movies WHERE PC1 IS NOT NULL"
    )


def to_json(records: list[dict]) -> str:
    """Ubah baris hasil query jadi JSON, dipakai sebagai output tool dan konteks agent."""
    return json.dumps(records, ensure_ascii=False, default=str)


def for_llm(movies: list[dict]) -> str:
    """JSON ringkas film untuk konteks LLM (Poster_Link dan PC tidak ikut)."""
    return json.dumps([{key: movie.get(key) for key in LLM_FIELDS} for movie in movies],
                      ensure_ascii=False, default=str)


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
