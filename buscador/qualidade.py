"""Fotos ruins para revisar: borradas, escuras demais, estouradas e rajadas repetidas.

Critérios conservadores (fotos suaves de ensaio, com pouca textura, NÃO entram):
- borrada: nem o trecho mais nítido da foto tem foco;
- escura / estourada: a foto quase inteira é preta / branca;
- repetida: rajada (mesma pasta, até 3 s de diferença, quase idêntica) — fica a mais nítida, as outras vão para revisão.

Nada é movido nem apagado: as fotos aparecem em "📥 Para revisar", onde você decide (Lixeira ou Manter).
"""
import time
from typing import Callable

import numpy as np

from .db import connect

BLUR_MAX = 50          # nitidez do trecho mais nítido (variância do Laplaciano); mediana do catálogo ≈ 1800
DARK_MEAN, DARK_P99 = 22, 120
BRIGHT_MEAN, BRIGHT_P1 = 245, 200
BURST_SECONDS = 3
BURST_SIM = 0.965      # semelhança (IA de imagem) para considerar "a mesma foto" da rajada

REASONS = {"borrada": "borrada", "escura": "escura demais", "clara": "estourada (clara demais)",
           "repetida": "repetida (rajada)"}


def sharpness_and_light(path) -> tuple[float, float, float, float]:
    import cv2
    from PIL import Image
    g = np.asarray(Image.open(path).convert("L"), dtype=np.uint8)
    h, w = g.shape
    th, tw = max(h // 4, 8), max(w // 4, 8)
    sharp = max(cv2.Laplacian(g[y:y + th, x:x + tw], cv2.CV_64F).var()
                for y in range(0, h - th + 1, th) for x in range(0, w - tw + 1, tw))
    return float(sharp), float(g.mean()), float(np.percentile(g, 1)), float(np.percentile(g, 99))


def _flag(sharp: float, mean: float, p1: float, p99: float) -> str | None:
    if mean < DARK_MEAN and p99 < DARK_P99:
        return "escura"
    if mean > BRIGHT_MEAN and p1 > BRIGHT_P1:
        return "clara"
    if sharp < BLUR_MAX:
        return "borrada"
    return None


def process_pending(progress: Callable[[dict], None] | None = None, stop=None, only_ids=None) -> dict:
    from .media import thumb_path

    progress = progress or (lambda d: None)
    conn = connect()
    rows = conn.execute(
        """SELECT f.id, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id
           WHERE f.kind = 'image' AND f.quality_done = 0 AND f.has_thumb = 1 AND f.missing = 0 AND f.error IS NULL
           ORDER BY f.id""").fetchall()
    if only_ids is not None:
        rows = [r for r in rows if r["id"] in only_ids]
    total = len(rows)
    progress({"phase": "procurando fotos ruins", "done": 0, "total": total})
    t0, flagged, last = time.time(), 0, 0.0
    for n, r in enumerate(rows, 1):
        if stop is not None and stop.is_set():
            break
        try:
            sharp, mean, p1, p99 = sharpness_and_light(thumb_path(r["serial"], r["id"]))
            flag = _flag(sharp, mean, p1, p99)
        except Exception:
            sharp, flag = None, None
        conn.execute("UPDATE files SET quality_done = 1, sharpness = ?, review = CASE WHEN review = 'kept' THEN review "
                     "ELSE ? END WHERE id = ?", (sharp, flag, r["id"]))
        flagged += bool(flag)
        if time.time() - last > 1 or n == total:
            last = time.time()
            conn.commit()
            progress({"phase": "procurando fotos ruins", "done": n, "total": total})
    conn.commit()
    flagged += _bursts(conn, {r["id"] for r in rows})
    return {"total": total, "flagged": flagged, "seconds": round(time.time() - t0, 1)}


def _bursts(conn, touched: set[int]) -> int:
    """Rajadas: na mesma pasta, fotos com até 3 s de diferença e quase idênticas → fica a mais nítida."""
    if not touched:
        return 0
    from datetime import datetime
    rows = conn.execute(
        """SELECT f.id, f.volume_id, f.relpath, f.taken_at, f.sharpness, f.review, e.vec FROM files f
           JOIN embeddings e ON e.file_id = f.id
           WHERE f.kind = 'image' AND f.missing = 0 AND f.taken_at IS NOT NULL AND f.sharpness IS NOT NULL
           ORDER BY f.volume_id, f.relpath""").fetchall()
    by_folder: dict = {}
    for r in rows:
        by_folder.setdefault((r["volume_id"], r["relpath"].rsplit("\\", 1)[0]), []).append(r)
    marked = 0
    for items in by_folder.values():
        if len(items) < 2 or not any(r["id"] in touched for r in items):
            continue
        items.sort(key=lambda r: r["taken_at"])
        group = [items[0]]
        for prev, cur in zip(items, items[1:]):
            dt = (datetime.fromisoformat(cur["taken_at"]) - datetime.fromisoformat(prev["taken_at"])).total_seconds()
            a = np.frombuffer(prev["vec"], dtype=np.float16).astype(np.float32)
            b = np.frombuffer(cur["vec"], dtype=np.float16).astype(np.float32)
            if dt <= BURST_SECONDS and float(a @ b) >= BURST_SIM:
                group.append(cur)
                continue
            marked += _mark_burst(conn, group)
            group = [cur]
        marked += _mark_burst(conn, group)
    conn.commit()
    return marked


def _mark_burst(conn, group: list) -> int:
    if len(group) < 2:
        return 0
    best = max(group, key=lambda r: r["sharpness"] or 0)
    n = 0
    for r in group:
        if r["id"] != best["id"] and r["review"] is None:
            conn.execute("UPDATE files SET review = 'repetida' WHERE id = ?", (r["id"],))
            n += 1
    return n


def review_counts() -> dict:
    rows = connect().execute("""SELECT review, COUNT(*) FROM files WHERE missing = 0 AND trashed = 0
                                AND review IS NOT NULL AND review != 'kept' GROUP BY review""").fetchall()
    return {r[0]: r[1] for r in rows}


def keep(ids: list[int]) -> None:
    """"Manter": sai da revisão e não volta."""
    conn = connect()
    conn.executemany("UPDATE files SET review = 'kept' WHERE id = ?", [(i,) for i in ids])
    conn.commit()
