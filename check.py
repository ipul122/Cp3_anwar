"""Cek cepat tanpa memanggil LLM: `python check.py`.

Memastikan data SQLite, logika PCA, prompt fallback, dan wiring graph beres.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from imdb_anwar import config, data, prompts, workflow


def test_data():
    assert config.DB_PATH.exists(), f"database tidak ada: {config.DB_PATH}"

    movies = data.random_movies(3)
    assert len(movies) == 3, movies
    assert data.by_ids([1, 2])[0]["id"] == 1
    assert data.by_ids([2, 1])[0]["id"] == 2, "urutan by_ids harus mengikuti input"

    ratings = {movies[0]["id"]: 10, movies[1]["id"]: 2}
    center = data.rating_center(ratings)
    assert center and len(center) == 2, center

    neighbors = data.pca_neighbors(center, k=3, exclude=ratings)
    assert len(neighbors) == 3, neighbors
    assert not ({m["id"] for m in neighbors} & set(ratings)), "film yang dirating harus dibuang"


def test_prompts():
    """Prompt hanya boleh datang dari Langfuse; kode cuma mengisi variabelnya."""
    assert not hasattr(prompts, "FALLBACK"), "teks prompt tidak boleh ada di kode"
    assert prompts._fill("{{context}}|{{question}}", {"context": "C", "question": "Q"}) == "C|Q"
    assert issubclass(prompts.PromptMissing, RuntimeError)


def test_graph():
    nodes = set(workflow.GRAPH.get_graph().nodes)
    assert {"supervisor", "retrieve", "analytics", "recommend", "lookup", "answer"} <= nodes, nodes

    trace = workflow.new_trace()
    workflow.log_event(trace, "test", detail="oke")
    assert trace["logs"][0]["event"] == "test"
    assert trace["prompt_tokens"] == 0 and trace["cost"] == 0.0


def test_rating_center():
    """Rating bagus menarik titik selera, rating jelek justru mendorongnya menjauh."""
    pool = data.random_movies(10)
    liked = {pool[0]["id"]: 9}
    disliked = pool[1]

    def distance(center):
        return ((center[0] - disliked["PC1"]) ** 2 + (center[1] - disliked["PC2"]) ** 2) ** 0.5

    only_liked = data.rating_center(liked)
    mild = data.rating_center({**liked, disliked["id"]: 5})
    hated = data.rating_center({**liked, disliked["id"]: 1})
    assert only_liked and mild and hated
    assert distance(hated) > distance(only_liked), "film yang tidak disukai harus mendorong pusat menjauh"
    assert distance(hated) > distance(mild), "rating 1 harus mendorong lebih kuat daripada rating 5"
    assert data.rating_center({disliked["id"]: 2}) is not None, "semua jelek tetap harus menghasilkan titik"

    # hanya RECENT_RATINGS terbaru yang dipakai
    pool = data.random_movies(data.RECENT_RATINGS + 2)
    semua = {movie["id"]: 9 for movie in pool}
    terbaru = dict(list(semua.items())[-data.RECENT_RATINGS:])
    assert data.rating_center(semua) == data.rating_center(terbaru), \
        "rating lama harus diabaikan setelah lebih dari RECENT_RATINGS"


def test_lookup_by_title():
    """Film bisa diambil dari judul (route lookup) dan link IMDb ikut ke konteks LLM."""
    sample = data.random_movies(1)[0]
    judul = str(sample["Series_Title"]).title()

    for variant in (judul, f"{judul} (1999)"):  # tahun di judul harus dibuang dulu
        found = [m for m in data.by_titles([variant]) if m["id"] == sample["id"]]
        assert found, f"judul '{variant}' harus ketemu"

    konteks = data.for_llm(data.by_titles([judul]))
    assert "imdb.com/find" in konteks, "link IMDb harus ada di konteks LLM"
    assert data.by_titles(["ab"]) == [], "judul terlalu pendek harus dilewati"


def test_rating_note():
    """Agent harus tahu film apa saja yang sudah dirating user."""
    movies = data.random_movies(2)
    note = workflow._rating_note({movies[0]["id"]: 9})
    assert movies[0]["Series_Title"] in note, note
    assert "9/10" in note, note
    assert "belum ada" in workflow._rating_note({})


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"ok  {name}")
    print("\nsemua cek lulus")
