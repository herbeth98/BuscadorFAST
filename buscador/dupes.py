"""Duplicados exatos (mesmo conteúdo byte a byte) e a lixeira do BuscadorFAST.

Como acha: arquivos de mesmo tamanho → hash rápido (início, meio e fim) → hash do arquivo inteiro.
Só o hash do arquivo inteiro conta como duplicado.

Como remove: move para X:\\BuscadorFAST-Lixeira\\<caminho original> no mesmo disco (instantâneo e
reversível). O espaço só é liberado ao esvaziar a lixeira.
"""
import hashlib
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .db import connect, refresh_fts
from .volumes import connected

TRASH_DIR = "BuscadorFAST-Lixeira"
CHUNK = 1024 * 1024
QUICK_PART = 256 * 1024


def _path(row, online: dict) -> Path | None:
    info = online.get(row["serial"])
    return Path(f"{info['letter']}:{row['relpath']}") if info else None


def quick_hash(path: Path, size: int) -> str:
    h = hashlib.blake2b(digest_size=16)
    h.update(str(size).encode())
    with open(path, "rb") as f:
        if size <= 3 * QUICK_PART:
            h.update(f.read())
        else:
            for pos in (0, size // 2, size - QUICK_PART):
                f.seek(pos)
                h.update(f.read(QUICK_PART))
    return h.hexdigest()


def full_hash(path: Path, stop=None) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK * 4):
            h.update(chunk)
            if stop is not None and stop.is_set():
                return None
    return h.hexdigest()


# ---------------------------------------------------------------- procurar

def find(progress: Callable[[dict], None] | None = None, stop=None) -> dict:
    progress = progress or (lambda d: None)
    conn = connect()
    online = connected()
    base = """FROM files f JOIN volumes v ON v.id = f.volume_id
              WHERE f.missing = 0 AND f.trashed = 0 AND f.size > 0"""

    # 1) só arquivos cujo tamanho aparece mais de uma vez podem ser duplicados
    rows = conn.execute(
        f"""SELECT f.id, f.relpath, f.size, f.mtime, f.qhash, f.fhash, f.hash_mtime, v.serial {base}
            AND f.size IN (SELECT size FROM files WHERE missing = 0 AND trashed = 0 GROUP BY size HAVING COUNT(*) > 1)
            ORDER BY f.size DESC"""
    ).fetchall()
    todo = [r for r in rows if not r["qhash"] and r["serial"] in online]
    progress({"phase": "comparando arquivos de mesmo tamanho", "done": 0, "total": len(todo)})
    last = 0.0
    for n, r in enumerate(todo, 1):
        if stop is not None and stop.is_set():
            return {"stopped": True}
        try:
            q = quick_hash(_path(r, online), r["size"])
            conn.execute("UPDATE files SET qhash = ? WHERE id = ?", (q, r["id"]))
        except OSError:
            pass
        if time.time() - last > 1 or n == len(todo):
            last = time.time()
            conn.commit()
            progress({"phase": "comparando arquivos de mesmo tamanho", "done": n, "total": len(todo)})
    conn.commit()

    # 2) confirma com o arquivo inteiro os que bateram no hash rápido
    rows = conn.execute(
        f"""SELECT f.id, f.relpath, f.size, f.mtime, f.fhash, f.hash_mtime, v.serial {base}
            AND f.qhash IN (SELECT qhash FROM files WHERE qhash IS NOT NULL AND missing = 0 AND trashed = 0
                            GROUP BY qhash HAVING COUNT(*) > 1)"""
    ).fetchall()
    todo = [r for r in rows if r["serial"] in online and (not r["fhash"] or r["hash_mtime"] != r["mtime"])]
    total_bytes = sum(r["size"] for r in todo) or 1
    done_bytes, last = 0, 0.0
    for n, r in enumerate(todo, 1):
        if stop is not None and stop.is_set():
            return {"stopped": True}
        try:
            fh = full_hash(_path(r, online), stop)
            if fh:
                conn.execute("UPDATE files SET fhash = ?, hash_mtime = ? WHERE id = ?", (fh, r["mtime"], r["id"]))
                conn.commit()
        except OSError:
            pass
        done_bytes += r["size"]
        if time.time() - last > 1 or n == len(todo):
            last = time.time()
            progress({"phase": "confirmando duplicados (lendo o arquivo inteiro)", "done": n, "total": len(todo),
                      "pct_bytes": round(100 * done_bytes / total_bytes)})
    conn.commit()
    s = summary()
    progress({"phase": "concluído", "done": 1, "total": 1, **s})
    return s


