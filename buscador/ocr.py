"""Lê o texto escrito dentro das fotos (OCR com EasyOCR na GPU): placas, banners, documentos, camisetas."""
import threading
import time
from typing import Callable

from .db import connect, normalize, refresh_fts

MIN_CONF = 0.25     # trechos com confiança menor são quase sempre ruído
CANVAS = 1600       # lado maior usado na detecção de texto

_lock = threading.Lock()
_reader = None


def _load():
    global _reader
    if _reader is None:
        with _lock:
            if _reader is None:
                import torch
                import easyocr
                _reader = easyocr.Reader(["pt", "en"], gpu=torch.cuda.is_available(), verbose=False)
    return _reader


def read_text(img) -> str:
    res = _load().readtext(img, canvas_size=CANVAS, mag_ratio=1.0)
    return " ".join(txt.strip() for _, txt, conf in res if conf >= MIN_CONF and len(txt.strip()) >= 2)


def process_pending(progress: Callable[[dict], None] | None = None, stop=None, only_ids=None) -> dict:
    from .faces import _source_images

    progress = progress or (lambda d: None)
    conn = connect()
    rows = conn.execute(
        """SELECT f.id, f.kind, f.relpath, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id
           WHERE f.ocr_done = 0 AND f.has_thumb = 1 AND f.error IS NULL AND f.missing = 0 ORDER BY f.id"""
    ).fetchall()
    if only_ids is not None:  # só os arquivos que acabaram de chegar
        rows = [r for r in rows if r["id"] in only_ids]
    total = len(rows)
    progress({"phase": "lendo texto nas fotos", "done": 0, "total": total})
    if not total:
        return {"total": 0, "with_text": 0}
    from .prefetch import ahead

    _load()
    t0, with_text, last = time.time(), 0, 0.0
    # o disco abre e reduz as próximas fotos enquanto a placa lê o texto da atual
    for n, (row, src) in enumerate(ahead(rows, _source_images, workers=4, depth=8, stop=stop), 1):
        if stop is not None and stop.is_set():
            break
        try:
            if isinstance(src, Exception):
                raise src
            text = " ".join(t for t in (read_text(img) for img in src[0]) if t)
        except Exception:
            text = ""
        with_text += bool(text)
        conn.execute("UPDATE files SET ocr_done = 1, ocr_text = ?, ocr_norm = ? WHERE id = ?",
                     (text or None, normalize(text) or None, row["id"]))
        refresh_fts(conn, row["id"])
        conn.commit()
        if time.time() - last > 1 or n == total:
            last = time.time()
            rate = n / max(last - t0, 1e-3)
            progress({"phase": "lendo texto nas fotos", "done": n, "total": total,
                      "per_hour": int(rate * 3600), "with_text": with_text})
    return {"total": total, "with_text": with_text, "seconds": round(time.time() - t0, 1)}
