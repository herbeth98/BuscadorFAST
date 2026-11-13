"""Servidor local (FastAPI) que liga o catálogo à tela no navegador."""
import os
import subprocess
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import jobs
from .config import RAW_EXT, WEB_DIR
from .db import connect, file_tags, refresh_fts, tag_id
from .media import VIDEO_FRAMES, thumb_path
from .search import cameras, search, top_tags
from .volumes import connected, list_volumes

app = FastAPI(title="BuscadorFAST")

_LOCKED_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BuscadorFAST</title><body style="font:16px system-ui;padding:32px;text-align:center;color:#333">
<h2>BuscadorFAST</h2><p>Para abrir pelo celular, no computador vá em <b>⚙ → Acesso pelo celular</b>
e leia o QR code com a câmera.</p></body>"""


@app.middleware("http")
async def _fresh_page(request, call_next):
    """A página (html, js, css) é sempre conferida com o servidor: depois de uma atualização, aparece na hora."""
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.middleware("http")
async def _guard(request, call_next):
    """No próprio PC: tudo liberado. Pela rede: só com a chave, e sem as ações que mexem nos arquivos."""
    import secrets

    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

    from . import rede

    if rede.is_local_request(request):
        return await call_next(request)
    s = rede.settings()
    if not s["enabled"] or not s["token"]:
        return HTMLResponse(_LOCKED_PAGE, status_code=403)
    key = request.query_params.get("chave")
    if key and secrets.compare_digest(key, s["token"]):
        resp = RedirectResponse("/", status_code=303)  # guarda a chave no celular e tira ela do endereço
        resp.set_cookie(rede.COOKIE, s["token"], max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
        return resp
    cookie = request.cookies.get(rede.COOKIE) or ""
    if not cookie or not secrets.compare_digest(cookie, s["token"]):
        return HTMLResponse(_LOCKED_PAGE, status_code=401)
    if request.url.path.startswith(rede.BLOCKED):
        return JSONResponse({"detail": "Pelo celular essa ação fica bloqueada. Faça no computador."}, status_code=403)
    return await call_next(request)


@app.on_event("startup")
def _preload():
    # Carrega a IA em segundo plano para a primeira busca por frase não demorar
    import threading

    from . import ai, backup
    threading.Thread(target=lambda: (ai._load(), ai.tag_vectors(), ai._index()), daemon=True).start()
    backup.start_scheduler()  # backup diário do catálogo enquanto o programa estiver aberto
    from .db import start_checkpoints
    start_checkpoints()  # não deixa o registro do banco crescer sem parar durante a indexação
    from . import rede
    if rede.settings()["enabled"]:
        rede.start(app)  # acesso pelo celular, se você deixou ligado
    from . import vigia
    vigia.start()  # acompanha arquivos apagados, movidos e novos enquanto o programa está aberto


def _file_row(fid: int):
    row = connect().execute(
        "SELECT f.*, v.serial, v.label AS volume FROM files f JOIN volumes v ON v.id = f.volume_id WHERE f.id = ?",
        (fid,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "arquivo não encontrado")
    return row


def _real_path(row) -> Path | None:
    info = connected().get(row["serial"])
    return Path(f"{info['letter']}:{row['relpath']}") if info else None


@app.get("/api/volumes")
def api_volumes():
    return list_volumes()


@app.get("/api/search")
def api_search(q: str = "", mode: str = "auto", kind: str = "", volume: int | None = None, tag: str = "",
               date_from: str = "", date_to: str = "", camera: str = "", only_online: bool = False,
               similar: int | None = None, limit: int = 200, offset: int = 0, sort: str = "relevancia",
               favorite: bool = False, collection: int | None = None, foto: str = "", area: str = "",
               album: str = "", revisar: bool = False, pessoas: str = "", pessoas_modo: str = "juntas"):
    online_ids = None
    if only_online:
        online_ids = {v["id"] for v in list_volumes() if v["online"]}
    return search(q, mode, kind, volume, tag, date_from, date_to, camera, online_ids, similar,
                  min(limit, 1000), offset, sort, favorite, collection, foto, area, album, revisar,
                  pessoas, pessoas_modo)


@app.get("/api/revisar")
def api_review_counts():
    from .qualidade import REASONS, review_counts
    c = review_counts()
    return {"total": sum(c.values()), "por_motivo": c, "motivos": REASONS}


class ReviewReq(BaseModel):
    ids: list[int]


@app.post("/api/revisar/manter")
def api_review_keep(body: ReviewReq):
    from .qualidade import keep
    keep(body.ids)
    return {"ok": True}


@app.post("/api/revisar/lixeira")
def api_review_trash(body: ReviewReq):
    from .dupes import trash_files
    return trash_files(body.ids)


@app.get("/api/albuns")
def api_albums(kind: str = "", volume: int | None = None, only_online: bool = False, date_from: str = "",
               date_to: str = ""):
    """Álbuns automáticos: mesmo dia e mesmo lugar (GPS) ou mesma pasta."""
    from .albuns import albums
    from .search import _filters
    online_ids = {v["id"] for v in list_volumes() if v["online"]} if only_online else None
    where, params = _filters(kind=kind, volume=volume, online_ids=online_ids, date_from=date_from, date_to=date_to)
    return albums(" AND ".join(where), params)


@app.get("/api/mapa")
def api_map(kind: str = "", volume: int | None = None, tag: str = "", date_from: str = "", date_to: str = "",
            camera: str = "", only_online: bool = False, favorite: bool = False, collection: int | None = None,
            pessoas: str = "", pessoas_modo: str = "juntas"):
    from .search import map_points
    online_ids = {v["id"] for v in list_volumes() if v["online"]} if only_online else None
    return map_points(kind=kind, volume=volume, tag=tag, date_from=date_from, date_to=date_to, camera=camera,
                      online_ids=online_ids, favorite=favorite, collection=collection,
                      people=pessoas, people_mode=pessoas_modo)


@app.put("/api/voz")
async def api_voice(request: Request):
    """Busca por voz: recebe o áudio gravado no celular, o Whisper do PC transcreve (português) e devolve o texto.
    A gravação não é guardada."""
    import tempfile

    from fastapi.concurrency import run_in_threadpool

    from . import speech
    data = await request.body()
    if not data or len(data) > 20_000_000:
        raise HTTPException(400, "envie o áudio")
    ext = ".mp4" if "mp4" in (request.headers.get("content-type") or "") else ".webm"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"voz{ext}"
        path.write_bytes(data)
        segments = await run_in_threadpool(speech.transcribe, path)
    text = " ".join(t for _, _, t in segments).strip().rstrip(".!?")
    if not text:
        raise HTTPException(422, "Não entendi. Fale um pouco mais perto do microfone.")
    return {"texto": text}


@app.put("/api/buscar-por-foto")
async def api_search_by_photo(request: Request):
    """Reconhecimento facial: acha a pessoa da foto enviada em todo o catálogo (a foto não é gravada)."""
    from fastapi.concurrency import run_in_threadpool

    from . import faces
    data = await request.body()
    if not data or len(data) > 60_000_000:
        raise HTTPException(400, "envie uma imagem")
    try:
        r = await run_in_threadpool(faces.search_by_face, data)
    except Exception:
        raise HTTPException(400, "não consegui ler essa imagem")
    if not r["faces"]:
        raise HTTPException(422, "Não encontrei nenhum rosto nessa foto. Envie uma foto em que o rosto apareça bem.")
    return {"foto": r["token"], "faces": r["faces"], "found": r["found"]}


@app.get("/api/linha-do-tempo")
def api_timeline(year: str = "", month: str = "", kind: str = "", volume: int | None = None, tag: str = "",
                 camera: str = "", only_online: bool = False, favorite: bool = False, collection: int | None = None,
                 pessoas: str = "", pessoas_modo: str = "juntas"):
    from .search import timeline
    online_ids = {v["id"] for v in list_volumes() if v["online"]} if only_online else None
    return timeline(year[:4], month[:2], kind=kind, volume=volume, tag=tag, camera=camera, online_ids=online_ids,
                    favorite=favorite, collection=collection, people=pessoas, people_mode=pessoas_modo)


# ---------------------------------------------------------------- gravar XMP nos arquivos

class XmpReq(BaseModel):
    ids: list[int] = []
    collection: int | None = None
    favorites: bool = False
    mode: str = "dentro"        # dentro | ao_lado
    include_ai: bool = False


@app.post("/api/xmp")
def api_xmp(body: XmpReq):
    from . import xmp
    try:
        xmp.exiftool()
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc))
    conn = connect()
    ids = list(body.ids)
    if body.collection:
        ids += [r[0] for r in conn.execute("SELECT file_id FROM collection_items WHERE collection_id = ?",
                                           (body.collection,))]
    if body.favorites:
        ids += [r[0] for r in conn.execute("SELECT id FROM files WHERE favorite = 1 AND missing = 0")]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(400, "nenhum arquivo escolhido")
    jobs.submit("xmp", ids=ids, mode="ao_lado" if body.mode == "ao_lado" else "dentro", include_ai=body.include_ai)
    return {**jobs.status(), "count": len(ids)}


# ---------------------------------------------------------------- favoritos e coleções

class IdsReq(BaseModel):
    ids: list[int]
    value: bool = True


@app.post("/api/favoritos")
def api_favorite(body: IdsReq):
    from . import colecoes
    return {"changed": colecoes.set_favorite(body.ids, body.value)}


@app.get("/api/colecoes")
def api_collections():
    from . import colecoes
    return colecoes.list_all()


class CollectionReq(BaseModel):
    name: str = ""
    ids: list[int] = []


@app.post("/api/colecoes")
def api_collection_create(body: CollectionReq):
    """Cria a coleção (ou usa a que já tem esse nome) e já põe os arquivos nela."""
    from . import colecoes
    if not body.name.strip():
        raise HTTPException(400, "dê um nome à coleção")
    cid = colecoes.create(body.name)
    added = colecoes.add(cid, body.ids) if body.ids else 0
    return {"id": cid, "added": added}


@app.post("/api/colecoes/{cid}/adicionar")
def api_collection_add(cid: int, body: CollectionReq):
    from . import colecoes
    return {"added": colecoes.add(cid, body.ids)}


@app.post("/api/colecoes/{cid}/remover")
def api_collection_remove(cid: int, body: CollectionReq):
    from . import colecoes
    colecoes.remove(cid, body.ids)
    return {"ok": True}


@app.post("/api/colecoes/{cid}/renomear")
def api_collection_rename(cid: int, body: CollectionReq):
    from . import colecoes
    if not body.name.strip():
        raise HTTPException(400, "dê um nome à coleção")
    try:
        colecoes.rename(cid, body.name)
    except Exception:
        raise HTTPException(409, "já existe uma coleção com esse nome")
    return {"ok": True}


@app.delete("/api/colecoes/{cid}")
def api_collection_delete(cid: int):
    from . import colecoes
    colecoes.delete(cid)
    return {"ok": True}


@app.post("/api/colecoes/{cid}/premiere")
def api_collection_premiere(cid: int):
    """Importa a coleção inteira numa pasta com o nome dela no Premiere."""
    from . import colecoes
    name = colecoes.name_of(cid)
    if not name:
        raise HTTPException(404, "coleção não encontrada")
    ids = [r[0] for r in connect().execute(
        "SELECT ci.file_id FROM collection_items ci JOIN files f ON f.id = ci.file_id "
        "WHERE ci.collection_id = ? AND f.missing = 0 ORDER BY ci.added", (cid,))]
    if not ids:
        raise HTTPException(400, "a coleção está vazia")
    return api_premiere_import(PremiereReq(ids=ids, bin=name))


class CheckReq(BaseModel):
    ids: list[int]


@app.post("/api/conferir")
def api_check_exists(body: CheckReq):
    """Confere se os arquivos mostrados ainda existem (discos conectados). Os apagados saem do catálogo."""
    conn = connect()
    online = connected()
    gone = []
    for fid in body.ids[:500]:
        row = conn.execute("SELECT f.relpath, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id "
                           "WHERE f.id = ? AND f.missing = 0", (fid,)).fetchone()
        info = online.get(row["serial"]) if row else None
        if info and not Path(f"{info['letter']}:{row['relpath']}").exists():
            gone.append(fid)
    if gone:
        conn.executemany("UPDATE files SET missing = 1 WHERE id = ?", [(i,) for i in gone])
        conn.commit()
    return {"gone": gone}


@app.get("/api/tags")
def api_tags(limit: int = 80):
    return top_tags(limit)


@app.get("/api/cameras")
def api_cameras():
    return cameras()


@app.get("/api/file/{fid}")
def api_file(fid: int):
    row = _file_row(fid)
    d = dict(row)
    path = _real_path(row)
    d["online"] = path is not None and path.exists()
    d["full_path"] = str(path) if path else f"[{row['volume']}]{row['relpath']}"
    d["tags"] = file_tags(connect(), fid)
    from .faces import faces_in_file
    from .speech import segments_of
    from .colecoes import of_file
    d["faces"] = faces_in_file(fid)
    d["collections"] = of_file(fid)
    d["transcript"] = segments_of(fid) if row["kind"] == "video" else []
    from .som import events_of
    d["sounds"] = events_of(fid) if row["kind"] == "video" else []
    d["frames"] = len(VIDEO_FRAMES) if row["kind"] == "video" else 1
    return d


@app.get("/api/thumb/{fid}")
def api_thumb(fid: int, frame: int = 0):
    row = _file_row(fid)
    p = thumb_path(row["serial"], fid, frame)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/webp", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/media/{fid}")
def api_media(fid: int, baixar: bool = False, jpg: bool = False, leve: bool = False, t: float = 0):
    """Arquivo original. `baixar`: salva em vez de abrir. `jpg`: de um RAW, a prévia JPEG em alta.
    `leve`: vídeo convertido na hora para H.264 1080p (toca em qualquer celular; nada é gravado)."""
    path = _real_path(_file_row(fid))
    if not path or not path.exists():
        raise HTTPException(409, "disco desconectado")
    if leve:
        return _light_video(path, max(0.0, t))
    is_raw = path.suffix.lower() in RAW_EXT
    if is_raw and (jpg or not baixar):
        # o navegador e o celular não abrem RAW: entrega a prévia JPEG em alta que vem dentro do arquivo
        import rawpy
        with rawpy.imread(str(path)) as raw:
            th = raw.extract_thumb()
        if th.format != rawpy.ThumbFormat.JPEG:
            raise HTTPException(415, "RAW sem prévia JPEG")
        headers = {"Content-Disposition": _attachment(path.stem + ".jpg")} if baixar else None
        return Response(th.data, media_type="image/jpeg", headers=headers)
    if baixar:
        return FileResponse(path, headers={"Content-Disposition": _attachment(path.name)})
    return FileResponse(path)


def _light_video(path: Path, start: float):
    """Converte o vídeo enquanto envia (placa de vídeo, ~4× mais rápido que o tempo real)."""
    from fastapi.responses import StreamingResponse

    def encoder() -> list[str]:
        nv = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "5M"] if b"h264_nvenc" in nv \
            else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "24"]

    cmd = (["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?"]
           + encoder() + ["-vf", "scale=-2:'min(1080,ih)'", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                          "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", "-"])

    def stream():
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            while chunk := proc.stdout.read(256 * 1024):
                yield chunk
        finally:
            proc.kill()  # o celular fechou ou pulou para outro ponto: para a conversão

    return StreamingResponse(stream(), media_type="video/mp4")


def _attachment(name: str) -> str:
    """Cabeçalho de download que funciona com acentos (iPhone e Android)."""
    from urllib.parse import quote
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


@app.get("/api/baixar")
def api_download_zip(ids: str, nome: str = ""):
    """Vários arquivos num .zip montado na hora (sem compactar: fotos e vídeos já são comprimidos)."""
    import zipfile
    from fastapi.responses import StreamingResponse

    files = []
    for fid in [int(x) for x in ids.split(",") if x.strip().isdigit()][:2000]:
        try:
            p = _real_path(_file_row(fid))
        except HTTPException:
            continue
        if p and p.exists():
            files.append(p)
    if not files:
        raise HTTPException(409, "os arquivos estão em discos desconectados")

    class _Sink:  # o zipfile escreve aqui; o servidor vai mandando os pedaços para o celular
        def __init__(self):
            self.chunks, self.pos = [], 0
        def write(self, b):
            self.chunks.append(bytes(b)); self.pos += len(b); return len(b)
        def tell(self):
            return self.pos
        def flush(self):
            pass

    def stream():
        sink, used = _Sink(), set()
        with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for p in files:
                name, n = p.name, 1
                while name.lower() in used:  # mesmo nome vindo de pastas diferentes
                    n += 1
                    name = f"{p.stem} ({n}){p.suffix}"
                used.add(name.lower())
                with p.open("rb") as src, z.open(zipfile.ZipInfo(name, time.localtime(p.stat().st_mtime)[:6]),
                                                 "w", force_zip64=True) as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
                        if sink.chunks:
                            yield b"".join(sink.chunks); sink.chunks.clear()
                if sink.chunks:
                    yield b"".join(sink.chunks); sink.chunks.clear()
        if sink.chunks:
            yield b"".join(sink.chunks)

    zip_name = (nome.strip() or f"BuscadorFAST - {len(files)} arquivos") + ".zip"
    return StreamingResponse(stream(), media_type="application/zip",
                             headers={"Content-Disposition": _attachment(zip_name)})


class TagEdit(BaseModel):
    add: list[str] = []
    remove: list[str] = []


@app.post("/api/file/{fid}/tags")
def api_edit_tags(fid: int, body: TagEdit):
    conn = connect()
    _file_row(fid)
    for name in body.add:
        if name.strip():
            tid = tag_id(conn, name)
            conn.execute("INSERT OR REPLACE INTO file_tags(file_id, tag_id, source, score) VALUES (?, ?, 'user', 1)",
                         (fid, tid))
            conn.execute("DELETE FROM rejected_tags WHERE file_id = ? AND tag_id = ?", (fid, tid))
    for name in body.remove:
        tid = tag_id(conn, name)
        # remover o nome de uma pessoa = "não é ela" nos rostos deste arquivo
        conn.execute(
            """UPDATE faces SET not_person = person_id, person_id = NULL, manual = 0
               WHERE file_id = ? AND person_id = (SELECT id FROM people WHERE name = ?)""",
            (fid, name.strip()),
        )
        conn.execute("DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?", (fid, tid))
        conn.execute("INSERT OR IGNORE INTO rejected_tags(file_id, tag_id) VALUES (?, ?)", (fid, tid))
    refresh_fts(conn, fid)
    conn.commit()
    return file_tags(conn, fid)


class BulkTag(BaseModel):
    ids: list[int]
    add: list[str] = []


@app.post("/api/tags/bulk")
def api_bulk_tags(body: BulkTag):
    conn = connect()
    tids = [tag_id(conn, n) for n in body.add if n.strip()]
    for fid in body.ids:
        for tid in tids:
            conn.execute("INSERT OR REPLACE INTO file_tags(file_id, tag_id, source, score) VALUES (?, ?, 'user', 1)",
                         (fid, tid))
        refresh_fts(conn, fid)
    conn.commit()
    return {"ok": True, "files": len(body.ids)}


@app.post("/api/open/{fid}")
def api_open(fid: int, folder: bool = False):
    path = _real_path(_file_row(fid))
    if not path or not path.exists():
        raise HTTPException(409, "disco desconectado")
    if folder:
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        os.startfile(path)
    return {"ok": True}


class ScanReq(BaseModel):
    path: str


@app.post("/api/scan")
def api_scan(body: ScanReq):
    p = Path(body.path.strip().strip('"'))
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f"pasta não encontrada: {p}")
    jobs.submit("scan", str(p))
    return jobs.status()


# ---------------------------------------------------------------- rostos

@app.get("/api/people")
def api_people():
    from . import faces
    return faces.people_overview()


@app.get("/api/faces")
def api_faces(person: int | None = None, cluster: int | None = None):
    from . import faces
    return faces.faces_of(person_id=person, cluster_id=cluster)


@app.get("/api/face/{face_id}")
def api_face_crop(face_id: int):
    from . import faces
    p = faces.face_crop_path(face_id)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/webp", headers={"Cache-Control": "max-age=86400"})


class FaceAction(BaseModel):
    name: str = ""
    face_ids: list[int] = []
    cluster_id: int | None = None
    person_id: int | None = None


@app.post("/api/faces/name")
def api_faces_name(body: FaceAction):
    from . import faces
    if not body.name.strip():
        raise HTTPException(400, "digite um nome")
    pid = faces.name_faces(body.name, body.face_ids or None, body.cluster_id, body.person_id)
    return {"person_id": pid}


@app.post("/api/faces/remove")
def api_faces_remove(body: FaceAction):
    from . import faces
    faces.unassign(body.face_ids)
    return {"ok": True}


@app.post("/api/faces/ignore")
def api_faces_ignore(body: FaceAction):
    from . import faces
    faces.ignore(body.face_ids or None, body.cluster_id)
    return {"ok": True}


@app.post("/api/rostos")
def api_rostos():
    jobs.submit("rostos")
    return jobs.status()


@app.get("/api/vigia")
def api_watch_status():
    from . import vigia
    return vigia.status()


@app.get("/api/atualizar")
def api_update_roots():
    from .atualizar import roots
    return roots()


@app.post("/api/atualizar")
def api_update_all():
    """Indexa todos os discos conectados (só o que é novo/mudou) e depois processa o que falta."""
    from .atualizar import roots
    if not any(r["included"] for r in roots()):
        raise HTTPException(400, "nenhum disco marcado para atualizar")
    jobs.submit("atualizar")
    return jobs.status()


class IncludeReq(BaseModel):
    serial: str
    included: bool


@app.post("/api/atualizar/disco")
def api_update_include(body: IncludeReq):
    from .atualizar import set_included
    return {"excluded": set_included(body.serial, body.included)}


@app.post("/api/pendentes")
def api_pending_run():
    """Palavras-chave → rostos → texto nas fotos → fala dos vídeos, só no que ainda falta."""
    jobs.submit("pendentes")
    return jobs.status()


@app.get("/api/pendentes")
def api_pending_counts():
    online = {v["serial"] for v in list_volumes() if v["online"]}
    conn = connect()
    base = "FROM files f JOIN volumes v ON v.id = f.volume_id WHERE f.missing = 0 AND f.error IS NULL"
    one = lambda sql: conn.execute(f"SELECT COUNT(*) {base} AND {sql}").fetchone()[0]  # noqa: E731
    def split(cond):  # etapas que precisam do arquivo original: (com disco conectado, desconectado)
        rows = conn.execute(f"SELECT v.serial, COUNT(*) {base} AND {cond} GROUP BY v.serial").fetchall()
        return sum(n for s, n in rows if s in online), sum(n for s, n in rows if s not in online)
    fala, fala_off = split("f.kind = 'video' AND f.has_thumb = 1 AND f.speech_done = 0")
    som, som_off = split("f.kind = 'video' AND f.has_thumb = 1 AND f.sound_done = 0")
    lr, _ = split("f.lr_done = 0")
    return {
        "miniaturas": one("f.has_thumb = 0"),   # esses precisam de "Indexar" (ler o disco)
        "lightroom": lr,
        "ia": one("f.has_thumb = 1 AND f.ai_done = 0"),
        "qualidade": one("f.kind = 'image' AND f.has_thumb = 1 AND f.quality_done = 0"),
        "descricao": one("f.has_thumb = 1 AND f.desc_done = 0"),
        "rostos": one("f.has_thumb = 1 AND f.faces_done = 0"),
        "ocr": one("f.has_thumb = 1 AND f.ocr_done = 0"),
        "fala": fala, "fala_offline": fala_off,  # precisa do disco conectado
        "som": som, "som_offline": som_off,
    }


@app.post("/api/ocr")
def api_ocr():
    jobs.submit("ocr")
    return jobs.status()


@app.post("/api/fala")
def api_fala():
    jobs.submit("fala")
    return jobs.status()


@app.post("/api/ai")
def api_ai(redo: bool = False):
    jobs.submit("ia", redo=redo)
    return jobs.status()


@app.post("/api/cancel")
def api_cancel():
    jobs.cancel()
    return jobs.status()


@app.get("/api/jobs")
def api_jobs():
    return jobs.status()


# ---------------------------------------------------------------- duplicados

@app.post("/api/duplicados/procurar")
def api_dupes_find():
    jobs.submit("duplicados")
    return jobs.status()


@app.get("/api/duplicados")
def api_dupes(prefer: str = "", kind: str = "", limit: int = 100, offset: int = 0):
    from . import dupes
    return dupes.groups(prefer, kind, min(limit, 500), offset)


class TrashReq(BaseModel):
    ids: list[int] = []
    serial: str = ""


@app.post("/api/duplicados/lixeira")
def api_dupes_trash(body: TrashReq):
    from . import dupes
    return dupes.move_to_trash(body.ids)


@app.get("/api/lixeira")
def api_trash():
    from . import dupes
    return dupes.trash_summary()


@app.post("/api/lixeira/restaurar")
def api_trash_restore(body: TrashReq):
    from . import dupes
    return dupes.restore(body.serial, body.ids or None)


@app.post("/api/lixeira/esvaziar")
def api_trash_empty(body: TrashReq):
    from . import dupes
    if not body.serial:
        raise HTTPException(400, "escolha o disco")
    return dupes.empty(body.serial)


# ---------------------------------------------------------------- Premiere

@app.get("/api/premiere/status")
def api_premiere_status():
    from . import premiere
    return premiere.status()


class PremiereReq(BaseModel):
    ids: list[int]
    bin: str = ""
    q: str = ""          # busca pelo que foi falado: cria subclipes nos trechos
    trechos: bool = False


@app.post("/api/premiere/importar")
def api_premiere_import(body: PremiereReq):
    from . import premiere
    from .search import _fts_query

    conn = connect()
    paths, offline, subclips = [], [], []
    for fid in body.ids[:500]:
        row = _file_row(fid)
        p = _real_path(row)
        if not p or not p.exists():
            offline.append(row["name"]); continue
        paths.append(str(p))
        if body.trechos and body.q and row["kind"] == "video":
            subclips += _speech_subclips(conn, fid, str(p), row, _fts_query(body.q))
    if not paths:
        raise HTTPException(409, "Os arquivos estão em discos desconectados.")
    bin_name = body.bin.strip() or ("BuscadorFAST - " + body.q.strip()[:40] if body.q.strip() else "BuscadorFAST")
    try:
        r = premiere.import_files(paths, bin_name, subclips)
    except (ConnectionError, TimeoutError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))
    return {**r, "offline": offline}


def _speech_subclips(conn, fid: int, path: str, row, fts: str, per_file: int = 5) -> list[dict]:
    """Um subclipe por trecho em que a frase foi dita (com folga antes e depois)."""
    if not fts:
        return []
    segs = conn.execute("SELECT start, end, text FROM transcripts WHERE file_id = ? ORDER BY start", (fid,)).fetchall()
    hits = {r[0] for r in conn.execute(
        "SELECT t.start FROM speech_fts s JOIN transcripts t ON t.id = s.rowid "
        "WHERE speech_fts MATCH ? AND t.file_id = ?", (fts, fid))}
    out, last_end = [], -1.0
    dur = row["duration"] or 1e9
    for i, s in enumerate(segs):
        if s["start"] not in hits or s["start"] < last_end:
            continue
        start = max(0.0, s["start"] - 1.5)
        end = min(dur, (segs[i + 1]["end"] if i + 1 < len(segs) else s["end"]) + 1.5)
        mm, ss = divmod(int(s["start"]), 60)
        out.append({"path": path, "start": round(start, 2), "end": round(end, 2),
                    "name": f"{Path(path).stem} {mm}:{ss:02d} – {s['text'][:40].strip()}"})
        last_end = end
        if len(out) >= per_file:
            break
    return out


# ---------------------------------------------------------------- transferir entre PC e celular

@app.get("/api/transferir")
def api_transfer():
    from . import transfer
    return {"dest": transfer.settings()["dest"], "received": transfer.received(), "outbox": transfer.outbox_list()}


@app.put("/api/transferir/enviar")
async def api_transfer_upload(request: Request, nome: str, modificado: float | None = None):
    """Recebe um arquivo do celular (o corpo da requisição é o próprio arquivo, em pedaços)."""
    from . import transfer
    folder = transfer.inbox_today()
    path = await transfer.receive(request.stream(), nome, folder, modificado)
    return {"name": path.name, "size": path.stat().st_size, "folder": str(folder)}


@app.post("/api/transferir/escolher")
def api_transfer_pick():
    """Abre a janela do Windows para escolher arquivos; a caixa do celular guarda só os caminhos."""
    from . import transfer
    paths = transfer.pick_files()
    for p in paths:
        transfer.outbox_add_path(p)
    return {"added": len(paths)}


@app.post("/api/transferir/concluir")
def api_transfer_done():
    """Depois de um lote vindo do celular: indexa a pasta do dia (miniaturas, IA, rostos…)."""
    from . import transfer
    folder = transfer.inbox_today()
    jobs.submit("scan", str(folder), only_new=True)
    return {"indexing": str(folder)}


class TransferDest(BaseModel):
    dest: str


@app.post("/api/transferir/destino")
def api_transfer_dest(body: TransferDest):
    from . import transfer
    try:
        return transfer.set_dest(body.dest)
    except OSError as exc:
        raise HTTPException(400, f"não consegui usar essa pasta: {exc}")


@app.post("/api/transferir/abrir-pasta")
def api_transfer_open():
    from . import transfer
    folder = Path(transfer.settings()["dest"])
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(folder)
    return {"ok": True}


class OutboxReq(BaseModel):
    ids: list[int]


@app.post("/api/transferir/caixa")
def api_outbox_add(body: OutboxReq):
    from . import transfer
    return {"added": transfer.outbox_add_files(body.ids)}


@app.get("/api/transferir/caixa/{oid}/baixar")
def api_outbox_download(oid: int):
    from . import transfer

    def real(fid):
        try:
            return _real_path(_file_row(fid))
        except HTTPException:
            return None
    p = transfer.outbox_path(oid, real)
    if not p or not p.exists():
        raise HTTPException(409, "o arquivo não está disponível (disco desconectado?)")
    return FileResponse(p, headers={"Content-Disposition": _attachment(p.name)})


@app.delete("/api/transferir/caixa/{oid}")
def api_outbox_remove(oid: int):
    from . import transfer
    transfer.outbox_remove(oid)
    return {"ok": True}


@app.get("/api/leitura")
def api_read_test_summary():
    from . import leitura
    return leitura.summary()


class ReadTestReq(BaseModel):
    horas: float = 3


@app.post("/api/leitura")
def api_read_test(body: ReadTestReq):
    """Lê os arquivos por até N horas, começando pelos testados há mais tempo."""
    jobs.submit("leitura", hours=max(0.1, min(body.horas, 24)))
    return jobs.status()


@app.get("/api/saude")
def api_disk_health(atualizar: bool = False):
    from . import saude
    try:
        return saude.report(force=atualizar)
    except Exception as exc:
        raise HTTPException(500, f"não consegui ler a saúde dos discos: {exc}")


# ---------------------------------------------------------------- atualização automática à noite

@app.get("/api/agenda")
def api_schedule():
    from . import agenda
    return agenda.status()


class ScheduleReq(BaseModel):
    on: bool
    start: str = "01:00"
    stop: str = "07:00"


@app.post("/api/agenda")
def api_schedule_set(body: ScheduleReq):
    from . import agenda
    try:
        return agenda.enable(body.start, body.stop) if body.on else agenda.disable()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))


# ---------------------------------------------------------------- acesso pelo celular

@app.get("/api/eu")
def api_whoami(request: Request):
    from . import rede
    return {"remote": not rede.is_local_request(request)}


@app.get("/api/rede")
def api_rede():
    from . import rede
    return rede.status()


class RedeReq(BaseModel):
    on: bool


@app.post("/api/rede")
def api_rede_set(body: RedeReq):
    from . import rede
    return rede.enable(app, body.on)


@app.post("/api/rede/fora-https")
def api_rede_https():
    from . import rede
    return rede.tailscale_https()


@app.post("/api/rede/nova-chave")
def api_rede_key():
    from . import rede
    return rede.new_key()


# ---------------------------------------------------------------- backup

@app.get("/api/backup")
def api_backup():
    from . import backup
    return backup.status()


@app.post("/api/backup/agora")
def api_backup_now():
    from . import backup
    try:
        return backup.run()
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc))


class BackupCfg(BaseModel):
    dest: str
    keep: int = 7


@app.post("/api/backup/config")
def api_backup_config(body: BackupCfg):
    from . import backup
    dest = body.dest.strip().strip('"')
    if len(dest) == 2 and dest[1] == ":":
        dest += "\\"
    if not Path(dest).exists():
        raise HTTPException(400, f"não encontrei {dest}")
    if Path(dest).resolve().drive.upper() == Path(__file__).resolve().drive.upper():
        raise HTTPException(400, "escolha um disco diferente do que guarda o programa")
    return backup.save_settings(dest=dest, keep=max(1, min(body.keep, 60)))


@app.post("/api/sair")
def api_sair():
    """Fecha o programa (o servidor roda sem janela quando aberto pelo BuscadorFAST.exe)."""
    import threading

    jobs.cancel()
    threading.Timer(0.5, lambda: os._exit(0)).start()  # responde antes de sair
    return {"ok": True}


@app.get("/api/drives")
def api_drives():
    return sorted(connected().values(), key=lambda d: d["letter"])


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
