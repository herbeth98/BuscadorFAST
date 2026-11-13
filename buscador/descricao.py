"""Descrição em português de cada foto/vídeo (Qwen2.5-VL na GPU), para buscar pelo assunto.

O modelo olha a miniatura (funciona com o disco desconectado) e devolve:
  DESCRIÇÃO: uma ou duas frases objetivas (quem, o quê, onde, que tipo de evento)
  PALAVRAS: palavras-chave livres
A descrição entra na busca por texto; as palavras viram palavras-chave (origem "desc").
"""
import re
import threading
import time
from typing import Callable

from .db import connect, refresh_fts, tag_id

MODEL = "Qwen/Qwen2.5-VL-3B-Instruct"
BATCH = 16
MAX_PIXELS = 448 * 448      # a miniatura já tem esse tamanho: rápido e suficiente para o assunto
MAX_NEW_TOKENS = 90         # uma frase + palavras: respostas curtas são o que deixa isto rápido

PROMPT = (
    "Descreva esta {tipo} em português do Brasil, de forma objetiva, sem inventar nomes de pessoas. "
    "Diga o que acontece, onde parece ser e que tipo de evento ou situação é.\n"
    "Responda exatamente neste formato, sem mais nada:\n"
    "DESCRIÇÃO: <uma frase de até 30 palavras>\n"
    "PALAVRAS: <de 6 a 12 palavras-chave curtas em minúsculas, separadas por vírgula>"
)

_lock = threading.Lock()
_model = _processor = None


def _load():
    global _model, _processor
    if _model is None:
        with _lock:
            if _model is None:
                import torch
                from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

                _processor = AutoProcessor.from_pretrained(MODEL, min_pixels=128 * 28 * 28, max_pixels=MAX_PIXELS)
                _processor.tokenizer.padding_side = "left"  # necessário para gerar em lote
                device = "cuda" if torch.cuda.is_available() else "cpu"
                _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    MODEL, dtype=torch.bfloat16 if device == "cuda" else torch.float32).to(device).eval()
    return _model, _processor


def unload() -> None:
    """Libera a memória da placa de vídeo para as próximas etapas (rostos, texto, fala)."""
    global _model, _processor
    with _lock:
        _model = _processor = None
    try:
        import gc

        import torch
        gc.collect()
        torch.cuda.empty_cache()
    except Exception:
        pass


def parse(text: str) -> tuple[str, list[str]]:
    # o modelo às vezes erra o rótulo ("DESCRÍVE:", "DESCRÍO:"): corta pelo "PALAVRAS…:" e tira o rótulo do início
    parts = re.split(r"PALAVRAS[\w\s-]*:", text, maxsplit=1, flags=re.I)
    head, tail = parts[0], (parts[1] if len(parts) > 1 else "")
    d = re.sub(r"^\s*DESCR\w*\s*:\s*", "", head, flags=re.I)
    d = " ".join(d.split())[:500]
    kws = []
    for w in tail.replace(";", ",").replace("\n", ",").split(","):
        w = w.strip(" .-*\"'").lower()
        if 2 <= len(w) <= 40 and w not in kws:
            kws.append(w)
    return d, kws[:15]


HINT_MIN = 0.35  # só passa como dica o que a IA de palavras-chave viu com bastante certeza


def describe(images: list, kinds: list[str], hints: list[list[str]] | None = None) -> list[tuple[str, list[str]]]:
    import torch

    model, proc = _load()
    texts = []
    for i, kind in enumerate(kinds):
        prompt = PROMPT.format(tipo="cena de vídeo" if kind == "video" else "foto")
        if hints and hints[i]:
            # a outra IA acerta bem objetos e animais (ex.: carneiro, que este modelo confunde com cachorro)
            prompt += f"\nElementos já identificados na imagem: {', '.join(hints[i])}."
        msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        texts.append(proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True))
    inputs = proc(text=texts, images=images, return_tensors="pt", padding=True).to(model.device)
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
    out = out[:, inputs["input_ids"].shape[1]:]
    return [parse(t) for t in proc.batch_decode(out, skip_special_tokens=True)]


def _save(conn, fid: int, desc: str, kws: list[str]) -> None:
    conn.execute("UPDATE files SET descricao = ?, desc_done = 1 WHERE id = ?", (desc or None, fid))
    conn.execute("DELETE FROM file_tags WHERE file_id = ? AND source = 'desc'", (fid,))
    rejected = {r[0] for r in conn.execute("SELECT tag_id FROM rejected_tags WHERE file_id = ?", (fid,))}
    for w in kws:
        tid = tag_id(conn, w)
        if tid not in rejected:
            # se a mesma palavra já veio de outra fonte (sua, rosto, IA), não duplica
            conn.execute("INSERT OR IGNORE INTO file_tags(file_id, tag_id, source, score) VALUES (?, ?, 'desc', 0.5)",
                         (fid, tid))
    refresh_fts(conn, fid)


