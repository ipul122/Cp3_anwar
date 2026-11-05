"""Workflow multi-agent (LangGraph) untuk IMDb Movie Assistant.

Start -> Supervisor -> (Retrieve | Analytics | Recommend) -> Supervisor -> Answer -> Stop

Supervisor memilih satu langkah sekaligus, mirip pola "multi-agent as tools".
"""

import json
import time
from typing import Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langfuse import propagate_attributes
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from . import config, data, prompts, tools, vectorstore

MAX_STEPS = 6


class Decision(BaseModel):
    """Keputusan supervisor untuk langkah berikutnya."""

    route: Literal["retrieve", "analytics", "recommend", "answer"] = Field(
        description="retrieve=pencarian film, analytics=statistik/SQL, "
        "recommend=rekomendasi dari rating user, answer=jawab sekarang"
    )
    query: str = Field(default="", description="Query pencarian atau pertanyaan statistik")
    reason: str = Field(default="", description="Alasan singkat pemilihan route")


class State(TypedDict):
    """State yang mengalir di seluruh node."""

    question: str
    history: list
    ratings: dict
    context: list
    route: str
    query: str
    steps: int
    visited: list
    answer: str
    trace: dict


def new_trace(session_id: str = "streamlit") -> dict:
    """Wadah log interaktif + akumulasi token & biaya untuk panel console."""
    return {
        "logs": [],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost": 0.0,
        "session_id": session_id,
    }


def log_event(trace: dict, event: str, **details) -> None:
    """Tulis satu baris ke console log."""
    trace["logs"].append({"event": event, **details})


def _messages(system: str, history: list, question: str) -> list:
    messages = [SystemMessage(system)]
    for item in history[-6:]:  # simpan sampai 3 percakapan terakhir (user + assistant)
        messages.append(HumanMessage(item["content"]) if item["role"] == "user" else AIMessage(item["content"]))
    messages.append(HumanMessage(question))
    return messages


def _invoke(model, messages, attempts: int = 2):
    """Retry singkat untuk error sementara (mis. rate limit provider)."""
    for attempt in range(attempts):
        try:
            return model.invoke(messages)
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(3)


def _call_llm(trace: dict, name: str, messages: list, schema=None):
    """Panggil LLM + catat observability (Langfuse), token, dan biaya."""
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



def supervisor(state: State) -> dict:
    system = prompts.get(
        config.PROMPT_SUPERVISOR,
        question=state["question"],
        history="\n".join(f"{m['role']}: {m['content']}" for m in state["history"][-6:]) or "(kosong)",
        context="\n".join(state["context"]) or "(belum ada)",
    )
    result = _call_llm(state["trace"], "supervisor", _messages(system, [], state["question"]), Decision)
    decision = result["parsed"] or Decision(route="answer")
    visited = list(state["visited"])
    # Satu route hanya boleh sekali per pertanyaan supaya agent tidak berputar-putar.
    if decision.route in visited:
        decision.route = "answer"
    if state["steps"] >= MAX_STEPS:
        decision.route = "answer"
    if decision.route != "answer":
        visited.append(decision.route)
    log_event(state["trace"], "route", route=decision.route, detail=decision.reason)
    return {"route": decision.route, "query": decision.query,
            "steps": state["steps"] + 1, "visited": visited}


def retrieve(state: State) -> dict:
    """Ambil film dari vector database (Qdrant) lalu rerank."""
    query = state["query"] or state["question"]
    log_event(state["trace"], "tool", name="search_movies", detail=query)
    movies = json.loads(tools.search_movies.invoke({"query": query}))
    log_event(state["trace"], "tool_result", name="search_movies",
              detail=f"{len(movies)} film · rerank: {vectorstore.last_rerank}")
    return {"context": state["context"] + [f"Hasil pencarian film: {data.to_json(movies)}"]}


def analytics(state: State) -> dict:
    """Jawab pertanyaan angka lewat SQL ke SQLite."""
    question = state["query"] or state["question"]
    log_event(state["trace"], "tool", name="movie_stats", detail=question)
    rows = tools.movie_stats.invoke({"question": question})
    log_event(state["trace"], "tool_result", name="movie_stats", detail=rows[:120])
    return {"context": state["context"] + [f"Hasil statistik: {rows}"]}


def recommend(state: State) -> dict:
    """Rekomendasi berbasis PCA: titik tengah rating user -> k tetangga terdekat."""
    center = data.rating_center(state["ratings"])
    if center is None:
        log_event(state["trace"], "tool_result", name="pca_recommend", detail="belum ada rating user")
        return {"context": state["context"] + ["Rekomendasi PCA: user belum memberi rating."]}
    movies = data.pca_neighbors(center, k=5, exclude=state["ratings"])
    log_event(state["trace"], "tool", name="pca_recommend",
              detail=f"PC1={center[0]:.2f}, PC2={center[1]:.2f} dari {len(state['ratings'])} rating")
    # Teks singkat lebih mudah dipakai LLM dibanding JSON mentah.
    lines = "; ".join(
        f"{m['Series_Title']} ({int(m['year']) if m['year'] else '?'}) [{m['genre']}] rating {m['rating']}: {str(m['overview'])[:120]}"
        for m in movies
    )
    return {"context": state["context"] + [f"Rekomendasi film mirip berbasis PCA untuk user ini: {lines}"]}


def answer(state: State) -> dict:
    """Susun jawaban akhir memakai prompt `imdb-answer-agent`."""
    system = prompts.get(
        config.PROMPT_ANSWER,
        question=state["question"],
        context="\n".join(state["context"]) or "(tidak ada data)",
    )
    result = _call_llm(state["trace"], "answer", _messages(system, state["history"], state["question"]))
    log_event(state["trace"], "final", detail="jawaban dikirim ke user")
    return {"answer": result.content}


def _build_graph():
    graph = StateGraph(State)
    graph.add_node("supervisor", supervisor)
    graph.add_node("retrieve", retrieve)
    graph.add_node("analytics", analytics)
    graph.add_node("recommend", recommend)
    graph.add_node("answer", answer)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda state: state["route"],
        {"retrieve": "retrieve", "analytics": "analytics", "recommend": "recommend", "answer": "answer"},
    )
    for node in ("retrieve", "analytics", "recommend"):
        graph.add_edge(node, "supervisor")
    graph.add_edge("answer", END)
    return graph.compile()


GRAPH = _build_graph()


def run(question: str, history=None, ratings=None, trace=None) -> tuple[str, dict, dict]:
    """Jalankan agent untuk satu pertanyaan. Mengembalikan (jawaban, state, trace)."""
    trace = trace if trace is not None else new_trace()
    state: State = {
        "question": question,
        "history": history or [],
        "ratings": ratings or {},
        "context": [],
        "route": "",
        "query": "",
        "steps": 0,
        "visited": [],
        "answer": "",
        "trace": trace,
    }
    log_event(trace, "user", detail=question)
    try:
        with propagate_attributes(session_id=trace["session_id"], trace_name="imdb-agent", tags=["imdb", "capstone"]):
            result = GRAPH.invoke(state)
        answer = result["answer"]
    except Exception as error:  # jangan bikin app mati kalau provider bermasalah
        log_event(trace, "error", detail=f"{type(error).__name__}: {error}"[:200])
        answer = "Maaf, model sedang bermasalah (rate limit / timeout). Coba lagi sebentar lagi."
        result = {**state, "answer": answer}
    config.langfuse().flush()
    return answer, result, trace
