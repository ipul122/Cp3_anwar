"""Aturan batas usia: sertifikat film -> umur minimal penonton.

SEMUA aturan ada di file ini. Bagian lain hanya memanggil `allowed()` (cek satu
film di Python) atau `sql_condition()` (cek langsung di query SQL).

Prinsip:
- Umur hanya dari kotak input di UI, tidak pernah dari isi chat.
- Kalau ragu, pakai batas yang lebih ketat (PG dan "16" dinaikkan ke tingkat berikutnya).
- Sertifikat yang tidak diketahui (kosong / unrated) diperlakukan 17+.
- Umur diisi sendiri oleh user dan TIDAK diverifikasi: ini filter kenyamanan, bukan pengamanan.
"""

MIN_USER_AGE, MAX_USER_AGE = 3, 100

# sertifikat (huruf kecil, sesuai kolom Certificate di database) -> umur minimal
MIN_AGE = {
    "u": 0, "g": 0, "approved": 0, "passed": 0,  # semua umur
    "pg": 13, "gp": 13, "tv-pg": 13, "ua": 13, "u/a": 13, "pg-13": 13, "tv-14": 13,
    "r": 17, "tv-ma": 17, "16": 17,
    "a": 18,
}
UNKNOWN_MIN_AGE = 17  # sertifikat kosong ("nan") atau "unrated"


def min_age(certificate) -> int:
    """Umur minimal untuk satu sertifikat (yang tidak dikenal = UNKNOWN_MIN_AGE)."""
    return MIN_AGE.get(str(certificate or "").strip().lower(), UNKNOWN_MIN_AGE)


def allowed(movie: dict, age: int | None) -> bool:
    """Boleh tampil untuk user berumur `age`? (`age=None` = tanpa batas, dipakai tes/skrip)."""
    return age is None or int(age) >= min_age(movie.get("certificate"))


def hides_some_movies(age: int | None) -> bool:
    """True kalau umur ini membuat sebagian film tersembunyi (user di bawah batas tertinggi)."""
    return age is not None and int(age) < max(*MIN_AGE.values(), UNKNOWN_MIN_AGE)


def sql_condition(age: int | None) -> str:
    """Potongan SQL (untuk WHERE) yang hanya meloloskan film yang boleh untuk `age`.

    Nilainya ditulis langsung (bukan parameter `?`) karena VIEW SQLite tidak menerima parameter.
    Aman: semua isinya dari konstanta di file ini, dan `age` dipaksa jadi angka.
    """
    if age is None:
        return "1=1"
    age = int(age)
    quote = lambda items: ", ".join(f"'{item}'" for item in items)
    ok = [c for c, minimum in MIN_AGE.items() if minimum <= age]
    condition = f"lower(Certificate) IN ({quote(ok)})" if ok else "0"
    if age >= UNKNOWN_MIN_AGE:  # sertifikat tidak dikenal ikut lolos
        condition += f" OR Certificate IS NULL OR lower(Certificate) NOT IN ({quote(MIN_AGE)})"
    return f"({condition})"


def rules_markdown() -> str:
    """Tabel aturan untuk ditampilkan di UI."""
    groups: dict[int, list[str]] = {}
    for certificate, minimum in MIN_AGE.items():
        groups.setdefault(minimum, []).append(certificate.upper())
    groups.setdefault(UNKNOWN_MIN_AGE, []).append("(tidak diketahui)")
    lines = ["| Umur minimal | Sertifikat |", "|---|---|"]
    lines += [f"| {minimum}+ | {', '.join(certs)} |" for minimum, certs in sorted(groups.items())]
    return "\n".join(lines)
