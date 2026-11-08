import sys
import uuid
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from imdb_anwar import config, data, workflow  # noqa: E402

st.set_page_config(page_title="IMDb Movie Assistant", page_icon="🎬", layout="wide")

# Tinggi panel dibuat tetap supaya halaman tidak makin panjang saat chat/rating
# bertambah - yang scroll hanya bagian dalam panelnya.
K_RECO = 5  # jumlah card rekomendasi
K_RANDOM = 3  # jumlah card acak
LOG_HEIGHT = 1000
CHAT_HEIGHT = 570
CARDS_HEIGHT = 700
RANDOM_HEIGHT = 500
PCA_HEIGHT = 400
RATED_HEIGHT = 150

# Warna badge di console log supaya alurnya mudah dibaca:
# user biru, supervisor violet, tool oranye, hasil tool abu-abu, jawaban hijau,
# guardrail/error merah.
LOG_COLORS = {
    "user": "blue",
    "rating": "blue",
    "route": "violet",
    "llm": "green",
    "tool": "orange",
    "tool_result": "gray",
    "final": "green",
    "warn": "red",
    "error": "red",
}


def log_color(entry) -> str:
    """Warna badge; panggilan LLM milik supervisor dibedakan dari answer."""
    if entry["event"] == "llm" and entry.get("name") == "supervisor":
        return "violet"
    return LOG_COLORS.get(entry["event"], "gray")


ASSETS_DIR = Path(__file__).resolve().parent / "data"
BANNERS = {
    "jailbreak": ASSETS_DIR / "jailbreak.jpg",
    "limit": ASSETS_DIR / "limit_token.jpg",  
}


def show_banner(kind: str, caption: str = "") -> None:
    """Tampilkan gambar peringatan di dalam chat."""
    path = BANNERS.get(kind)
    if path and path.exists():
        st.image(str(path), width="stretch")
    else:
        st.error(f"Gambar '{kind}' tidak ditemukan di {path}")
    if caption:
        st.caption(caption)


def limit_reached() -> bool:
    """True kalau biaya sesi sudah melewati config.LIMIT_USD."""
    return st.session_state.trace["cost"] >= config.LIMIT_USD


