"""Identifica cada disco pelo número de série do volume, não pela letra.

Assim um HD que hoje é E: e amanhã volta como H: continua sendo o mesmo disco no catálogo.
"""
import ctypes
import shutil
import string
from datetime import datetime
from pathlib import Path

from .db import connect


def volume_info(letter: str) -> dict | None:
    root = f"{letter.upper()}:\\"
    label = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_uint32()
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root), label, 261, ctypes.byref(serial), None, None, fs, 261
    )
    if not ok:
        return None
    try:
        total = shutil.disk_usage(root).total
    except OSError:
        total = None
    return {"letter": letter.upper(), "serial": f"{serial.value:08X}", "label": label.value or root, "total": total}


def connected() -> dict[str, dict]:
    """Discos conectados agora, por número de série."""
    out = {}
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << i):
            info = volume_info(letter)
            if info:
                out[info["serial"]] = info
    return out


def register(path: Path) -> tuple[int, dict]:
    """Garante que o disco de `path` está no catálogo e devolve (volume_id, info)."""
    letter = path.drive.rstrip(":")
    info = volume_info(letter)
    if not info:
        raise RuntimeError(f"Não consegui ler o disco {path.drive}")
    conn = connect()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO volumes(serial, label, last_letter, total_bytes, last_seen) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(serial) DO UPDATE SET label=excluded.label, last_letter=excluded.last_letter,
           total_bytes=excluded.total_bytes, last_seen=excluded.last_seen""",
        (info["serial"], info["label"], info["letter"], info["total"], now),
    )
    conn.commit()
    vid = conn.execute("SELECT id FROM volumes WHERE serial = ?", (info["serial"],)).fetchone()[0]
    return vid, info


def list_volumes() -> list[dict]:
    """Discos do catálogo, com o estado (conectado ou offline) e a letra atual."""
    conn = connect()
    online = connected()
    rows = conn.execute(
        """SELECT v.*, COUNT(f.id) AS files, SUM(f.kind='image') AS images, SUM(f.kind='video') AS videos,
                  SUM(f.ai_done=0) AS pending_ai
           FROM volumes v LEFT JOIN files f ON f.volume_id = v.id AND f.missing = 0
           GROUP BY v.id ORDER BY v.label"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        cur = online.get(d["serial"])
        d["online"] = cur is not None
        d["letter"] = cur["letter"] if cur else None
        out.append(d)
    return out


def current_root(serial: str) -> str | None:
    """Letra atual do disco (ex.: 'E:'), ou None se estiver desconectado."""
    info = connected().get(serial)
    return f"{info['letter']}:" if info else None
