import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langfuse import Langfuse
from openai import OpenAI
from qdrant_client import QdrantClient

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "database.db"
DB_URI = f"file:{DB_PATH.as_posix()}?mode=ro" 

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

LLM_MODEL = os.getenv("LLM_MODEL", "inclusionai/ling-3.1-flash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
RERANK_MODEL = os.getenv("Rerank_MODEL") or os.getenv("RERANK_MODEL", "mongodb/rerank-2.5")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "imdb_movies")

LIMIT_USD = float(os.getenv("LIMIT_USD", "0.001"))

PROMPT_LABEL = os.getenv("LANGFUSE_PROMPT_LABEL", "production")
PROMPT_SUPERVISOR = os.getenv("LANGFUSE_PROMPT_SUPERVISOR", "imdb-supervisor")
PROMPT_SQL = os.getenv("LANGFUSE_PROMPT_SQL", "imdb-sql-agent")
PROMPT_ANSWER = os.getenv("LANGFUSE_PROMPT_ANSWER", "imdb-answer-agent")


def llm(temperature: float = 0) -> ChatOpenAI:
    """LLM chat lewat OpenRouter (API-nya kompatibel dengan OpenAI)."""
    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        temperature=temperature,
        max_retries=0,  # retry ditangani sendiri di workflow._invoke
        timeout=60,  # jangan menggantung kalau provider lambat
    )


@lru_cache(maxsize=1)
def embeddings() -> OpenAI:
    """Client untuk membuat embedding query."""
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)


@lru_cache(maxsize=1)
def qdrant() -> QdrantClient:
    """Client Qdrant Cloud (collection `imdb_movies`, payload hanya sqlite_id)."""
    return QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))


@lru_cache(maxsize=1)
def langfuse() -> Langfuse:
    """Client Langfuse untuk prompt management + observability (OTel)."""
    return Langfuse()
