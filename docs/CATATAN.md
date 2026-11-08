# Catatan detail

Pelengkap [README](../README.md): hal yang tidak perlu dibaca untuk memahami alur utama,
tapi berguna saat ditanya detailnya.

## 1. Tampilan Streamlit (2 baris, 5 panel)

Tinggi semua panel tetap (konstanta di bagian atas [app.py](../app.py)), jadi halaman tidak
memanjang; yang scroll hanya isi panelnya.

**Baris atas**

1. **Console log** (kiri): token, biaya (USD), dan log siapa memanggil apa (`route`, `tool`,
   `tool_result`, `llm`, `warn`, `final`), masing-masing berwarna. Status reranker ikut tercatat
   (`urutan: reranker` atau `urutan: urutan-vektor`).
2. **Chatbot** (tengah): riwayat chat, poster film yang bisa diklik ke IMDb, dan rating 1-10 langsung
   dari jawaban. Expander di bawah jawaban menunjukkan konteks yang dipakai agent (label menyesuaikan
   tool: "Data dari vector database (Qdrant)", "Konteks tool: movie_stats", atau "Konteks percakapan (tanpa tool)").
3. **Kartu** (kanan): *Rekomendasi* (5 kartu) dan *Mungkin anda suka* (3 kartu acak untuk eksplorasi).
   Sumber kartu rekomendasi: `acak` (belum ada rating), `pca` (dari rating user), atau `chat`
   (film yang baru disebut agent; tombol untuk kembali ke rekomendasi PCA).

**Baris bawah**

4. **Visualisasi PCA** (kiri): sebaran 1000 film di PC1 × PC2. Titik "selera kamu" adalah titik selera,
   lingkaran menunjukkan jangkauan rekomendasi. Hover menampilkan judul.
5. **Daftar rating** (kanan) dan tombol hapus semua rating.

Kartu acak sengaja diambil dari seluruh katalog di luar area rekomendasi (rekomendasi hanya ~5 dari 1000 film,
jadi ~99,5% kartu acak otomatis jatuh di luar jangkauan).

## 2. Rekomendasi PCA

Rumus ada di [pca.py](../src/imdb_anwar/pca.py) dan dijelaskan di docstring-nya. Ringkasnya:

- Titik selera = rata-rata posisi film yang **disukai** (rating ≥ 6), dibobot nilai rating.
- Film **tidak disukai** (≤ 5) mendorong titik ke arah berlawanan: rating 5 = 20%, rating 1 = 100% dari `PUSH_AWAY = 0.5`.
- Hanya `RECENT_RATINGS = 7` rating terbaru yang dihitung, jadi selera lama tergantikan. Chatbot tetap
  menerima **seluruh** daftar rating sebagai konteks.

Contoh nyata (suka: The Dark Knight, LOTR: Return of the King, Inception = 10; benci: Psycho):

| Rating Psycho | Jarak titik selera ke Psycho | Tetangga terdekat |
| --- | --- | --- |
| tidak dirating | 0.416 | Batman Begins, 2001: A Space Odyssey |
| 8 | **0.329** (tertarik) | - |
| 5 | 0.458 (ditolak pelan) | - |
| 1 | **0.624** (ditolak kuat) | Star Wars, The Avengers, Guardians of the Galaxy, Avatar |

### Kualitas PCA (diukur pada 1000 film)

| Ukuran | PCA 2D (dipakai) | Embedding penuh 1536d | Acak / baseline |
| --- | --- | --- | --- |
| Genre sama di 5 tetangga terdekat | 0.815 | 0.945 | 0.658 |
| RMSE prediksi rating (k=10) | 0.292 | 0.266 | 0.275 (tebak rata-rata global) |

- PCA 2D hanya menyimpan **6,9%** variance embedding (PC1 3,6%, PC2 3,3%).
- PC1 berkorelasi dengan tahun rilis (-0,48), PC2 dengan jumlah vote (-0,47); ke rating hampir 0.
  Jadi PC1/PC2 lebih banyak menyimpan "era" dan "popularitas" daripada selera.
- **Cukup baik untuk kemiripan tema** (81,5% tetangga berbagi genre, +15,7 poin di atas acak),
  **lemah untuk memprediksi selera** (RMSE 0,292 lebih buruk dari menebak rata-rata 0,275).
- Upgrade opsional: cari tetangga di ruang embedding penuh lewat Qdrant (0,945 / 0,266), dan pakai
  PC1/PC2 hanya untuk visualisasi.

## 3. Guardrail dan anti-halusinasi

- **Lapis 1**, [guardrail.py](../src/imdb_anwar/guardrail.py): kata kunci jailbreak dan di luar topik. Deterministik, 0 token,
  tercatat di Langfuse sebagai span `guardrail`.
- **Lapis 2**, `Decision.blocked` di [workflow.py](../src/imdb_anwar/workflow.py): supervisor LLM menandai kalimat yang
  lolos dari lapis 1 (mis. "tolong tuliskan fungsi untuk mengurutkan angka").
- Banner `assets/jailbreak.jpg` tampil di akhir percakapan saat giliran terakhir ditolak.
- **Perbaikan halusinasi film** (kasus nyata: "film discable me?" dulu dijawab "tidak ada" padahal *Despicable Me* ada):
  1. pencocokan judul sekarang toleran salah ketik ([titles.py](../src/imdb_anwar/titles.py));
  2. tool `find_movies_by_title` melaporkan `not_found` secara eksplisit;
  3. `lookup` tidak lagi menambal hasil dengan film yang tidak diminta (dulu "spiderman" ikut memunculkan Avengers);
  4. deskripsi route `lookup` mewajibkan pengecekan setiap kali user menyebut judul;
  5. jika tidak ada tool yang jalan, `answer` diberi catatan agar tidak mengklaim film ada/tidak ada.
