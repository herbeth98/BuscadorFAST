"""Sons dos vídeos: aplausos, torcida, fogos, música, sanfona… com o momento em que acontecem.

Uma IA treinada no AudioSet (527 tipos de som) escuta o vídeo em trechos de 3 s (a cada 1,5 s). Trechos
seguidos com o mesmo som viram um "evento" (ex.: aplausos de 0:42 a 0:51), guardado com a intensidade.
"Momentos altos" = aplausos + torcida + fogos, os picos de emoção de um evento.
"""
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .db import connect

MODEL = "MIT/ast-finetuned-audioset-10-10-0.4593"
SR = 16000
WIN, HOP = 3.0, 1.5          # segundos
BATCH = 48
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# nome em português → (emoji, sons do AudioSet, certeza mínima)
SOUNDS: dict[str, tuple[str, list[str], float]] = {
    "aplausos": ("👏", ["Applause", "Clapping"], 0.25),
    "torcida": ("📣", ["Cheering", "Children shouting", "Shout", "Yell", "Whoop"], 0.25),
    "multidão": ("👥", ["Crowd", "Hubbub, speech noise, speech babble"], 0.35),
    "fogos": ("🎆", ["Fireworks", "Firecracker", "Explosion"], 0.2),
    "música": ("🎵", ["Music"], 0.45),
    "canto": ("🎤", ["Singing", "Choir", "Male singing", "Female singing"], 0.3),
    "sanfona": ("🪗", ["Accordion"], 0.2),
    "percussão": ("🥁", ["Drum", "Drum kit", "Bass drum", "Percussion", "Snare drum"], 0.3),
    "risadas": ("😂", ["Laughter", "Giggle", "Chuckle, chortle", "Belly laugh"], 0.25),
    "buzina": ("📯", ["Vehicle horn, car horn, honking", "Air horn, truck horn"], 0.25),
    "sirene": ("🚨", ["Siren", "Police car (siren)", "Ambulance (siren)", "Emergency vehicle"], 0.3),
    "balido": ("🐑", ["Sheep", "Bleat", "Goat"], 0.2),
    "mugido": ("🐄", ["Cattle, bovinae", "Moo"], 0.2),
    "cavalo": ("🐎", ["Horse", "Neigh, whinny", "Clip-clop"], 0.25),
    "cachorro": ("🐕", ["Dog", "Bark", "Howl"], 0.3),
    "chuva": ("🌧", ["Rain", "Rain on surface", "Raindrop"], 0.3),
}
HIGHLIGHT = ("aplausos", "torcida", "fogos")  # "momentos altos"

# palavras que você pode digitar → som
SYNONYMS = {
    "aplauso": "aplausos", "aplausos": "aplausos", "palmas": "aplausos", "aplaudindo": "aplausos",
    "torcida": "torcida", "gritos": "torcida", "gritaria": "torcida", "comemoracao": "torcida", "vibracao": "torcida",
    "multidao": "multidão", "publico": "multidão",
    "fogos": "fogos", "foguetes": "fogos", "foguetorio": "fogos", "bombas": "fogos", "rojao": "fogos", "rojoes": "fogos",
    "musica": "música", "banda": "música", "show": "música",
    "canto": "canto", "cantando": "canto", "cantoria": "canto", "cantor": "canto", "cantora": "canto",
    "sanfona": "sanfona", "acordeon": "sanfona", "sanfoneiro": "sanfona", "forro": "sanfona",
    "percussao": "percussão", "bateria": "percussão", "tambor": "percussão", "zabumba": "percussão",
    "risada": "risadas", "risadas": "risadas", "risos": "risadas", "gargalhada": "risadas",
    "buzina": "buzina", "buzinaco": "buzina", "sirene": "sirene",
    "balido": "balido", "berro": "balido", "berros": "balido", "berrando": "balido", "berrar": "balido",
    "balindo": "balido", "mugido": "mugido", "mugindo": "mugido", "relincho": "cavalo", "relinchando": "cavalo",
    "latido": "cachorro", "latindo": "cachorro", "chuva": "chuva",
}
HIGHLIGHT_WORDS = ("momentos altos", "momento alto", "auge", "climax", "emocao", "pico")

_lock = threading.Lock()
_model = _fe = None
_idx: dict[str, list[int]] = {}


def _load():
    global _model, _fe
    if _model is None:
        with _lock:
            if _model is None:
                import torch
                from transformers import ASTFeatureExtractor, ASTForAudioClassification
                _fe = ASTFeatureExtractor.from_pretrained(MODEL)
                device = "cuda" if torch.cuda.is_available() else "cpu"
                _model = ASTForAudioClassification.from_pretrained(MODEL).to(device).eval()
                names = {v: int(k) for k, v in _model.config.id2label.items()}
                for pt, (_, labels, _) in SOUNDS.items():
                    _idx[pt] = [names[l] for l in labels if l in names]
    return _model, _fe


def _audio(path: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, timeout=1800, creationflags=NO_WINDOW)
    return np.frombuffer(out.stdout, dtype=np.float32)


