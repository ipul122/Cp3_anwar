"""Streamlit app: console log (kiri) - chatbot (tengah) - card rekomendasi (kanan).

Console log menampilkan siapa yang dipanggil (agent/tool) beserta token dan biaya
supaya alur agent terpantau. User memberi rating dari card rekomendasi; rekomendasi
berikutnya dihitung dari rating itu memakai kedekatan PCA.
"""

import sys
import uuid
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from imdb_anwar import config, data, workflow  # noqa: E402

st.set_page_config(page_title="IMDb Movie Assistant", page_icon="🎬", layout="wide")

# Tinggi panel dibuat tetap supaya halaman tidak makin panjang saat chat/rating
# bertambah - yang scroll hanya bagian dalam panelnya (kiri, tengah, kanan).
LOG_HEIGHT = 520
CHAT_HEIGHT = 520
CARDS_HEIGHT = 340
RATED_HEIGHT = 160


def setup():
    """Siapkan state sesi: rating user, log agent, chat, dan card rekomendasi."""
    st.session_state.setdefault("ratings", {})
    st.session_state.setdefault("titles", {})
    st.session_state.setdefault("trace", workflow.new_trace(f"streamlit-{uuid.uuid4().hex[:8]}"))
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("cards", data.random_movies(3))


def refresh_cards():
    """Card rekomendasi: acak kalau belum ada rating, PCA kalau sudah ada."""
    ratings = st.session_state.ratings
    if not ratings:
        st.session_state.cards = data.random_movies(3)
    else:
        st.session_state.cards = data.pca_neighbors(data.rating_center(ratings), k=3, exclude=ratings)


def save_rating(movie, score):
    """Simpan rating user, lalu segarkan rekomendasi supaya ikut rating (PCA)."""
    st.session_state.ratings[movie["id"]] = score
    st.session_state.titles[movie["id"]] = movie["Series_Title"]
    workflow.log_event(st.session_state.trace, "rating", agent="user",
                       detail=f"{movie['Series_Title']} = {score}/10")
    refresh_cards()
    st.rerun()


def ask(question):
    """Kirim pertanyaan ke agent (dengan indikator loading) lalu simpan jawabannya."""
    with st.spinner("Agent sedang memproses... (lihat flow-nya di console log)"):
        answer, state, _ = workflow.run(question, st.session_state.chat,
                                       st.session_state.ratings, st.session_state.trace)
    st.session_state.chat.append({"role": "user", "content": question})
    st.session_state.chat.append({"role": "assistant", "content": answer, "context": state["context"]})
    if state.get("movies"):  # film hasil rekomendasi agent langsung bisa dirating
        st.session_state.cards = state["movies"]


def movie_card(movie, prefix):
    """Card rekomendasi + rating 1-10."""
    with st.container(border=True):
        year = int(movie["year"]) if movie["year"] else "?"
        st.markdown(f"**{str(movie['Series_Title']).title()}** ({year})")
        st.caption(f"{movie['genre']} · ⭐ {movie['rating']}")
        st.write(f"{str(movie['overview'])[:160]}…")
        score = st.slider("Rating (1-10)", 1, 10, 7, key=f"slider_{prefix}_{movie['id']}")
        if st.button("Simpan rating", key=f"save_{prefix}_{movie['id']}", use_container_width=True):
            save_rating(movie, score)


def console_line(entry):
    """Satu baris console log: event + siapa yang dipanggil + detailnya."""
    fields = " ".join(f"{k}={v}" for k, v in entry.items() if k not in ("event", "detail"))
    detail = entry.get("detail") or ""
    return f"`{entry['event']}` {fields}  \n{detail}"


def console_panel():
    """Kiri: token, biaya, dan log flow agent/tool."""
    trace = st.session_state.trace
    st.subheader("Token")
    st.metric("Total", f"{trace['prompt_tokens'] + trace['completion_tokens']:,}",
              f"in {trace['prompt_tokens']:,} · out {trace['completion_tokens']:,}",
              delta_color="off")
    st.metric("Biaya (USD)", f"${trace['cost']:.6f}")
    st.caption(f"Log interaktif · sesi {trace['session_id']}")
    with st.container(height=LOG_HEIGHT, border=True):
        for entry in reversed(trace["logs"][-80:]):
            st.markdown(console_line(entry))
    st.caption(f"LLM: {config.LLM_MODEL}  \nRerank: {config.RERANK_MODEL}")


def chat_panel():
    """Tengah: percakapan dengan agent + bukti data dari vector database.

    Pesan chat dibungkus container bertinggi tetap supaya halaman tidak makin
    panjang; yang scroll hanya daftar pesannya (dan otomatis turun ke pesan baru).
    """
    with st.container(height=CHAT_HEIGHT, border=False, autoscroll=True):
        if not st.session_state.chat:
            st.caption("Mulai dengan bertanya, misal: \"rekomendasikan film perang dunia kedua\".")
        for message in st.session_state.chat:
            with st.chat_message(message["role"]):
                st.write(message["content"])
                if message["role"] == "assistant" and message.get("context"):
                    with st.expander("Data dari vector database (Qdrant)"):
                        for item in message["context"]:
                            st.write(item[:600])
    question = st.chat_input("Tanya soal film IMDb...")
    if question:
        ask(question)
        st.rerun()


def card_panel():
    """Kanan: card rekomendasi yang bisa dirating + daftar film yang sudah dirating."""
    ratings = st.session_state.ratings
    st.subheader("Card rekomendasi")
    st.caption("acak dulu (belum ada rating)" if not ratings
               else f"mengikuti {len(ratings)} rating kamu lewat PCA")
    with st.container(height=CARDS_HEIGHT, border=False):
        for movie in st.session_state.cards:
            movie_card(movie, "card")
    if st.button("Segarkan dari PCA", use_container_width=True):
        refresh_cards()
        st.rerun()

    st.subheader("Daftar film yang dirating user 1-10")
    with st.container(height=RATED_HEIGHT, border=False):
        if not ratings:
            st.caption("Belum ada. Beri rating dari card di atas atau dari rekomendasi chatbot.")
        for movie_id, score in ratings.items():
            st.write(f"**{score}/10** · {st.session_state.titles.get(movie_id, movie_id)}")
    if ratings and st.button("Hapus semua rating", use_container_width=True):
        st.session_state.ratings = {}
        st.session_state.titles = {}
        refresh_cards()
        st.rerun()


def main():
    setup()
    left, middle, right = st.columns([1, 2.2, 1.3], gap="large")
    with left:
        console_panel()
    with middle:
        st.subheader("Chatbot")
        chat_panel()
    with right:
        card_panel()


main()

