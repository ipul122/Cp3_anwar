"""Sinkronkan prompt di README_prompt.md (fallback di prompts.py) ke Langfuse."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from imdb_anwar import config, prompts  # noqa: E402

langfuse = config.langfuse()
for name in (config.PROMPT_SUPERVISOR, config.PROMPT_SQL, config.PROMPT_ANSWER):
    text = prompts.FALLBACK[name]
    langfuse.create_prompt(name=name, type="text", prompt=text, labels=[config.PROMPT_LABEL],
                           commit_message="sync dari README_prompt.md")
    print(f"{name}: tersimpan & berlabel {config.PROMPT_LABEL}")
langfuse.flush()
