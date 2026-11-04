from pathlib import Path
import os
import sqlite3
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from qdrant_client import QdrantClient

# 1. Load file .env dari folder src/imdb_anwar/.env
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "inclusionai/ling-3.1-flash")
EMBED_MODEL = os.getenv("Embed_MODEL", "openai/text-embedding-3-small")
QDRANT_HOST = os.getenv("Qdrant_HOST")
QDRANT_API = os.getenv("Qdrant_API")

# Path ke file database SQLite lokal
DB_PATH = BASE_DIR.parent.parent / "data" / "database.db"

if not OPENROUTER_API_KEY:
    raise ValueError(f"OPENROUTER_API_KEY tidak ditemukan di {ENV_PATH}")

# 2. Inisialisasi LangChain Embeddings & LLM (OpenRouter)
embeddings = OpenAIEmbeddings(
    model=EMBED_MODEL,
    openai_api_key=OPENROUTER_API_KEY,
    openai_api_base="https://openrouter.ai/api/v1",
)

llm = ChatOpenAI(
    model=LLM_MODEL,
    openai_api_key=OPENROUTER_API_KEY,
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0,
)

# 3. Inisialisasi Client Qdrant Remote
qdrant_client = QdrantClient(url=QDRANT_HOST, api_key=QDRANT_API, timeout=60.0)
COLLECTION_NAME = "imdb_movies"


# 4. Helper Function untuk mengambil detail film dari SQLite berdasarkan ID
def get_movie_by_id(movie_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT Series_Title, Overview FROM imdb_movies WHERE id = ?",
        (movie_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        return {"id": movie_id, "title": row[0], "overview": row[1]}
    return None