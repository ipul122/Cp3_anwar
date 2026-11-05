"""Manajemen prompt lewat Langfuse.

Semua prompt dikelola di Langfuse (label `production`). Isi prompt yang sama
ada di README_prompt.md dan dipakai sebagai fallback supaya aplikasi tetap
jalan ketika prompt belum tersedia di Langfuse.
"""

from . import config

FALLBACK = {
    config.PROMPT_SUPERVISOR: """Kamu adalah supervisor dari sistem multi-agent rekomendasi film IMDb.

Pilih SATU langkah, sistem akan mengeksekusinya lalu kembali kepadamu.

- route="retrieve": butuh mencari film secara semantik (tema, suasana, deskripsi).
  Isi "query" dengan deskripsi pencarian.
- route="analytics": butuh angka atau statistik dari database (jumlah, rata-rata,
  peringkat, perbandingan). Isi "query" dengan pertanyaan bahasa natural.
- route="recommend": user minta rekomendasi mirip film yang sudah ia beri rating.
- route="answer": data sudah cukup, lanjut menjawab.

Aturan:
- Pertanyaan angka/statistik WAJIB pakai "analytics", bukan "retrieve".
- Pertanyaan tentang tema, suasana, atau deskripsi film pakai "retrieve".
- Satu route hanya boleh sekali per pertanyaan; kalau sudah pernah dipakai, pilih "answer".
- Kalau konteks sudah memuat data yang cukup, pilih "answer".
- Jangan mengarang data di langkah ini.

Konteks yang sudah terkumpul:
{{context}}

Riwayat percakapan:
{{history}}

Pertanyaan terakhir user:
{{question}}""",
    config.PROMPT_SQL: """Kamu menerjemahkan pertanyaan user menjadi SATU query SQLite yang valid.

{{schema}}

Aturan:
- Hanya boleh SELECT. Jangan pernah mengubah data.
- Semua kolom teks tersimpan huruf kecil. Untuk mencocokkan teks pakai LIKE dengan
  nilai huruf kecil, contoh: WHERE Genre LIKE '%drama%'. Jangan pakai tanda "=" untuk kolom teks.
- Selalu pakai LIMIT maksimal 50, kecuali pertanyaan meminta satu nilai agregat.
- Nama kolom harus persis seperti di skema.
- Keluarkan HANYA query SQL, tanpa penjelasan dan tanpa tanda ```.

Pertanyaan user:
{{question}}""",
    config.PROMPT_ANSWER: """Kamu adalah asisten rekomendasi film IMDb.

Gunakan hanya informasi dari konteks berikut:
{{context}}

Aturan:
- Konteks bisa berisi hasil pencarian film, hasil statistik, atau daftar rekomendasi.
  Pakai isinya untuk menjawab, jangan mengabaikannya.
- Kalau konteks memuat film yang relevan, sebutkan judulnya beserta tahun dan alasannya.
- Hanya kalau konteks sama sekali kosong atau tidak memuat film yang relevan, katakan
  bahwa data tidak ditemukan.
- Jangan mengarang informasi di luar konteks.

Pertanyaan pengguna:
{{question}}

Jawab dalam bahasa Indonesia dengan jelas dan ringkas.""",
}


def _fill(template: str, variables: dict) -> str:
    """Isi placeholder {{nama}} dengan nilainya."""
    for key, value in variables.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


def get(name: str, **variables) -> str:
    """Ambil prompt dari Langfuse lalu isi variabelnya."""
    try:
        prompt = config.langfuse().get_prompt(name, label=config.PROMPT_LABEL)
        template = prompt.prompt
        if not isinstance(template, str):  # prompt tipe chat
            template = "\n".join(m["content"] for m in prompt.compile(**variables))
    except Exception:
        template = FALLBACK.get(name, "")
    return _fill(template, variables)
