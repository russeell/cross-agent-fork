"""Minimal i18n: output language follows the user's input.

Priority: `--lang` flag > `CAF_LANG` env > system locale (zh* -> Chinese, else English).
"""

from __future__ import annotations

import os

LANG = "en"


def detect_lang() -> str:
    env = os.environ.get("CAF_LANG", "")
    if env:
        return "zh" if env.lower().startswith("zh") else "en"
    loc = os.environ.get("LC_ALL", "") or os.environ.get("LANG", "")
    return "zh" if loc.lower().startswith(("zh", "cmn")) else "en"


def set_lang(lang: str) -> None:
    global LANG
    LANG = "zh" if lang.lower().startswith("zh") else "en"


def extract_lang(argv: list[str]) -> tuple[list[str], str | None]:
    """Pull --lang out of argv (works before or after the subcommand)."""
    rest: list[str] = []
    lang = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
            i += 2
            continue
        if a.startswith("--lang="):
            lang = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    return rest, lang


def t(en: str, zh: str) -> str:
    """Pick the translation for the active language."""
    return zh if LANG == "zh" else en
