"""Rekomendasi film berbasis PCA 2D.

Setiap film punya koordinat (PC1, PC2) di database. Ide dasarnya:

1. Dari rating user, hitung satu "titik selera" di peta 2D itu (`rating_center`).
2. Rekomendasikan film yang letaknya paling dekat dengan titik itu (`pca_neighbors`).

Contoh kecil: user memberi 10 untuk film A dan 9 untuk film B -> titik selera ada
di antara A dan B (lebih dekat ke A). Film yang dirating 1 mendorong titik itu
menjauh dari dirinya.
"""

from . import age_rules, database

PUSH_AWAY = 0.5  # seberapa kuat film yang tidak disukai mendorong titik selera
RECENT_RATINGS = 7  # hanya rating terbaru sebanyak ini yang dipakai (selera lama tergantikan)
LIKED_FROM = 6  # rating >= 6 = disukai, rating <= 5 = tidak disukai


def _catalog_mean(column: str) -> float:
    """Rata-rata satu kolom PC di seluruh katalog (titik awal kalau belum ada film disukai)."""
    return database.query(f"SELECT AVG({column}) AS mean FROM imdb_movies")[0]["mean"]


def rating_center(ratings: dict) -> tuple[float, float] | None:
    """Titik selera user di peta PCA 2D, atau None kalau belum ada rating.

    `ratings` = {id_film: nilai 1-10}, urutan dict = urutan pemberian rating.

    - Film disukai (>= 6) MENARIK titik: titik = rata-rata posisi film itu,
      dibobot nilai ratingnya.
    - Film tidak disukai (<= 5) MENDORONG titik ke arah berlawanan. Makin rendah
      ratingnya makin kuat dorongannya (rating 5 = 20%, rating 1 = 100% dari PUSH_AWAY).
    - Kalau semua yang dirating tidak disukai, titik awalnya pusat katalog.
    """
    ratings = dict(list(ratings.items())[-RECENT_RATINGS:])
    if not ratings:
        return None

    placeholders = ",".join("?" * len(ratings))
    rows = database.query(f"SELECT id, PC1, PC2 FROM imdb_movies WHERE id IN ({placeholders})", tuple(ratings))
    rows = [r for r in rows if r["PC1"] is not None and r["PC2"] is not None]
    if not rows:
        return None

    liked = [(r, ratings[r["id"]]) for r in rows if ratings[r["id"]] >= LIKED_FROM]
    disliked = [(r, ratings[r["id"]]) for r in rows if ratings[r["id"]] < LIKED_FROM]

    # 1) tarik ke film yang disukai
    if liked:
        total = sum(weight for _, weight in liked)
        center = [sum(weight * r["PC1"] for r, weight in liked) / total,
                  sum(weight * r["PC2"] for r, weight in liked) / total]
    else:
        center = [_catalog_mean("PC1"), _catalog_mean("PC2")]

    # 2) dorong menjauh dari film yang tidak disukai
    if disliked:
        total = sum(6 - weight for _, weight in disliked)  # rating rendah = bobot besar
        away = [sum((6 - weight) * r["PC1"] for r, weight in disliked) / total,
                sum((6 - weight) * r["PC2"] for r, weight in disliked) / total]
        push = PUSH_AWAY * total / (len(disliked) * 5)
        center = [center[0] - push * (away[0] - center[0]),
                  center[1] - push * (away[1] - center[1])]

    return center[0], center[1]


def pca_neighbors(center: tuple[float, float], k: int = 3, exclude=(), age: int | None = None) -> list[dict]:
    """`k` film terdekat dari `center` (jarak euclidean), tanpa film di `exclude`,
    dan hanya film yang boleh untuk umur `age`."""
    pc1, pc2 = center
    sql = (
        f"SELECT {database.FIELDS} FROM imdb_movies WHERE PC1 IS NOT NULL AND PC2 IS NOT NULL "
        f"AND {age_rules.sql_condition(age)} "
        "ORDER BY (PC1 - ?) * (PC1 - ?) + (PC2 - ?) * (PC2 - ?) ASC LIMIT ?"
    )
    # Ambil lebih banyak dari yang diminta supaya film yang sudah dirating bisa dibuang.
    rows = database.query(sql, (pc1, pc1, pc2, pc2, k + len(exclude)))
    skip = set(exclude)
    return [r for r in rows if r["id"] not in skip][:k]


def points(age: int | None = None) -> list[dict]:
    """Titik (PC1, PC2) film yang boleh untuk `age`, untuk grafik sebaran
    (judul di tooltip tidak boleh membocorkan film yang dibatasi)."""
    return database.query(
        "SELECT id, Series_Title, IMDB_Rating AS rating, PC1, PC2 "
        f"FROM imdb_movies WHERE PC1 IS NOT NULL AND {age_rules.sql_condition(age)}"
    )
