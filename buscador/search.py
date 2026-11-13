"""Busca combinada: texto (nome, pasta, palavras-chave) + IA (frase livre) + filtros."""
import re

from .db import connect, normalize

SEMANTIC_MIN = 0.06  # similaridade mínima para a IA considerar um resultado

# "relevancia" só vale quando há busca; sem busca, cai em data_desc
SORTS = {
    "data_desc": "f.taken_at DESC",
    "data_asc": "f.taken_at ASC",
    "modificado_desc": "f.mtime DESC",
    "modificado_asc": "f.mtime ASC",
    "adicionado_desc": "f.id DESC",
    "nome_asc": "f.name COLLATE NOCASE ASC",
    "tamanho_desc": "f.size DESC",
    "duracao_desc": "f.duration DESC NULLS LAST",
}


# Palavras pequenas que mudam muito de uma frase para outra ("portal da/de transparência"): não exigir
STOPWORDS = {"a", "o", "as", "os", "e", "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
             "um", "uma", "para", "pra", "com", "que", "por", "ao", "à"}


def _fts_query(q: str) -> str:
    words = re.findall(r"\w+", q, flags=re.UNICODE)
    kept = [w for w in words if w.lower() not in STOPWORDS] or words
    return " ".join(f'"{w}"*' for w in kept)


def _speech_hits(conn, q: str) -> dict[int, dict]:
    """Vídeos em que a frase foi dita → primeiro momento em que aparece e quantas vezes."""
    fts = _fts_query(q)
    if not fts:
        return {}
    hits: dict[int, dict] = {}
    rows = conn.execute(
        """SELECT t.file_id, t.start, t.text FROM speech_fts s JOIN transcripts t ON t.id = s.rowid
           WHERE speech_fts MATCH ? ORDER BY t.file_id, t.start""", (fts,))
    for fid, start, text in rows:
        h = hits.setdefault(fid, {"match_start": start, "match_text": text, "matches": 0})
        h["matches"] += 1
    return hits


# Captura de tela: pelo nome, pela pasta, pelo formato (PNG de celular, sem câmera) ou pela IA
SCREENSHOT_SQL = r"""(f.kind = 'image' AND (
    lower(f.name) LIKE 'screenshot%' OR lower(f.name) LIKE 'captura de tela%' OR lower(f.name) LIKE 'print%'
    OR lower(f.name) LIKE 'screen shot%' OR lower(f.name) LIKE 'capture%'
    OR lower(f.relpath) LIKE '%\screenshots\%' OR lower(f.relpath) LIKE '%\capturas de tela\%'
    OR (f.ext = '.png' AND f.camera IS NULL AND f.width > 0 AND f.height >= f.width * 1.9
        AND f.height BETWEEN 1500 AND 3200)  -- PNG em pé com altura de tela de celular (logotipos são largos)
    OR EXISTS (SELECT 1 FROM file_tags ft JOIN tags t ON t.id = ft.tag_id
               WHERE ft.file_id = f.id AND t.name = 'captura de tela' AND ft.source IN ('ai', 'user'))))"""


