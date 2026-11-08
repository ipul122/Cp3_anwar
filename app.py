"""Aplikasi Streamlit: console log (kiri) - chatbot (tengah) - kartu rekomendasi (kanan).

Peta file ini:
  1. setting tampilan           4. panel (console, chat, kartu, PCA, daftar rating)
  2. state sesi, umur & rating  5. main(): gerbang umur + susunan 5 panel
  3. bertanya ke agent

Umur: user wajib mengisinya dulu di sidebar. Aturannya ada di src/imdb_anwar/age_rules.py.

Komponen gambar (poster, kartu, grafik) ada di src/imdb_anwar/ui.py.
Jalankan:  streamlit run app.py
"""

import math
import sys
import uuid
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from imdb_anwar import age_rules, config, database, pca, tracing, ui, workflow  # noqa: E402

st.set_page_config(page_title="IMDb Movie Assistant", page_icon="🎬", layout="wide")

# --- 1. Setting tampilan -----------------------------------------------------
# Tinggi panel dibuat tetap: yang scroll hanya isi panelnya, bukan seluruh halaman.
K_RECO = 5  # jumlah kartu rekomendasi
K_RANDOM = 3  # jumlah kartu acak
LOG_HEIGHT, CHAT_HEIGHT, CARDS_HEIGHT = 1000, 570, 700
RANDOM_HEIGHT, PCA_HEIGHT, RATED_HEIGHT = 500, 400, 150


# --- 2. State sesi & rating --------------------------------------------------
# st.session_state = "memori" satu sesi browser. Refresh halaman = sesi baru.
# Sumber kartu rekomendasi (card_source): "acak" (belum ada rating),
# "pca" (dari rating user), atau "chat" (film yang baru disebut chatbot).

def setup() -> None:
    """Isi state awal sesi (hanya sekali per sesi)."""
    state = st.session_state
    state.setdefault("ratings", {})  # {id_film: nilai}; urutan = urutan pemberian rating
    state.setdefault("titles", {})  # {id_film: judul}, untuk daftar rating
    state.setdefault("trace", tracing.new_trace(f"streamlit-{uuid.uuid4().hex[:8]}"))
    state.setdefault("chat", [])
    state.setdefault("cards", [])  # diisi setelah umur diketahui (apply_age)
    state.setdefault("random_cards", [])
    state.setdefault("card_source", "acak")
    state.setdefault("card_query", "")


def current_age() -> int | None:
    """Umur yang diisi user di sidebar (None = belum diisi). Satu-satunya sumber umur."""
    age = st.session_state.get("age_input")
    return int(age) if age is not None else None


def apply_age() -> None:
    """Dipanggil saat umur berubah: kosongkan chat dan buang rating film yang kini dibatasi
    (keduanya dikirim ke LLM sebagai konteks), lalu muat ulang kartu sesuai umur baru."""
    st.session_state.chat = []
    for movie in database.by_ids(list(st.session_state.ratings)):
        if not age_rules.allowed(movie, current_age()):
            st.session_state.ratings.pop(movie["id"], None)
            st.session_state.titles.pop(movie["id"], None)
    refresh_cards()
    refresh_random()


def limit_reached() -> bool:
    """True kalau biaya sesi sudah melewati batas config.LIMIT_USD."""
    return st.session_state.trace["cost"] >= config.LIMIT_USD


def unrated(movies: list[dict]) -> list[dict]:
    """Buang film yang sudah dirating user."""
    return [m for m in movies if m["id"] not in st.session_state.ratings]


def refresh_random() -> None:
    """Kartu acak untuk eksplorasi: belum dirating dan tidak kembar dengan kartu rekomendasi."""
    exclude = set(st.session_state.ratings) | {m["id"] for m in st.session_state.cards}
    st.session_state.random_cards = database.random_movies(K_RANDOM, exclude=exclude, age=current_age())


def refresh_cards() -> None:
    """Kartu rekomendasi: acak kalau belum ada rating, tetangga PCA kalau sudah ada."""
    ratings = st.session_state.ratings
    if ratings:
        st.session_state.cards = pca.pca_neighbors(pca.rating_center(ratings), k=K_RECO, exclude=ratings, age=current_age())
        st.session_state.card_source = "pca"
    else:
        st.session_state.cards = database.random_movies(K_RECO, age=current_age())
        st.session_state.card_source = "acak"
    st.session_state.card_query = ""