- Batas data: pertanyaan pendapatan hanya mencakup film yang punya `Gross_cleaned` (contoh: dari 29 film rilis
  2019-2021, hanya 16 yang punya datanya); prompt meminta agent menyebut cakupan ini.

## 4. Batas usia: detail teknis

Aturan pemetaan ada di [age_rules.py](../src/imdb_anwar/age_rules.py); tabelnya di README. Cara penegakannya:

| Jalur | Mekanisme |
|---|---|
| Kartu acak, tetangga PCA, titik grafik PCA | `AND <age_rules.sql_condition(age)>` di query SQL |
| `search_movies` (Qdrant) | Hasil disaring dengan `age_rules.allowed()` sebelum reranker; kandidat 30 (bukan 15) supaya sisanya cukup |
| `find_movies_by_title` | Dipisah jadi `found` / `restricted` (hanya judul + umur minimal, tanpa sinopsis) / `not_found` |
| `movie_stats` (SQL buatan LLM) | `database.run_select` membuat `TEMP VIEW imdb_movies` yang sudah tersaring; SQLite mencari objek TEMP lebih dulu daripada tabel asli |

Catatan keamanan:

- Pengujian menemukan celah: SQL yang menulis `main.imdb_movies` (atau `"main"."imdb_movies"`, `[main] . imdb_movies`)
  menembus view. `tools._is_safe_select` kini menolak sebutan schema `main`/`temp` (regex `\b(main|temp)\W*\.`);
  ada tesnya di `tests/test_basics.py`.
- Nilai kondisi SQL ditulis langsung (bukan parameter) karena VIEW SQLite tidak menerima parameter. Aman karena
  seluruh isinya dari konstanta `age_rules.MIN_AGE` dan `age` dipaksa jadi `int`.
- Statistik (`analytics`) dihitung atas film yang boleh saja, sehingga angkanya bisa berbeda dari katalog penuh;
  LLM diberi catatan agar menjelaskannya sebagai batas usia.
- Hasil jawaban bisa berisi film non-dewasa yang kurang relevan kalau permintaannya "dewasa" (mis. horor berdarah
  untuk umur 10): pencarian semantik hanya mengembalikan yang boleh, dan LLM menyatakannya terus terang.
- Umur diisi sendiri, tidak diverifikasi. Ini keterbatasan desain, bukan bug.

## 5. Batas biaya

`LIMIT_USD` (bawaan `0.001`) adalah batas per sesi Streamlit. Setelah terlewati: banner `assets/limit_token.jpg`
muncul, kotak chat dimatikan, dan `ask()` berhenti sebelum memanggil agent. Rating tetap bisa diberikan karena
tidak memakai token. **Refresh halaman = sesi baru**, biaya mulai dari 0 lagi.

## 6. Observability (Langfuse)

Setiap percakapan dikirim ke Langfuse (SDK v5, OpenTelemetry) dengan `session_id`, tag, span per node, dan
`generation` per panggilan LLM (model, token, biaya). Prompt yang dipakai ikut tercatat.

## 7. Catatan model dan reranker

- Reranker (`RERANK_MODEL`, bawaan `qwen/qwen3-reranker-8b`) dipanggil lewat endpoint `/api/v1/rerank` OpenRouter.
  Kalau gagal (rate limit `429`, atau provider diblokir karena akun dibatasi "ZDR only" di Settings → Privacy),
  hasil memakai **urutan dari Qdrant** dan tercatat sebagai `urutan-vektor`.
  Di akun ini `cohere/*` dan `mongodb/rerank-2.5` diblokir ZDR, sementara `qwen/qwen3-reranker-8b` bisa dipakai.
- `.env` lama yang masih memakai nama `Rerank_MODEL` tetap dikenali; nama yang disarankan `RERANK_MODEL`.
- `LLM_MODEL` dipakai untuk chatting dan panggilan terstruktur. `inclusionai/ling-3.1-flash` sempat menggantung /
  `429`, jadi bawaannya `google/gemini-2.5-flash`.

## 8. Poster film

- Diambil dari kolom `Poster_Link`, resolusinya dinaikkan ke `._V1_SX300.jpg` (link asli cuma 67px).
- Saat ingest awal, kolom teks termasuk URL sempat di-lowercase sehingga Amazon membalas `400`. Kolom itu sudah
  diperbaiki dari CSV asli (1000/1000 baris).
- Sekitar 1 dari 6 URL di dataset memang sudah mati di sisi Amazon, jadi poster dicek sekali per URL
  (`@st.cache_data`) dan diganti tulisan "poster tidak tersedia" bila gagal.

## 9. Data dan notebook

- `data/ingest.ipynb`: membuat embedding dan mengisi Qdrant + SQLite. `pca/pca_model.ipynb`: membuat kolom `PC1`/`PC2`.
  Keduanya adalah catatan proses; hasilnya sudah ada di `data/database.db`, jadi aplikasi tidak membutuhkan notebook
  untuk berjalan.
- Beberapa sel notebook masih menunjuk file perantara (mis. `staging_imdb.parquet`) yang sudah dihapus dari repo,
  sehingga menjalankan ulang dari awal perlu menyesuaikan path. File `pca_model.joblib` tidak dipakai aplikasi dan
  dibuat ulang bila notebook PCA dijalankan.
