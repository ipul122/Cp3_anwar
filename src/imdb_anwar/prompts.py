"""Manajemen prompt: SEMUA prompt diambil dari Langfuse (label `production`).

Tidak ada teks prompt di kode. Kalau prompt belum ada di Langfuse, langkah itu
dihentikan dengan pesan yang jelas dan tercatat di console log. Teks prompt untuk
ditempel di UI Langfuse ada di README_prompt.md - dokumen itu bukan sumber runtime.
"""

from . import config


class PromptMissing(RuntimeError):
    """Prompt belum ada di Langfuse (nama atau labelnya salah)."""

    def __init__(self, name: str, label: str, cause: Exception):
        super().__init__(f"Prompt '{name}' (label '{label}') tidak ditemukan di Langfuse: {cause}")
        self.name = name


def _fill(template: str, variables: dict) -> str:
    """Isi placeholder {{nama}} dengan nilainya."""
    for key, value in variables.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


def get(name: str, **variables) -> str:
    """Ambil prompt dari Langfuse lalu isi variabelnya."""
    try:
        prompt = config.langfuse().get_prompt(name, label=config.PROMPT_LABEL)
        template = prompt.prompt
        if not isinstance(template, str):  # prompt bertipe chat
            template = "\n".join(m["content"] for m in prompt.compile(**variables))
    except Exception as error:
        raise PromptMissing(name, config.PROMPT_LABEL, error) from error
    return _fill(template, variables)
