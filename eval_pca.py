"""Evaluasi kualitas rekomendasi berbasis PCA 2D (PC1, PC2).

Tiga ukuran:
1. Genre agreement @k  : seberapa sering tetangga terdekat punya genre yang sama
                         dibanding baseline acak dan dibanding kNN di ruang embedding penuh.
2. RMSE prediksi rating: rating film ditebak dari rata-rata rating k tetangga terdekat
                         (leave-one-out) dibanding baseline rata-rata global.
3. Isi PC1/PC2         : korelasi dengan rating, tahun, jumlah vote, runtime.
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from imdb_anwar import config  # noqa: E402

K = 5
RATING_K = 10

conn = sqlite3.connect(config.DB_URI, uri=True)
conn.row_factory = sqlite3.Row
rows = [dict(r) for r in conn.execute(
    "SELECT id, Series_Title, Genre, IMDB_Rating, Released_Year_numeric, No_of_Votes, "
    "Runtime_minutes, PC1, PC2 FROM imdb_movies WHERE PC1 IS NOT NULL")]
conn.close()

genres = [set(g.lower() for g in (row["Genre"] or "").split(", ")) for row in rows]
ratings = np.array([row["IMDB_Rating"] for row in rows], dtype=float)
pca = np.array([[row["PC1"], row["PC2"]] for row in rows], dtype=float)
print(f"film dievaluasi: {len(rows)} | k={K} | rating_k={RATING_K}")

# --- embedding penuh sebagai pembanding -------------------------------------
staging = pd.read_parquet(ROOT / "data" / "staging_imdb.parquet")
staging = staging.set_index("id").reindex([row["id"] for row in rows])
full = np.vstack([np.asarray(vector, dtype=float) for vector in staging["embed"]])
print("matriks embedding penuh:", full.shape)


def neighbours(points: np.ndarray, k: int) -> np.ndarray:
    """Indeks k tetangga terdekat (tanpa dirinya sendiri) untuk setiap baris."""
    square = np.einsum("ij,ij->i", points, points)
    distance = square[:, None] + square[None, :] - 2.0 * (points @ points.T)
    np.fill_diagonal(distance, np.inf)
    return np.argsort(distance, axis=1)[:, :k]


def genre_agreement(neighbour_index: np.ndarray) -> float:
    hits = [len(genres[i] & genres[j]) > 0 for i, js in enumerate(neighbour_index) for j in js]
    return float(np.mean(hits))


def rmse(neighbour_index: np.ndarray) -> float:
    predicted = np.array([ratings[js].mean() for js in neighbour_index])
    return float(np.sqrt(np.mean((predicted - ratings) ** 2)))


rng = np.random.default_rng(0)
random_pairs = rng.integers(0, len(rows), size=(len(rows), K))
baseline_global = float(np.sqrt(np.mean((ratings.mean() - ratings) ** 2)))

pca_index = neighbours(pca, K)
full_index = neighbours(full, K)

print("\n== 1. Genre agreement @5 (makin tinggi makin baik) ==")
print(f"  PCA 2D          : {genre_agreement(pca_index):.3f}")
print(f"  embedding penuh : {genre_agreement(full_index):.3f}")
print(f"  acak            : {genre_agreement(random_pairs):.3f}")

print(f"\n== 2. RMSE prediksi rating (makin kecil makin baik, skala 0-10) ==")
print(f"  PCA 2D          : {rmse(neighbours(pca, RATING_K)):.3f}")
print(f"  embedding penuh : {rmse(neighbours(full, RATING_K)):.3f}")
print(f"  baseline global : {baseline_global:.3f}")

print("\n== 3. Isi komponen ==")
frame = pd.DataFrame(rows)
print(f"  sebaran rating   : min {ratings.min()} | max {ratings.max()} | std {ratings.std():.3f}")
print(f"  RMSE rata-rata global {baseline_global:.3f} vs std rating {ratings.std():.3f} "
      f"-> baseline sudah kuat karena dataset Top 1000 semuanya rating tinggi")
for column in ("IMDB_Rating", "Released_Year_numeric", "No_of_Votes", "Runtime_minutes"):
    print(f"  korelasi PC1 vs {column:22}: {frame['PC1'].corr(frame[column]):+.3f} | "
          f"PC2: {frame['PC2'].corr(frame[column]):+.3f}")

total_variance = full.var(axis=0).sum()
kept = pca[:, 0].var() + pca[:, 1].var()
print(f"  variance dijaga PCA 2D: {kept / total_variance:.1%} dari total variance embedding "
      f"{full.shape[1]} dimensi (PC1 {pca[:, 0].var() / total_variance:.1%}, "
      f"PC2 {pca[:, 1].var() / total_variance:.1%})")

print("\n== 4. Contoh hasil PCA untuk 3 film ==")
for i in (0, 100, 500):
    print(f"  {rows[i]['Series_Title']} [{rows[i]['Genre']}]")
    for j in pca_index[i]:
        print(f"     - {rows[j]['Series_Title']} [{rows[j]['Genre']}] rating {rows[j]['IMDB_Rating']}")
