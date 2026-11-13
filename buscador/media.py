"""Lê metadados (EXIF, ffprobe) e gera miniaturas de fotos e quadros de vídeos."""
import json
import re
import subprocess
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import ExifTags, Image, ImageOps

from .config import THUMB_DIR, THUMB_SIZE

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # sem suporte a HEIC; o resto funciona
    pass

Image.MAX_IMAGE_PIXELS = 400_000_000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VIDEO_FRAMES = (0.1, 0.5, 0.85)  # posições (fração da duração) dos quadros que a IA analisa


_NAME_DATE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"  # 20240315 / 2024-03-15
    r"(?:(?:[ _T-]|\sat\s|\s?às\s)?([01]\d|2[0-3])[.:\-h]?([0-5]\d)[.:\-m]?([0-5]\d))?(?!\d{3})"
)
_PT_MONTHS = {m: i for i, m in enumerate(["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out",
                                          "nov", "dez"], 1)}
_PT_DATE = re.compile(r"(?<!\d)(\d{1,2})[-_ ]de[-_ ](jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-zç]*[-_ ]de[-_ ]"
                      r"((?:19|20)\d{2})", re.I)


def date_from_name(name: str) -> str | None:
    """Data no nome do arquivo: IMG_20240315_143012, WhatsApp Image 2025-01-10 at 14.30.12,
    dji_fly_20230116_182844, HS20260209_0138, 6-de-nov-de-2026… Devolve ISO ou None."""
    m = _NAME_DATE.search(name)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(hh or 12), int(mm or 0), int(ss or 0))
        except ValueError:
            dt = None
        if dt and 1990 <= dt.year <= datetime.now().year + 1:
            return dt.isoformat()
    m = _PT_DATE.search(name)
    if m:
        try:
            return datetime(int(m.group(3)), _PT_MONTHS[m.group(2).lower()[:3]], int(m.group(1)), 12).isoformat()
        except ValueError:
            pass
    return None


def thumb_path(serial: str, file_id: int, frame: int = 0) -> Path:
    suffix = f"_{frame}" if frame else ""
    return THUMB_DIR / serial / f"{file_id}{suffix}.webp"


def thumb_paths(serial: str, file_id: int, kind: str) -> list[Path]:
    """Miniaturas que a IA deve analisar: uma para foto, três para vídeo."""
    n = len(VIDEO_FRAMES) if kind == "video" else 1
    return [p for p in (thumb_path(serial, file_id, i) for i in range(n)) if p.exists()]


# ---------------------------------------------------------------- fotos

def _gps_to_float(values, ref) -> float | None:
    try:
        d, m, s = (float(v) for v in values)
        val = d + m / 60 + s / 3600
        return -val if ref in ("S", "W") else val
    except Exception:
        return None


def _exif_date(text: str | None) -> str | None:
    if not text:
        return None
    try:
        return datetime.strptime(text.strip()[:19], "%Y:%m:%d %H:%M:%S").isoformat()
    except ValueError:
        return None


def raw_meta_and_thumb(src: Path, dest: Path) -> dict:
    """Fotos RAW (ARW, CR2, NEF, DNG…): usa o JPEG de prévia que a câmera grava dentro do arquivo."""
    import numpy as np
    import rawpy

    with rawpy.imread(str(src)) as raw:
        w, h, flip = raw.sizes.width, raw.sizes.height, raw.sizes.flip
        try:
            th = raw.extract_thumb()
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            th = None
        if th is not None and th.format == rawpy.ThumbFormat.JPEG:
            data = th.data
        else:
            arr = th.data if th is not None else raw.postprocess(half_size=True, use_camera_wb=True)
            buf = BytesIO()
            Image.fromarray(np.asarray(arr)).save(buf, "PNG")
            data = buf.getvalue()
    meta = image_meta_and_thumb(BytesIO(data), dest)
    if not meta.get("camera") or not meta.get("taken_at"):
        try:  # muitos RAW são TIFF por dentro: o Pillow consegue ler o EXIF do arquivo original
            with Image.open(src) as im:
                for k, v in _exif_meta(im.getexif()).items():
                    if not meta.get(k):
                        meta[k] = v
        except Exception:
            pass
    meta["width"], meta["height"] = (h, w) if flip in (5, 6) else (w, h)
    return meta


def _exif_meta(exif) -> dict:
    meta: dict = {}
    if not exif:
        return meta
    ifd = exif.get_ifd(ExifTags.IFD.Exif)
    meta["taken_at"] = _exif_date(ifd.get(0x9003) or ifd.get(0x9004) or exif.get(0x0132))
    make = (exif.get(0x010F) or "").strip("\x00 ")
    model = (exif.get(0x0110) or "").strip("\x00 ")
    if model:
        meta["camera"] = model if make and make.split()[0].lower() in model.lower() else f"{make} {model}".strip()
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    if gps and 2 in gps and 4 in gps:
        meta["gps_lat"] = _gps_to_float(gps[2], gps.get(1))
        meta["gps_lon"] = _gps_to_float(gps[4], gps.get(3))
    return {k: v for k, v in meta.items() if v}


