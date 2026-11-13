"""Rostos: detecção (SCRFD), reconhecimento (ArcFace), agrupamento e nomes.

Modelos do pacote buffalo_l do InsightFace (uso pessoal/não comercial), rodando na GPU via ONNX Runtime.
"""
import threading
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageOps

from .config import DATA_DIR, RAW_EXT, ROOT
from .db import connect, refresh_fts, tag_id

MODELS_DIR = ROOT / "models"
FACE_DIR = DATA_DIR / "faces"

DET_SIZE = 640
DET_THRESH = 0.6
MIN_FACE_PX = 36          # rostos menores que isso no arquivo dão reconhecimento ruim
SOURCE_MAX = 1600         # lado maior da imagem usada para achar rostos
CLUSTER_SIM = 0.50        # semelhança para dois rostos sem nome ficarem no mesmo grupo
PERSON_SIM = 0.45         # semelhança para um rosto novo receber o nome de uma pessoa conhecida

ARCFACE_DST = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)

_lock = threading.Lock()
_det = _rec = None


# ---------------------------------------------------------------- modelos

def _model_file(name: str) -> Path:
    path = MODELS_DIR / name
    if not path.exists():
        zpath = MODELS_DIR / "buffalo_l.zip"
        if not zpath.exists():
            raise FileNotFoundError(f"Modelo de rostos ausente: {zpath}")
        with zipfile.ZipFile(zpath) as z:
            member = next(m for m in z.namelist() if m.endswith(name))
            path.write_bytes(z.read(member))
    return path


def _load():
    global _det, _rec
    if _det is not None:
        return
    with _lock:
        if _det is not None:
            return
        import torch  # noqa: F401  carrega as DLLs de CUDA/cuDNN que vêm com o PyTorch
        import onnxruntime as ort

        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls()
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _rec = ort.InferenceSession(str(_model_file("w600k_r50.onnx")), opts, providers=providers)
        _det = ort.InferenceSession(str(_model_file("det_10g.onnx")), opts, providers=providers)


# ---------------------------------------------------------------- detecção (SCRFD)

_anchor_cache: dict = {}


def _nms(dets: np.ndarray, thresh: float = 0.4) -> list[int]:
    x1, y1, x2, y2, s = dets.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = s.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]]); yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]]); yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1 + 1) * np.maximum(0, yy2 - yy1 + 1)
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(ovr <= thresh)[0] + 1]
    return keep


def detect(img: np.ndarray) -> list[tuple[np.ndarray, float, np.ndarray]]:
    """img RGB uint8 → lista de (caixa x1,y1,x2,y2, confiança, 5 pontos do rosto)."""
    _load()
    h, w = img.shape[:2]
    scale = DET_SIZE / max(h, w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    canvas = np.zeros((DET_SIZE, DET_SIZE, 3), dtype=np.uint8)
    canvas[:nh, :nw] = np.asarray(Image.fromarray(img).resize((nw, nh), Image.Resampling.BILINEAR))
    blob = ((canvas.astype(np.float32) - 127.5) / 128.0).transpose(2, 0, 1)[None]
    outs = _det.run(None, {_det.get_inputs()[0].name: blob})

    scores_l, boxes_l, kps_l = [], [], []
    for idx, stride in enumerate((8, 16, 32)):
        scores = outs[idx].reshape(-1)
        bbox = outs[idx + 3].reshape(-1, 4) * stride
        kps = outs[idx + 6].reshape(-1, 10) * stride
        fh = fw = DET_SIZE // stride
        key = (fh, fw, stride)
        if key not in _anchor_cache:
            centers = np.stack(np.mgrid[:fh, :fw][::-1], axis=-1).astype(np.float32).reshape(-1, 2) * stride
            _anchor_cache[key] = np.repeat(centers, 2, axis=0)
        centers = _anchor_cache[key]
        pos = np.where(scores >= DET_THRESH)[0]
        if not len(pos):
            continue
        c = centers[pos]
        b = bbox[pos]
        boxes_l.append(np.stack([c[:, 0] - b[:, 0], c[:, 1] - b[:, 1], c[:, 0] + b[:, 2], c[:, 1] + b[:, 3]], axis=-1))
        k = kps[pos].reshape(-1, 5, 2) + c[:, None, :]
        kps_l.append(k)
        scores_l.append(scores[pos])
    if not scores_l:
        return []
    boxes = np.concatenate(boxes_l) / scale
    kps = np.concatenate(kps_l) / scale
    scores = np.concatenate(scores_l)
    keep = _nms(np.hstack([boxes, scores[:, None]]))
    return [(boxes[i], float(scores[i]), kps[i]) for i in keep]


# ---------------------------------------------------------------- reconhecimento (ArcFace)

def _align(img: np.ndarray, kps: np.ndarray) -> np.ndarray:
    import cv2

    m, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), ARCFACE_DST, method=cv2.LMEDS)
    return cv2.warpAffine(img, m, (112, 112), borderValue=0)


