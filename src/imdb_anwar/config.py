"""Konfigurasi: baca .env, lalu sediakan client LLM, embedding, Qdrant, dan Langfuse.

Semua file lain mengambil setting dan client dari sini, jadi hanya di sini
tempat kita menyentuh environment variable.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langfuse import Langfuse
from openai import OpenAI
from qdrant_client import QdrantClient

load_dotenv()

# --- Database SQLite (read-only: agent tidak bisa mengubah data) ---
ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "database.db"
DB_URI = f"file:{DB_PATH.as_posix()}?mode=ro"

# --- Model lewat OpenRouter (API-nya kompatibel dengan OpenAI) ---
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.5-flash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
# Nama lama `Rerank_MODEL` masih dikenali supaya .env lama tetap jalan.
RERANK_MODEL = os.getenv("RERANK_MODEL") or os.getenv("Rerank_MODEL", "qwen/qwen3-reranker-8b")

QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "imdb_movies")

# Batas biaya (USD) per sesi Streamlit. Kalau tercapai, chatbot berhenti
# sampai halaman di-refresh (sesi baru).
LIMIT_USD = float(os.getenv("LIMIT_USD", "0.001"))

# Nama prompt di Langfuse (semua prompt disimpan di sana, bukan di kode).
PROMPT_LABEL = os.getenv("LANGFUSE_PROMPT_LABEL", "production")
PROMPT_SUPERVISOR = os.getenv("LANGFUSE_PROMPT_SUPERVISOR", "imdb-supervisor")
PROMPT_SQL = os.getenv("LANGFUSE_PROMPT_SQL", "imdb-sql-agent")
PROMPT_ANSWER = os.getenv("LANGFUSE_PROMPT_ANSWER", "imdb-answer-agent")


def llm(temperature: float = 0) -> ChatOpenAI:
    """LLM chat. Retry ditangani sendiri di tracing.call_llm."""
    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        temperature=temperature,
        max_retries=0,
        timeout=60,  # jangan menggantung kalau provider lambat
    )


@lru_cache(maxsize=1)
def embeddings() -> OpenAI:
    """Client untuk membuat embedding."""
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)


@lru_cache(maxsize=1)
def qdrant() -> QdrantClient:
    """Client Qdrant Cloud (payload tiap vektor hanya berisi `sqlite_id`)."""
    return QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))


@lru_cache(maxsize=1)
def langfuse() -> Langfuse:
    """Client Langfuse: pengelolaan prompt + observability."""
    return Langfuse()