def image_meta_and_thumb(src, dest: Path) -> dict:
    meta: dict = {}
    with Image.open(src) as im:
        meta["width"], meta["height"] = im.size
        exif = im.getexif()
        if exif:
            meta.update(_exif_meta(exif))
            orientation = exif.get(0x0112)
            if orientation in (5, 6, 7, 8):
                meta["width"], meta["height"] = meta["height"], meta["width"]
        if im.format == "JPEG":
            im.draft("RGB", (THUMB_SIZE * 2, THUMB_SIZE * 2))  # decodifica em escala menor: bem mais rápido
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "WEBP", quality=80, method=4)
    return meta


# ---------------------------------------------------------------- vídeos

_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def _probe(src: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(src)],
        capture_output=True, timeout=60, creationflags=NO_WINDOW,
    )
    return json.loads(out.stdout or b"{}")


def _frame(src: Path, t: float) -> Image.Image | None:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
         "-vf", f"scale='min({THUMB_SIZE},iw)':-2", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, timeout=60, creationflags=NO_WINDOW,
    )
    if not out.stdout:
        return None
    return Image.open(BytesIO(out.stdout)).convert("RGB")


def _frames_fast(src: Path, times: list[float]) -> list[Image.Image] | None:
    """Os quadros de uma vez só, decodificando apenas quadros-chave (3 a 4× mais rápido em vídeo 4K)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["ffmpeg", "-v", "error", "-y"]
        for t in times:
            cmd += ["-skip_frame", "nokey", "-ss", f"{t:.2f}", "-i", str(src)]
        outs = [Path(tmp) / f"{i}.png" for i in range(len(times))]
        for i, out in enumerate(outs):
            cmd += ["-map", f"{i}:v:0", "-frames:v", "1", "-vf", f"scale='min({THUMB_SIZE * 2},iw)':-2", str(out)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return None
        if not all(o.exists() and o.stat().st_size for o in outs):
            return None
        return [Image.open(o).convert("RGB") for o in outs]


def video_meta_and_thumbs(src: Path, dest0: Path) -> dict:
    info = _probe(src)
    fmt = info.get("format", {})
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    meta: dict = {}
    try:
        meta["duration"] = float(fmt.get("duration"))
    except (TypeError, ValueError):
        pass
    vstream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if vstream:
        w, h = vstream.get("width"), vstream.get("height")
        rot = 0
        for sd in vstream.get("side_data_list", []) or []:
            rot = int(sd.get("rotation", 0) or 0) or rot
        rot = rot or int((vstream.get("tags") or {}).get("rotate", 0) or 0)
        if abs(rot) in (90, 270):
            w, h = h, w
        meta["width"], meta["height"] = w, h
        tags.update({k.lower(): v for k, v in (vstream.get("tags") or {}).items() if k.lower() not in tags})

    created = tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time")
    if created:
        try:
            meta["taken_at"] = datetime.fromisoformat(created.replace("Z", "+00:00")).replace(tzinfo=None).isoformat()
        except ValueError:
            pass
    model = tags.get("com.apple.quicktime.model") or tags.get("model")
    if model:
        make = tags.get("com.apple.quicktime.make") or tags.get("make") or ""
        meta["camera"] = f"{make} {model}".strip() if make and make.lower() not in model.lower() else model
    loc = tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
    if loc and (m := _ISO6709.match(loc)):
        meta["gps_lat"], meta["gps_lon"] = float(m.group(1)), float(m.group(2))

    if not vstream:
        raise ValueError("arquivo sem trilha de vídeo")
    dur = meta.get("duration") or 0
    dest0.parent.mkdir(parents=True, exist_ok=True)
    times = [dur * frac if dur > 2 else min(i, max(dur - 0.1, 0)) for i, frac in enumerate(VIDEO_FRAMES)]
    frames = _frames_fast(src, times)
    if frames:
        for i, frame in enumerate(frames):
            frame.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
            frame.save(dest0 if i == 0 else dest0.with_name(f"{dest0.stem}_{i}.webp"), "WEBP", quality=80, method=4)
        return meta
    got = 0  # reserva: um quadro por vez (mais lento, mas acha o quadro exato)
    for i, frac in enumerate(VIDEO_FRAMES):
        t = dur * frac if dur > 2 else min(i, max(dur - 0.1, 0))
        frame = _frame(src, t)
        if frame is None and i == 0:
            frame = _frame(src, 0)
        if frame is None:
            continue
        frame.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
        dest = dest0 if i == 0 else dest0.with_name(f"{dest0.stem}_{i}.webp")
        frame.save(dest, "WEBP", quality=80, method=4)
        got += 1
    if not got:
        raise ValueError("não consegui extrair quadros do vídeo")
    return meta
