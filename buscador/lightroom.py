"""Lê o que você já marcou no Lightroom/Bridge/Premiere (XMP): palavras-chave e estrelas.

- Palavras-chave (dc:subject) viram palavras-chave suas (origem "lr", verdes como as que você põe aqui).
- 4 ou 5 estrelas viram favorito (⭐). Nunca tira um favorito que você marcou.
- Lê o .xmp ao lado (RAW) e o XMP gravado dentro de JPG, DNG, HEIC, MP4, MOV…
Precisa do disco conectado; arquivos de discos desconectados ficam para depois.
"""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from .db import connect, refresh_fts, tag_id

BATCH = 200
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _sidecars(path: Path) -> list[Path]:
    return [p for p in (path.with_suffix(".xmp"), path.with_suffix(".XMP"), path.with_name(path.name + ".xmp"))
            if p.exists()]


def _read(paths: list[Path]) -> dict[str, dict]:
    from .xmp import exiftool
    with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False, encoding="utf-8") as f:
        f.write("\n".join(["-j", "-charset", "filename=utf8", "-q", "-q", "-m",
                           "-XMP-dc:Subject", "-IPTC:Keywords", "-XMP-xmp:Rating"] + [str(p) for p in paths]))
        argfile = f.name
    try:
        out = subprocess.run([exiftool(), "-@", argfile], capture_output=True, timeout=600, creationflags=NO_WINDOW)
    finally:
        os.unlink(argfile)
    try:
        data = json.loads(out.stdout.decode("utf-8", "replace") or "[]")
    except ValueError:
        return {}
    return {str(Path(d["SourceFile"])).lower(): d for d in data}


def _as_list(v) -> list[str]:
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def process_pending(progress: Callable[[dict], None] | None = None, stop=None, only_ids=None) -> dict:
    from .volumes import connected

    progress = progress or (lambda d: None)
    conn = connect()
    online = connected()
    rows = [r for r in conn.execute(
        """SELECT f.id, f.relpath, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id
           WHERE f.lr_done = 0 AND f.missing = 0 AND f.error IS NULL ORDER BY f.id""").fetchall()
        if r["serial"] in online]
    if only_ids is not None:
        rows = [r for r in rows if r["id"] in only_ids]
    total = len(rows)
    progress({"phase": "lendo palavras-chave e estrelas do Lightroom", "done": 0, "total": total})
    if not total:
        return {"total": 0}
    t0, done, found_kw, found_fav = time.time(), 0, 0, 0
    for start in range(0, total, BATCH):
        if stop is not None and stop.is_set():
            break
        batch = rows[start:start + BATCH]
        files = {r["id"]: Path(f"{online[r['serial']]['letter']}:{r['relpath']}") for r in batch}
        to_read = [p for p in files.values() if p.exists()]
        to_read += [s for p in files.values() for s in _sidecars(p)]
        meta = _read(to_read) if to_read else {}
        for fid, p in files.items():
            kws, rating = [], 0
            for src in [p] + _sidecars(p):
                d = meta.get(str(src).lower())
                if not d:
                    continue
                kws += _as_list(d.get("Subject")) + _as_list(d.get("Keywords"))
                try:
                    rating = max(rating, int(float(d.get("Rating") or 0)))
                except (TypeError, ValueError):
                    pass
            kws = list(dict.fromkeys(k.strip().lower() for k in kws if k and k.strip()))
            for k in kws[:40]:
                conn.execute("INSERT OR IGNORE INTO file_tags(file_id, tag_id, source, score) VALUES (?, ?, 'lr', 1)",
                             (fid, tag_id(conn, k)))
            if rating >= 4:
                conn.execute("UPDATE files SET favorite = 1 WHERE id = ?", (fid,))
                found_fav += 1
            found_kw += bool(kws)
            conn.execute("UPDATE files SET lr_done = 1 WHERE id = ?", (fid,))
            if kws:
                refresh_fts(conn, fid)
        conn.commit()
        done += len(batch)
        progress({"phase": "lendo palavras-chave e estrelas do Lightroom", "done": done, "total": total})
    return {"total": total, "done": done, "with_keywords": found_kw, "favorites": found_fav,
            "seconds": round(time.time() - t0, 1)}
