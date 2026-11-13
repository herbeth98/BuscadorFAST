"""IA local (SigLIP 2 na GPU): palavras-chave automáticas e busca por frase livre."""
import hashlib
import threading
import time
from typing import Callable

import numpy as np

from .config import AI_BATCH, DATA_DIR, MAX_TAGS_PER_FILE, MODEL_NAME, TAG_THRESHOLD
from .db import connect, refresh_fts, tag_id
from .vocab import CONFLICTS, TEMPLATES, VOCAB

_lock = threading.Lock()
_model = None
_processor = None
_device = "cpu"
_tag_vecs: np.ndarray | None = None
_scale = _bias = 0.0


def _load():
    global _model, _processor, _device, _scale, _bias
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        import torch
        from transformers import AutoModel, AutoProcessor

        _device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if _device == "cuda" else torch.float32
        _processor = AutoProcessor.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME, dtype=dtype).to(_device).eval()
        _scale = float(model.logit_scale.exp())
        _bias = float(model.logit_bias)
        _model = model


def _as_tensor(out):
    # Versões novas do transformers devolvem um objeto em vez do tensor
    return out if hasattr(out, "shape") else out.pooler_output


def _normalize(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-8)


def embed_texts(texts: list[str]) -> np.ndarray:
    import torch

    _load()
    out = []
    for i in range(0, len(texts), 64):
        inputs = _processor(text=texts[i:i + 64], padding="max_length", max_length=64,
                            truncation=True, return_tensors="pt").to(_device)
        with torch.inference_mode():
            feats = _as_tensor(_model.get_text_features(**inputs))
        out.append(feats.float().cpu().numpy())
    return _normalize(np.concatenate(out))


def embed_images(images) -> np.ndarray:
    import torch

    _load()
    inputs = _processor(images=images, return_tensors="pt").to(_device)
    inputs["pixel_values"] = inputs["pixel_values"].to(_model.dtype)
    with torch.inference_mode():
        feats = _as_tensor(_model.get_image_features(**inputs))
    return _normalize(feats.float().cpu().numpy())


def tag_vectors() -> np.ndarray:
    """Vetores do vocabulário, guardados em disco para não recalcular toda vez."""
    global _tag_vecs
    if _tag_vecs is not None:
        return _tag_vecs
    key = hashlib.md5((MODEL_NAME + repr(VOCAB) + repr(TEMPLATES)).encode()).hexdigest()[:12]
    cache = DATA_DIR / f"vocab_{key}.npy"
    if cache.exists():
        _tag_vecs = np.load(cache)
    else:
        # média das várias formas de descrever cada palavra ("a photo of X", "X", …)
        per_template = [embed_texts([t.format(en) for _, en in VOCAB]) for t in TEMPLATES]
        _tag_vecs = _normalize(np.mean(per_template, axis=0))
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        np.save(cache, _tag_vecs)
    return _tag_vecs


def tag_probs(img_vecs: np.ndarray) -> np.ndarray:
    logits = img_vecs @ tag_vectors().T * _scale + _bias
    return 1 / (1 + np.exp(-logits))


# ---------------------------------------------------------------- processamento em lote

def process_pending(progress: Callable[[dict], None] | None = None, redo: bool = False, only_ids=None,
                    stop: threading.Event | None = None) -> dict:
    from PIL import Image

    from .media import thumb_paths

    progress = progress or (lambda d: None)
    conn = connect()
    if redo:
        conn.execute("UPDATE files SET ai_done = 0 WHERE has_thumb = 1 AND error IS NULL")
        conn.commit()
    rows = conn.execute(
        """SELECT f.id, f.kind, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id
           WHERE f.ai_done = 0 AND f.has_thumb = 1 ORDER BY f.id"""
    ).fetchall()
    if only_ids is not None:  # só os arquivos que acabaram de chegar
        rows = [r for r in rows if r["id"] in only_ids]
    total = len(rows)
    progress({"phase": "carregando modelo de IA", "done": 0, "total": total})
    if not total:
        return {"total": 0}
    _load()
    tag_vectors()
    tag_ids = [tag_id(conn, pt) for pt, _ in VOCAB]
    conn.commit()

    t0 = time.time()
    done = 0
    for start in range(0, total, AI_BATCH):
        if stop and stop.is_set():
            break
        batch = rows[start:start + AI_BATCH]
        images, owners = [], []
        for r in batch:
            for p in thumb_paths(r["serial"], r["id"], r["kind"]):
                try:
                    images.append(Image.open(p).convert("RGB"))
                    owners.append(r["id"])
                except OSError:
                    pass
        vecs = embed_images(images) if images else np.zeros((0, 1))
        probs = tag_probs(vecs) if images else vecs
        owners_arr = np.array(owners)
        for r in batch:
            fid = r["id"]
            idx = np.where(owners_arr == fid)[0]
            if len(idx):
                emb = _normalize(vecs[idx].mean(axis=0))   # vídeo: média dos quadros
                p = probs[idx].max(axis=0)                  # vídeo: palavra-chave se aparecer em qualquer quadro
                _save(conn, fid, emb, p, tag_ids)
            conn.execute("UPDATE files SET ai_done = 1 WHERE id = ?", (fid,))
            refresh_fts(conn, fid)
        conn.commit()
        done += len(batch)
        rate = done / max(time.time() - t0, 1e-3)
        progress({"phase": "gerando palavras-chave", "done": done, "total": total,
                  "per_hour": int(rate * 3600)})
    invalidate_index()
    return {"total": total, "done": done, "seconds": round(time.time() - t0, 1)}


