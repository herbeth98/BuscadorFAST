"""Backup do catálogo em outro disco.

Em <destino>\\BuscadorFAST-Backup:
  catalogo-AAAA-MM-DD_HHMM.zip   cópia do banco (nomes de pessoas, palavras-chave, transcrições…); guarda as últimas N
  thumbs\\, faces\\               espelho das miniaturas e recortes de rosto (só copia o que mudou)

O banco é copiado com a API de backup do SQLite, então funciona com o programa aberto e indexando.
"""
import json
import shutil
import sqlite3
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR, DB_PATH, THUMB_DIR

SETTINGS = DATA_DIR / "backup.json"
FOLDER = "BuscadorFAST-Backup"
DEFAULTS = {"dest": "", "keep": 7, "every_hours": 24, "last": None, "last_error": None}
_lock = threading.Lock()


def _default_dest() -> str:
    """Sem disco escolhido: outro disco que não o do Windows (o com mais espaço livre); sem outro, o do programa."""
    import os
    import string
    system = (os.environ.get("SystemDrive") or "C:").upper()[:1]
    best, free = "", -1
    for letter in string.ascii_uppercase[2:]:
        drive = f"{letter}:\\"
        if letter == system or not os.path.exists(drive):
            continue
        try:
            f = shutil.disk_usage(drive).free
        except OSError:
            continue
        if f > free:
            best, free = drive, f
    return best or Path(DATA_DIR).anchor


def settings() -> dict:
    try:
        s = {**DEFAULTS, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (FileNotFoundError, ValueError):
        s = dict(DEFAULTS)
    if not s.get("dest"):
        s["dest"] = _default_dest()
    return s


def save_settings(**kw) -> dict:
    s = {**settings(), **kw}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return s


def root(s: dict | None = None) -> Path:
    return Path((s or settings())["dest"]) / FOLDER


def _mirror(src: Path, dst: Path) -> int:
    """Copia arquivos novos ou alterados e remove do espelho o que não existe mais. Devolve quantos copiou."""
    copied = 0
    if not src.exists():
        return 0
    seen = set()
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        seen.add(rel)
        out = dst / rel
        st = f.stat()
        try:
            ost = out.stat()
            if ost.st_size == st.st_size and ost.st_mtime >= st.st_mtime - 1:
                continue
        except FileNotFoundError:
            pass
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
        copied += 1
    if dst.exists():
        for f in dst.rglob("*"):
            if f.is_file() and f.relative_to(dst) not in seen:
                f.unlink(missing_ok=True)
    return copied


def run() -> dict:
    """Faz um backup agora. Levanta erro se o destino não estiver disponível."""
    from .faces import FACE_DIR

    with _lock:
        s = settings()
        dest_drive = Path(s["dest"])
        if not dest_drive.exists():
            save_settings(last_error=f"destino {s['dest']} não está conectado")
            raise FileNotFoundError(f"O destino do backup ({s['dest']}) não está conectado.")
        if dest_drive.resolve().drive.upper() == DATA_DIR.resolve().drive.upper():
            raise ValueError("Escolha um disco diferente do que guarda o programa; senão o backup não protege nada.")
        t0 = time.time()
        r = root(s)
        r.mkdir(parents=True, exist_ok=True)

        # 1) banco: cópia consistente mesmo com o programa gravando
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        tmp_db = r / f".catalogo-{stamp}.db"
        src = sqlite3.connect(DB_PATH, timeout=90)
        dst = sqlite3.connect(tmp_db)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        zpath = r / f"catalogo-{stamp}.zip"
        with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(tmp_db, "catalogo.db")
            for extra in ("backup.json",):
                if (DATA_DIR / extra).exists():
                    z.write(DATA_DIR / extra, extra)
        tmp_db.unlink(missing_ok=True)

        # 2) guarda só as últimas N cópias do banco
        zips = sorted(r.glob("catalogo-*.zip"))
        for old in zips[:-max(1, int(s["keep"]))]:
            old.unlink(missing_ok=True)

        # 3) espelho de miniaturas e rostos (necessários para ver discos desconectados)
        copied = _mirror(THUMB_DIR, r / "thumbs") + _mirror(FACE_DIR, r / "faces")

        info = {"file": str(zpath), "size": zpath.stat().st_size, "copied": copied,
                "seconds": round(time.time() - t0, 1)}
        save_settings(last=datetime.now().isoformat(timespec="seconds"), last_error=None)
        return info


def status() -> dict:
    s = settings()
    r = root(s)
    online = Path(s["dest"]).exists()
    backups = []
    if online and r.exists():
        for z in sorted(r.glob("catalogo-*.zip"), reverse=True):
            backups.append({"name": z.name, "size": z.stat().st_size,
                            "date": datetime.fromtimestamp(z.stat().st_mtime).isoformat(timespec="minutes")})
    return {**s, "online": online, "path": str(r), "backups": backups,
            "program_drive": DATA_DIR.resolve().drive[:1].upper()}


def due() -> bool:
    s = settings()
    if not s["last"]:
        return True
    try:
        age = (datetime.now() - datetime.fromisoformat(s["last"])).total_seconds()
    except ValueError:
        return True
    return age >= float(s["every_hours"]) * 3600


def start_scheduler() -> None:
    """Com o programa aberto, confere a cada 30 min se já passou o intervalo e faz o backup."""
    def loop():
        time.sleep(60)  # deixa o programa terminar de abrir
        while True:
            try:
                if due() and Path(settings()["dest"]).exists():
                    run()
            except Exception as exc:
                save_settings(last_error=f"{type(exc).__name__}: {exc}")
            time.sleep(1800)

    threading.Thread(target=loop, daemon=True, name="backup").start()


def restore(zip_path: str) -> str:
    """Substitui o catálogo pelo de um backup. O programa precisa estar fechado.
    O catálogo atual é guardado antes como data\\catalogo-antes-de-restaurar-<data>.db."""
    import urllib.request

    try:
        urllib.request.urlopen("http://127.0.0.1:8765/api/jobs", timeout=2)
        raise RuntimeError("Feche o BuscadorFAST (botão ⏻) antes de restaurar um backup.")
    except OSError:
        pass  # fechado: pode seguir
    zp = Path(zip_path)
    with zipfile.ZipFile(zp) as z:
        if "catalogo.db" not in z.namelist():
            raise ValueError("Esse arquivo não é um backup do BuscadorFAST.")
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safety = DATA_DIR / f"catalogo-antes-de-restaurar-{stamp}.db"
        if DB_PATH.exists():
            src = sqlite3.connect(DB_PATH)
            dst = sqlite3.connect(safety)
            src.backup(dst)
            dst.close(); src.close()
        for side in ("-wal", "-shm"):
            Path(str(DB_PATH) + side).unlink(missing_ok=True)
        with z.open("catalogo.db") as fin, open(DB_PATH, "wb") as fout:
            shutil.copyfileobj(fin, fout)
    # miniaturas e rostos que faltarem voltam do espelho
    from .faces import FACE_DIR
    r = zp.parent
    for name, local in (("thumbs", THUMB_DIR), ("faces", FACE_DIR)):
        mirror = r / name
        if mirror.exists():
            for f in mirror.rglob("*"):
                out = local / f.relative_to(mirror)
                if f.is_file() and not out.exists():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, out)
    return str(safety)
