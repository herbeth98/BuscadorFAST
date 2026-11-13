"""Remove do catálogo arquivos de pastas que não deveriam ter sido indexadas.

    python -m buscador.cleanup
"""
import os

from functools import lru_cache

from .config import is_code_project, is_sequence_frame, skip_dir_name
from .db import connect
from .faces import face_crop_path
from .media import thumb_path
from .volumes import connected

# Pontos de junção do Windows que antes eram seguidos por engano
JUNCTIONS = {"local settings", "application data", "my documents", "my pictures", "my music", "my videos",
             "cookies", "nethood", "printhood", "recent", "sendto", "start menu", "templates"}


def bad(relpath: str) -> bool:
    parts = [p for p in relpath.split("\\") if p]
    return (parts[-1].startswith("._") or is_sequence_frame(parts[-1])
            or any(p.lower() in JUNCTIONS or skip_dir_name(p) for p in parts[:-1]))


@lru_cache(maxsize=None)
def _code_folder(folder: str) -> bool:
    return is_code_project(folder)


def in_code_project(letter: str, relpath: str) -> bool:
    """Alguma pasta acima do arquivo é um projeto de software (tem .git, package.json…)?"""
    parts = [p for p in relpath.split("\\") if p][:-1]
    return any(_code_folder(f"{letter}:\\" + "\\".join(parts[:i])) for i in range(1, len(parts) + 1))


def main() -> None:
    conn = connect()
    online = connected()
    rows = conn.execute("SELECT f.id, f.relpath, f.kind, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id")
    victims = [r for r in rows if bad(r["relpath"]) or (
        r["serial"] in online and in_code_project(online[r["serial"]]["letter"], r["relpath"]))]
    for r in victims:
        for (face_id,) in conn.execute("SELECT id FROM faces WHERE file_id = ?", (r["id"],)).fetchall():
            face_crop_path(face_id).unlink(missing_ok=True)
        for frame in range(3 if r["kind"] == "video" else 1):
            thumb_path(r["serial"], r["id"], frame).unlink(missing_ok=True)
        conn.execute("DELETE FROM files_fts WHERE rowid = ?", (r["id"],))
        conn.execute("DELETE FROM files WHERE id = ?", (r["id"],))  # rostos, tags e vetores saem em cascata
    conn.commit()
    conn.execute("DELETE FROM people WHERE id NOT IN (SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL)")
    conn.commit()
    print(f"{len(victims)} arquivos removidos do catálogo (nada foi apagado do disco).")
    if victims:
        from .ai import invalidate_index
        from .faces import regroup
        invalidate_index()
        regroup()


if __name__ == "__main__":
    main()
