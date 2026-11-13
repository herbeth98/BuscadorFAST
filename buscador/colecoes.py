"""Favoritos (⭐) e coleções montadas por você."""
from datetime import datetime

from .db import connect


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def set_favorite(ids: list[int], value: bool) -> int:
    conn = connect()
    conn.executemany("UPDATE files SET favorite = ? WHERE id = ?", [(1 if value else 0, i) for i in ids])
    conn.commit()
    return len(ids)


def list_all() -> dict:
    conn = connect()
    favs = conn.execute("SELECT COUNT(*) FROM files WHERE favorite = 1 AND missing = 0").fetchone()[0]
    rows = conn.execute(
        """SELECT c.id, c.name, COUNT(f.id) AS n,
                  (SELECT ci.file_id FROM collection_items ci JOIN files f2 ON f2.id = ci.file_id
                   WHERE ci.collection_id = c.id AND f2.has_thumb = 1 ORDER BY ci.added LIMIT 1) AS cover
           FROM collections c
           LEFT JOIN collection_items ci ON ci.collection_id = c.id
           LEFT JOIN files f ON f.id = ci.file_id AND f.missing = 0
           GROUP BY c.id ORDER BY c.name COLLATE NOCASE"""
    ).fetchall()
    return {"favorites": favs, "collections": [dict(r) for r in rows]}


def create(name: str) -> int:
    conn = connect()
    name = " ".join(name.split())
    row = conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    cid = conn.execute("INSERT INTO collections(name, created) VALUES (?, ?)", (name, _now())).lastrowid
    conn.commit()
    return cid


def rename(cid: int, name: str) -> None:
    conn = connect()
    conn.execute("UPDATE collections SET name = ? WHERE id = ?", (" ".join(name.split()), cid))
    conn.commit()


def delete(cid: int) -> None:
    """Apaga só a coleção; os arquivos continuam onde estão."""
    conn = connect()
    conn.execute("DELETE FROM collections WHERE id = ?", (cid,))
    conn.commit()


def add(cid: int, ids: list[int]) -> int:
    conn = connect()
    now = _now()
    before = conn.total_changes
    conn.executemany("INSERT OR IGNORE INTO collection_items(collection_id, file_id, added) VALUES (?, ?, ?)",
                     [(cid, i, now) for i in ids])
    conn.commit()
    return conn.total_changes - before


def remove(cid: int, ids: list[int]) -> None:
    conn = connect()
    conn.executemany("DELETE FROM collection_items WHERE collection_id = ? AND file_id = ?", [(cid, i) for i in ids])
    conn.commit()


def of_file(fid: int) -> list[dict]:
    rows = connect().execute(
        """SELECT c.id, c.name FROM collection_items ci JOIN collections c ON c.id = ci.collection_id
           WHERE ci.file_id = ? ORDER BY c.name COLLATE NOCASE""", (fid,)).fetchall()
    return [dict(r) for r in rows]


def name_of(cid: int) -> str | None:
    row = connect().execute("SELECT name FROM collections WHERE id = ?", (cid,)).fetchone()
    return row[0] if row else None
