"""'Atualizar todos os discos': quais pastas percorrer em cada disco conectado.

- C: (Windows) → só a sua pasta de usuário; os outros discos → inteiros.
- Dá para tirar um disco da atualização (fica guardado pelo número de série, não pela letra).
"""
import json
from pathlib import Path

from .config import DATA_DIR
from .volumes import connected

SETTINGS = DATA_DIR / "atualizar.json"


def _settings() -> dict:
    try:
        return {"excluded": [], **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (FileNotFoundError, ValueError):
        return {"excluded": []}


def set_included(serial: str, included: bool) -> list[str]:
    s = _settings()
    ex = set(s["excluded"])
    ex.discard(serial) if included else ex.add(serial)
    s["excluded"] = sorted(ex)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s["excluded"]


def excluded() -> set[str]:
    return set(_settings()["excluded"])


def root_for(letter: str) -> str:
    """Pasta a percorrer num disco: no disco do Windows, só a pasta do usuário."""
    home = Path.home()
    if home.drive.upper().startswith(letter.upper()):
        return str(home)
    return f"{letter}:\\"


def roots() -> list[dict]:
    """Discos conectados, na ordem das letras, com a pasta que será percorrida."""
    ex = excluded()
    out = []
    for d in sorted(connected().values(), key=lambda d: d["letter"]):
        out.append({"letter": d["letter"], "label": d["label"], "serial": d["serial"],
                    "root": root_for(d["letter"]), "included": d["serial"] not in ex})
    return out
