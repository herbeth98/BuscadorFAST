"""Transferir arquivos entre o PC e o celular.

Celular → PC: o arquivo chega em pedaços direto na pasta de destino (<destino>\\AAAA-MM-DD\\), sem passar
por arquivo temporário; depois a pasta é indexada.
PC → celular: a "caixa do celular" guarda só o caminho dos arquivos (do catálogo ou escolhidos na
janela do Windows) — nada é copiado; o celular vê a lista e baixa direto do lugar original.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR, IMAGE_EXT, VIDEO_EXT
from .db import connect

SETTINGS = DATA_DIR / "transferencia.json"
DEFAULT_DEST = str(DATA_DIR.parent.parent / "BuscadorFAST-Recebidos")  # D:\BuscadorFAST-Recebidos
OUTBOX = "Para o celular"

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id      INTEGER PRIMARY KEY,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,  -- arquivo do catálogo, ou
    path    TEXT,                                            -- arquivo enviado pelo PC (cópia na caixa)
    name    TEXT NOT NULL,
    size    INTEGER,
    added   TEXT
);
"""


def _conn():
    conn = connect()
    conn.executescript(SCHEMA)
    return conn


def settings() -> dict:
    try:
        return {"dest": DEFAULT_DEST, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (FileNotFoundError, ValueError):
        return {"dest": DEFAULT_DEST}


def set_dest(dest: str) -> dict:
    p = Path(dest.strip().strip('"'))
    p.mkdir(parents=True, exist_ok=True)
    s = {**settings(), "dest": str(p)}
    SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return s


def safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return (name or "arquivo")[:180]


def unique(folder: Path, name: str) -> Path:
    p = folder / name
    n = 1
    while p.exists():
        n += 1
        p = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
    return p


def inbox_today() -> Path:
    folder = Path(settings()["dest"]) / datetime.now().strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


async def receive(stream, name: str, folder: Path, mtime_ms: float | None = None) -> Path:
    """Grava o corpo da requisição direto no disco. Se a conexão cair, apaga o pedaço."""
    final = unique(folder, safe_name(name))
    part = final.with_name(final.name + ".parte")
    try:
        with open(part, "wb") as f:
            async for chunk in stream:
                f.write(chunk)
        os.replace(part, final)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if mtime_ms:
        t = mtime_ms / 1000
        os.utime(final, (t, t))  # mantém a data original do arquivo do celular
    return final


def received(limit: int = 60) -> list[dict]:
    """Últimos arquivos que chegaram do celular."""
    root = Path(settings()["dest"])
    if not root.exists():
        return []
    files = [p for p in root.rglob("*") if p.is_file() and p.parent.name != OUTBOX and not p.name.endswith(".parte")]
    files.sort(key=lambda p: p.stat().st_ctime, reverse=True)
    conn = connect()
    out = []
    for p in files[:limit]:
        row = conn.execute("SELECT id FROM files WHERE relpath = ? AND missing = 0", (str(p)[len(p.drive):],)).fetchone()
        out.append({"name": p.name, "size": p.stat().st_size, "folder": p.parent.name, "path": str(p),
                    "file_id": row[0] if row else None,
                    "media": p.suffix.lower() in IMAGE_EXT | VIDEO_EXT,  # só fotos e vídeos entram no catálogo
                    "when": datetime.fromtimestamp(p.stat().st_ctime).isoformat(timespec="minutes")})
    return out


# ---------------------------------------------------------------- caixa do celular (PC → celular)

def outbox_add_files(ids: list[int]) -> int:
    conn = _conn()
    now = datetime.now().isoformat(timespec="seconds")
    have = {r[0] for r in conn.execute("SELECT file_id FROM outbox WHERE file_id IS NOT NULL")}
    added = 0
    for fid in ids:
        if fid in have:
            continue
        row = conn.execute("SELECT name, size FROM files WHERE id = ?", (fid,)).fetchone()
        if row:
            conn.execute("INSERT INTO outbox(file_id, name, size, added) VALUES (?, ?, ?, ?)",
                         (fid, row["name"], row["size"], now))
            added += 1
    conn.commit()
    return added


PICKER = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false; Opacity = 0}
$owner.Show(); $owner.Activate()
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Multiselect = $true
$d.Title = 'Escolha os arquivos para mandar ao celular'
if ($d.ShowDialog($owner) -eq 'OK') { $d.FileNames -join "`n" }
$owner.Close()
"""


def pick_files() -> list[Path]:
    """Abre a janela "Abrir arquivo" do Windows no PC e devolve os caminhos escolhidos (nada é copiado)."""
    import subprocess
    out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", PICKER],
                         capture_output=True, timeout=1800)
    text = out.stdout.decode("utf-8", "replace").strip()
    return [Path(line) for line in text.splitlines() if line.strip() and Path(line.strip()).is_file()]


def outbox_add_path(path: Path) -> int:
    conn = _conn()
    oid = conn.execute("INSERT INTO outbox(path, name, size, added) VALUES (?, ?, ?, ?)",
                       (str(path), path.name, path.stat().st_size,
                        datetime.now().isoformat(timespec="seconds"))).lastrowid
    conn.commit()
    return oid


def outbox_list() -> list[dict]:
    conn = _conn()
    # arquivo que você apagou ou moveu no PC sai da caixa sozinho
    for r in conn.execute("SELECT id, path FROM outbox WHERE path IS NOT NULL").fetchall():
        if not Path(r["path"]).exists():
            conn.execute("DELETE FROM outbox WHERE id = ?", (r["id"],))
    conn.commit()
    rows = conn.execute(
        """SELECT o.id, o.file_id, o.path, o.name, o.size, o.added, f.kind, f.has_thumb
           FROM outbox o LEFT JOIN files f ON f.id = o.file_id ORDER BY o.added DESC, o.id DESC""").fetchall()
    return [dict(r) for r in rows]


def outbox_path(oid: int, real_path) -> Path | None:
    """Caminho atual de um item da caixa (None se o disco estiver desconectado)."""
    row = _conn().execute("SELECT file_id, path FROM outbox WHERE id = ?", (oid,)).fetchone()
    if not row:
        return None
    if row["path"]:
        return Path(row["path"])
    return real_path(row["file_id"])


def outbox_remove(oid: int) -> None:
    """Tira da caixa. O arquivo no PC não é tocado (a caixa só guarda o caminho)."""
    conn = _conn()
    conn.execute("DELETE FROM outbox WHERE id = ?", (oid,))
    conn.commit()
