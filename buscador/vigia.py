"""Vigia os discos em tempo real (enquanto o programa está aberto).

- Arquivo apagado (ou mandado para a Lixeira) → sai da busca na hora.
- Renomeado ou movido no mesmo disco → o catálogo acompanha, mantendo palavras-chave, rostos, coleções.
- Arquivo novo ou alterado → quando terminar de ser copiado, é indexado sozinho (só ele).

Vigia as mesmas pastas do "Atualizar todos os discos" (C: só a pasta do usuário; os outros, inteiros),
e acompanha discos que são conectados ou desconectados.
"""
import threading
import time
from pathlib import Path

from .config import skip_dir_name
from .db import connect, refresh_fts

QUIET_SECONDS = 5     # espera o arquivo parar de mudar (cópia em andamento) antes de indexar
CHECK_DRIVES = 30     # de quanto em quanto tempo confere se um disco foi conectado/desconectado

_lock = threading.Lock()
_events: list[tuple[str, str, str | None, bool]] = []   # (tipo, caminho, destino, é pasta)
_pending_new: dict[str, tuple[float, int]] = {}         # caminho -> (último evento, último tamanho)
_watching: dict[str, object] = {}                       # serial -> observer
_status = {"running": False, "roots": [], "last": None}


def status() -> dict:
    with _lock:
        return {**_status, "waiting": len(_pending_new)}


# ---------------------------------------------------------------- eventos do Windows

def _handler():
    from watchdog.events import FileSystemEventHandler

    class H(FileSystemEventHandler):
        def on_any_event(self, e):
            if e.event_type not in ("created", "modified", "deleted", "moved"):
                return
            if e.event_type == "modified" and e.is_directory:
                return
            with _lock:
                _events.append((e.event_type, e.src_path, getattr(e, "dest_path", None) or None, e.is_directory))
    return H()


def _sync_watchers() -> None:
    """Liga a vigilância nos discos conectados e marcados; desliga nos que saíram."""
    from watchdog.observers import Observer

    from .atualizar import roots
    wanted = {r["serial"]: r for r in roots() if r["included"]}
    for serial in list(_watching):
        if serial not in wanted:
            obs = _watching.pop(serial)
            try:
                obs.stop()
            except Exception:
                pass
    for serial, r in wanted.items():
        if serial in _watching:
            continue
        try:
            obs = Observer()
            obs.schedule(_handler(), r["root"], recursive=True)
            obs.daemon = True
            obs.start()
            _watching[serial] = obs
        except Exception:
            continue
    with _lock:
        _status["roots"] = [wanted[s]["root"] for s in _watching if s in wanted]


# ---------------------------------------------------------------- aplicar no catálogo

def _volume_map() -> dict[str, int]:
    """Letra → id do disco no catálogo (só discos conectados)."""
    from .volumes import connected
    conn = connect()
    ids = {r["serial"]: r["id"] for r in conn.execute("SELECT id, serial FROM volumes")}
    return {d["letter"].upper(): ids[s] for s, d in connected().items() if s in ids}


def _split(path: str, vols: dict[str, int]) -> tuple[int, str] | None:
    p = Path(path)
    vid = vols.get(p.drive[:1].upper())
    return (vid, str(p)[len(p.drive):]) if vid else None


def _like(prefix: str) -> str:
    return prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "\\%"


def _gone(conn, vols, path: str, is_dir: bool) -> int:
    loc = _split(path, vols)
    if not loc:
        return 0
    vid, rel = loc
    if is_dir:
        cur = conn.execute("UPDATE files SET missing = 1 WHERE volume_id = ? AND missing = 0 AND relpath LIKE ? "
                           "ESCAPE '!'", (vid, _like(rel)))
    else:
        cur = conn.execute("UPDATE files SET missing = 1 WHERE volume_id = ? AND relpath = ? AND missing = 0",
                           (vid, rel))
    return cur.rowcount


