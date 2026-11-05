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
    assert {"supervisor", "retrieve", "analytics", "recommend", "answer"} <= nodes, nodes

    trace = workflow.new_trace()
    workflow.log_event(trace, "test", detail="oke")
    assert trace["logs"][0]["event"] == "test"
    assert trace["prompt_tokens"] == 0 and trace["cost"] == 0.0


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