def save_rating(movie: dict, score: int) -> None:
    """Simpan rating (yang terbaru di urutan paling belakang), lalu segarkan rekomendasi."""
    ratings = st.session_state.ratings
    ratings.pop(movie["id"], None)  # dirating ulang -> pindah ke urutan terbaru
    ratings[movie["id"]] = score
    st.session_state.titles[movie["id"]] = movie["Series_Title"]
    tracing.log_event(st.session_state.trace, "rating", agent="user", detail=f"{movie['Series_Title']} = {score}/10")
    refresh_cards()
    if len(unrated(st.session_state.random_cards)) < K_RANDOM:
        refresh_random()
    st.rerun()


def current_taste():
    """(titik selera, jangkauan, rekomendasi) dari rating user; (None, None, []) kalau belum ada."""
    center = pca.rating_center(st.session_state.ratings)
    if center is None:
        return None, None, []
    if st.session_state.card_source == "acak":
        recommendations = pca.pca_neighbors(center, k=K_RECO, exclude=st.session_state.ratings, age=current_age())
    else:
        recommendations = st.session_state.cards
    radius = max(math.hypot(m["PC1"] - center[0], m["PC2"] - center[1]) for m in recommendations)
    return center, radius, recommendations


# --- 3. Bertanya ke agent ------------------------------------------------------

def ask(question: str) -> None:
    """Kirim pertanyaan ke agent lalu simpan jawabannya (beserta film dan buktinya) di chat."""
    if limit_reached() or current_age() is None:
        return
    first_log = len(st.session_state.trace["logs"])
    with st.spinner("Agent sedang memproses... (lihat flow-nya di console log)"):
        answer, final_state, _ = workflow.run(question, st.session_state.chat, st.session_state.ratings,
                                              st.session_state.trace, age=current_age())
    # Tool yang dipakai giliran ini -> label bukti di bawah jawaban.
    sources = sorted({e["name"] for e in st.session_state.trace["logs"][first_log:]
                      if e["event"] == "tool" and e.get("name")})
    st.session_state.chat.append({"role": "user", "content": question})
    st.session_state.chat.append({"role": "assistant", "content": answer,
                                  "context": final_state["context"], "sources": sources,
                                  "movies": (final_state.get("movies") or [])[:3],
                                  "blocked": final_state.get("blocked", "")})
    if final_state.get("movies"):  # film dari agent langsung muncul sebagai kartu yang bisa dirating
        st.session_state.cards = final_state["movies"]
        st.session_state.card_source = "chat"
        st.session_state.card_query = question


# --- 4. Panel -------------------------------------------------------------------

def console_panel() -> None:
    """Kiri: token, biaya, dan log siapa memanggil apa."""
    trace = st.session_state.trace
    st.subheader("Token")
    st.metric("Total", f"{trace['prompt_tokens'] + trace['completion_tokens']:,}",
              f"in {trace['prompt_tokens']:,} · out {trace['completion_tokens']:,}", delta_color="off")
    st.metric("Biaya (USD)", f"${trace['cost']:.6f}")
    st.caption(f"Log interaktif · sesi {trace['session_id']}")
    with st.container(height=LOG_HEIGHT, border=True):
        for entry in reversed(trace["logs"][-80:]):
            st.markdown(ui.console_line(entry))
    st.caption(f"LLM: {config.LLM_MODEL}  \nRerank: {config.RERANK_MODEL}")


def chat_panel() -> None:
    """Tengah: percakapan + bukti data. Banner peringatan muncul di akhir percakapan."""
    chat = st.session_state.chat
    with st.container(height=CHAT_HEIGHT, border=False, autoscroll=True):
        if not chat:
            st.caption("Mulai dengan bertanya, misal: \"rekomendasikan film perang dunia kedua\".")
        for position, message in enumerate(chat):
            with st.chat_message(message["role"]):
                st.write(message["content"])
                if message["role"] != "assistant":
                    continue
                if message.get("movies"):
                    ui.chat_movies(message["movies"], position, st.session_state.ratings, save_rating)
                if message.get("context"):
                    with st.expander(ui.source_label(message.get("sources") or [])):
                        for item in message["context"]:
                            st.write(item[:600])

        if limit_reached():
            ui.show_banner("limit", f"Batas biaya sesi (${config.LIMIT_USD:.4f}) sudah tercapai. "
                                    "Chatbot berhenti dulu - refresh halaman untuk memulai sesi baru "
                                    "(rating film tetap bisa diberikan).")
        elif chat and chat[-1].get("blocked"):
            ui.show_banner("jailbreak", "Percobaan jailbreak terdeteksi - permintaan ditolak.")

    question = st.chat_input("Tanya soal film IMDb...", disabled=limit_reached())
    if question:
        ask(question)
        st.rerun()