@st.cache_data(show_spinner=False, ttl=86400)
def poster_bytes(url: str) -> bytes | None:
    """Ambil gambar poster sekali per URL (hasilnya di-cache). None kalau URL mati."""
    try:
        response = httpx.get(url, timeout=15, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return response.content
    except Exception:
        return None


def poster_url(movie) -> str | None:
    """Poster ukuran 300px. Poster_Link di database cuma 67px."""
    link = str(movie.get("Poster_Link") or "")
    return link.split("._V1")[0] + "._V1_SX300.jpg" if link.startswith("http") else None


def show_poster(movie, width: int = 104):
    """Poster yang bisa diklik langsung ke halaman IMDb film itu.

    Gambar diambil sekali per URL (di-cache) untuk memastikan URL-nya hidup;
    sekitar 1 dari 6 URL di dataset asli sudah mati, jadi perlu dicek dulu.
    """
    url = poster_url(movie)
    if url and poster_bytes(url):
        st.markdown(
            f'<a href="{data.imdb_url(movie)}" target="_blank">'
            f'<img src="{url}" width="{width}" alt="poster"></a>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("🎬 poster tidak tersedia")


def setup():
    """Siapkan state sesi: rating user, log agent, chat, dan card rekomendasi."""
    st.session_state.setdefault("ratings", {})
    st.session_state.setdefault("titles", {})
    st.session_state.setdefault("trace", workflow.new_trace(f"streamlit-{uuid.uuid4().hex[:8]}"))
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("cards", data.random_movies(K_RECO))
    st.session_state.setdefault("card_source", "acak")
    st.session_state.setdefault("card_query", "")
    if "random_cards" not in st.session_state:  # card acak tidak boleh kembar dengan card rekomendasi
        refresh_random()


def _unrated(movies) -> list[dict]:
    """Buang film yang sudah dirating user."""
    ratings = st.session_state.ratings
    return [movie for movie in movies if movie["id"] not in ratings]


def current_taste():
    """(pusat selera, jangkauan, rekomendasi) dari rating user. None kalau belum ada rating."""
    center = data.rating_center(st.session_state.ratings)
    if center is None:
        return None, None, []
    recommendations = (st.session_state.cards if st.session_state.card_source != "acak"
                       else data.pca_neighbors(center, k=K_RECO, exclude=st.session_state.ratings))
    radius = max(float(np.hypot(m["PC1"] - center[0], m["PC2"] - center[1])) for m in recommendations)
    return center, radius, recommendations


def refresh_random():
    """Card acak untuk eksplorasi: film yang belum dirating, di luar area rekomendasi."""
    exclude = set(st.session_state.ratings) | {m["id"] for m in st.session_state.cards}
    st.session_state.random_cards = data.random_movies(K_RANDOM, exclude=exclude)


def refresh_cards():
    """Card rekomendasi: acak kalau belum ada rating, PCA kalau sudah ada."""
    ratings = st.session_state.ratings
    if not ratings:
        st.session_state.cards = data.random_movies(K_RECO)
        st.session_state.card_source = "acak"
    else:
        st.session_state.cards = data.pca_neighbors(data.rating_center(ratings), k=K_RECO, exclude=ratings)
        st.session_state.card_source = "pca"
    st.session_state.card_query = ""


def save_rating(movie, score):
    """Simpan rating user (paling baru di urutan terakhir), lalu segarkan rekomendasi."""
    st.session_state.ratings.pop(movie["id"], None)  # rating ulang -> pindah ke terbaru
    st.session_state.ratings[movie["id"]] = score
    st.session_state.titles[movie["id"]] = movie["Series_Title"]
    workflow.log_event(st.session_state.trace, "rating", agent="user",
                       detail=f"{movie['Series_Title']} = {score}/10")
    refresh_cards()
    if len(_unrated(st.session_state.random_cards)) < K_RANDOM:  # isi ulang card acak
        refresh_random()
    st.rerun()


def ask(question):
    """Kirim pertanyaan ke agent (dengan indikator loading) lalu simpan jawabannya."""
    if limit_reached():  # sudah lewat batas biaya sesi
        return
    awal_log = len(st.session_state.trace["logs"])
    with st.spinner("Agent sedang memproses... (lihat flow-nya di console log)"):
        answer, state, _ = workflow.run(question, st.session_state.chat,
                                        st.session_state.ratings, st.session_state.trace)
    # tool apa saja yang dipakai turn ini -> untuk label bukti di chat
    sumber = sorted({e.get("name") for e in st.session_state.trace["logs"][awal_log:]
                     if e["event"] == "tool" and e.get("name")})
    st.session_state.chat.append({"role": "user", "content": question})
    st.session_state.chat.append({"role": "assistant", "content": answer,
                                  "context": state["context"],
                                  "sources": sumber,
                                  "movies": (state.get("movies") or [])[:3],
                                  "blocked": state.get("blocked", "")})
    if state.get("movies"):  # film hasil rekomendasi agent langsung bisa dirating
        st.session_state.cards = state["movies"]
        st.session_state.card_source = "chat"
        st.session_state.card_query = question


def movie_card(movie, prefix):
    """Card rekomendasi (poster + info film) dengan rating 1-10."""
    with st.container(border=True):
        poster, info = st.columns([1, 2.2], gap="small")
        with poster:
            show_poster(movie, width=104)
        with info:
            year = int(movie["year"]) if movie["year"] else "?"
            st.markdown(f"**[{str(movie['Series_Title']).title()}]({data.imdb_url(movie)})** ({year})")
            st.caption(f"{movie['genre']} · ⭐ {movie['rating']}")
            st.write(f"{str(movie['overview'])[:110]}…")
        score = st.slider("Rating (1-10)", 1, 10, 7, key=f"slider_{prefix}_{movie['id']}")
        if st.button("Simpan rating", key=f"save_{prefix}_{movie['id']}", width="stretch"):
            save_rating(movie, score)


def console_line(entry):
    """Satu baris console log dengan warna sesuai jenis pemanggilan."""
    fields = " ".join(f"{k}={v}" for k, v in entry.items() if k not in ("event", "detail"))
    head = f":{log_color(entry)}[**{entry['event']}**] {fields}".rstrip()
    detail = entry.get("detail") or ""
    return f"{head}  \n{detail}" if detail else head


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


def chat_movies(movies, position):
    """Poster + rating untuk film yang direkomendasikan di jawaban chatbot."""
    ratings = st.session_state.ratings
    columns = st.columns(len(movies))
    for index, (column, movie) in enumerate(zip(columns, movies)):
        with column:
            show_poster(movie, width=84)
            st.markdown(f"[{str(movie['Series_Title']).title()}]({data.imdb_url(movie)})")
            if movie["id"] in ratings:
                st.caption(f"✓ dirating {ratings[movie['id']]}/10")
                continue
            score = st.selectbox("rating", range(1, 11), index=6, key=f"chat_{position}_{index}_{movie['id']}",
                                 label_visibility="collapsed")
            if st.button("Simpan", key=f"chatsave_{position}_{index}_{movie['id']}", width="stretch"):
                save_rating(movie, score)


def chat_panel():
    """Tengah: percakapan dengan agent + bukti data dari vector database.

    Pesan chat dibungkus container bertinggi tetap supaya halaman tidak makin
    panjang; yang scroll hanya daftar pesannya (dan otomatis turun ke pesan baru).
    """
    with st.container(height=CHAT_HEIGHT, border=False, autoscroll=True):
        if not st.session_state.chat:
            st.caption("Mulai dengan bertanya, misal: \"rekomendasikan film perang dunia kedua\".")
        for position, message in enumerate(st.session_state.chat):
            with st.chat_message(message["role"]):
                st.write(message["content"])
                if message["role"] == "assistant" and message.get("movies"):
                    # film di jawaban chatbot bisa langsung dirating
                    chat_movies(message["movies"], position)
                if message["role"] == "assistant" and message.get("context"):
                    sumber = message.get("sources") or []
                    if "search_movies" in sumber:
                        label = "Data dari vector database (Qdrant)"
                    elif sumber:
                        label = f"Konteks tool: {', '.join(sumber)}"
                    else:
                        label = "Konteks percakapan (tanpa tool)"
                    with st.expander(label):
                        for item in message["context"]:
                            st.write(item[:600])

        # Banner gambar ditaruh di AKHIR percakapan (bukan di awal)
        terakhir = st.session_state.chat[-1] if st.session_state.chat else None
        if limit_reached():
            show_banner("limit", f"Batas biaya sesi (${config.LIMIT_USD:.4f}) sudah tercapai. "
                                 "Chatbot berhenti dulu - refresh halaman untuk memulai sesi baru "
                                 "(rating film tetap bisa diberikan).")
        elif terakhir and terakhir.get("blocked"):
            show_banner("jailbreak", "Percobaan jailbreak terdeteksi - permintaan ditolak.")

    question = st.chat_input("Tanya soal film IMDb...", disabled=limit_reached())
    if question:
        ask(question)
        st.rerun()


def card_panel():
    """Kanan atas: card rekomendasi (PCA/chatbot) + card acak untuk eksplorasi."""
    ratings = st.session_state.ratings
    source = st.session_state.card_source

    st.subheader("Rekomendasi")
    if source == "chat":
        st.caption(f"dari jawaban chatbot · {st.session_state.card_query}")
    elif source == "pca":
        dipakai = min(len(ratings), data.RECENT_RATINGS)
        ekstra = f" dari {len(ratings)}" if len(ratings) > data.RECENT_RATINGS else ""
        st.caption(f"{K_RECO} film terdekat dari {dipakai} rating terbaru{ekstra} (PCA)")
    else:
        st.caption(f"{K_RECO} film acak (belum ada rating user)")
    with st.container(height=CARDS_HEIGHT, border=False):
        for movie in st.session_state.cards:
            movie_card(movie, "reco")

    # Tombol ini baru berguna kalau card sekarang berasal dari chatbot:
    # sekali klik untuk kembali ke rekomendasi hasil PCA dari rating user.
    if source == "chat":
        label = f"Pakai rekomendasi PCA ({len(ratings)} rating)" if ratings else "Segarkan card acak"
        if st.button(label, width="stretch"):
            refresh_cards()
            st.rerun()

    st.subheader("Mungkin anda suka")
    st.caption("film yang belum kamu rating (untuk eksplorasi)")
    fresh = _unrated(st.session_state.random_cards)
    with st.container(height=RANDOM_HEIGHT, border=False):
        if not fresh:
            st.caption("Semua card acak sudah dirating. Klik tombol Acak lagi.")
        for movie in fresh:
            movie_card(movie, "random")
    if st.button("Acak lagi", width="stretch"):
        refresh_random()
        st.rerun()


def _ring(center, radius, label):
    """Titik-titik lingkaran (untuk menggambar jangkauan/zona di scatter)."""
    angle = np.linspace(0, 2 * np.pi, 90)
    return pd.DataFrame({
        "PC1": center[0] + radius * np.cos(angle),
        "PC2": center[1] + radius * np.sin(angle),
        "Series_Title": label,
        "kelompok": label,
    })


def pca_panel():
    """Kiri bawah: sebaran film di PCA + titik selera + jangkauan & zona eksplorasi."""
    ratings = st.session_state.ratings
    frame = pd.DataFrame(data.pca_points())
    frame["kelompok"] = "semua film"
    frame.loc[frame["id"].isin(ratings), "kelompok"] = "film yang kamu rating"
    caption = (f"{len(frame)} film di ruang PCA 2D. Beri rating supaya titik selera muncul: "
               "film yang disukai (>=6) menarik titik, film yang tidak disukai (<=5) menolaknya.")

    center, radius, recommendations = current_taste()
    if center:
        marks = [{"id": -1, "Series_Title": "selera kamu", "PC1": center[0], "PC2": center[1],
                  "kelompok": "selera kamu"}]
        for movie in recommendations:
            marks.append({"id": movie["id"], "Series_Title": movie["Series_Title"],
                          "rating": movie["rating"], "PC1": movie["PC1"], "PC2": movie["PC2"],
                          "kelompok": "rekomendasi"})
        for movie in _unrated(st.session_state.random_cards):
            marks.append({"id": movie["id"], "Series_Title": movie["Series_Title"],
                          "rating": movie["rating"], "PC1": movie["PC1"], "PC2": movie["PC2"],
                          "kelompok": "card acak"})
        frame = pd.concat([
            frame,
            pd.DataFrame(marks),
            _ring(center, radius, "jangkauan rekomendasi"),
        ], ignore_index=True)
        caption = (f"titik selera kamu: PC1={center[0]:.2f}, PC2={center[1]:.2f} · "
                   f"jangkauan {len(recommendations)} rekomendasi = {radius:.3f} · "
                   f"dihitung dari {min(len(ratings), data.RECENT_RATINGS)} rating terbaru · "
                   "card acak diambil dari seluruh katalog di luar area ini")

    st.subheader("Visualisasi PCA")
    st.caption("Hover pada titik untuk melihat judul filmnya.")
    st.vega_lite_chart(
        frame,
        {
            "mark": {"type": "circle", "size": 45, "opacity": 0.85},
            "encoding": {
                "x": {"field": "PC1", "type": "quantitative"},
                "y": {"field": "PC2", "type": "quantitative"},
                "color": {"field": "kelompok", "type": "nominal"},
                "tooltip": [
                    {"field": "Series_Title", "type": "nominal", "title": "Film"},
                    {"field": "rating", "type": "quantitative", "title": "Rating IMDb"},
                    {"field": "PC1", "type": "quantitative", "title": "PC1", "format": ".3f"},
                    {"field": "PC2", "type": "quantitative", "title": "PC2", "format": ".3f"},
                    {"field": "kelompok", "type": "nominal", "title": "Kelompok"},
                ],
            },
        },
        height=PCA_HEIGHT,
        width="stretch",
    )
    st.caption(caption)


def rated_panel():
    """Kanan bawah: daftar film yang sudah dirating user."""
    ratings = st.session_state.ratings
    st.subheader("Daftar film yang dirating user 1-10")
    with st.container(height=RATED_HEIGHT, border=False):
        if not ratings:
            st.caption("Belum ada. Beri rating dari card rekomendasi, card acak, atau jawaban chatbot.")
        for movie_id, score in ratings.items():
            st.caption(f"{score}/10 · {st.session_state.titles.get(movie_id, movie_id)}")
    if ratings and st.button("Hapus semua rating", width="stretch"):
        st.session_state.ratings = {}
        st.session_state.titles = {}
        refresh_cards()
        st.rerun()


def main():
    setup()
    top_left, top_middle, top_right = st.columns([1, 2.2, 1.2], gap="large")
    with top_left:
        console_panel()
    with top_middle:
        st.subheader("Chatbot")
        chat_panel()
    with top_right:
        card_panel()

    bottom_left, bottom_right = st.columns([2.2, 1.2], gap="large")
    with bottom_left:
        pca_panel()
    with bottom_right:
        rated_panel()


main()

