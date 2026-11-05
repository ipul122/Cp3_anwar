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
MAX_CARDS = 10  # batas film yang dikirim ke UI dari hasil tool (jangan sampai card kebanjiran)

# Guardrail: permintaan di luar topik film dan usaha mengubah instruksi ditolak
# sebelum agent/tool dipanggil, jadi tidak ada token yang terbuang.
JAILBREAK_PATTERNS = (
    "ignore previous", "ignore all previous", "abaikan instruksi", "abaikan semua instruksi",
    "lupakan instruksi", "instruksi sebelumnya", "system prompt", "prompt sistem",
    "kamu sekarang adalah", "you are now", "act as", "berperan sebagai", "developer mode",
    "jailbreak", "mode pengembang",
)
OFF_TOPIC_PATTERNS = (
    "buatkan kode", "buat kode", "tulis kode", "tulis code", "script python", "print hello",
    "program python", "resep", "puisi", "lirik lagu", "terjemahkan", "translate",
    "soal matematika",
)
GUARD_REPLY = (
    "Maaf, saya hanya membantu soal film IMDb: rekomendasi, statistik, dan penjelasan film. "
    "Permintaan di luar itu tidak saya layani."
)


def _guardrail_hit(question: str) -> str | None:
    """Kembalikan pola yang terdeteksi kalau pertanyaan keluar dari topik film."""
    text = question.lower()
    return next((p for p in JAILBREAK_PATTERNS + OFF_TOPIC_PATTERNS if p in text), None)


class Decision(BaseModel):
    """Keputusan supervisor untuk langkah berikutnya."""

    route: Literal["retrieve", "analytics", "recommend", "lookup", "answer"] = Field(
        description="retrieve=pencarian film dari deskripsi, analytics=statistik/SQL, "
        "recommend=rekomendasi dari rating user, lookup=ambil film dari JUDUL yang disebut "
        "user/riwayat (mis. minta link atau menampilkan film), answer=jawab sekarang"
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
    movies: list
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
    log_event(state["trace"], "route", agent="supervisor", route=decision.route, detail=decision.reason)
    return {"route": decision.route, "query": decision.query,
            "steps": state["steps"] + 1, "visited": visited}


def retrieve(state: State) -> dict:
    """Agent retrieve: ambil film dari vector database (Qdrant) lalu rerank."""
    query = state["query"] or state["question"]
    log_event(state["trace"], "tool", agent="retrieve-agent", name="search_movies", detail=query)
    movies = json.loads(tools.search_movies.invoke({"query": query}))
    log_event(state["trace"], "tool_result", agent="retrieve-agent", name="search_movies",
              detail=f"{len(movies)} film · rerank: {vectorstore.last_rerank}")
    return {"context": state["context"] + [f"Hasil pencarian film: {data.for_llm(movies)}"],
            "movies": movies}


def _compact_result(hasil: str, limit: int = 10) -> str:
    """Ringkas hasil SQL supaya konteks LLM tidak boros token."""
    try:
        muatan = json.loads(hasil)
    except (ValueError, TypeError):
        return hasil[:600]
    if not isinstance(muatan, dict) or "rows" not in muatan:
        return hasil[:600]
    baris = muatan["rows"]
    ringkas = {"sql": muatan.get("sql", ""), "rows": baris[:limit]}
    if len(baris) > limit:
        ringkas["catatan"] = f"ditampilkan {limit} dari {len(baris)} baris"
    return json.dumps(ringkas, ensure_ascii=False, default=str)


def _ids_from_result(hasil: str) -> list[int]:
    """Ambil kolom `id` dari hasil SQL, kalau ada (untuk memunculkan card film)."""
    try:
        payload = json.loads(hasil)
    except (ValueError, TypeError):
        return []
    baris = payload.get("rows", []) if isinstance(payload, dict) else payload
    return [row["id"] for row in baris if isinstance(row, dict) and isinstance(row.get("id"), int)]


def analytics(state: State) -> dict:
    """Agent analytics: jawab pertanyaan angka lewat SQL ke SQLite."""
    question = state["query"] or state["question"]
    log_event(state["trace"], "tool", agent="analytics-agent", name="movie_stats", detail=question)
    hasil = tools.movie_stats.invoke({"question": question})
    log_event(state["trace"], "tool_result", agent="analytics-agent", name="movie_stats", detail=hasil[:120])
    hasil_state = {"context": state["context"] + [f"Hasil statistik: {_compact_result(hasil)}"]}
    # kalau hasil SQL berisi daftar film, kirim juga ke UI supaya bisa tampil sebagai card
    movies = data.by_ids(_ids_from_result(hasil)[:MAX_CARDS])
    if movies:
        hasil_state["movies"] = movies
    return hasil_state


def lookup(state: State) -> dict:
    """Agent lookup: ambil film dari JUDUL yang disebut user atau riwayat percakapan."""
    titles = state["query"] or state["question"]
    log_event(state["trace"], "tool", agent="lookup-agent", name="find_movies_by_title",
              detail=titles[:120])
    movies = json.loads(tools.find_movies_by_title.invoke({"titles": titles}))
    log_event(state["trace"], "tool_result", agent="lookup-agent", name="find_movies_by_title",
              detail=f"{len(movies)} film")
    movies = movies[:MAX_CARDS]
    hasil_state = {"context": state["context"] + [f"Detail film yang diminta: {data.for_llm(movies)}"]}
    if movies:
        hasil_state["movies"] = movies
    return hasil_state


def recommend(state: State) -> dict:
    """Agent recommend: rekomendasi PCA dari rating user -> k tetangga terdekat."""
    center = data.rating_center(state["ratings"])
    if center is None:
        log_event(state["trace"], "tool_result", agent="recommend-agent", name="pca_recommend",
                  detail="belum ada rating user")
        return {"context": state["context"] + ["Rekomendasi PCA: user belum memberi rating."]}
    movies = data.pca_neighbors(center, k=5, exclude=state["ratings"])
    log_event(state["trace"], "tool", agent="recommend-agent", name="pca_recommend",
              detail=f"PC1={center[0]:.2f}, PC2={center[1]:.2f} dari {len(state['ratings'])} rating")
    # Teks singkat lebih mudah dipakai LLM dibanding JSON mentah.
    lines = "; ".join(
        f"{m['Series_Title']} ({int(m['year']) if m['year'] else '?'}) [{m['genre']}] rating {m['rating']}: {str(m['overview'])[:120]}"
        for m in movies
    )
    return {"context": state["context"] + [f"Rekomendasi film mirip berbasis PCA untuk user ini: {lines}"],
            "movies": movies}


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
    graph.add_node("lookup", lookup)
    graph.add_node("answer", answer)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda state: state["route"],
        {"retrieve": "retrieve", "analytics": "analytics", "recommend": "recommend",
         "lookup": "lookup", "answer": "answer"},
    )
    for node in ("retrieve", "analytics", "recommend", "lookup"):
        graph.add_edge(node, "supervisor")
    graph.add_edge("answer", END)
    return graph.compile()