def embed(crops: list[np.ndarray]) -> np.ndarray:
    _load()
    blob = ((np.stack(crops).astype(np.float32) - 127.5) / 127.5).transpose(0, 3, 1, 2)
    out = _rec.run(None, {_rec.get_inputs()[0].name: blob})[0]
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-8)


# ---------------------------------------------------------------- imagem de origem

def _source_images(row) -> tuple[list[np.ndarray], bool]:
    """Imagem usada para achar rostos: o original (reduzido) se o disco estiver conectado, senão a miniatura.

    Devolve (imagens, veio_do_original)."""
    from .media import thumb_paths
    from .volumes import connected

    if row["kind"] == "image":
        info = connected().get(row["serial"])
        path = Path(f"{info['letter']}:{row['relpath']}") if info else None
        if path and path.exists():
            try:
                if path.suffix.lower() in RAW_EXT:
                    import rawpy
                    with rawpy.imread(str(path)) as raw:
                        th = raw.extract_thumb()
                    src = BytesIO(th.data) if th.format == rawpy.ThumbFormat.JPEG else None
                else:
                    src = path
                if src is not None:
                    with Image.open(src) as im:
                        if im.format == "JPEG":
                            im.draft("RGB", (SOURCE_MAX, SOURCE_MAX))
                        im = ImageOps.exif_transpose(im).convert("RGB")
                        im.thumbnail((SOURCE_MAX, SOURCE_MAX), Image.Resampling.BILINEAR)
                        return [np.asarray(im)], True
            except Exception:
                pass
    out = []
    for p in thumb_paths(row["serial"], row["id"], row["kind"]):
        with Image.open(p) as im:
            out.append(np.asarray(im.convert("RGB")))
    return out, False


def _save_crop(img: np.ndarray, box: np.ndarray, face_id: int) -> None:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    cx, cy, side = (x1 + x2) / 2, (y1 + y2) / 2, max(w, h) * 1.35
    crop = Image.fromarray(img).crop((int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2)))
    crop.thumbnail((160, 160), Image.Resampling.LANCZOS)
    FACE_DIR.mkdir(parents=True, exist_ok=True)
    crop.save(FACE_DIR / f"{face_id}.webp", "WEBP", quality=82)


def face_crop_path(face_id: int) -> Path:
    return FACE_DIR / f"{face_id}.webp"


# ---------------------------------------------------------------- processamento em lote

