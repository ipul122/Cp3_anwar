"""Guardrail lapis 1: tolak permintaan di luar topik film SEBELUM LLM dipanggil.

Murah dan pasti (cuma cek kata kunci, 0 token). Yang lolos dari sini masih dijaga
lapis 2: supervisor LLM bisa menandai `blocked` (lihat workflow.Decision).
"""

JAILBREAK_PATTERNS = (
    "ignore previous", "ignore all previous", "abaikan instruksi", "abaikan semua instruksi",
    "lupakan instruksi", "instruksi sebelumnya", "system prompt", "prompt sistem",
    "kamu sekarang adalah", "you are now", "act as", "berperan sebagai", "developer mode",
    "jailbreak", "mode pengembang",
)
OFF_TOPIC_PATTERNS = (
    "buatkan kode", "buat kode", "tulis kode", "tulis code", "buatkan code", "buat code",
    "script python", "python code", "code python", "kode python", "program python",
    "buatkan program", "tulis program", "buatkan script", "print hello", "hello world",
    "javascript", "html", "css", "koding", "coding", "resep", "puisi", "lirik lagu",
    "terjemahkan", "translate", "soal matematika",
)

REPLY = (
    "Maaf, saya hanya membantu soal film IMDb: rekomendasi, statistik, dan penjelasan film. "
    "Permintaan di luar itu tidak saya layani."
)


def check(question: str) -> str | None:
    """Pola terlarang yang ditemukan di pertanyaan, atau None kalau aman."""
    text = question.lower()
    return next((p for p in JAILBREAK_PATTERNS + OFF_TOPIC_PATTERNS if p in text), None)