GRAPH = _build_graph()


def _rating_note(ratings: dict) -> str:
    """Catatan rating untuk agent.

    Berisi SEMUA film yang dirating user (urut dari paling lama) supaya bot bisa
    menjawab pertanyaan soal selera/profil secara utuh - termasuk film yang dirating
    jauh sebelumnya. Yang dibatasi hanya perhitungan titik selera (RECENT_RATINGS),
    dan itu disebutkan di catatan supaya agent tidak salah menjelaskan.
    """
    if not ratings:
        return "Rating user: belum ada film yang diberi rating."
    movies = data.by_ids(list(ratings))
    baris = "\n".join(
        f"{nomor}. {m['Series_Title']} ({int(m['year']) if m['year'] else '?'}) = {ratings[m['id']]}/10"
        for nomor, m in enumerate(movies, start=1)
    )
    dipakai = min(len(movies), data.RECENT_RATINGS)
    return (f"Rating user - {len(movies)} film, urut dari yang paling lama dirating:\n{baris}\n"
            f"({dipakai} rating terakhir pada daftar di atas yang dipakai menghitung "
            "rekomendasi PCA; sisanya tetap catatan selera user.)")


def run(question: str, history=None, ratings=None, trace=None) -> tuple[str, dict, dict]:
    """Jalankan agent untuk satu pertanyaan. Mengembalikan (jawaban, state, trace)."""
    trace = trace if trace is not None else new_trace()
    state: State = {
        "question": question,
        "history": history or [],
        "ratings": ratings or {},
        "context": [_rating_note(ratings or {})],
        "route": "",
        "query": "",
        "steps": 0,
        "visited": [],
        "movies": [],
        "answer": "",
        "trace": trace,
    }
    log_event(trace, "user", detail=question)
    try:
        with propagate_attributes(session_id=trace["session_id"], trace_name="imdb-agent",
                                  tags=["imdb", "capstone"]):
            blocked = _guardrail_hit(question)
            if blocked:
                # Guardrail: jawab tanpa memanggil agent/tool sama sekali.
                with config.langfuse().start_as_current_observation(
                    name="guardrail", as_type="guardrail", input=question, output=GUARD_REPLY
                ):
                    log_event(trace, "warn", agent="guardrail", detail=f"pola '{blocked}' ditolak")
                log_event(trace, "final", agent="guardrail", detail="dijawab tanpa agent/tool")
                answer = GUARD_REPLY
                result = {**state, "answer": answer}
            else:
                result = GRAPH.invoke(state)
                answer = result["answer"]
    except prompts.PromptMissing as error:
        log_event(trace, "error", agent="langfuse", detail=str(error)[:200])
        answer = f"Prompt '{error.name}' belum ada di Langfuse (label {config.PROMPT_LABEL})."
        result = {**state, "answer": answer}
    except Exception as error:  # jangan bikin app mati kalau provider bermasalah
        log_event(trace, "error", detail=f"{type(error).__name__}: {error}"[:200])
        answer = "Maaf, model sedang bermasalah (rate limit / timeout). Coba lagi sebentar lagi."
        result = {**state, "answer": answer}
    config.langfuse().flush()
    return answer, result, trace