def _moved(conn, vols, src: str, dest: str, is_dir: bool) -> None:
    from .scanner import classify
    s, d = _split(src, vols), _split(dest, vols)
    if not s:
        return
    into_skipped = any(skip_dir_name(p) for p in Path(dest).parts[1:])  # ex.: $Recycle.Bin, lixeira
    if not d or d[0] != s[0] or into_skipped or (not is_dir and not classify(Path(dest))):
        # foi para outro disco, para a Lixeira ou virou outra coisa: some daqui
        _gone(conn, vols, src, is_dir)
        if d and not is_dir and classify(Path(dest)):
            _queue_new(dest)
        return
    vid, old = s
    new = d[1]
    if is_dir:
        rows = conn.execute("SELECT id, relpath FROM files WHERE volume_id = ? AND relpath LIKE ? ESCAPE '!'",
                            (vid, _like(old))).fetchall()
        for r in rows:
            conn.execute("UPDATE OR IGNORE files SET relpath = ? WHERE id = ?", (new + r["relpath"][len(old):], r["id"]))
            refresh_fts(conn, r["id"])
        return
    row = conn.execute("SELECT id FROM files WHERE volume_id = ? AND relpath = ?", (vid, old)).fetchone()
    if not row:
        _queue_new(dest)
        return
    clash = conn.execute("SELECT id FROM files WHERE volume_id = ? AND relpath = ?", (vid, new)).fetchone()
    if clash:  # já existia um registro no destino: fica o que já estava, este some
        conn.execute("UPDATE files SET missing = 1 WHERE id = ?", (row["id"],))
        conn.execute("UPDATE files SET missing = 0 WHERE id = ?", (clash["id"],))
        return
    conn.execute("UPDATE files SET relpath = ?, name = ?, missing = 0 WHERE id = ?", (new, Path(dest).name, row["id"]))
    refresh_fts(conn, row["id"])


def _queue_new(path: str) -> None:
    from .scanner import classify
    if not classify(Path(path)) or path.endswith(".parte"):
        return
    with _lock:
        _pending_new[path] = (time.time(), -1)


def _apply(events) -> dict:
    conn = connect()
    vols = _volume_map()
    stats = {"apagados": 0, "movidos": 0, "novos": 0}
    for kind, src, dest, is_dir in events:
        try:
            if kind == "deleted":
                stats["apagados"] += _gone(conn, vols, src, is_dir)
                with _lock:
                    _pending_new.pop(src, None)
            elif kind == "moved":
                _moved(conn, vols, src, dest, is_dir)
                stats["movidos"] += 1
            elif not is_dir:
                _queue_new(src)
        except Exception:
            continue
    conn.commit()
    return stats


def _ready_new() -> list[str]:
    """Arquivos novos que pararam de mudar (terminaram de ser copiados)."""
    ready, now = [], time.time()
    with _lock:
        items = list(_pending_new.items())
    for path, (t, last_size) in items:
        if now - t < QUIET_SECONDS:
            continue
        try:
            size = Path(path).stat().st_size
            with open(path, "rb"):
                pass
        except OSError:
            if not Path(path).exists():
                with _lock:
                    _pending_new.pop(path, None)
            continue  # ainda bloqueado pela cópia
        if size != last_size:
            with _lock:
                _pending_new[path] = (now, size)  # confere de novo daqui a pouco
            continue
        ready.append(path)
        with _lock:
            _pending_new.pop(path, None)
    return ready


def _loop() -> None:
    from . import jobs
    last_sync = 0.0
    while True:
        try:
            if time.time() - last_sync > CHECK_DRIVES:
                last_sync = time.time()
                _sync_watchers()
            with _lock:
                batch = _events[:]
                _events.clear()
            if batch:
                st = _apply(batch)
                if st["apagados"] or st["movidos"]:
                    with _lock:
                        _status["last"] = {**st, "t": time.strftime("%H:%M:%S")}
            ready = _ready_new()
            if ready:
                jobs.submit_files(ready)
        except Exception:
            pass
        time.sleep(2)


def start() -> None:
    with _lock:
        if _status["running"]:
            return
        _status["running"] = True
    threading.Thread(target=_loop, daemon=True, name="vigia").start()