def analyze(path: Path, audio: np.ndarray | None = None) -> list[tuple[str, float, float, float]]:
    """[(som, início, fim, força)] — força = certeza do som × volume (0 a 1)."""
    import torch

    audio = _audio(path) if audio is None else audio
    if len(audio) < SR:
        return []
    model, fe = _load()
    w, h = int(WIN * SR), int(HOP * SR)
    starts = list(range(0, max(1, len(audio) - w + 1), h))
    windows = [audio[s:s + w] for s in starts]
    rms = np.array([np.sqrt(np.mean(x ** 2)) + 1e-9 for x in windows])
    loud = np.clip((20 * np.log10(rms) + 50) / 40, 0.1, 1.0)  # -50 dB → 0,1 … -10 dB → 1
    probs = []
    for i in range(0, len(windows), BATCH):
        feats = fe(windows[i:i + BATCH], sampling_rate=SR, return_tensors="pt")
        with torch.inference_mode():
            logits = model(**{k: v.to(model.device) for k, v in feats.items()}).logits
        probs.append(torch.sigmoid(logits).float().cpu().numpy())
    probs = np.concatenate(probs)
    events = []
    for pt, (_, _, thr) in SOUNDS.items():
        score = probs[:, _idx[pt]].max(axis=1) if _idx[pt] else np.zeros(len(windows))
        on = score >= thr
        i = 0
        while i < len(on):
            if not on[i]:
                i += 1; continue
            j = i
            while j + 1 < len(on) and on[j + 1]:
                j += 1
            strength = float(np.max(score[i:j + 1] * loud[i:j + 1]))
            events.append((pt, starts[i] / SR, starts[j] / SR + WIN, round(strength, 3)))
            i = j + 1
    return events


def save(conn, file_id: int, events) -> None:
    conn.execute("DELETE FROM sound_events WHERE file_id = ?", (file_id,))
    conn.executemany("INSERT INTO sound_events(file_id, label, start, end, score) VALUES (?, ?, ?, ?, ?)",
                     [(file_id, *e) for e in events])


def process_pending(progress: Callable[[dict], None] | None = None, stop=None, only_ids=None) -> dict:
    from .volumes import connected

    progress = progress or (lambda d: None)
    conn = connect()
    online = connected()
    rows = [r for r in conn.execute(
        """SELECT f.id, f.relpath, f.duration, v.serial FROM files f JOIN volumes v ON v.id = f.volume_id
           WHERE f.kind = 'video' AND f.sound_done = 0 AND f.has_thumb = 1 AND f.error IS NULL AND f.missing = 0
           ORDER BY f.id""").fetchall() if r["serial"] in online]  # precisa do arquivo original
    if only_ids is not None:
        rows = [r for r in rows if r["id"] in only_ids]
    total = len(rows)
    progress({"phase": "ouvindo os sons dos vídeos", "done": 0, "total": total})
    if not total:
        return {"total": 0}
    _load()
    t0, last, found = time.time(), 0.0, 0
    for n, r in enumerate(rows, 1):
        if stop is not None and stop.is_set():
            break
        try:
            ev = analyze(Path(f"{online[r['serial']]['letter']}:{r['relpath']}"))
        except Exception:
            ev = []
        save(conn, r["id"], ev)
        found += bool(ev)
        conn.execute("UPDATE files SET sound_done = 1 WHERE id = ?", (r["id"],))
        conn.commit()
        if time.time() - last > 1 or n == total:
            last = time.time()
            progress({"phase": "ouvindo os sons dos vídeos", "done": n, "total": total})
    return {"total": total, "with_sounds": found, "seconds": round(time.time() - t0, 1)}


def wanted(query: str) -> list[str] | None:
    """Que sons a busca pede? None se a busca não é sobre som."""
    from .db import normalize
    q = normalize(query)
    if any(w in q for w in HIGHLIGHT_WORDS):
        return list(HIGHLIGHT)
    labels = [SYNONYMS[w] for w in q.split() if w in SYNONYMS]
    return list(dict.fromkeys(labels)) or None


def wanted_any(query: str) -> list[str] | None:
    """No modo "Sons nos vídeos", aceita também o nome do som como aparece na lista (ex.: "percussão")."""
    from .db import normalize
    q = normalize(query)
    return [k for k in SOUNDS if normalize(k) in q] or None


def hits(conn, labels: list[str]) -> dict[int, dict]:
    """Arquivos com esses sons → o momento mais forte, e quantas vezes acontece."""
    marks = ",".join("?" * len(labels))
    out: dict[int, dict] = {}
    for fid, label, start, score, n in conn.execute(
            f"""SELECT file_id, label, start, score, COUNT(*) OVER (PARTITION BY file_id) FROM sound_events
                WHERE label IN ({marks}) ORDER BY score DESC""", labels):
        if fid not in out:
            out[fid] = {"sound_start": start, "sound_label": f"{SOUNDS[label][0]} {label}", "sound_score": score,
                        "sound_count": n}
    return out


def events_of(file_id: int) -> list[dict]:
    rows = connect().execute("SELECT label, start, end, score FROM sound_events WHERE file_id = ? ORDER BY start",
                             (file_id,)).fetchall()
    return [{"label": r["label"], "emoji": SOUNDS.get(r["label"], ("🔊",))[0], "start": r["start"], "end": r["end"],
             "score": r["score"]} for r in rows]