def process_pending(progress: Callable[[dict], None] | None = None, stop: threading.Event | None = None,
                    only_ids=None) -> dict:
    progress = progress or (lambda d: None)
    conn = connect()
    rows = conn.execute(
        """SELECT f.id, f.kind, f.relpath, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id
           WHERE f.faces_done = 0 AND f.has_thumb = 1 AND f.error IS NULL AND f.missing = 0 ORDER BY f.id"""
    ).fetchall()
    if only_ids is not None:  # só os arquivos que acabaram de chegar
        rows = [r for r in rows if r["id"] in only_ids]
    total = len(rows)
    progress({"phase": "procurando rostos", "done": 0, "total": total})
    if not total:
        return {"total": 0, "faces": 0}
    _load()
    t0, found = time.time(), 0
    for n, row in enumerate(rows, 1):
        if stop and stop.is_set():
            break
        old = [r[0] for r in conn.execute("SELECT id FROM faces WHERE file_id = ?", (row["id"],))]
        conn.execute("DELETE FROM faces WHERE file_id = ?", (row["id"],))
        for fid in old:
            face_crop_path(fid).unlink(missing_ok=True)
        try:
            images, original = _source_images(row)
        except Exception:
            images, original = [], False
        min_px = MIN_FACE_PX if original else MIN_FACE_PX * 0.6  # miniatura é menor: aceita rosto menor
        for frame, img in enumerate(images):
            dets = [d for d in detect(img) if min(d[0][2] - d[0][0], d[0][3] - d[0][1]) >= min_px]
            if not dets:
                continue
            vecs = embed([_align(img, k) for _, _, k in dets])
            h, w = img.shape[:2]
            for (box, score, _), vec in zip(dets, vecs):
                rel = f"{box[0] / w:.4f},{box[1] / h:.4f},{(box[2] - box[0]) / w:.4f},{(box[3] - box[1]) / h:.4f}"
                face_id = conn.execute(
                    "INSERT INTO faces(file_id, frame, box, score, vec) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], frame, rel, score, vec.astype(np.float16).tobytes()),
                ).lastrowid
                _save_crop(img, box, face_id)
                found += 1
        conn.execute("UPDATE files SET faces_done = 1 WHERE id = ?", (row["id"],))
        conn.commit()  # um arquivo por vez: ler o original do HD pode demorar, não segura o banco
        if n % 50 == 0 or n == total:
            rate = n / max(time.time() - t0, 1e-3)
            progress({"phase": "procurando rostos", "done": n, "total": total, "per_hour": int(rate * 3600),
                      "faces": found})
    conn.commit()
    progress({"phase": "agrupando rostos", "done": total, "total": total, "faces": found})
    regroup()
    return {"total": total, "faces": found, "seconds": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- agrupamento e nomes

def _vecs(rows) -> np.ndarray:
    return np.stack([np.frombuffer(r["vec"], dtype=np.float16).astype(np.float32) for r in rows])


def regroup() -> None:
    """1) dá o nome de pessoas conhecidas a rostos parecidos; 2) agrupa o resto (sem nome)."""
    conn = connect()
    # centro de cada pessoa = média dos rostos que você confirmou (ou de todos, se nenhum confirmado)
    people = conn.execute("SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL").fetchall()
    centers, pids = [], []
    for (pid,) in people:
        rows = conn.execute("SELECT vec FROM faces WHERE person_id = ? AND manual = 1", (pid,)).fetchall() or \
               conn.execute("SELECT vec FROM faces WHERE person_id = ?", (pid,)).fetchall()
        c = _vecs(rows).mean(axis=0)
        centers.append(c / np.linalg.norm(c)); pids.append(pid)

    free = conn.execute(
        "SELECT id, vec, not_person FROM faces WHERE person_id IS NULL AND ignored = 0 ORDER BY score DESC"
    ).fetchall()
    touched: set[int] = set()
    if free and centers:
        v = _vecs(free)
        sims = v @ np.stack(centers).T
        for i, r in enumerate(free):
            order = np.argsort(-sims[i])
            for j in order[:2]:
                if sims[i, j] < PERSON_SIM:
                    break
                if pids[j] != r["not_person"]:
                    conn.execute("UPDATE faces SET person_id = ?, cluster_id = NULL WHERE id = ?", (pids[j], r["id"]))
                    touched.add(r["id"])
                    break
        free = [r for r in free if r["id"] not in touched]

    # agrupamento guloso: cada rosto entra no grupo mais parecido ou abre um novo
    conn.execute("UPDATE faces SET cluster_id = NULL WHERE person_id IS NULL")
    if free:
        v = _vecs(free)
        sums = np.zeros_like(v)   # pré-alocado: no máximo um grupo por rosto
        cent = np.zeros_like(v)
        k = 0
        labels = np.empty(len(free), dtype=np.int64)
        for i in range(len(free)):
            if k:
                sims = cent[:k] @ v[i]
                j = int(np.argmax(sims))
                if sims[j] >= CLUSTER_SIM:
                    sums[j] += v[i]
                    cent[j] = sums[j] / np.linalg.norm(sums[j])
                    labels[i] = j
                    continue
            sums[k] = cent[k] = v[i]
            labels[i] = k
            k += 1
        conn.executemany("UPDATE faces SET cluster_id = ? WHERE id = ?",
                         [(int(labels[i]) + 1, r["id"]) for i, r in enumerate(free)])
    conn.commit()
    if touched:
        sync_tags([r[0] for r in conn.execute(
            f"SELECT DISTINCT file_id FROM faces WHERE id IN ({','.join(map(str, touched))})")])


def sync_tags(file_ids) -> None:
    """Nome de cada pessoa vira palavra-chave (origem 'face') nos arquivos em que ela aparece."""
    conn = connect()
    for fid in set(file_ids):
        conn.execute("DELETE FROM file_tags WHERE file_id = ? AND source = 'face'", (fid,))
        for (name,) in conn.execute(
            "SELECT DISTINCT p.name FROM faces f JOIN people p ON p.id = f.person_id WHERE f.file_id = ?", (fid,)
        ).fetchall():
            conn.execute("INSERT OR IGNORE INTO file_tags(file_id, tag_id, source, score) VALUES (?, ?, 'face', 1)",
                         (fid, tag_id(conn, name)))
        refresh_fts(conn, fid)
    conn.commit()


def _person(conn, name: str) -> int:
    name = " ".join(name.split())
    row = conn.execute("SELECT id FROM people WHERE name = ?", (name,)).fetchone()
    return row[0] if row else conn.execute("INSERT INTO people(name) VALUES (?)", (name,)).lastrowid


def _face_ids(conn, face_ids=None, cluster_id=None, person_id=None) -> list[int]:
    if face_ids:
        return list(face_ids)
    if cluster_id is not None:
        return [r[0] for r in conn.execute("SELECT id FROM faces WHERE cluster_id = ? AND person_id IS NULL",
                                           (cluster_id,))]
    if person_id is not None:
        return [r[0] for r in conn.execute("SELECT id FROM faces WHERE person_id = ?", (person_id,))]
    return []


def _files_of(conn, ids: list[int]) -> list[int]:
    if not ids:
        return []
    return [r[0] for r in conn.execute(f"SELECT DISTINCT file_id FROM faces WHERE id IN ({','.join(map(str, ids))})")]


def name_faces(name: str, face_ids=None, cluster_id=None, person_id=None) -> int:
    """Dá um nome a rostos (de um grupo, de outra pessoa = juntar, ou avulsos). Nome repetido junta as pessoas."""
    conn = connect()
    ids = _face_ids(conn, face_ids, cluster_id, person_id)
    pid = _person(conn, name)
    conn.executemany("UPDATE faces SET person_id = ?, manual = 1, cluster_id = NULL, ignored = 0 WHERE id = ?",
                     [(pid, i) for i in ids])
    if person_id is not None and person_id != pid:
        conn.execute("DELETE FROM people WHERE id = ? AND NOT EXISTS (SELECT 1 FROM faces WHERE person_id = ?)",
                     (person_id, person_id))
    conn.commit()
    files = _files_of(conn, ids)
    regroup()  # o nome novo puxa rostos parecidos que ainda estavam sem nome
    sync_tags(files)
    return pid


def unassign(face_ids: list[int]) -> None:
    """Tira rostos de uma pessoa (não é ela)."""
    conn = connect()
    files = _files_of(conn, face_ids)
    conn.executemany("UPDATE faces SET not_person = person_id, person_id = NULL, manual = 0 WHERE id = ?",
                     [(i,) for i in face_ids])
    conn.commit()
    sync_tags(files)
    regroup()


def ignore(face_ids=None, cluster_id=None) -> None:
    conn = connect()
    ids = _face_ids(conn, face_ids, cluster_id)
    files = _files_of(conn, ids)
    conn.executemany("UPDATE faces SET ignored = 1, person_id = NULL, cluster_id = NULL WHERE id = ?",
                     [(i,) for i in ids])
    conn.commit()
    sync_tags(files)


def rename_person(person_id: int, name: str) -> int:
    return name_faces(name, person_id=person_id)


def people_overview(min_cluster: int = 2, limit: int = 300) -> dict:
    conn = connect()
    named = conn.execute(
        """SELECT p.id, p.name, COUNT(f.id) AS faces, COUNT(DISTINCT f.file_id) AS files,
                  (SELECT id FROM faces WHERE person_id = p.id ORDER BY manual DESC, score DESC LIMIT 1) AS cover
           FROM people p JOIN faces f ON f.person_id = p.id GROUP BY p.id ORDER BY files DESC"""
    ).fetchall()
    groups = conn.execute(
        """SELECT cluster_id, COUNT(*) AS faces, COUNT(DISTINCT file_id) AS files,
                  (SELECT id FROM faces f2 WHERE f2.cluster_id = f.cluster_id ORDER BY score DESC LIMIT 1) AS cover
           FROM faces f WHERE cluster_id IS NOT NULL AND person_id IS NULL AND ignored = 0
           GROUP BY cluster_id HAVING COUNT(DISTINCT file_id) >= ? ORDER BY files DESC LIMIT ?""",
        (min_cluster, limit),
    ).fetchall()
    return {"people": [dict(r) for r in named], "groups": [dict(r) for r in groups]}


def faces_of(person_id=None, cluster_id=None, limit: int = 500) -> list[dict]:
    conn = connect()
    if person_id is not None:
        rows = conn.execute("SELECT id, file_id, manual FROM faces WHERE person_id = ? ORDER BY manual, score LIMIT ?",
                            (person_id, limit))
    else:
        rows = conn.execute("SELECT id, file_id, manual FROM faces WHERE cluster_id = ? AND person_id IS NULL "
                            "ORDER BY score DESC LIMIT ?", (cluster_id, limit))
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- buscar pessoa por foto

QUERY_SIM = 0.42        # semelhança mínima de rosto para dizer "é a mesma pessoa"
_face_index: tuple | None = None
_face_queries: dict[str, dict[int, float]] = {}


def _faces_matrix():
    """Todos os rostos do catálogo numa matriz (recarrega quando o número de rostos muda)."""
    global _face_index
    conn = connect()
    n = conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
    if _face_index is None or _face_index[0] != n:
        rows = conn.execute("SELECT f.file_id, f.vec FROM faces f JOIN files x ON x.id = f.file_id "
                            "WHERE x.missing = 0").fetchall()
        ids = np.array([r[0] for r in rows]) if rows else np.zeros(0, dtype=int)
        vecs = _vecs(rows) if rows else np.zeros((0, 512), dtype=np.float32)
        _face_index = (n, ids, vecs)
    return _face_index[1], _face_index[2]


def search_by_face(data: bytes) -> dict:
    """Acha o maior rosto da foto enviada e devolve os arquivos em que essa pessoa aparece.
    Devolve {"token", "faces", "found"}; a busca usa o token."""
    import uuid

    with Image.open(BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((SOURCE_MAX, SOURCE_MAX))
        img = np.asarray(im)
    dets = detect(img)
    if not dets:
        return {"token": None, "faces": 0, "found": 0}
    box, _, kps = max(dets, key=lambda d: (d[0][2] - d[0][0]) * (d[0][3] - d[0][1]))  # o rosto principal
    q = embed([_align(img, kps)])[0]
    ids, vecs = _faces_matrix()
    scores: dict[int, float] = {}
    if len(ids):
        sims = vecs @ q
        for fid, s in zip(ids[sims >= QUERY_SIM].tolist(), sims[sims >= QUERY_SIM].tolist()):
            scores[fid] = max(scores.get(fid, 0.0), s)  # vários rostos no mesmo arquivo: fica o mais parecido
    token = uuid.uuid4().hex[:12]
    if len(_face_queries) > 50:
        _face_queries.pop(next(iter(_face_queries)))
    _face_queries[token] = scores
    return {"token": token, "faces": len(dets), "found": len(scores)}


def face_query_scores(token: str) -> dict[int, float]:
    return _face_queries.get(token, {})


def faces_in_file(file_id: int) -> list[dict]:
    rows = connect().execute(
        """SELECT f.id, f.frame, f.box, f.manual, f.cluster_id, p.id AS person_id, p.name FROM faces f
           LEFT JOIN people p ON p.id = f.person_id WHERE f.file_id = ? AND f.ignored = 0 ORDER BY f.frame, f.id""",
        (file_id,),
    ).fetchall()
    return [dict(r) for r in rows]
