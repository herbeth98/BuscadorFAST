"""Álbuns automáticos: fotos e vídeos do mesmo dia e do mesmo lugar.

- Com localização (GPS): mesmo dia e mesma região (quadrado de ~5 km).
- Sem localização: mesmo dia e mesma pasta (fotos da câmera costumam ficar numa pasta por evento).
O nome do álbum vem da pasta mais comum dentro dele.
"""
import re
from collections import Counter, defaultdict

from .db import connect

CELL = 0.05          # graus (~5,5 km no Nordeste)
MIN_ITEMS = 4        # menos que isso não vira álbum

_GENERIC = re.compile(r"^(fotos?|raw|jpe?g|editadas?|selecionadas?|v[ií]deos?|camera|dcim|\d+[a-z]*|100[a-z]+|"
                      r"imagens|images|imgs?|novo|nova pasta|backup.*|stories|reels?)$", re.I)


def _title(folders: Counter) -> str:
    """Nome legível a partir das pastas: ignora nomes genéricos ("Fotos", "RAW", "EDITADAS"…)."""
    for folder, _ in folders.most_common():
        for part in reversed([p for p in folder.split("\\") if p]):
            if not _GENERIC.match(part.strip()):
                return part.strip()
    return "Sem nome"


def key_of(row) -> str:
    day = row["taken_at"][:10]
    if row["gps_lat"] is not None and row["gps_lon"] is not None and (row["gps_lat"], row["gps_lon"]) != (0, 0):
        return f"g|{day}|{round(row['gps_lat'] / CELL)}|{round(row['gps_lon'] / CELL)}"
    folder = row["relpath"].rsplit("\\", 1)[0]
    return f"p|{day}|{row['volume_id']}|{folder}"


def _merge_same_event(groups: dict[str, list]) -> dict[str, list]:
    """Câmera sem GPS + celular com GPS no mesmo evento: mesmo dia e mesma pasta → um álbum só.
    A chave do álbum juntado é a lista das chaves, separadas por "||"."""
    by_day: dict[str, list[str]] = defaultdict(list)
    for k in groups:
        by_day[k.split("|")[1]].append(k)
    merged: dict[str, list] = {}
    for day, keys in by_day.items():
        folders = {k: {(r["volume_id"], r["relpath"].rsplit("\\", 1)[0]) for r in groups[k]} for k in keys}
        parent = {k: k for k in keys}

        def root(k):
            while parent[k] != k:
                k = parent[k]
            return k
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if folders[a] & folders[b]:
                    parent[root(b)] = root(a)
        sets: dict[str, list[str]] = defaultdict(list)
        for k in keys:
            sets[root(k)].append(k)
        for ks in sets.values():
            merged["||".join(sorted(ks))] = [r for k in ks for r in groups[k]]
    return merged


def albums(where_sql: str = "1", params: list | None = None, limit: int = 400) -> list[dict]:
    rows = connect().execute(
        f"""SELECT f.id, f.taken_at, f.gps_lat, f.gps_lon, f.volume_id, f.relpath, f.kind, f.favorite, f.has_thumb
            FROM files f WHERE {where_sql} AND f.taken_at IS NOT NULL""", params or []).fetchall()
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[key_of(r)].append(r)
    groups = _merge_same_event(groups)
    out = []
    for key, items in groups.items():
        if len(items) < MIN_ITEMS:
            continue
        items.sort(key=lambda r: r["taken_at"])
        with_thumb = [r for r in items if r["has_thumb"]] or items
        favs = [r for r in with_thumb if r["favorite"]]
        cover = (favs or [r for r in with_thumb if r["kind"] == "image"] or with_thumb)
        cover = cover[len(cover) // 2]["id"]  # do meio do evento costuma ser mais representativa
        folders = Counter(r["relpath"].rsplit("\\", 1)[0] for r in items)
        out.append({
            "key": key, "title": _title(folders), "day": items[0]["taken_at"][:10],
            "start": items[0]["taken_at"][11:16], "end": items[-1]["taken_at"][11:16],
            "photos": sum(r["kind"] == "image" for r in items), "videos": sum(r["kind"] == "video" for r in items),
            "gps": "g|" in key, "cover": cover,
        })
    out.sort(key=lambda a: (a["day"], a["photos"] + a["videos"]), reverse=True)
    return out[:limit]


def album_filter(key: str) -> tuple[str, list]:
    """Condição SQL que traz os arquivos de um álbum (álbuns juntados: uma condição por parte, com OU)."""
    parts = [_one_filter(k) for k in key.split("||") if k]
    return " OR ".join(f"({s})" for s, _ in parts) or "0", [a for _, args in parts for a in args]


def _one_filter(key: str) -> tuple[str, list]:
    kind, day, a, b = (key.split("|", 3) + ["", "", "", ""])[:4]
    if kind == "g":
        lat, lon = int(a) * CELL, int(b) * CELL
        return ("substr(f.taken_at, 1, 10) = ? AND f.gps_lat >= ? AND f.gps_lat < ? AND f.gps_lon >= ? AND f.gps_lon < ?",
                [day, lat - CELL / 2, lat + CELL / 2, lon - CELL / 2, lon + CELL / 2])
    if kind == "p":
        vid, folder = a, b
        esc = folder.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        return ("substr(f.taken_at, 1, 10) = ? AND f.volume_id = ? AND f.relpath LIKE ? ESCAPE '!' "
                "AND f.relpath NOT LIKE ? ESCAPE '!' AND (f.gps_lat IS NULL OR (f.gps_lat = 0 AND f.gps_lon = 0))",
                [day, int(vid), esc + "\\%", esc + "\\%\\%"])
    return "0", []
