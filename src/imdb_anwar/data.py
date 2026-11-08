"""Akses tabel `imdb_movies` di SQLite."""

import difflib
import json
import re
import sqlite3
import unicodedata
from functools import lru_cache
from urllib.parse import quote_plus

from . import config

# Kolom yang dipakai aplikasi (sekaligus nama alias yang ramah dibaca).
FIELDS = (
    "id, Series_Title, Released_Year_numeric AS year, Genre AS genre, "
    "Director AS director, IMDB_Rating AS rating, Overview AS overview, "
    "Runtime_minutes AS runtime, Meta_score AS meta_score, Poster_Link, PC1, PC2"
)

# Kolom yang perlu dikirim ke LLM sebagai konteks (tanpa poster/PC agar hemat token).
LLM_FIELDS = ("id", "Series_Title", "year", "genre", "director", "rating", "overview")

OVERVIEW_CHARS = 200  # overview dipotong supaya konteks tidak boros token

PUSH_AWAY = 0.5  # seberapa kuat film yang tidak disukai mendorong titik selera
RECENT_RATINGS = 7  # hanya rating terbaru ini yang dipakai menghitung titik selera


def query(sql: str, params=()) -> list[dict]:
    """Jalankan SQL (read-only) dan kembalikan list of dict."""
    with sqlite3.connect(config.DB_URI, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def imdb_url(movie: dict) -> str:
    """Link halaman film di IMDb (pencarian judul + tahun). Dipakai UI dan konteks LLM."""
    year = int(movie["year"]) if movie.get("year") else ""
    return f"https://www.imdb.com/find/?q={quote_plus(str(movie['Series_Title']).title())}+{year}"


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

    Hanya RECENT_RATINGS (7) rating TERBARU yang dipakai, jadi selera yang lama
    otomatis tergantikan begitu user memberi rating baru (urutan dict = urutan
    pemberian rating, yang dirating ulang pindah ke paling belakang).

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
    ratings = dict(list(ratings.items())[-RECENT_RATINGS:])
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


def pca_points() -> list[dict]:
    """Semua titik (PC1, PC2) untuk visualisasi sebaran film."""
    return query(
        "SELECT id, Series_Title, IMDB_Rating AS rating, PC1, PC2 "
        "FROM imdb_movies WHERE PC1 IS NOT NULL"
    )


def to_json(records: list[dict]) -> str:
    """Ubah baris hasil query jadi JSON, dipakai sebagai output tool dan konteks agent."""
    return json.dumps(records, ensure_ascii=False, default=str)


def _normalize(text: str) -> str:
    """Huruf kecil, aksen dibuang, semua tanda baca jadi spasi."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _clean_title(text: str) -> str:
    """Buang tahun dari judul: "Tumbbad (2018)" -> "Tumbbad"."""
    text = re.sub(r"\(\s*(19|20)\d{2}\s*\)", " ", str(text))
    text = re.sub(r"\b(19|20)\d{2}\b", " ", text)
    return text.strip(" \t\"'.,;:-–—()[]")


@lru_cache(maxsize=1)
def _title_index() -> list[tuple[int, str, str]]:
    """(id, judul ternormalisasi, judul tanpa spasi) untuk semua film. Di-cache per proses."""
    index = []
    for row in query("SELECT id, Series_Title FROM imdb_movies"):
        norm = _normalize(row["Series_Title"])
        index.append((row["id"], norm, norm.replace(" ", "")))
    return index


FUZZY_CUTOFF = 0.8  # kemiripan minimal (0-1) untuk judul yang salah ketik
FUZZY_MIN_CHARS = 5  # judul lebih pendek dari ini tidak di-fuzzy, terlalu mudah salah cocok


def match_titles(titles: list[str]) -> tuple[list[dict], list[str]]:
    """Cari film dari daftar judul. Mengembalikan (film ditemukan, judul yang TIDAK ketemu).

    Tahan beda tanda baca, aksen, spasi, dan salah ketik:

    - Tahun di judul dibuang: "Tumbbad (2018)" -> "Tumbbad".
    - "Spiderman" tetap ketemu "spider-man: into the spider-verse" (tanda baca diabaikan).
    - "Tokyo" tetap ketemu "tôkyô goddofâzâzu" (aksen diabaikan).
    - Kecocokan persis diutamakan; potongan judul hanya untuk kata >= 4 huruf, supaya
      judul pendek seperti "up"/"saw" tidak menarik film lain yang kebetulan mirip.
    - Kalau semua cara di atas gagal, dicoba kemiripan teks (salah ketik):
      "Discable Me" -> "Despicable Me".
    """
    index = _title_index()
    by_norm = {norm: movie_id for movie_id, norm, _ in index}
    ditemukan: list[int] = []
    tidak_ketemu: list[str] = []
    for title in titles:
        needle = _normalize(_clean_title(title))
        if len(needle) < 2:
            continue
        padat = needle.replace(" ", "")
        cocok = [movie_id for movie_id, norm, compact in index
                 if norm == needle or compact == padat]
        if not cocok and len(padat) >= 4:
            cocok = [movie_id for movie_id, norm, compact in index
                     if needle in norm or padat in compact][:5]
        if not cocok and len(padat) >= FUZZY_MIN_CHARS:
            mirip = difflib.get_close_matches(needle, list(by_norm), n=2, cutoff=FUZZY_CUTOFF)
            cocok = [by_norm[norm] for norm in mirip]
        if not cocok:
            tidak_ketemu.append(title.strip())
        for movie_id in cocok:
            if movie_id not in ditemukan:
                ditemukan.append(movie_id)
    return by_ids(ditemukan), tidak_ketemu


def by_titles(titles: list[str]) -> list[dict]:
    """Seperti `match_titles`, tapi hanya mengembalikan film yang ketemu."""
    return match_titles(titles)[0]


def for_llm(movies: list[dict]) -> str:
    """JSON ringkas film untuk konteks LLM (tanpa poster/PC, overview dipotong)."""
    ringkas = []
    for movie in movies:
        item = {key: movie.get(key) for key in LLM_FIELDS}
        item["link"] = imdb_url(movie)
        item["overview"] = str(movie.get("overview") or "")[:OVERVIEW_CHARS]
        ringkas.append(item)
    return json.dumps(ringkas, ensure_ascii=False, default=str)


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
