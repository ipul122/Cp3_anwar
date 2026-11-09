"""Manajemen prompt: SEMUA prompt diambil dari Langfuse (label `production`).

Tidak ada teks prompt di kode. Kalau prompt belum ada di Langfuse, langkah itu
dihentikan dengan pesan yang jelas dan tercatat di console log.
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


def load(name: str, **variables) -> tuple[str, object]:
    """Ambil prompt dari Langfuse. Mengembalikan (teks yang sudah terisi, objek prompt Langfuse).

    Objek prompt diteruskan ke `tracing.call_llm(prompt=...)` supaya pemanggilan LLM
    tertaut ke versi prompt yang dipakai (muncul di halaman Prompts di Langfuse).
    """
    try:
        prompt = config.langfuse().get_prompt(name, label=config.PROMPT_LABEL)
        template = prompt.prompt
        if not isinstance(template, str):  # prompt bertipe chat
            template = "\n".join(m["content"] for m in prompt.compile(**variables))
    except Exception as error:
        raise PromptMissing(name, config.PROMPT_LABEL, error) from error
    return _fill(template, variables), prompt
