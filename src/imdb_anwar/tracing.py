"""Memanggil LLM sambil mencatat: log untuk console UI, token, biaya, dan Langfuse.

`trace` adalah dict sederhana yang dibawa sepanjang satu sesi chat:
    {"logs": [...], "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "session_id": "..."}
"""

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from . import config

HISTORY_MESSAGES = 6  # riwayat yang dikirim ke LLM: 3 percakapan terakhir (user + assistant)


def new_trace(session_id: str = "streamlit") -> dict:
    """Wadah log + akumulasi token & biaya untuk panel console."""
    return {"logs": [], "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "session_id": session_id}


def log_event(trace: dict, event: str, **details) -> None:
    """Tulis satu baris ke console log."""
    trace["logs"].append({"event": event, **details})


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


def call_llm(trace: dict, name: str, messages: list, schema=None):
    """Panggil LLM lalu catat token & biaya. Dengan `schema`, hasilnya objek terstruktur.

    Tanpa `schema` mengembalikan pesan LLM; dengan `schema` mengembalikan
    {"parsed": objek schema, "raw": pesan LLM}.
    """
    model = config.llm()
    if schema:
        model = model.with_structured_output(schema, include_raw=True)
    with config.langfuse().start_as_current_observation(
        name=name, as_type="generation", model=config.LLM_MODEL, input=messages[-1].content
    ):
        result = _invoke(model, messages)
        message = result["raw"] if schema else result
        usage = getattr(message, "usage_metadata", None) or {}
        cost = (message.response_metadata.get("token_usage") or {}).get("cost", 0) or 0
        trace["prompt_tokens"] += usage.get("input_tokens", 0)
        trace["completion_tokens"] += usage.get("output_tokens", 0)
        trace["cost"] += cost
        log_event(trace, "llm", name=name, tokens=usage.get("total_tokens", 0), cost=round(cost, 6))
        config.langfuse().update_current_generation(output=str(message.content)[:500])
    return result
