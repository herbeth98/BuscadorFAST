"""Saúde dos discos: o que o Windows sabe de cada disco físico (sem precisar de administrador).

Para cada disco: modelo, tipo, letras, espaço livre, temperatura, horas ligado, desgaste e erros.
Guarda os contadores de erro de um dia para o outro e avisa se eles aumentarem.
Caixas USB (como as dos SSDs externos) costumam não repassar os dados internos: aí só vale o que o
Windows informa (saúde geral) e o espaço livre.
"""
import json
import subprocess
import time
from datetime import datetime

from .config import DATA_DIR

HISTORY = DATA_DIR / "saude.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$out = foreach ($d in Get-PhysicalDisk) {
  $r = $null; try { $r = $d | Get-StorageReliabilityCounter -ErrorAction Stop } catch {}
  $vols = foreach ($p in (Get-Partition -DiskNumber $d.DeviceId -ErrorAction SilentlyContinue | Where-Object DriveLetter)) {
    $v = Get-Volume -DriveLetter $p.DriveLetter -ErrorAction SilentlyContinue
    if ($v) { [pscustomobject]@{ letter = "$($p.DriveLetter)"; label = $v.FileSystemLabel; size = $v.Size; free = $v.SizeRemaining } }
  }
  [pscustomobject]@{
    id = $d.DeviceId; serial = "$($d.SerialNumber)".Trim(); model = $d.FriendlyName; media = "$($d.MediaType)"; bus = "$($d.BusType)"
    size = $d.Size; health = "$($d.HealthStatus)"; status = ($d.OperationalStatus -join ', ')
    temp = $r.Temperature; tempMax = $r.TemperatureMax; wear = $r.Wear; hours = $r.PowerOnHours
    startStop = $r.StartStopCycleCount; readCorr = $r.ReadErrorsCorrected; readUncorr = $r.ReadErrorsUncorrected
    writeUncorr = $r.WriteErrorsUncorrected; volumes = @($vols)
  }
}
@($out) | ConvertTo-Json -Depth 4 -Compress
"""

_cache: dict = {"t": 0.0, "data": None}


def _read() -> list[dict]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", PS], capture_output=True, timeout=90,
                         creationflags=NO_WINDOW)
    data = json.loads(out.stdout.decode("utf-8", "replace") or "[]")
    return data if isinstance(data, list) else [data]


def _num(v):
    return v if isinstance(v, (int, float)) and v > 0 else None


def _evaluate(d: dict, prev: dict | None) -> tuple[str, list[str]]:
    """('ok' | 'atencao' | 'problema', motivos)."""
    problems, warnings = [], []
    if d["health"] not in ("Healthy", "0", ""):
        problems.append(f"o Windows indica saúde \"{d['health']}\"")
    if d["status"] and "OK" not in d["status"]:
        problems.append(f"estado do disco: {d['status']}")
    if _num(d.get("readUncorr")):
        problems.append(f"{d['readUncorr']} erro(s) de leitura não corrigido(s) — faça backup desse disco")
    if _num(d.get("writeUncorr")):
        problems.append(f"{d['writeUncorr']} erro(s) de escrita não corrigido(s) — faça backup desse disco")
    temp = _num(d.get("temp"))
    hot = 55 if d["media"] == "HDD" else 70
    if temp and temp >= hot:
        warnings.append(f"temperatura alta: {temp} °C")
    wear = _num(d.get("wear"))
    if wear and wear >= 80:
        warnings.append(f"desgaste em {wear}% da vida útil")
    if d["media"] == "HDD" and (_num(d.get("hours")) or 0) > 35000:
        warnings.append(f"HD com muitas horas de uso ({d['hours']:,} h)".replace(",", "."))
    if prev and _num(d.get("readCorr")) and (prev.get("readCorr") or 0) < d["readCorr"]:
        warnings.append(f"erros de leitura corrigidos aumentaram ({prev.get('readCorr') or 0} → {d['readCorr']})")
    for v in d.get("volumes") or []:
        if v.get("size") and v.get("free") is not None and v["free"] / v["size"] < 0.10:
            warnings.append(f"{v['letter']}: quase cheio ({v['free'] / 1e9:.0f} GB livres)")
    if problems:
        return "problema", problems + warnings
    return ("atencao", warnings) if warnings else ("ok", [])


def report(force: bool = False) -> dict:
    if not force and _cache["data"] and time.time() - _cache["t"] < 120:
        return _cache["data"]
    disks = _read()
    try:
        history = json.loads(HISTORY.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        history = {}
    out = []
    for d in disks:
        key = d.get("serial") or d.get("model")
        prev = history.get(key)
        level, reasons = _evaluate(d, prev)
        has_smart = any(_num(d.get(k)) for k in ("temp", "hours", "readCorr", "startStop"))
        out.append({**d, "level": level, "reasons": reasons, "smart": has_smart,
                    "letters": [v["letter"] for v in d.get("volumes") or []]})
        # guarda o maior valor visto, uma vez por dia, para notar aumento de erros
        today = datetime.now().date().isoformat()
        if not prev or prev.get("day") != today:
            history[key] = {"day": today, "readCorr": d.get("readCorr") or 0, "hours": d.get("hours")}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(history, indent=2), encoding="utf-8")
    worst = "problema" if any(x["level"] == "problema" for x in out) else \
        "atencao" if any(x["level"] == "atencao" for x in out) else "ok"
    data = {"disks": sorted(out, key=lambda x: (x["letters"] or ["Z"])[0]), "worst": worst,
            "checked": datetime.now().isoformat(timespec="minutes")}
    _cache.update(t=time.time(), data=data)
    return data