def card_panel() -> None:
    """Kanan atas: kartu rekomendasi (acak / PCA / dari chatbot) dan kartu acak untuk eksplorasi."""
    ratings = st.session_state.ratings
    source = st.session_state.card_source

    st.subheader("Rekomendasi")
    if source == "chat":
        st.caption(f"dari jawaban chatbot · {st.session_state.card_query}")
    elif source == "pca":
        used = min(len(ratings), pca.RECENT_RATINGS)
        extra = f" dari {len(ratings)}" if len(ratings) > pca.RECENT_RATINGS else ""
        st.caption(f"{K_RECO} film terdekat dari {used} rating terbaru{extra} (PCA)")
    else:
        st.caption(f"{K_RECO} film acak (belum ada rating user)")
    with st.container(height=CARDS_HEIGHT, border=False):
        for movie in st.session_state.cards:
            ui.movie_card(movie, "reco", save_rating)

    if source == "chat":  # kembali ke rekomendasi PCA dari rating user
        label = f"Pakai rekomendasi PCA ({len(ratings)} rating)" if ratings else "Segarkan card acak"
        if st.button(label, width="stretch"):
            refresh_cards()
            st.rerun()

    st.subheader("Mungkin anda suka")
    st.caption("film yang belum kamu rating (untuk eksplorasi)")
    fresh = unrated(st.session_state.random_cards)
    with st.container(height=RANDOM_HEIGHT, border=False):
        if not fresh:
            st.caption("Semua card acak sudah dirating. Klik tombol Acak lagi.")
        for movie in fresh:
            ui.movie_card(movie, "random", save_rating)
    if st.button("Acak lagi", width="stretch"):
        refresh_random()
        st.rerun()


def pca_panel() -> None:
    """Kiri bawah: peta PCA semua film + titik selera + jangkauan rekomendasi."""
    ratings = st.session_state.ratings
    center, radius, recommendations = current_taste()
    st.subheader("Visualisasi PCA")
    st.caption("Hover pada titik untuk melihat judul filmnya.")
    ui.pca_scatter(ratings, center, radius, recommendations, unrated(st.session_state.random_cards), PCA_HEIGHT,
                   age=current_age())
    if center:
        st.caption(f"titik selera kamu: PC1={center[0]:.2f}, PC2={center[1]:.2f} · "
                   f"jangkauan {len(recommendations)} rekomendasi = {radius:.3f} · "
                   f"dihitung dari {min(len(ratings), pca.RECENT_RATINGS)} rating terbaru · "
                   "card acak diambil dari seluruh katalog di luar area ini")
    else:
        st.caption("Beri rating supaya titik selera muncul: film yang disukai (>=6) menarik titik, "
                   "film yang tidak disukai (<=5) menolaknya.")


def rated_panel() -> None:
    """Kanan bawah: daftar film yang sudah dirating."""
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


# --- 5. Gerbang umur + susunan halaman ----------------------------------------------

def age_panel() -> None:
    """Sidebar: input umur, jumlah film yang boleh tampil, dan tabel aturannya."""
    with st.sidebar:
        st.subheader("Umur kamu")
        st.number_input("Isi umur (3-100)", min_value=age_rules.MIN_USER_AGE, max_value=age_rules.MAX_USER_AGE,
                        value=None, step=1, key="age_input", on_change=apply_age,
                        help="Menentukan film yang boleh tampil. Mengganti umur mengosongkan riwayat chat.")
        age = current_age()
        if age is not None:
            st.caption(f"Katalog untuk umur {age}: **{database.visible_count(age)}** dari "
                       f"{database.visible_count(None)} film.")
        with st.expander("Aturan batas usia"):
            st.markdown(age_rules.rules_markdown())
            st.caption("Umur diisi sendiri dan tidak diverifikasi: ini filter kenyamanan, bukan pengamanan.")


def main() -> None:
    setup()
    age_panel()
    if current_age() is None:  # gerbang: tanpa umur, tidak ada film yang ditampilkan
        st.title("🎬 IMDb Movie Assistant")
        st.info("Isi **umur kamu** di sidebar kiri dulu. Umur dipakai untuk menyaring film sesuai batas usia.")
        return
    left, middle, right = st.columns([1, 2.2, 1.2], gap="large")
    with left:
        console_panel()
    with middle:
        st.subheader("Chatbot")
        chat_panel()
    with right:
        card_panel()

    bottom_left, bottom_right = st.columns([2.2, 1.2], gap="large")
    with bottom_left:
        pca_panel()
    with bottom_right:
        rated_panel()


main()
