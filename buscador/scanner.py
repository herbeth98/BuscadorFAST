"""Percorre uma pasta ou disco e atualiza o catálogo (só processa o que é novo ou mudou)."""
import os
from functools import lru_cache
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import (IMAGE_EXT, MIN_IMAGE_BYTES, RAW_EXT, VIDEO_EXT, is_code_project, is_sequence_frame,
                     skip_dir_name)
from .db import connect, refresh_fts
from .media import date_from_name, image_meta_and_thumb, raw_meta_and_thumb, thumb_path, video_meta_and_thumbs
from .volumes import register

Progress = Callable[[dict], None]


def _walk(root: Path):
    """Gera (caminho, tipo, ext, tamanho, mtime) e, de vez em quando, None — um "pulso" para o
    chamador gravar o banco mesmo atravessando pastas sem nenhuma foto ou vídeo."""
    stack = [root]
    seen = 0
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    seen += 1
                    if seen % 500 == 0:
                        yield None
                    try:
                        if e.is_dir(follow_symlinks=False):
                            # Pontos de junção ("My Documents", "Local Settings"…) apontam para outras
                            # pastas: seguir isso duplica arquivos e entra no AppData
                            attrs = getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0)
                            if e.is_junction() or attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                                continue
                            # pastas de sistema, programas, jogos, IA e projetos de software ficam de fora
                            if not skip_dir_name(e.name) and not is_code_project(e.path):
                                stack.append(Path(e.path))
                            continue
                        if e.name.startswith("._") or is_sequence_frame(e.name):  # lixo do macOS; quadros de animação
                            continue
                        ext = os.path.splitext(e.name)[1].lower()
                        if ext in IMAGE_EXT:
                            kind = "image"
                        elif ext in VIDEO_EXT:
                            kind = "video"
                        else:
                            continue
                        st = e.stat()
                        if kind == "image" and st.st_size < MIN_IMAGE_BYTES:
                            continue
                        yield Path(e.path), kind, ext, st.st_size, st.st_mtime
                    except OSError:
                        continue
        except OSError:
            continue


def _process(serial: str, file_id: int, path: Path, kind: str) -> tuple[int, dict | None, str | None]:
    try:
        dest = thumb_path(serial, file_id)
        if kind == "video":
            meta = video_meta_and_thumbs(path, dest)
        elif path.suffix.lower() in RAW_EXT:
            meta = raw_meta_and_thumb(path, dest)
        else:
            meta = image_meta_and_thumb(path, dest)
        return file_id, meta, None
    except Exception as exc:  # arquivo corrompido, formato raro etc.
        return file_id, None, f"{type(exc).__name__}: {exc}"[:300]


def scan(root: str | Path, progress: Progress | None = None, workers: int = 6, stop=None) -> dict:
    """`stop`: objeto com is_set() (threading.Event ou control.StopSignal) para interromper no meio."""
    root = Path(root).resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    progress = progress or (lambda d: None)
    vid, vinfo = register(root)
    serial = vinfo["serial"]
    drive = root.drive  # "E:"
    conn = connect()

    stats = {"found": 0, "new": 0, "changed": 0, "unchanged": 0, "errors": 0, "missing": 0, "stopped": False}
    stopped = (lambda: stop is not None and stop.is_set())
    seen: set[int] = set()
    todo: list[tuple[int, Path, str]] = []

    progress({"phase": "listando arquivos", "root": str(root), **stats})
    t0 = last_commit = time.time()
    for item in _walk(root):
        if stopped():
            stats["stopped"] = True
            break
        if item is None or time.time() - last_commit > 2:  # grava sempre: não deixa o banco travado para a tela
            conn.commit()
            last_commit = time.time()
            progress({"phase": "listando arquivos", "root": str(root), **stats})
            if item is None:
                continue
        path, kind, ext, size, mtime = item
        stats["found"] += 1
        fid, needs_work = _register(conn, vid, drive, path, kind, ext, size, mtime, stats)
        seen.add(fid)
        if needs_work:
            todo.append((fid, path, kind))
    conn.commit()

    # Arquivos que estavam no catálogo nesta pasta e sumiram do disco
    # (se a listagem foi interrompida, não dá para saber o que sumiu: pula)
    prefix = str(root)[len(drive):].rstrip("\\")
    like = prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "\\%"
    gone = [] if stats["stopped"] else [
        r[0] for r in conn.execute(
            "SELECT id FROM files WHERE volume_id = ? AND missing = 0 AND (relpath LIKE ? ESCAPE '!' OR ? = '')",
            (vid, like, prefix),
        )
        if r[0] not in seen
    ]
    for fid in gone:
        conn.execute("UPDATE files SET missing = 1 WHERE id = ?", (fid,))
    stats["missing"] = len(gone)
    conn.commit()

    # Metadados + miniaturas em paralelo
    total = len(todo)
    progress({"phase": "lendo metadados e miniaturas", "done": 0, "total": total, **stats})
    done = _thumbs(conn, serial, todo, stats, stopped, progress, workers)
    stats["seconds"] = round(time.time() - t0, 1)
    progress({"phase": "parado" if stats["stopped"] else "concluído", "done": done, "total": total, **stats})
    return {**stats, "new_ids": [fid for fid, _, _ in todo]}


