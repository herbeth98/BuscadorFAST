"""Banco SQLite: discos, arquivos, palavras-chave, vetores de IA e busca por texto."""
import sqlite3
import threading

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS volumes (
    id          INTEGER PRIMARY KEY,
    serial      TEXT UNIQUE NOT NULL,
    label       TEXT,
    last_letter TEXT,
    total_bytes INTEGER,
    last_seen   TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id        INTEGER PRIMARY KEY,
    volume_id INTEGER NOT NULL REFERENCES volumes(id),
    relpath   TEXT NOT NULL,          -- caminho sem a letra do disco, ex.: \\Fotos\\2024\\a.jpg
    name      TEXT NOT NULL,
    ext       TEXT NOT NULL,
    kind      TEXT NOT NULL,          -- image | video
    size      INTEGER,
    mtime     REAL,
    width     INTEGER,
    height    INTEGER,
    duration  REAL,
    taken_at  TEXT,                   -- ISO; data da foto (EXIF) ou da gravação
    camera    TEXT,
    gps_lat   REAL,
    gps_lon   REAL,
    has_thumb INTEGER DEFAULT 0,
    ai_done   INTEGER DEFAULT 0,
    missing   INTEGER DEFAULT 0,
    error     TEXT,
    UNIQUE(volume_id, relpath)
);
CREATE INDEX IF NOT EXISTS ix_files_kind ON files(kind);
CREATE INDEX IF NOT EXISTS ix_files_taken ON files(taken_at);
CREATE INDEX IF NOT EXISTS ix_files_ai ON files(ai_done);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS file_tags (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id),
    source  TEXT NOT NULL,            -- ai | user
    score   REAL,
    PRIMARY KEY (file_id, tag_id)
);
CREATE INDEX IF NOT EXISTS ix_file_tags_tag ON file_tags(tag_id);

-- Palavras-chave que o usuário removeu: a IA não volta a colocá-las
CREATE TABLE IF NOT EXISTS rejected_tags (
    file_id INTEGER NOT NULL,
    tag_id  INTEGER NOT NULL,
    PRIMARY KEY (file_id, tag_id)
);

CREATE TABLE IF NOT EXISTS embeddings (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    vec     BLOB NOT NULL             -- float16, normalizado
);

CREATE TABLE IF NOT EXISTS people (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS faces (
    id         INTEGER PRIMARY KEY,
    file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    frame      INTEGER DEFAULT 0,     -- vídeo: qual quadro
    box        TEXT,                  -- x,y,w,h relativos (0-1) à imagem
    score      REAL,
    vec        BLOB NOT NULL,         -- float16, 512 dimensões, normalizado
    cluster_id INTEGER,               -- grupo automático (rostos ainda sem nome)
    person_id  INTEGER REFERENCES people(id) ON DELETE SET NULL,
    manual     INTEGER DEFAULT 0,     -- 1 = você confirmou o nome
    not_person INTEGER,               -- você tirou este rosto dessa pessoa: não sugerir de novo
    ignored    INTEGER DEFAULT 0      -- desconhecido que você mandou ignorar
);
CREATE INDEX IF NOT EXISTS ix_faces_file ON faces(file_id);
CREATE INDEX IF NOT EXISTS ix_faces_person ON faces(person_id);
CREATE INDEX IF NOT EXISTS ix_faces_cluster ON faces(cluster_id);

-- Coleções: grupos que você monta, com arquivos de qualquer pasta ou disco
CREATE TABLE IF NOT EXISTS collections (
    id      INTEGER PRIMARY KEY,
    name    TEXT UNIQUE NOT NULL COLLATE NOCASE,
    created TEXT
);
CREATE TABLE IF NOT EXISTS collection_items (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    added         TEXT,
    PRIMARY KEY (collection_id, file_id)
);
CREATE INDEX IF NOT EXISTS ix_collection_items_file ON collection_items(file_id);

-- Duplicados movidos para a lixeira do BuscadorFAST (pasta no mesmo disco; dá para restaurar)
CREATE TABLE IF NOT EXISTS trash (
    id            INTEGER PRIMARY KEY,
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    kept_file_id  INTEGER,
    trash_relpath TEXT NOT NULL,      -- onde está agora (sem a letra do disco)
    size          INTEGER,
    moved_at      TEXT
);

-- Sons dos vídeos (aplausos, fogos, música…) com o momento em que acontecem
CREATE TABLE IF NOT EXISTS sound_events (
    id      INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    label   TEXT NOT NULL,
    start   REAL NOT NULL,
    end     REAL NOT NULL,
    score   REAL
);
CREATE INDEX IF NOT EXISTS ix_sound_label ON sound_events(label, score);
CREATE INDEX IF NOT EXISTS ix_sound_file ON sound_events(file_id, start);

-- Fala transcrita dos vídeos (Whisper), em trechos com o tempo
CREATE TABLE IF NOT EXISTS transcripts (
    id      INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    start   REAL NOT NULL,
    end     REAL NOT NULL,
    text    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_transcripts_file ON transcripts(file_id, start);

-- Cada linha = um trecho + o seguinte, para achar frases que passam de um trecho para outro
CREATE VIRTUAL TABLE IF NOT EXISTS speech_fts USING fts5(
    text, tokenize = 'unicode61 remove_diacritics 2'
);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    name, path, tags, ocr, descricao, tokenize = 'unicode61 remove_diacritics 2'
);
"""

_local = threading.local()


def connect() -> sqlite3.Connection:
    """Uma conexão por thread."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=90)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA journal_size_limit=67108864")  # o registro (WAL) encolhe para 64 MB depois de esvaziado
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        _migrate(conn)
        _local.conn = conn
    return conn