def _filters(kind="", volume=None, tag="", date_from="", date_to="", camera="", online_ids=None,
             favorite=False, collection=None, area="", album="", review=False, people="",
             people_mode="juntas") -> tuple[list[str], list]:
    """Filtros da barra lateral em SQL (usados pela busca, pela linha do tempo e pelo mapa)."""
    where = ["f.missing = 0", "f.error IS NULL"]
    params: list = []
    if review:  # "Para revisar": fotos ruins que você ainda não decidiu
        where.append("f.review IS NOT NULL AND f.review != 'kept'")
    if album:  # álbum automático (mesmo dia e lugar)
        from .albuns import album_filter
        sql, args = album_filter(album)
        where.append(f"({sql})"); params += args
    if area:  # "sul,oeste,norte,leste": só o que foi feito dentro desse retângulo do mapa
        try:
            s, w, n, e = (float(x) for x in area.split(","))
            where.append("f.gps_lat BETWEEN ? AND ? AND f.gps_lon BETWEEN ? AND ?")
            params += [s, n, w, e]
        except ValueError:
            pass
    if kind == "screenshot":
        where.append(SCREENSHOT_SQL)
    elif kind == "image":  # "Fotos" não inclui as capturas de tela (elas têm a categoria delas)
        where.append(f"f.kind = 'image' AND NOT {SCREENSHOT_SQL}")
    elif kind:
        where.append("f.kind = ?"); params.append(kind)
    if volume:
        where.append("f.volume_id = ?"); params.append(volume)
    if date_from:
        where.append("f.taken_at >= ?"); params.append(date_from)
    if date_to:
        where.append("f.taken_at < ?"); params.append(date_to + "T99")
    if camera:
        where.append("f.camera = ?"); params.append(camera)
    for t in [t for t in tag.split(",") if t.strip()]:
        where.append("EXISTS (SELECT 1 FROM file_tags ft JOIN tags t ON t.id = ft.tag_id "
                     "WHERE ft.file_id = f.id AND t.name = ?)")
        params.append(t.strip().lower())
    pids = [int(x) for x in str(people).split(",") if x.strip().isdigit()]
    if pids:  # pessoas pelo rosto: juntas na mesma foto, qualquer uma delas, ou só elas
        marks = ",".join("?" * len(pids))
        # "f.id IN (arquivos da pessoa)": usa o índice por pessoa uma vez só, em vez de olhar arquivo por arquivo
        if people_mode == "qualquer":
            where.append(f"f.id IN (SELECT file_id FROM faces WHERE person_id IN ({marks}))")
            params += pids
        else:
            for pid in pids:
                where.append("f.id IN (SELECT file_id FROM faces WHERE person_id = ?)")
                params.append(pid)
        if people_mode == "so":  # e nenhuma outra pessoa com nome
            where.append(f"f.id NOT IN (SELECT file_id FROM faces WHERE person_id IS NOT NULL AND person_id NOT IN ({marks}))")
            params += pids
    if online_ids is not None:
        where.append(f"f.volume_id IN ({','.join(str(i) for i in online_ids) or '0'})")
    if favorite:
        where.append("f.favorite = 1")
    if collection:
        where.append("EXISTS (SELECT 1 FROM collection_items ci WHERE ci.file_id = f.id AND ci.collection_id = ?)")
        params.append(collection)
    return where, params


def map_points(limit: int = 30000, **filters) -> list[list]:
    """Pontos do mapa: [id, lat, lon, é vídeo] de tudo que tem localização (respeitando os filtros)."""
    where, params = _filters(**filters)
    rows = connect().execute(
        f"""SELECT f.id, round(f.gps_lat, 5), round(f.gps_lon, 5), f.kind = 'video' FROM files f
            WHERE {' AND '.join(where)} AND f.gps_lat IS NOT NULL AND f.gps_lon IS NOT NULL
              AND NOT (f.gps_lat = 0 AND f.gps_lon = 0) LIMIT ?""", params + [limit]).fetchall()
    return [list(r) for r in rows]


def timeline(year: str = "", month: str = "", **filters) -> dict:
    """Quantidade de fotos e vídeos por ano → por mês de um ano → por dia de um mês."""
    where, params = _filters(**filters)
    if year and month:
        width, prefix, level = 10, f"{year}-{month}-", "dia"
    elif year:
        width, prefix, level = 7, f"{year}-", "mes"
    else:
        width, prefix, level = 4, "", "ano"
    conn = connect()
    undated = 0 if prefix else conn.execute(
        f"SELECT COUNT(*) FROM files f WHERE {' AND '.join(where)} AND f.taken_at IS NULL", params).fetchone()[0]
    if prefix:
        where.append("f.taken_at LIKE ?"); params.append(prefix + "%")
    where.append("f.taken_at IS NOT NULL")
    rows = conn.execute(
        f"""SELECT substr(f.taken_at, 1, {width}) AS k, COUNT(*) AS n, SUM(f.kind = 'video') AS videos
            FROM files f WHERE {' AND '.join(where)} GROUP BY k ORDER BY k""", params).fetchall()
    return {"level": level, "year": year, "month": month, "undated": undated, "buckets": [dict(r) for r in rows]}


