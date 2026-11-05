"""Streamlit app: rekomendasi film IMDb + chat agent, dengan console log di kiri.

Layout kiri = console log interaktif (agent, tool call, token, biaya).
Layout kanan = rekomendasi film berbasis rating + PCA, dan chat dengan agent.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from imdb_anwar import config, data, workflow  # noqa: E402

st.set_page_config(page_title="IMDb Movie Assistant", page_icon="🎬", layout="wide")


def setup():
    """Siapkan state awal: rating user, log agent, chat, dan film acak."""
    st.session_state.setdefault("ratings", {})
    st.session_state.setdefault("trace", workflow.new_trace())
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("seed", data.random_movies(3))


def rate(movie, score):
    """Simpan rating user dan refresh halaman."""
    st.session_state.ratings[movie["id"]] = score
    workflow.log_event(st.session_state.trace, "rating", detail=f"{movie['Series_Title']}: {score}/10")
    st.rerun()


def ask(question):
    """Kirim pertanyaan ke agent, simpan jawaban + konteks RAG-nya."""
    answer, state, _ = workflow.run(question, st.session_state.chat, st.session_state.ratings, st.session_state.trace)
    st.session_state.chat.append({"role": "user", "content": question})
    st.session_state.chat.append({"role": "assistant", "content": answer, "context": state["context"]})


def movie_card(movie, prefix):
    """Kartu film + slider rating 1-10."""
    with st.container(border=True):
        year = int(movie["year"]) if movie["year"] else "?"
        st.markdown(f"**{str(movie['Series_Title']).title()}** ({year})")
        st.caption(f"{movie['genre']} · ⭐ {movie['rating']} · {movie['director']}")
        st.write(f"{str(movie['overview'])[:220]}…")
        slider, button = st.columns([3, 1])
        score = slider.slider("Rating kamu (1-10)", 1, 10, 7, key=f"slider_{prefix}_{movie['id']}")
        if button.button("Beri rating", key=f"btn_{prefix}_{movie['id']}", use_container_width=True):
            rate(movie, score)


def console_line(entry):
    """Satu baris console log."""
    detail = entry.get("detail") or " ".join(f"{k}={v}" for k, v in entry.items() if k != "event")
    return f"`{entry['event']:>11}` {str(detail)[:160]}"


def render_console():
    """Panel kiri: token, biaya, dan log interaksi agent + tool call."""
    trace = st.session_state.trace
    st.subheader("Console log")
    st.metric(
        "Token",
        f"{trace['prompt_tokens'] + trace['completion_tokens']:,}",
        f"in {trace['prompt_tokens']:,} · out {trace['completion_tokens']:,}",
        delta_color="off",
    )
    st.metric("Biaya (USD)", f"${trace['cost']:.6f}")
    st.caption("Log interaktif")
    with st.container(height=480, border=True):
        for entry in reversed(trace["logs"][-80:]):
            st.markdown(console_line(entry))


def recommendation_tab():
    """Rekomendasi awal acak, lalu berbasis PCA setelah user memberi rating."""
    ratings = st.session_state.ratings
    if not ratings:
        st.subheader("Rekomendasi awal (acak)")
        st.caption(
            "Kamu belum memberi rating, jadi film di bawah dipilih acak. "
            "Beri rating 1-10 pada film yang kamu kenal, "
            "rekomendasi berikutnya dihitung dari kedekatan PCA."
        )
        for movie in st.session_state.seed:
            movie_card(movie, "seed")
    else:
        center = data.rating_center(ratings)
        recommendations = data.pca_neighbors(center, k=3, exclude=ratings)
        st.subheader("Rekomendasi berbasis PCA")
        st.caption(
            f"Dihitung dari {len(ratings)} rating kamu "
            f"(titik tengah PC1={center[0]:.2f}, PC2={center[1]:.2f}, dibobot nilai rating)."
        )
        for movie in recommendations:
            movie_card(movie, "reco")
        if st.button("Kenapa film-film ini cocok untuk saya?"):
            ask("Kenapa film-film rekomendasi ini cocok untuk saya?")
            st.rerun()

    with st.expander(f"Rating kamu ({len(ratings)} film)"):
        for movie_id, score in ratings.items():
            st.write(f"id {movie_id} → {score}/10")
        if st.button("Hapus semua rating"):
            st.session_state.ratings = {}
            st.session_state.seed = data.random_movies(3)
            st.rerun()


def chat_tab():
    """Chat dengan agent multi-agent + bukti jawaban dari vector database."""
    for message in st.session_state.chat:
        with st.chat_message(message["role"]):
            st.write(message["content"])
            if message.get("context"):
                with st.expander("Data dari vector database (Qdrant)"):
                    for item in message["context"]:
                        st.write(item[:600])
    question = st.chat_input("Tanya apa saja soal film IMDb...")
    if question:
        ask(question)
        st.rerun()


def main():
    setup()
    left, right = st.columns([1, 2.2], gap="large")
    with left:
        render_console()
    with right:
        st.title("🎬 IMDb Movie Assistant")
        st.caption(f"LLM: {config.LLM_MODEL} · embedding: {config.EMBEDDING_MODEL} · reranker: {config.RERANK_MODEL}")
        tab_recommendation, tab_chat = st.tabs(["Rekomendasi film", "Chat dengan agent"])
        with tab_recommendation:
            recommendation_tab()
        with tab_chat:
            chat_tab()


main()
