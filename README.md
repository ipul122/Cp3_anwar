# IMDb Movie Assistant

Chatbot rekomendasi film dengan arsitektur **multi-agent** (LangGraph) + RAG,
UI **Streamlit**, prompt dikelola di **Langfuse**, dan vector database
**Qdrant Cloud**.

Sumber data: SQLite `data/database.db` (tabel `imdb_movies`, 1000 film + kolom
`PC1`/`PC2` hasil PCA 2D dari embedding). Qdrant hanya menyimpan vektor + payload
`{"sqlite_id": ...}`, sehingga data teks tetap diambil dari SQLite.

## Alur

```
Start -> Supervisor -> (Retrieve | Analytics | Recommend) -> Supervisor -> Answer -> Stop
```

- **Supervisor** memilih satu langkah (route) memakai prompt `imdb-supervisor`.
- **Retrieve** = tool `search_movies`: embedding query -> Qdrant -> SQLite ->
  **reranker** (`mongodb/rerank-2.5`, bisa diganti via env `Rerank_MODEL`).
- **Analytics** = tool `movie_stats`: LLM menyusun SQL (prompt `imdb-sql-agent`)
  lalu dijalankan read-only ke SQLite.
- **Recommend** = rekomendasi berbasis PCA dari rating user.
- **Answer** memakai prompt `imdb-answer-agent` (jawaban hanya dari konteks RAG).

## Fitur Streamlit

- Panel kiri = **console log interaktif**: route agent, tool call, token, dan biaya
  (USD) per sesi.
- Saat dibuka, muncul **3 film acak** untuk diberi rating 1-10.
- Setelah ada rating, rekomendasi dihitung dari **kedekatan PCA**: titik tengah
  `PC1, PC2` film yang dirating (dibobot nilai rating) -> k tetangga terdekat di
  database (jarak euclidean), film yang sudah dirating dibuang.
- Tab **Chat dengan agent**: percakapan dengan chat history + expander
  "Data dari vector database (Qdrant)" sebagai bukti jawaban berasal dari RAG.

## Prompt di Langfuse

Lihat **`README_prompt.md`** - tempel 3 prompt di sana (`imdb-supervisor`,
`imdb-sql-agent`, `imdb-answer-agent`) dengan label `production`.
Prompt dipakai lewat SDK, bukan hardcode; kalau tidak ada di Langfuse, aplikasi
memakai fallback di `src/imdb_anwar/prompts.py`.

## Observability (Langfuse)

Setiap percakapan dikirim ke Langfuse (SDK v5, OpenTelemetry) dengan
`session_id`, `tags`, span per node, dan `generation` per panggilan LLM
(model + token + biaya). Prompt yang dipakai ikut tercatat.

## Catatan model & reranker

- Reranker (`Rerank_MODEL`, default `mongodb/rerank-2.5`) dipanggil lewat endpoint
  `/api/v1/rerank` OpenRouter. Kalau akun OpenRouter dibatasi "ZDR only"
  (Settings → Privacy), semua provider reranker akan balas `404` sehingga
  urutan hasil diambil dari **LLM sebagai cadangan** (`llm-fallback`).
  Sumber urutan selalu tercatat di console log Streamlit pada baris `tool_result`.
  Setelah provider reranker diizinkan, otomatis kembali memakai `reranker` tanpa ubah kode.
- `LLM_MODEL` dipakai untuk chatting **dan** panggilan tool/structured. Model
  `inclusionai/ling-3.1-flash` sempat menggantung/`429` untuk panggilan tool
  ber-tools, jadi default di sini `google/gemini-2.5-flash`.

## Setup

```bash
poetry install
copy .env.example .env      # Linux/macOS: cp .env.example .env
poetry run streamlit run app.py
```

Untuk Streamlit Cloud, masukkan seluruh isi `.env` ke bagian **Secrets**.

## Struktur

```
app.py                          # UI Streamlit
src/imdb_anwar/config.py        # env, client LLM/embedding/Qdrant/Langfuse
src/imdb_anwar/prompts.py       # prompt dari Langfuse + fallback
src/imdb_anwar/data.py          # SQLite: film, rating center, tetangga PCA
src/imdb_anwar/vectorstore.py   # embed, Qdrant, reranker
src/imdb_anwar/tools.py         # tool agent: search_movies, movie_stats
src/imdb_anwar/workflow.py      # graph LangGraph + log token/biaya
check.py                        # cek cepat tanpa panggilan LLM
```
