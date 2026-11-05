from pathlib import Path

from src.imdb_anwar.workflow import workflow


OUTPUT_DIR = Path("graph_output")
OUTPUT_DIR.mkdir(exist_ok=True)

graph = workflow.get_graph()
mermaid = graph.draw_mermaid()

(OUTPUT_DIR / "workflow.mmd").write_text(mermaid, encoding="utf-8")
print("Mermaid graph saved to graph_output/workflow.mmd")
print()
print(mermaid)

try:
    image = graph.draw_mermaid_png()
except Exception as error:
    print()
    print("PNG graph could not be generated.")
    print(f"Reason: {error}")
else:
    (OUTPUT_DIR / "workflow.png").write_bytes(image)
    print()
    print("PNG graph saved to graph_output/workflow.png")