def summary() -> dict:
    row = connect().execute(
        """SELECT COUNT(*) AS groups, COALESCE(SUM(waste), 0) AS waste, COALESCE(SUM(n - 1), 0) AS extra FROM (
               SELECT fhash, COUNT(*) AS n, (COUNT(*) - 1) * MAX(size) AS waste FROM files
               WHERE fhash IS NOT NULL AND missing = 0 AND trashed = 0 GROUP BY fhash HAVING COUNT(*) > 1)"""
    ).fetchone()
    return dict(row)


# ---------------------------------------------------------------- listar e sugerir

def groups(prefer_serial: str = "", kind: str = "", limit: int = 100, offset: int = 0) -> dict:
    conn = connect()
    online = connected()
    kind_sql = "AND kind = ?" if kind else ""
    params = [kind] if kind else []
    heads = conn.execute(
        f"""SELECT fhash, COUNT(*) AS n, MAX(size) AS size, (COUNT(*) - 1) * MAX(size) AS waste FROM files
            WHERE fhash IS NOT NULL AND missing = 0 AND trashed = 0 {kind_sql}
            GROUP BY fhash HAVING COUNT(*) > 1 ORDER BY waste DESC LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    out = []
    for h in heads:
        copies = [dict(r) for r in conn.execute(
            """SELECT f.id, f.name, f.relpath, f.kind, f.size, f.mtime, f.taken_at, f.has_thumb,
                      v.serial, v.label AS volume,
                      (SELECT COUNT(*) FROM file_tags ft WHERE ft.file_id = f.id AND ft.source != 'ai')
                      + f.favorite * 5
                      + (SELECT COUNT(*) FROM collection_items ci WHERE ci.file_id = f.id) * 5 AS my_tags
               FROM files f JOIN volumes v ON v.id = f.volume_id
               WHERE f.fhash = ? AND f.missing = 0 AND f.trashed = 0""", (h["fhash"],))]
        for c in copies:
            info = online.get(c["serial"])
            c["online"] = info is not None
            c["full_path"] = f"{info['letter']}:{c['relpath']}" if info else f"[{c['volume']}]{c['relpath']}"
        keep = suggest_keep(copies, prefer_serial)
        for c in copies:
            c["keep"] = c["id"] == keep
        out.append({"fhash": h["fhash"], "n": h["n"], "size": h["size"], "waste": h["waste"], "copies": copies})
    return {**summary(), "items": out}


def suggest_keep(copies: list[dict], prefer_serial: str = "") -> int:
    """Qual cópia manter: no disco preferido > conectada > com palavras-chave suas > mais antiga > caminho mais curto."""
    def score(c):
        return (
            0 if prefer_serial and c["serial"] == prefer_serial else 1,
            0 if c["online"] else 1,
            -c["my_tags"],
            c["mtime"] or 0,
            len(c["relpath"]),
        )
    return min(copies, key=score)["id"]


# ---------------------------------------------------------------- lixeira

def _row(conn, fid: int):
    return conn.execute(
        """SELECT f.id, f.relpath, f.size, f.mtime, f.fhash, f.hash_mtime, f.trashed, f.missing, v.serial
           FROM files f JOIN volumes v ON v.id = f.volume_id WHERE f.id = ?""", (fid,)).fetchone()


def _same_on_disk(row, path: Path) -> bool:
    """O arquivo ainda é o mesmo que foi conferido (tamanho e data não mudaram desde o hash)?"""
    try:
        st = path.stat()
    except OSError:
        return False
    return st.st_size == row["size"] and row["hash_mtime"] is not None and abs(st.st_mtime - row["hash_mtime"]) < 2


def move_to_trash(remove_ids: list[int]) -> dict:
    """Move cópias duplicadas para a lixeira. Recusa qualquer uma que deixaria o grupo sem cópia segura."""
    conn = connect()
    online = connected()
    moved, refused = [], []
    for fid in remove_ids:
        r = _row(conn, fid)
        if not r or r["trashed"] or r["missing"] or not r["fhash"]:
            refused.append({"id": fid, "motivo": "não está na lista de duplicados"}); continue
        src = _path(r, online)
        if not src or not _same_on_disk(r, src):
            refused.append({"id": fid, "motivo": "disco desconectado ou arquivo mudou; procure duplicados de novo"})
            continue
        # precisa sobrar pelo menos uma cópia conectada, idêntica, que não esteja sendo removida
        keepers = [k for k in conn.execute(
            """SELECT f.id, f.relpath, f.size, f.mtime, f.fhash, f.hash_mtime, v.serial FROM files f
               JOIN volumes v ON v.id = f.volume_id
               WHERE f.fhash = ? AND f.id != ? AND f.missing = 0 AND f.trashed = 0""", (r["fhash"], fid))
            if k["id"] not in remove_ids]
        safe = next((k for k in keepers if (p := _path(k, online)) and _same_on_disk(k, p)), None)
        if not safe:
            refused.append({"id": fid, "motivo": "ficaria sem nenhuma cópia conectada e conferida"}); continue

        drive = src.drive
        dest = Path(f"{drive}\\{TRASH_DIR}{r['relpath']}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}~{fid}{dest.suffix}")
        try:
            os.replace(src, dest)  # mesmo disco: só muda o arquivo de pasta
        except OSError as exc:
            refused.append({"id": fid, "motivo": f"não consegui mover: {exc}"}); continue
        _merge_metadata(conn, fid, safe["id"])
        conn.execute("UPDATE files SET trashed = 1, missing = 1 WHERE id = ?", (fid,))
        conn.execute("INSERT INTO trash(file_id, kept_file_id, trash_relpath, size, moved_at) VALUES (?, ?, ?, ?, ?)",
                     (fid, safe["id"], str(dest)[len(drive):], r["size"], datetime.now().isoformat(timespec="seconds")))
        conn.execute("DELETE FROM files_fts WHERE rowid = ?", (fid,))
        conn.commit()
        moved.append({"id": fid, "size": r["size"]})
    return {"moved": len(moved), "bytes": sum(m["size"] for m in moved), "refused": refused}


def trash_files(ids: list[int]) -> dict:
    """Manda arquivos (não duplicados) para a lixeira do BuscadorFAST — usado em "Para revisar".
    Dá para restaurar; o espaço só é liberado ao esvaziar a lixeira daquele disco."""
    conn = connect()
    online = connected()
    moved, failed = [], []
    for fid in ids:
        r = _row(conn, fid)
        if not r or r["trashed"] or r["missing"]:
            continue
        src = _path(r, online)
        if not src or not src.exists():
            failed.append(fid); continue
        dest = Path(f"{src.drive}\\{TRASH_DIR}{r['relpath']}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}~{fid}{dest.suffix}")
        try:
            os.replace(src, dest)
        except OSError:
            failed.append(fid); continue
        conn.execute("UPDATE files SET trashed = 1, missing = 1 WHERE id = ?", (fid,))
        conn.execute("INSERT INTO trash(file_id, kept_file_id, trash_relpath, size, moved_at) VALUES (?, NULL, ?, ?, ?)",
                     (fid, str(dest)[len(src.drive):], r["size"], datetime.now().isoformat(timespec="seconds")))
        conn.execute("DELETE FROM files_fts WHERE rowid = ?", (fid,))
        conn.commit()
        moved.append(r["size"] or 0)
    return {"moved": len(moved), "bytes": sum(moved), "failed": len(failed)}


def _merge_metadata(conn, from_id: int, to_id: int) -> None:
    """Palavras-chave suas, favorito e coleções da cópia removida passam para a cópia mantida."""
    conn.execute(
        """INSERT OR IGNORE INTO file_tags(file_id, tag_id, source, score)
           SELECT ?, tag_id, source, score FROM file_tags WHERE file_id = ? AND source = 'user'""", (to_id, from_id))
    conn.execute("UPDATE files SET favorite = 1 WHERE id = ? AND (SELECT favorite FROM files WHERE id = ?) = 1",
                 (to_id, from_id))
    conn.execute(
        """INSERT OR IGNORE INTO collection_items(collection_id, file_id, added)
           SELECT collection_id, ?, added FROM collection_items WHERE file_id = ?""", (to_id, from_id))
    refresh_fts(conn, to_id)


def trash_summary() -> list[dict]:
    conn = connect()
    online = connected()
    rows = conn.execute(
        """SELECT v.serial, v.label, COUNT(*) AS n, SUM(t.size) AS bytes FROM trash t
           JOIN files f ON f.id = t.file_id JOIN volumes v ON v.id = f.volume_id GROUP BY v.serial"""
    ).fetchall()
    return [{**dict(r), "online": r["serial"] in online} for r in rows]


def restore(serial: str = "", ids: list[int] | None = None) -> dict:
    conn = connect()
    online = connected()
    rows = conn.execute(
        """SELECT t.id AS tid, t.trash_relpath, f.id, f.relpath, v.serial FROM trash t
           JOIN files f ON f.id = t.file_id JOIN volumes v ON v.id = f.volume_id"""
    ).fetchall()
    rows = [r for r in rows if (not serial or r["serial"] == serial) and (not ids or r["id"] in ids)]
    restored, failed = 0, 0
    for r in rows:
        info = online.get(r["serial"])
        if not info:
            failed += 1; continue
        src = Path(f"{info['letter']}:{r['trash_relpath']}")
        dest = Path(f"{info['letter']}:{r['relpath']}")
        try:
            if dest.exists():
                raise FileExistsError(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dest)
        except OSError:
            failed += 1; continue
        conn.execute("UPDATE files SET trashed = 0, missing = 0 WHERE id = ?", (r["id"],))
        conn.execute("DELETE FROM trash WHERE id = ?", (r["tid"],))
        refresh_fts(conn, r["id"])
        conn.commit()
        restored += 1
    return {"restored": restored, "failed": failed}


def empty(serial: str) -> dict:
    """Apaga de vez a lixeira de um disco (libera o espaço). Não dá para desfazer."""
    from .faces import face_crop_path
    from .media import thumb_path

    conn = connect()
    info = connected().get(serial)
    if not info:
        return {"deleted": 0, "bytes": 0, "error": "disco desconectado"}
    rows = conn.execute(
        """SELECT t.id AS tid, t.trash_relpath, t.size, f.id, f.kind FROM trash t
           JOIN files f ON f.id = t.file_id JOIN volumes v ON v.id = f.volume_id WHERE v.serial = ?""", (serial,)
    ).fetchall()
    deleted, freed = 0, 0
    for r in rows:
        p = Path(f"{info['letter']}:{r['trash_relpath']}")
        try:
            p.unlink(missing_ok=True)
        except OSError:
            continue
        for (face_id,) in conn.execute("SELECT id FROM faces WHERE file_id = ?", (r["id"],)).fetchall():
            face_crop_path(face_id).unlink(missing_ok=True)
        for frame in range(3 if r["kind"] == "video" else 1):
            thumb_path(serial, r["id"], frame).unlink(missing_ok=True)
        conn.execute("DELETE FROM files WHERE id = ?", (r["id"],))  # tira do catálogo (trash sai em cascata)
        conn.commit()
        deleted += 1
        freed += r["size"] or 0
    root = Path(f"{info['letter']}:\\{TRASH_DIR}")
    if root.exists() and not conn.execute(
            "SELECT 1 FROM trash t JOIN files f ON f.id = t.file_id JOIN volumes v ON v.id = f.volume_id "
            "WHERE v.serial = ? LIMIT 1", (serial,)).fetchone():
        # remove as pastas vazias que sobraram
        for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass
    return {"deleted": deleted, "bytes": freed}
