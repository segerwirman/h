"""LanguageTranslation — detect source language, translate (Part 5)."""
from __future__ import annotations

import asyncio
import re

from jarvis.core import config, llm
from jarvis.nlp.base import Context, Response

_LANG_NAMES = {
    "id": "Indonesian", "en": "English", "ja": "Japanese", "ko": "Korean",
    "zh": "Chinese", "ar": "Arabic", "es": "Spanish", "fr": "French",
    "de": "German", "ru": "Russian", "pt": "Portuguese", "tr": "Turkish",
}
_ALIASES = {
    "indonesia": "id", "inggris": "en", "english": "en", "jepang": "ja",
    "japanese": "ja", "korea": "ko", "korean": "ko", "mandarin": "zh",
    "cina": "zh", "chinese": "zh", "arab": "ar", "arabic": "ar",
    "spanyol": "es", "spanish": "es", "prancis": "fr", "perancis": "fr",
    "french": "fr", "jerman": "de", "german": "de", "rusia": "ru",
    "russian": "ru", "portugis": "pt", "portuguese": "pt", "turki": "tr",
    "turkish": "tr",
}

_REQ_RE = re.compile(
    r"^(?:tolong\s+)?(?:terjemahkan|translate|artikan)\s+(?P<body>.+)$",
    re.IGNORECASE | re.DOTALL)
_TO_RE = re.compile(
    r"\s+(?:ke|to|into|dalam)\s+(?:bahasa\s+)?(?P<lang>[a-zA-Z]+)\s*$",
    re.IGNORECASE)


class LanguageTranslation:
    name = "LanguageTranslation"

    def __init__(self) -> None:
        self._langs = [str(l) for l in
                       config.get("nlp.translation_langs", list(_LANG_NAMES))]

    def can_handle(self, text: str, ctx: Context) -> float:
        return 0.95 if _REQ_RE.match(text.strip()) else 0.0

    async def handle(self, text: str, ctx: Context) -> Response:
        m = _REQ_RE.match(text.strip())
        body = m.group("body") if m else text
        target = ctx.language or "id"
        tm = _TO_RE.search(body)
        if tm:
            alias = tm.group("lang").lower()
            target = _ALIASES.get(alias, alias if alias in _LANG_NAMES else target)
            body = body[:tm.start()]
        body = body.strip().strip('"“”')

        target_name = _LANG_NAMES.get(target, target)
        prompt = (
            "Detect the source language of the text, then translate it.\n"
            f"Target language: {target_name}\n"
            "Reply with:\nSumber: <detected language>\nTerjemahan: <translation>\n\n"
            f"Text:\n{body}"
        )
        out = await asyncio.to_thread(llm.generate, prompt)
        return Response(out or "Modul terjemahan tidak tersedia.",
                        source=self.name)

    # auto-detect helper: is the user speaking a non-configured language?
    async def detect(self, text: str) -> str:
        out = await asyncio.to_thread(
            llm.generate,
            "Reply with only the ISO 639-1 code of this text's language: "
            + text[:300],
            None, config.get("llm.classify_model"))
        code = (out or "").strip().lower()[:2]
        return code if code in _LANG_NAMES else "id"