def start_checkpoints(every: int = 300) -> None:
    """Esvazia o registro (WAL) de tempos em tempos. Com a indexação gravando sem parar, ele não tinha
    hora de ser esvaziado e chegou a 2,9 GB, deixando as leituras mais lentas."""
    import threading
    import time

    def loop():
        while True:
            time.sleep(every)
            try:
                c = sqlite3.connect(DB_PATH, timeout=5)
                c.execute("PRAGMA journal_size_limit=67108864")
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                c.close()
            except sqlite3.Error:
                pass  # banco ocupado agora: tenta na próxima volta

    threading.Thread(target=loop, daemon=True, name="esvaziar-wal").start()


def _migrate(conn: sqlite3.Connection) -> None:
    """Atualiza bancos criados por versões anteriores."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
    for col, decl in (("faces_done", "INTEGER DEFAULT 0"), ("ocr_done", "INTEGER DEFAULT 0"),
                      ("ocr_text", "TEXT"), ("ocr_norm", "TEXT"), ("speech_done", "INTEGER DEFAULT 0"),
                      ("qhash", "TEXT"), ("fhash", "TEXT"), ("hash_mtime", "REAL"),
                      ("trashed", "INTEGER DEFAULT 0"), ("favorite", "INTEGER DEFAULT 0"),
                      ("descricao", "TEXT"), ("desc_done", "INTEGER DEFAULT 0"), ("lr_done", "INTEGER DEFAULT 0"),
                      ("quality_done", "INTEGER DEFAULT 0"), ("sharpness", "REAL"), ("review", "TEXT"),
                      ("read_at", "TEXT"), ("read_error", "TEXT"), ("sound_done", "INTEGER DEFAULT 0")):
        if col not in cols:
            conn.execute(f"ALTER TABLE files ADD COLUMN {col} {decl}")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_files_size ON files(size)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_files_fhash ON files(fhash)")
    fts_cols = {r[1] for r in conn.execute("PRAGMA table_info(files_fts)")}
    if "descricao" not in fts_cols:  # índice de texto de versão anterior (sem texto da foto/descrição): recria
        conn.execute("DROP TABLE files_fts")
        conn.executescript(SCHEMA)
        for (fid,) in conn.execute("SELECT id FROM files").fetchall():
            refresh_fts(conn, fid)
    conn.commit()


def normalize(text: str) -> str:
    """minúsculas, sem acentos e com espaços simples — para busca por trecho."""
    import unicodedata
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(text.split())


def tag_id(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip().lower()
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    return conn.execute("INSERT INTO tags(name) VALUES (?)", (name,)).lastrowid


def file_tags(conn: sqlite3.Connection, file_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT t.name, ft.source, ft.score FROM file_tags ft JOIN tags t ON t.id = ft.tag_id
           WHERE ft.file_id = ? ORDER BY ft.source DESC, ft.score DESC""",
        (file_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def refresh_fts(conn: sqlite3.Connection, file_id: int) -> None:
    """Reescreve a linha de busca por texto de um arquivo (nome, pasta, palavras-chave, texto, descrição)."""
    row = conn.execute("SELECT name, relpath, ocr_text, descricao FROM files WHERE id = ?", (file_id,)).fetchone()
    conn.execute("DELETE FROM files_fts WHERE rowid = ?", (file_id,))
    if not row:
        return
    tags = " ".join(t["name"] for t in file_tags(conn, file_id))
    folder = row["relpath"].rsplit("\\", 1)[0].replace("\\", " ").replace("_", " ").replace("-", " ")
    conn.execute(
        "INSERT INTO files_fts(rowid, name, path, tags, ocr, descricao) VALUES (?, ?, ?, ?, ?, ?)",
        (file_id, row["name"], folder, tags, row["ocr_text"] or "", row["descricao"] or ""),
    )