def _register(conn, vid: int, drive: str, path: Path, kind: str, ext: str, size: int, mtime: float,
              stats: dict) -> tuple[int, bool]:
    """Põe (ou atualiza) um arquivo no catálogo. Devolve (id, precisa de miniatura/metadados?)."""
    rel = str(path)[len(drive):]
    row = conn.execute("SELECT id, size, mtime, has_thumb, missing FROM files WHERE volume_id = ? AND relpath = ?",
                       (vid, rel)).fetchone()
    if row and row["size"] == size and abs((row["mtime"] or 0) - mtime) < 2 and row["has_thumb"]:
        if row["missing"]:
            conn.execute("UPDATE files SET missing = 0 WHERE id = ?", (row["id"],))
        stats["unchanged"] += 1
        return row["id"], False
    if row:
        conn.execute(
            "UPDATE files SET size=?, mtime=?, missing=0, ai_done=0, faces_done=0, has_thumb=0, error=NULL, "
            "qhash=NULL, fhash=NULL, ocr_done=0, speech_done=0, desc_done=0, quality_done=0, lr_done=0, sound_done=0 WHERE id=?", (size, mtime, row["id"]))
        stats["changed"] += 1
        return row["id"], True
    # OR IGNORE: a vigilância de pastas e uma indexação podem chegar no mesmo arquivo ao mesmo tempo
    conn.execute("INSERT OR IGNORE INTO files(volume_id, relpath, name, ext, kind, size, mtime) VALUES (?,?,?,?,?,?,?)",
                 (vid, rel, path.name, ext, kind, size, mtime))
    stats["new"] += 1
    return conn.execute("SELECT id FROM files WHERE volume_id = ? AND relpath = ?", (vid, rel)).fetchone()[0], True


@lru_cache(maxsize=20000)
def _in_code_project(folder: Path) -> bool:
    """Alguma pasta acima é um projeto de software? (para arquivos vistos um a um pela vigilância).
    Guardado em memória: milhares de arquivos da mesma pasta não repetem a consulta ao disco."""
    if folder == Path(folder.anchor):
        return False
    return is_code_project(folder) or _in_code_project(folder.parent)


def classify(path: Path) -> tuple[str, str] | None:
    """(tipo, extensão) se for foto ou vídeo que entra no catálogo; senão None."""
    if path.name.startswith("._") or is_sequence_frame(path.name) or any(
            skip_dir_name(p) for p in path.parts[1:-1]) or _in_code_project(path.parent):
        return None
    ext = path.suffix.lower()
    kind = "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else None
    return (kind, ext) if kind else None


def scan_paths(paths, progress: Progress | None = None, stop=None) -> dict:
    """Indexa só estes arquivos (usado pela vigilância de pastas quando um arquivo novo aparece)."""
    progress = progress or (lambda d: None)
    stopped = (lambda: stop is not None and stop.is_set())
    conn = connect()
    stats = {"found": 0, "new": 0, "changed": 0, "unchanged": 0, "errors": 0, "missing": 0, "stopped": False}
    new_ids: list[int] = []
    by_drive: dict[str, list[Path]] = {}
    for p in {Path(p) for p in paths}:
        by_drive.setdefault(p.drive.upper(), []).append(p)
    for drive, plist in by_drive.items():
        vid, vinfo = register(plist[0])
        todo = []
        last = time.time()
        for p in plist:
            if stopped():
                break
            if time.time() - last > 2:  # grava sempre: não segura o banco (as outras etapas esperam por ele)
                conn.commit(); last = time.time()
                progress({"phase": "conferindo arquivos novos", "found": stats["found"]})
            c = classify(p)
            try:
                st = p.stat()
            except OSError:
                continue
            if not c or (c[0] == "image" and st.st_size < MIN_IMAGE_BYTES):
                continue
            stats["found"] += 1
            fid, needs_work = _register(conn, vid, p.drive, p, c[0], c[1], st.st_size, st.st_mtime, stats)
            if needs_work:
                todo.append((fid, p, c[0]))
        conn.commit()
        _thumbs(conn, vinfo["serial"], todo, stats, stopped, progress, workers=4)
        new_ids += [fid for fid, _, _ in todo]
    return {**stats, "new_ids": new_ids}


def _thumbs(conn, serial: str, todo, stats: dict, stopped, progress: Progress, workers: int) -> int:
    """Metadados + miniaturas em paralelo. Devolve quantos foram feitos."""
    total = len(todo)
    done = 0
    last_progress = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_process, serial, fid, path, kind) for fid, path, kind in todo]
        for fut in as_completed(futures):
            if stopped():
                stats["stopped"] = True
                for f in futures:
                    f.cancel()  # os que já começaram terminam; o resto fica para a próxima indexação
                break
            fid, meta, err = fut.result()
            if err:
                stats["errors"] += 1
                conn.execute("UPDATE files SET error = ?, ai_done = 1 WHERE id = ?", (err, fid))
            else:
                if not meta.get("taken_at"):
                    # sem data da câmera: tenta o nome do arquivo (IMG_20240315…), senão a data de modificação
                    r = conn.execute("SELECT name, mtime FROM files WHERE id = ?", (fid,)).fetchone()
                    meta["taken_at"] = (date_from_name(r["name"])
                                        or datetime.fromtimestamp(r["mtime"]).isoformat(timespec="seconds"))
                cols = ["width", "height", "duration", "taken_at", "camera", "gps_lat", "gps_lon"]
                conn.execute(
                    f"UPDATE files SET {', '.join(c + '=?' for c in cols)}, has_thumb = 1 WHERE id = ?",
                    [meta.get(c) for c in cols] + [fid],
                )
            refresh_fts(conn, fid)
            done += 1
            conn.commit()  # o próximo arquivo pode demorar (vídeo grande no HD): não segura o banco
            if time.time() - last_progress > 1:
                last_progress = time.time()
                progress({"phase": "lendo metadados e miniaturas", "done": done, "total": total, **stats})
    conn.commit()
    return done
