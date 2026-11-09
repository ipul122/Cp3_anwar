"""Pencatatan: log console, token, biaya, dan pelacakan (trace) di Langfuse.

`trace` adalah dict sederhana yang dibawa sepanjang satu sesi chat:
    {"logs": [...], "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "session_id": "..."}

Pohon pelacakan di Langfuse untuk satu pertanyaan:

    chat-turn                       (root)
    |- supervisor                   generation  (LLM)
    |- retrieve-agent               agent
    |   `- search_movies            tool
    |       |- embedding            embedding   (OpenRouter)
    |       |- qdrant-search        retriever
    |       `- rerank               span        (OpenRouter)
    |- analytics-agent              agent
    |   `- movie_stats              tool
    |       |- sql                  generation  (LLM penulis SQL)
    |       `- sqlite-query         span
    |- lookup-agent / recommend-agent
    `- answer                       generation  (LLM)

Setiap layanan berbayar (LLM, embedding, reranker) menambah token dan biaya ke `trace`,
jadi angka di console dan batas LIMIT_USD mencakup semuanya.
"""

import contextvars
import functools
import time
from contextlib import contextmanager

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from . import config

HISTORY_MESSAGES = 6  # riwayat yang dikirim ke LLM: 3 percakapan terakhir (user + assistant)
OUTPUT_CHARS = 500  # panjang maksimal output yang dikirim ke Langfuse

# Trace sesi yang sedang berjalan. Diisi oleh workflow.run() lewat use_trace(), supaya tool
# (yang dipanggil tanpa membawa trace) tetap bisa mencatat token dan biaya.
_current_trace: contextvars.ContextVar = contextvars.ContextVar("current_trace", default=None)


def new_trace(session_id: str = "streamlit") -> dict:
    """Wadah log + akumulasi token & biaya untuk panel console."""
    return {"logs": [], "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "session_id": session_id}


def current_trace() -> dict | None:
    """Trace sesi yang sedang berjalan, atau None kalau dipanggil di luar workflow.run()."""
    return _current_trace.get()


@contextmanager
def use_trace(trace: dict):
    """Jadikan `trace` sebagai trace aktif selama blok `with` ini."""
    token = _current_trace.set(trace)
    try:
        yield trace
    finally:
        _current_trace.reset(token)


def log_event(trace: dict, event: str, **details) -> None:
    """Tulis satu baris ke console log."""
    trace["logs"].append({"event": event, **details})


def add_cost(name: str, cost: float, tokens: int = 0) -> None:
    """Catat biaya layanan non-LLM (embedding, reranker) ke trace aktif dan console log."""
    trace = current_trace()
    if trace is None or not cost:
        return
    trace["cost"] += cost
    log_event(trace, "api", name=name, tokens=tokens, cost=round(cost, 6))


# --- Pelacakan di Langfuse ------------------------------------------------------------

@contextmanager
def observe(name: str, as_type: str = "span", **kwargs):
    """Buka satu observasi di Langfuse (jenis: span, agent, tool, retriever, embedding, generation, ...).

    Hasilnya objek yang punya `.update(output=..., ...)` untuk mengisi hasil setelah selesai.
    """
    with config.langfuse().start_as_current_observation(name=name, as_type=as_type, **kwargs) as observation:
        yield observation


def traced_agent(name: str):
    """Dekorator untuk node agent: catat satu observasi `agent` berisi input dan hasilnya."""
    def decorator(node):
        @functools.wraps(node)
        def wrapper(state):
            with observe(name, "agent", input={"query": state["query"] or state["question"],
                                               "age": state["age"]}) as observation:
                update = node(state)
                added = update["context"][len(state["context"]):] if "context" in update else []
                observation.update(output={
                    "films": [m["Series_Title"] for m in update.get("movies", [])],
                    "context_added": [text[:OUTPUT_CHARS] for text in added],
                })
                return update
        return wrapper
    return decorator


# --- Pemanggilan LLM ---------------------------------------------------------------------

def build_messages(system: str, history: list, question: str) -> list:
    """System prompt + riwayat chat terakhir + pertanyaan sekarang."""
    messages = [SystemMessage(system)]
    for item in history[-HISTORY_MESSAGES:]:
        messages.append(HumanMessage(item["content"]) if item["role"] == "user" else AIMessage(item["content"]))
    messages.append(HumanMessage(question))
    return messages


def _invoke(model, messages, attempts: int = 2):
    """Coba lagi sekali untuk error sementara (mis. rate limit provider)."""
    for attempt in range(attempts):
        try:
            return model.invoke(messages)
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(3)


def _as_dicts(messages: list) -> list[dict]:
    """Pesan LangChain -> [{"role", "content"}] untuk ditampilkan di Langfuse."""
    roles = {"system": "system", "human": "user", "ai": "assistant"}
    return [{"role": roles.get(m.type, m.type), "content": m.content} for m in messages]


def call_llm(trace: dict, name: str, messages: list, schema=None, prompt=None):
    """Panggil LLM lalu catat token & biaya. Dengan `schema`, hasilnya objek terstruktur.

    Tanpa `schema` mengembalikan pesan LLM; dengan `schema` mengembalikan
    {"parsed": objek schema, "raw": pesan LLM}.
    `prompt` = objek prompt Langfuse (dari prompts.load) supaya generation tertaut ke versi prompt-nya.
    """
    model = config.llm()
    if schema:
        model = model.with_structured_output(schema, include_raw=True)
    with observe(name, "generation", model=config.LLM_MODEL, input=_as_dicts(messages), prompt=prompt) as generation:
        result = _invoke(model, messages)
        message = result["raw"] if schema else result
        usage = getattr(message, "usage_metadata", None) or {}
        cost = (message.response_metadata.get("token_usage") or {}).get("cost", 0) or 0
        trace["prompt_tokens"] += usage.get("input_tokens", 0)
        trace["completion_tokens"] += usage.get("output_tokens", 0)
        trace["cost"] += cost
        log_event(trace, "llm", name=name, tokens=usage.get("total_tokens", 0), cost=round(cost, 6))
        generation.update(
            output=str(message.content)[:OUTPUT_CHARS],
            usage_details={"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)},
            cost_details={"total": cost} if cost else None,
        )
    return result
