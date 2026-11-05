# IMDb Movie Assistant

Alur aplikasi: pertanyaan di-embedding, Qdrant mengembalikan ID film,
SQLite mengambil data lengkap, lalu agent menjawab memakai prompt Langfuse.

Supervisor memilih Retrieval Agent untuk pertanyaan rekomendasi/semantik dan
Analyst Agent untuk pertanyaan angka atau perbandingan. Keduanya meneruskan
hasilnya ke Answer Agent.

Prompt Langfuse yang diperlukan: `imdb-answer-agent`, dengan label
`production` dan variabel `context` dan `question`. Nama prompt dan label
dapat diubah melalui `LANGFUSE_PROMPT_NAME` dan `LANGFUSE_PROMPT_LABEL`.

```bash
poetry install
poetry run streamlit run app.py
```

Untuk Streamlit Cloud, masukkan environment variables dari `.env.example`
ke bagian Secrets.