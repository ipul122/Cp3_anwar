"""Komponen tampilan Streamlit: poster, kartu film, baris console log, grafik PCA.

File ini hanya MENGGAMBAR. Logika sesi (rating, kartu, tanya agent) ada di app.py;
tombol "Simpan" memanggil fungsi `on_save(movie, score)` yang diberikan app.py.
"""

import math

import httpx
import pandas as pd
import streamlit as st

from . import config, database, pca

BANNERS = {
    "jailbreak": config.ROOT / "assets" / "jailbreak.jpg",  # muncul kalau user mencoba jailbreak
    "limit": config.ROOT / "assets" / "limit_token.jpg",  # muncul kalau biaya sesi melewati LIMIT_USD
}

# Warna badge di console log: user biru, supervisor violet, tool oranye,
# hasil tool abu-abu, jawaban hijau, guardrail/error merah.
LOG_COLORS = {
    "user": "blue", "rating": "blue", "route": "violet", "llm": "green", "tool": "orange",
    "tool_result": "gray", "final": "green", "warn": "red", "error": "red",
}


# --- Banner & console log -----------------------------------------------------

def show_banner(kind: str, caption: str = "") -> None:
    """Tampilkan gambar peringatan di dalam chat."""
    path = BANNERS[kind]
    if path.exists():
        st.image(str(path), width="stretch")
    else:
        st.error(f"Gambar '{kind}' tidak ditemukan di {path}")
    if caption:
        st.caption(caption)


def console_line(entry: dict) -> str:
    """Satu baris console log (markdown) dengan warna sesuai jenis pemanggilan."""
    color = "violet" if entry["event"] == "llm" and entry.get("name") == "supervisor" \
        else LOG_COLORS.get(entry["event"], "gray")
    fields = " ".join(f"{k}={v}" for k, v in entry.items() if k not in ("event", "detail"))
    head = f":{color}[**{entry['event']}**] {fields}".rstrip()
    detail = entry.get("detail") or ""
    return f"{head}  \n{detail}" if detail else head


def source_label(sources: list[str]) -> str:
    """Judul expander bukti di bawah jawaban, sesuai tool yang dipakai."""
    if "search_movies" in sources:
        return "Data dari vector database (Qdrant)"
    if sources:
        return f"Konteks tool: {', '.join(sources)}"
    return "Konteks percakapan (tanpa tool)"


# --- Poster & kartu film -------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=86400)
def poster_bytes(url: str) -> bytes | None:
    """Ambil gambar poster sekali per URL (di-cache). None kalau URL mati."""
    try:
        response = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return response.content
    except Exception:
        return None


def poster_url(movie: dict) -> str | None:
    """Poster ukuran 300px (Poster_Link di database cuma 67px)."""
    link = str(movie.get("Poster_Link") or "")
    return link.split("._V1")[0] + "._V1_SX300.jpg" if link.startswith("http") else None


def show_poster(movie: dict, width: int = 104) -> None:
    """Poster yang bisa diklik ke halaman IMDb. Sekitar 1 dari 6 URL di dataset sudah mati,
    jadi gambar dicek dulu dan diganti tulisan kalau gagal."""
    url = poster_url(movie)
    if url and poster_bytes(url):
        st.markdown(
            f'<a href="{database.imdb_url(movie)}" target="_blank">'
            f'<img src="{url}" width="{width}" alt="poster"></a>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("🎬 poster tidak tersedia")


def movie_card(movie: dict, prefix: str, on_save) -> None:
    """Kartu film (poster + info) dengan slider rating 1-10."""
    with st.container(border=True):
        poster, info = st.columns([1, 2.2], gap="small")
        with poster:
            show_poster(movie, width=104)
        with info:
            year = int(movie["year"]) if movie["year"] else "?"
            st.markdown(f"**[{str(movie['Series_Title']).title()}]({database.imdb_url(movie)})** ({year})")
            st.caption(f"{movie['genre']} · ⭐ {movie['rating']}")
            st.write(f"{str(movie['overview'])[:110]}…")
        score = st.slider("Rating (1-10)", 1, 10, 7, key=f"slider_{prefix}_{movie['id']}")
        if st.button("Simpan rating", key=f"save_{prefix}_{movie['id']}", width="stretch"):
            on_save(movie, score)


def chat_movies(movies: list[dict], position: int, ratings: dict, on_save) -> None:
    """Poster + rating untuk film yang disebut di jawaban chatbot."""
    for index, (column, movie) in enumerate(zip(st.columns(len(movies)), movies)):
        with column:
            show_poster(movie, width=84)
            st.markdown(f"[{str(movie['Series_Title']).title()}]({database.imdb_url(movie)})")
            if movie["id"] in ratings:
                st.caption(f"✓ dirating {ratings[movie['id']]}/10")
                continue
            score = st.selectbox("rating", range(1, 11), index=6, key=f"chat_{position}_{index}_{movie['id']}",
                                 label_visibility="collapsed")
            if st.button("Simpan", key=f"chatsave_{position}_{index}_{movie['id']}", width="stretch"):
                on_save(movie, score)


# --- Grafik PCA ------------------------------------------------------------------

def _ring(center: tuple[float, float], radius: float, label: str, steps: int = 90) -> pd.DataFrame:
    """Titik-titik lingkaran untuk menggambar jangkauan rekomendasi."""
    angles = [2 * math.pi * i / (steps - 1) for i in range(steps)]
    return pd.DataFrame({
        "PC1": [center[0] + radius * math.cos(a) for a in angles],
        "PC2": [center[1] + radius * math.sin(a) for a in angles],
        "Series_Title": label,
        "group": label,
    })


def pca_scatter(ratings: dict, center, radius, recommendations: list[dict], random_cards: list[dict],
                height: int, age: int | None = None) -> None:
    """Sebaran film yang boleh untuk `age` di peta PCA. Kalau `center` ada, tambahkan titik selera,
    rekomendasi, kartu acak, dan lingkaran jangkauan."""
    frame = pd.DataFrame(pca.points(age))
    frame["group"] = "semua film"
    frame.loc[frame["id"].isin(ratings), "group"] = "film yang kamu rating"

    if center:
        marks = [{"id": -1, "Series_Title": "selera kamu", "PC1": center[0], "PC2": center[1], "group": "selera kamu"}]
        for group, movies in (("rekomendasi", recommendations), ("card acak", random_cards)):
            marks += [{"id": m["id"], "Series_Title": m["Series_Title"], "rating": m["rating"],
                       "PC1": m["PC1"], "PC2": m["PC2"], "group": group} for m in movies]
        frame = pd.concat([frame, pd.DataFrame(marks), _ring(center, radius, "jangkauan rekomendasi")],
                          ignore_index=True)

    st.vega_lite_chart(
        frame,
        {
            "mark": {"type": "circle", "size": 45, "opacity": 0.85},
            "encoding": {
                "x": {"field": "PC1", "type": "quantitative"},
                "y": {"field": "PC2", "type": "quantitative"},
                "color": {"field": "group", "type": "nominal", "title": "Kelompok"},
                "tooltip": [
                    {"field": "Series_Title", "type": "nominal", "title": "Film"},
                    {"field": "rating", "type": "quantitative", "title": "Rating IMDb"},
                    {"field": "PC1", "type": "quantitative", "title": "PC1", "format": ".3f"},
                    {"field": "PC2", "type": "quantitative", "title": "PC2", "format": ".3f"},
                    {"field": "group", "type": "nominal", "title": "Kelompok"},
                ],
            },
        },
        height=height,
        width="stretch",
    )
