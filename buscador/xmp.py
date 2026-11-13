"""Grava palavras-chave e nomes de pessoas no padrão XMP (Lightroom, Bridge, Premiere leem).

- RAW (ARW, CR2, NEF…): sempre num .xmp ao lado (padrão Adobe), acrescentando ao que o Lightroom já gravou.
- JPG, PNG, TIFF, HEIC, DNG, MP4, MOV: "dentro" do arquivo, ou num .xmp ao lado se você preferir.
- Formatos que não aceitam XMP dentro (MTS, AVI, MKV, BMP…): sempre .xmp ao lado.

Usa o ExifTool. A data de modificação do arquivo é preservada (-P).
"""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from .config import RAW_EXT
from .db import connect

EMBEDDABLE = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".dng", ".webp", ".mp4", ".mov", ".m4v",
              ".3gp"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def exiftool() -> str:
    found = shutil.which("exiftool")
    if found:
        return found
    for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ExifTool" / "ExifTool.exe",
              Path(r"C:\Program Files\ExifTool\ExifTool.exe")):
        if p.exists():
            return str(p)
    raise FileNotFoundError("ExifTool não está instalado (winget install OliverBetz.ExifTool).")


def keywords_for(conn, fid: int, include_ai: bool) -> tuple[list[str], list[str]]:
    """(palavras-chave, pessoas) do arquivo."""
    sources = ("user", "face", "lr", "ai", "desc") if include_ai else ("user", "face", "lr")
    rows = conn.execute(
        f"""SELECT t.name, ft.source FROM file_tags ft JOIN tags t ON t.id = ft.tag_id
            WHERE ft.file_id = ? AND ft.source IN ({','.join('?' * len(sources))})""", (fid, *sources)).fetchall()
    people = sorted({r[0] for r in rows if r[1] == "face"})
    # nomes vêm do banco em minúsculas quando viram palavra-chave: usa o nome como você digitou
    proper = {r[0].lower(): r[0] for r in conn.execute(
        "SELECT DISTINCT p.name FROM faces f JOIN people p ON p.id = f.person_id WHERE f.file_id = ?", (fid,))}
    people = sorted(proper.get(p, p) for p in people)
    kws = sorted({r[0] for r in rows if r[1] != "face"})
    return kws, people


def target_for(path: Path, mode: str) -> tuple[Path, bool]:
    """(arquivo onde gravar, é sidecar?)"""
    ext = path.suffix.lower()
    if ext in RAW_EXT:
        return path.with_suffix(".xmp"), True
    if ext not in EMBEDDABLE or mode == "ao_lado":
        # IMG_0001.JPG ao lado de IMG_0001.ARW: o .xmp do RAW é do Lightroom, não mistura
        raw_sibling = any(path.with_suffix(r).exists() or path.with_suffix(r.upper()).exists() for r in RAW_EXT)
        return (path.with_name(path.name + ".xmp") if raw_sibling else path.with_suffix(".xmp")), True
    return path, False


def _args(kws: list[str], people: list[str]) -> list[str]:
    args = []
    for k in kws + people:
        # tira antes e põe de novo: não duplica se já existir
        args += [f"-XMP-dc:Subject-={k}", f"-XMP-dc:Subject+={k}"]
    for p in people:
        h = f"Pessoas|{p}"
        args += [f"-XMP-lr:HierarchicalSubject-={h}", f"-XMP-lr:HierarchicalSubject+={h}"]
        args += [f"-XMP-iptcExt:PersonInImage-={p}", f"-XMP-iptcExt:PersonInImage+={p}"]
    return args


def write_one(path: Path, kws: list[str], people: list[str], mode: str) -> tuple[str, Path]:
    target, sidecar = target_for(path, mode)
    args = [exiftool(), "-charset", "filename=utf8", "-codedcharacterset=utf8", "-P", "-m", "-q", "-q"]
    if sidecar and not target.exists():
        # cria o .xmp a partir do original (leva junto data, câmera etc., como o Lightroom faz)
        args += ["-o", str(target), "-tagsfromfile", str(path), "-all:all"] + _args(kws, people) + [str(path)]
    else:
        args += ["-overwrite_original"] + _args(kws, people) + [str(target)]
    with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False, encoding="utf-8") as f:
        f.write("\n".join(args[1:]))  # argumentos num arquivo: acentos e caminhos longos sem problema
        argfile = f.name
    try:
        out = subprocess.run([args[0], "-@", argfile], capture_output=True, timeout=3600, creationflags=NO_WINDOW)
    finally:
        os.unlink(argfile)
    if out.returncode != 0 or not target.exists():
        raise RuntimeError((out.stderr or out.stdout).decode("utf-8", "replace").strip()[:300] or "erro no ExifTool")
    return ("sidecar" if sidecar else "dentro"), target


def write(ids: list[int], mode: str = "dentro", include_ai: bool = False,
          progress: Callable[[dict], None] | None = None, stop=None) -> dict:
    from .volumes import connected

    progress = progress or (lambda d: None)
    conn = connect()
    online = connected()
    res = {"dentro": 0, "sidecar": 0, "sem_palavras": 0, "desconectado": 0, "erros": [], "total": len(ids)}
    last = 0.0
    for n, fid in enumerate(ids, 1):
        if stop is not None and stop.is_set():
            break
        row = conn.execute("SELECT f.relpath, f.name, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id "
                           "WHERE f.id = ?", (fid,)).fetchone()
        info = online.get(row["serial"]) if row else None
        if not info:
            res["desconectado"] += 1
            continue
        path = Path(f"{info['letter']}:{row['relpath']}")
        kws, people = keywords_for(conn, fid, include_ai)
        if not kws and not people:
            res["sem_palavras"] += 1
            continue
        try:
            how, _ = write_one(path, kws, people, mode)
            res[how] += 1
            if how == "dentro":
                # o conteúdo mudou (a data não): atualiza o catálogo para não reprocessar nem confundir duplicados
                st = path.stat()
                conn.execute("UPDATE files SET size = ?, mtime = ?, qhash = NULL, fhash = NULL WHERE id = ?",
                             (st.st_size, st.st_mtime, fid))
                conn.commit()
        except Exception as exc:
            res["erros"].append(f"{row['name']}: {exc}")
        if time.time() - last > 1 or n == len(ids):
            last = time.time()
            progress({"phase": "gravando palavras-chave nos arquivos", "done": n, "total": len(ids)})
    res["erros"] = res["erros"][:20]
    return res
