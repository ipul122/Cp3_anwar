"""Perbaiki kolom Poster_Link di data/database.db dari CSV aslinya.

Saat ingest, semua kolom teks (termasuk Poster_Link) di-lowercase sehingga URL
gambar Amazon dibalas 400. Script ini mengembalikan huruf aslinya dari
data/imdb_top_1000.csv.

Pencocokan: judul film (huruf kecil) dulu, kalau tidak ketemu pakai urutan baris
CSV - urutan CSV sama dengan id di database.

Jalankan sekali: poetry run python fix_posters.py
"""

import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "database.db"

with (ROOT / "data" / "imdb_top_1000.csv").open(encoding="utf-8") as file:
    rows = list(csv.DictReader(file))

by_title = {row["Series_Title"].strip().lower(): row["Poster_Link"] for row in rows}

conn = sqlite3.connect(DB_PATH)
movies = conn.execute("SELECT id, Series_Title, Poster_Link FROM imdb_movies ORDER BY id").fetchall()

updates, without_poster = [], []
for index, (movie_id, title, current) in enumerate(movies):
    poster = by_title.get(title.strip().lower()) or (rows[index]["Poster_Link"] if index < len(rows) else "")
    if poster and poster != current:
        updates.append((poster, movie_id))
    elif not poster:
        without_poster.append(title)

conn.executemany("UPDATE imdb_movies SET Poster_Link = ? WHERE id = ?", updates)
conn.commit()
valid = conn.execute("SELECT COUNT(*) FROM imdb_movies WHERE Poster_Link LIKE '%/M/%'").fetchone()[0]
conn.close()

print(f"baris diperbarui   : {len(updates)}")
print(f"tanpa poster di CSV: {len(without_poster)} {without_poster[:3]}")
print(f"Poster_Link valid  : {valid}/{len(movies)}")
