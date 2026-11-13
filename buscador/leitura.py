"""Teste de leitura dos HDs: lê os arquivos inteiros aos poucos para achar problemas antes de você precisar deles.

- Arquivo que não lê (erro do disco) → anotado como "não lê".
- Arquivo cujo conteúdo mudou sem ninguém mexer (mesmo tamanho e data, impressão digital diferente) → "possível
  corrupção".
- Cada rodada tem um limite de tempo e começa pelos arquivos testados há mais tempo (ou nunca testados);
  de madrugada, continua de onde parou.
Aproveita a leitura para guardar a impressão digital do arquivo (usada também pelos duplicados).
"""
import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .db import connect
from .volumes import connected

CHUNK = 4 * 1024 * 1024


def run(hours: float = 3, progress: Callable[[dict], None] | None = None, stop=None) -> dict:
    progress = progress or (lambda d: None)
    conn = connect()
    online = connected()
    rows = [r for r in conn.execute(
        """SELECT f.id, f.relpath, f.size, f.mtime, f.fhash, f.hash_mtime, v.serial FROM files f
           JOIN volumes v ON v.id = f.volume_id WHERE f.missing = 0 AND f.trashed = 0
           ORDER BY f.read_at IS NOT NULL, f.read_at, f.id""").fetchall() if r["serial"] in online]
    deadline = time.time() + hours * 3600
    total_bytes = sum(r["size"] or 0 for r in rows) or 1
    done = done_bytes = errors = 0
    t0, last = time.time(), 0.0
    for r in rows:
        if (stop is not None and stop.is_set()) or time.time() > deadline:
            break
        path = Path(f"{online[r['serial']]['letter']}:{r['relpath']}")
        error = None
        try:
            st = path.stat()
            h = hashlib.blake2b(digest_size=20)
            with open(path, "rb") as f:
                while chunk := f.read(CHUNK):
                    h.update(chunk)
                    if stop is not None and stop.is_set():
                        break
            digest = h.hexdigest()
            unchanged = st.st_size == r["size"] and r["hash_mtime"] is not None and abs(st.st_mtime - r["hash_mtime"]) < 2
            if r["fhash"] and unchanged and digest != r["fhash"]:
                error = "possível corrupção: o conteúdo mudou sem o arquivo ter sido alterado"
            elif not r["fhash"] or not unchanged:
                conn.execute("UPDATE files SET fhash = ?, hash_mtime = ? WHERE id = ?", (digest, st.st_mtime, r["id"]))
        except FileNotFoundError:
            continue  # sumiu: a vigilância/atualização cuida
        except OSError as exc:
            error = f"não lê: {exc.strerror or exc}"
        if stop is not None and stop.is_set():
            break
        errors += bool(error)
        conn.execute("UPDATE files SET read_at = ?, read_error = ? WHERE id = ?",
                     (datetime.now().isoformat(timespec="seconds"), error, r["id"]))
        conn.commit()
        done += 1
        done_bytes += r["size"] or 0
        if time.time() - last > 1:
            last = time.time()
            rate = done_bytes / max(last - t0, 1e-3)
            progress({"phase": "testando a leitura dos discos", "done": done, "total": len(rows),
                      "pct_bytes": round(100 * done_bytes / total_bytes, 1), "mb_s": round(rate / 1e6)})
    return {"read": done, "gb": round(done_bytes / 1e9, 1), "errors": errors, "seconds": round(time.time() - t0)}


def summary() -> dict:
    conn = connect()
    online = connected()
    vols = conn.execute(
        """SELECT v.id, v.serial, v.label, COUNT(*) AS files, SUM(f.size) AS bytes,
                  SUM(f.read_at IS NOT NULL) AS tested, SUM(CASE WHEN f.read_at IS NOT NULL THEN f.size ELSE 0 END) AS tested_bytes,
                  SUM(f.read_error IS NOT NULL) AS errors, MAX(f.read_at) AS last
           FROM files f JOIN volumes v ON v.id = f.volume_id WHERE f.missing = 0 AND f.trashed = 0
           GROUP BY v.id ORDER BY v.label""").fetchall()
    bad = conn.execute(
        """SELECT f.id, f.name, f.relpath, f.read_error, f.read_at, v.label FROM files f
           JOIN volumes v ON v.id = f.volume_id WHERE f.read_error IS NOT NULL AND f.missing = 0
           ORDER BY f.read_at DESC LIMIT 100""").fetchall()
    return {"volumes": [{**dict(v), "online": v["serial"] in online} for v in vols], "errors": [dict(b) for b in bad]}