REUSE_SIM = 0.975  # foto praticamente igual a outra já descrita (rajada, cópia): aproveita a descrição dela


class _Described:
    """Vetores da IA das fotos já descritas, para achar uma quase igual sem rodar o modelo de novo."""

    def __init__(self, conn):
        import numpy as np
        self.np = np
        rows = conn.execute("SELECT e.file_id, e.vec FROM embeddings e JOIN files f ON f.id = e.file_id "
                            "WHERE f.desc_done = 1 AND f.descricao IS NOT NULL").fetchall()
        self.ids = [r[0] for r in rows]
        self.vecs = (np.stack([np.frombuffer(r[1], dtype=np.float16) for r in rows]).astype(np.float32)
                     if rows else None)

    def match(self, vec) -> int | None:
        if self.vecs is None or vec is None:
            return None
        sims = self.vecs @ vec
        i = int(sims.argmax())
        return self.ids[i] if sims[i] >= REUSE_SIM else None

    def add(self, fid: int, vec) -> None:
        if vec is None:
            return
        self.ids.append(fid)
        self.vecs = vec[None] if self.vecs is None else self.np.vstack([self.vecs, vec[None]])


def _vec(conn, fid: int):
    import numpy as np
    r = conn.execute("SELECT vec FROM embeddings WHERE file_id = ?", (fid,)).fetchone()
    return np.frombuffer(r[0], dtype=np.float16).astype(np.float32) if r else None


def _copy_from(conn, fid: int, src: int) -> None:
    desc = conn.execute("SELECT descricao FROM files WHERE id = ?", (src,)).fetchone()[0]
    kws = [t[0] for t in conn.execute("SELECT t.name FROM file_tags ft JOIN tags t ON t.id = ft.tag_id "
                                      "WHERE ft.file_id = ? AND ft.source = 'desc'", (src,))]
    _save(conn, fid, desc, kws)


def process_pending(progress: Callable[[dict], None] | None = None, stop=None, only_ids=None,
                    redo: bool = False, keep_loaded: bool = False) -> dict:
    from PIL import Image

    from .media import thumb_path

    progress = progress or (lambda d: None)
    conn = connect()
    if redo:
        conn.execute("UPDATE files SET desc_done = 0 WHERE has_thumb = 1")
        conn.commit()
    rows = conn.execute(
        """SELECT f.id, f.kind, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id
           WHERE f.desc_done = 0 AND f.ai_done = 1 AND f.has_thumb = 1 AND f.error IS NULL AND f.missing = 0
           ORDER BY f.id"""
    ).fetchall()
    if only_ids is not None:
        rows = [r for r in rows if r["id"] in only_ids]
    total = len(rows)
    progress({"phase": "descrevendo fotos e vídeos", "done": 0, "total": total})
    if not total:
        return {"total": 0}
    described = _Described(conn)
    t0, done, last, reused = time.time(), 0, 0.0, 0
    try:
        for start in range(0, total, BATCH):
            if stop is not None and stop.is_set():
                break
            batch = rows[start:start + BATCH]
            imgs, kinds, ids, vecs = [], [], [], {}
            for r in batch:
                vecs[r["id"]] = v = _vec(conn, r["id"])
                src = described.match(v)
                if src is not None:
                    _copy_from(conn, r["id"], src)
                    reused += 1
                    continue
                # vídeo: o quadro do meio mostra melhor o assunto
                p = thumb_path(r["serial"], r["id"], 1 if r["kind"] == "video" else 0)
                if not p.exists():
                    p = thumb_path(r["serial"], r["id"], 0)
                try:
                    imgs.append(Image.open(p).convert("RGB")); kinds.append(r["kind"]); ids.append(r["id"])
                except OSError:
                    conn.execute("UPDATE files SET desc_done = 1 WHERE id = ?", (r["id"],))
            conn.commit()  # não segura o banco enquanto o modelo trabalha
            if imgs:
                hints = [[t[0] for t in conn.execute(
                    "SELECT t.name FROM file_tags ft JOIN tags t ON t.id = ft.tag_id WHERE ft.file_id = ? "
                    "AND ft.source = 'ai' AND ft.score >= ? ORDER BY ft.score DESC LIMIT 4", (fid, HINT_MIN))]
                    for fid in ids]
                for fid, (desc, kws) in zip(ids, describe(imgs, kinds, hints)):
                    _save(conn, fid, desc, kws)
                    if desc:
                        described.add(fid, vecs[fid])
            conn.commit()
            done += len(batch)
            if time.time() - last > 1 or done >= total:
                last = time.time()
                rate = done / max(last - t0, 1e-3)
                progress({"phase": "descrevendo fotos e vídeos", "done": done, "total": total,
                          "per_hour": int(rate * 3600), "reused": reused})
    finally:
        if not keep_loaded:
            unload()
    return {"total": total, "done": done, "reused": reused, "seconds": round(time.time() - t0, 1)}
