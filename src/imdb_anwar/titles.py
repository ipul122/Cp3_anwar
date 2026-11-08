"""Mencocokkan judul film yang diketik user dengan judul di database.

Urutan percobaan untuk setiap judul (berhenti di yang pertama berhasil):

1. Cocok persis (setelah tanda baca, aksen, dan spasi diabaikan).
2. Potongan judul: "spiderman" ada di "spider-man: into the spider-verse".
3. Mirip (salah ketik): "discable me" -> "despicable me".
"""

import difflib
import re
import unicodedata
from functools import lru_cache

from . import age_rules, database

FUZZY_CUTOFF = 0.8  # kemiripan minimal (0-1) untuk judul yang salah ketik
FUZZY_MIN_CHARS = 5  # judul lebih pendek tidak di-fuzzy: terlalu mudah salah cocok
PARTIAL_MIN_CHARS = 4  # potongan judul hanya untuk kata >= 4 huruf ("up"/"saw" tidak menarik film lain)
PARTIAL_MAX = 5  # maksimal film dari satu potongan judul


def _normalize(text: str) -> str:
    """Huruf kecil, aksen dibuang, semua tanda baca jadi spasi."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _strip_year(text: str) -> str:
    """Buang tahun dari judul: "Tumbbad (2018)" -> "Tumbbad"."""
    text = re.sub(r"\(\s*(19|20)\d{2}\s*\)", " ", str(text))
    text = re.sub(r"\b(19|20)\d{2}\b", " ", text)
    return text.strip(" \t\"'.,;:-–—()[]")


@lru_cache(maxsize=1)
def _title_index() -> list[tuple[int, str, str]]:
    """(id, judul ternormalisasi, judul tanpa spasi) untuk semua film. Di-cache per proses."""
    index = []
    for row in database.query("SELECT id, Series_Title FROM imdb_movies"):
        normalized = _normalize(row["Series_Title"])
        index.append((row["id"], normalized, normalized.replace(" ", "")))
    return index


def _find_ids(needle: str) -> list[int]:
    """Id film untuk satu judul yang sudah dinormalisasi (3 percobaan di atas)."""
    index = _title_index()
    compact_needle = needle.replace(" ", "")

    exact = [i for i, norm, compact in index if norm == needle or compact == compact_needle]
    if exact:
        return exact

    if len(compact_needle) >= PARTIAL_MIN_CHARS:
        partial = [i for i, norm, compact in index if needle in norm or compact_needle in compact]
        if partial:
            return partial[:PARTIAL_MAX]

    if len(compact_needle) >= FUZZY_MIN_CHARS:
        id_by_title = {norm: i for i, norm, _ in index}
        close = difflib.get_close_matches(needle, list(id_by_title), n=2, cutoff=FUZZY_CUTOFF)
        return [id_by_title[title] for title in close]

    return []


def match_titles(titles: list[str], age: int | None = None) -> tuple[list[dict], list[dict], list[str]]:
    """Cari film dari daftar judul. Mengembalikan (film boleh tampil, film dibatasi usia, judul tidak ketemu).

    Film dibatasi hanya berisi judul dan umur minimalnya: {"title": ..., "min_age": 18}.
    Detail film (sinopsis, dll.) sengaja tidak ikut, supaya tidak bocor ke user maupun LLM.
    """
    found_ids: list[int] = []
    not_found: list[str] = []
    for title in titles:
        needle = _normalize(_strip_year(title))
        if len(needle) < 2:
            continue
        ids = _find_ids(needle)
        if not ids:
            not_found.append(title.strip())
        found_ids += [i for i in ids if i not in found_ids]

    movies = database.by_ids(found_ids)
    shown = [m for m in movies if age_rules.allowed(m, age)]
    restricted = [{"title": m["Series_Title"], "min_age": age_rules.min_age(m["certificate"])}
                  for m in movies if not age_rules.allowed(m, age)]
    return shown, restricted, not_found
