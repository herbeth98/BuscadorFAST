"""Transcreve a fala dos vídeos (faster-whisper large-v3-turbo na GPU, em português, com filtro de voz VAD
que pula os silêncios) para buscar pelo que foi dito."""
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .db import connect

MODEL = "large-v3-turbo"   # bem mais rápido que o large-v3, com qualidade parecida em português
LANGUAGE = "pt"
VAD = {"min_silence_duration_ms": 500}  # filtro de voz: pula trechos sem fala (silêncio, só música)
SAMPLE_RATE = 16000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_lock = threading.Lock()
_model = None


def _load():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                import torch  # noqa: F401  carrega as DLLs de CUDA que o CTranslate2 também usa
                from faster_whisper import WhisperModel
                device = "cuda" if torch.cuda.is_available() else "cpu"
                _model = WhisperModel(MODEL, device=device, compute_type="float16" if device == "cuda" else "int8")
    return _model


def _audio(path: Path) -> np.ndarray:
    """Áudio mono 16 kHz pelo ffmpeg (lê qualquer formato de vídeo que o ffmpeg abre)."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True, timeout=1800, creationflags=NO_WINDOW,
    )
    return np.frombuffer(out.stdout, dtype=np.float32)


def transcribe(path: Path, audio: np.ndarray | None = None) -> list[tuple[float, float, str]]:
    audio = _audio(path) if audio is None else audio
    if len(audio) < SAMPLE_RATE:  # sem áudio ou menos de 1 segundo
        return []
    segments, _ = _load().transcribe(
        audio, language=LANGUAGE, vad_filter=True, vad_parameters=VAD, beam_size=1,
        condition_on_previous_text=False,
    )
    return [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]


def save(conn, file_id: int, segments: list[tuple[float, float, str]]) -> None:
    old = [r[0] for r in conn.execute("SELECT id FROM transcripts WHERE file_id = ?", (file_id,))]
    if old:
        conn.execute(f"DELETE FROM speech_fts WHERE rowid IN ({','.join(map(str, old))})")
        conn.execute("DELETE FROM transcripts WHERE file_id = ?", (file_id,))
    ids = [conn.execute("INSERT INTO transcripts(file_id, start, end, text) VALUES (?, ?, ?, ?)",
                        (file_id, s, e, t)).lastrowid for s, e, t in segments]
    for i, sid in enumerate(ids):
        window = " ".join(t for _, _, t in segments[i:i + 2])
        conn.execute("INSERT INTO speech_fts(rowid, text) VALUES (?, ?)", (sid, window))


def process_pending(progress: Callable[[dict], None] | None = None, stop=None, only_ids=None) -> dict:
    from .volumes import connected

    progress = progress or (lambda d: None)
    conn = connect()
    online = connected()
    rows = [r for r in conn.execute(
        """SELECT f.id, f.relpath, f.duration, f.sound_done, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id
           WHERE f.kind = 'video' AND f.speech_done = 0 AND f.has_thumb = 1 AND f.error IS NULL AND f.missing = 0
           ORDER BY f.id""").fetchall() if r["serial"] in online]  # precisa do arquivo original
    if only_ids is not None:  # só os arquivos que acabaram de chegar
        rows = [r for r in rows if r["id"] in only_ids]
    total = len(rows)
    total_secs = sum(r["duration"] or 0 for r in rows)
    progress({"phase": "transcrevendo a fala dos vídeos", "done": 0, "total": total})
    if not total:
        return {"total": 0, "with_speech": 0}
    from . import som
    from .prefetch import ahead

    _load()
    path_of = lambda r: Path(f"{online[r['serial']]['letter']}:{r['relpath']}")  # noqa: E731
    t0, last, with_speech, secs_done = time.time(), 0.0, 0, 0.0
    # o disco lê os próximos vídeos enquanto a placa transcreve o atual
    for n, (row, audio) in enumerate(ahead(rows, lambda r: _audio(path_of(r)), workers=2, depth=3, stop=stop), 1):
        if stop is not None and stop.is_set():
            break
        segments, events = [], None
        if not isinstance(audio, Exception):
            try:
                segments = transcribe(path_of(row), audio)
            except Exception:
                segments = []
            if not row["sound_done"]:  # aproveita o mesmo áudio para os sons (aplausos, fogos…)
                try:
                    events = som.analyze(path_of(row), audio)
                except Exception:
                    events = []
        save(conn, row["id"], segments)
        with_speech += bool(segments)
        conn.execute("UPDATE files SET speech_done = 1 WHERE id = ?", (row["id"],))
        if events is not None:
            som.save(conn, row["id"], events)
            conn.execute("UPDATE files SET sound_done = 1 WHERE id = ?", (row["id"],))
        conn.commit()
        secs_done += row["duration"] or 0
        if time.time() - last > 1 or n == total:
            last = time.time()
            speed = secs_done / max(last - t0, 1e-3)  # segundos de vídeo por segundo
            left = (total_secs - secs_done) / speed if speed else 0
            progress({"phase": "transcrevendo a fala dos vídeos", "done": n, "total": total,
                      "with_speech": with_speech, "eta_min": round(left / 60)})
    return {"total": total, "with_speech": with_speech, "seconds": round(time.time() - t0, 1)}


def segments_of(file_id: int) -> list[dict]:
    rows = connect().execute("SELECT start, end, text FROM transcripts WHERE file_id = ? ORDER BY start",
                             (file_id,)).fetchall()
    return [dict(r) for r in rows]