def search(q: str = "", mode: str = "auto", kind: str = "", volume: int | None = None, tag: str = "",
           date_from: str = "", date_to: str = "", camera: str = "", online_ids: set[int] | None = None,
           similar: int | None = None, limit: int = 200, offset: int = 0, sort: str = "relevancia",
           favorite: bool = False, collection: int | None = None, photo: str = "", area: str = "",
           album: str = "", review: bool = False, people: str = "", people_mode: str = "juntas") -> dict:
    conn = connect()
    where, params = _filters(kind, volume, tag, date_from, date_to, camera, online_ids, favorite, collection, area,
                             album, review, people, people_mode)

    q = q.strip()
    scores: dict[int, float] = {}
    speech: dict[int, dict] = {}
    if q and mode in ("auto", "texto", "falado"):
        speech = _speech_hits(conn, q)
    sound: dict[int, dict] = {}
    if q and mode in ("auto", "som"):
        from . import som
        labels = som.wanted(q) or (som.wanted_any(q) if mode == "som" else None)
        if labels:
            sound = som.hits(conn, labels)  # aplausos, fogos, "momentos altos"… com o momento mais forte
    if photo:
        from .faces import face_query_scores
        scores = dict(face_query_scores(photo))  # arquivos em que aparece a pessoa da foto enviada
    elif similar:
        from .ai import similar_to
        scores = {k: v for k, v in similar_to(similar).items() if k != similar}
    elif q and mode == "escrito":
        # texto lido dentro da foto: procura trechos (o OCR às vezes corta letras), sem acento
        words = normalize(q).split()
        sql = " AND ".join("ocr_norm LIKE ? ESCAPE '!'" for _ in words)
        args = ["%" + w.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%" for w in words]
        for (fid,) in conn.execute(f"SELECT id FROM files WHERE ocr_norm IS NOT NULL AND {sql}", args):
            scores[fid] = 1.0
    elif q and (mode == "som" or (mode == "auto" and sound)):
        # busca por som: o momento mais forte primeiro; o que também tem o texto/palavra ganha um pouco
        scores = {fid: 1.0 + h["sound_score"] for fid, h in sound.items()}
    elif q and mode == "falado":
        # o que foi dito nos vídeos: quem falou mais vezes vem primeiro
        scores = {fid: 1.0 + min(h["matches"], 50) / 100 for fid, h in speech.items()}
    elif q:
        fts = _fts_query(q)
        text_hits = {}
        if fts:
            for r in conn.execute("SELECT rowid, rank FROM files_fts WHERE files_fts MATCH ?", (fts,)):
                text_hits[r[0]] = 1.0  # resultado exato vem primeiro
        if mode in ("auto", "ia"):
            try:
                from .ai import semantic_scores
                for fid, s in semantic_scores(q).items():
                    if s >= SEMANTIC_MIN:
                        scores[fid] = s
            except Exception:
                pass  # sem GPU/modelo: segue só com texto
        if mode == "texto" or not scores:
            scores = {}
        for fid in text_hits:
            scores[fid] = scores.get(fid, 0) + 1.0
        for fid in speech:
            scores[fid] = scores.get(fid, 0) + 0.9  # dito no vídeo

    sql_where = " AND ".join(where)
    if q or similar or photo:
        if not scores:
            return {"total": 0, "items": []}
        ranked = sorted(scores, key=scores.get, reverse=True)
        # aplica os filtros só sobre os candidatos
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS cand(id INTEGER PRIMARY KEY, score REAL)")
        conn.execute("DELETE FROM cand")
        conn.executemany("INSERT INTO cand VALUES (?, ?)", ((i, scores[i]) for i in ranked[:20000]))
        base = f"FROM files f JOIN cand c ON c.id = f.id JOIN volumes v ON v.id = f.volume_id WHERE {sql_where}"
        order = SORTS.get(sort, "c.score DESC")
    elif collection and sort == "relevancia":
        # coleção sem busca: na ordem em que você foi adicionando
        base = (f"FROM files f JOIN volumes v ON v.id = f.volume_id "
                f"JOIN collection_items cx ON cx.file_id = f.id AND cx.collection_id = {int(collection)} WHERE {sql_where}")
        order = "cx.added, f.taken_at"
    else:
        base = f"FROM files f JOIN volumes v ON v.id = f.volume_id WHERE {sql_where}"
        order = SORTS.get(sort, SORTS["data_desc"])

    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT f.id, f.name, f.relpath, f.kind, f.size, f.has_thumb, f.favorite, f.review, f.width, f.height, f.duration, f.taken_at,
                   f.camera, v.label AS volume, v.serial, v.id AS volume_id {base}
            ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    items = [dict(r) for r in rows]
    for it in items:
        if it["id"] in speech:
            it.update(speech[it["id"]])
        if it["id"] in sound:
            it.update(sound[it["id"]])
    return {"total": total, "items": items}


def top_tags(limit: int = 80) -> list[dict]:
    rows = connect().execute(
        """SELECT t.name, COUNT(*) AS n, SUM(ft.source = 'user') AS user_n FROM file_tags ft
           JOIN tags t ON t.id = ft.tag_id JOIN files f ON f.id = ft.file_id
           WHERE f.missing = 0 GROUP BY t.id ORDER BY n DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def cameras() -> list[str]:
    return [r[0] for r in connect().execute(
        "SELECT camera FROM files WHERE camera IS NOT NULL GROUP BY camera ORDER BY COUNT(*) DESC LIMIT 50")]
