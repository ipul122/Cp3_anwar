"""Kirim prompt dari README_prompt.md ke Langfuse.

README_prompt.md cuma dokumen pemasangan; sumber runtime aplikasi adalah Langfuse.
Jalankan ini setiap kali isi README_prompt.md diubah:
    poetry run python sync_prompts.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from imdb_anwar import config  # noqa: E402

text = (Path(__file__).parent / "README_prompt.md").read_text(encoding="utf-8")
prompts = re.findall(r"^## \d+\. Name: `([^`]+)`.*?^```\n(.*?)^```", text, re.DOTALL | re.MULTILINE)
assert len(prompts) == 3, f"harus ada 3 blok prompt di README_prompt.md, ketemu {len(prompts)}"

langfuse = config.langfuse()
for name, prompt in prompts:
    langfuse.create_prompt(name=name, type="text", prompt=prompt.rstrip() + "\n",
                           labels=[config.PROMPT_LABEL], commit_message="sync dari README_prompt.md")
    print(f"{name}: tersimpan (label {config.PROMPT_LABEL}, {len(prompt)} karakter)")
langfuse.flush()