def _save(conn, fid: int, emb: np.ndarray, probs: np.ndarray, tag_ids: list[int]) -> None:
    conn.execute("INSERT OR REPLACE INTO embeddings(file_id, vec) VALUES (?, ?)",
                 (fid, emb.astype(np.float16).tobytes()))
    conn.execute("DELETE FROM file_tags WHERE file_id = ? AND source = 'ai'", (fid,))
    rejected = {r[0] for r in conn.execute("SELECT tag_id FROM rejected_tags WHERE file_id = ?", (fid,))}
    for i in choose_tags(probs):
        if tag_ids[i] in rejected:
            continue
        conn.execute("INSERT OR IGNORE INTO file_tags(file_id, tag_id, source, score) VALUES (?, ?, 'ai', ?)",
                     (fid, tag_ids[i], float(probs[i])))


_conflict_idx: list[tuple[int, int]] | None = None


def choose_tags(probs: np.ndarray) -> list[int]:
    """Quais palavras entram: acima do limite, não muito abaixo da mais forte, sem pares que se confundem."""
    global _conflict_idx
    if _conflict_idx is None:
        pos = {pt: i for i, (pt, _) in enumerate(VOCAB)}
        _conflict_idx = [(pos[a], pos[b]) for a, b in CONFLICTS if a in pos and b in pos]
    top = float(probs.max()) if len(probs) else 0.0
    floor = max(TAG_THRESHOLD, top * 0.12)  # com uma palavra muito forte, as fracas viram ruído
    keep = {int(i) for i in np.where(probs >= floor)[0]}
    if not keep and top >= 0.03:
        keep = {int(probs.argmax())}  # pelo menos o assunto principal
    for a, b in _conflict_idx:
        if a in keep and b in keep:
            keep.discard(a if probs[a] < probs[b] else b)
    return sorted(keep, key=lambda i: -probs[i])[:MAX_TAGS_PER_FILE]


# ---------------------------------------------------------------- busca por frase livre

_index_ids: np.ndarray | None = None
_index_vecs: np.ndarray | None = None


def invalidate_index() -> None:
    global _index_ids, _index_vecs
    _index_ids = _index_vecs = None


def _index():
    global _index_ids, _index_vecs
    if _index_ids is None:
        rows = connect().execute("SELECT file_id, vec FROM embeddings").fetchall()
        if rows:
            _index_ids = np.array([r[0] for r in rows])
            _index_vecs = np.stack([np.frombuffer(r[1], dtype=np.float16) for r in rows])
        else:
            _index_ids, _index_vecs = np.zeros(0, dtype=int), np.zeros((0, 1), dtype=np.float16)
    return _index_ids, _index_vecs


def semantic_scores(query: str) -> dict[int, float]:
    ids, vecs = _index()
    if not len(ids):
        return {}
    q = embed_texts([query])[0].astype(np.float16)
    sims = (vecs @ q).astype(np.float32)
    return dict(zip(ids.tolist(), sims.tolist()))


def similar_to(file_id: int) -> dict[int, float]:
    ids, vecs = _index()
    hit = np.where(ids == file_id)[0]
    if not len(hit):
        return {}
    sims = (vecs @ vecs[hit[0]]).astype(np.float32)
    return dict(zip(ids.tolist(), sims.tolist()))
