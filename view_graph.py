"""Simpan diagram graph LangGraph ke graph_output/workflow.png."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from imdb_anwar.workflow import GRAPH  # noqa: E402

OUTPUT_DIR = Path("graph_output")
OUTPUT_DIR.mkdir(exist_ok=True)

graph = GRAPH.get_graph()

try:
    image = graph.draw_mermaid_png()
except Exception as error:
    print("PNG graph could not be generated.")
    print(f"Reason: {error}")
else:
    (OUTPUT_DIR / "workflow.png").write_bytes(image)
    print("PNG graph saved to graph_output/workflow.png")

