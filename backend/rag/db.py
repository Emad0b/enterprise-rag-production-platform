import sqlite3, json, time, uuid
from contextlib import contextmanager
from .config import DATABASE_URL, RUNTIME

PG = bool(DATABASE_URL)


@contextmanager
def db():
    if PG:
        import psycopg

        connection = psycopg.connect(DATABASE_URL)
    else:
        connection = sqlite3.connect(RUNTIME / "rag.db", timeout=30)
        connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def sql(connection, query, args=()):
    return connection.execute(query.replace("?", "%s") if PG else query, args)


def initialize():
    with db() as c:
        if PG:
            c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        statements = [
            "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT UNIQUE, name TEXT, password TEXT, groups_json TEXT, admin INTEGER)",
            "CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY,title TEXT,object_key TEXT,media_type TEXT,digest TEXT,status TEXT,error TEXT,created DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS acl (document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,group_name TEXT,PRIMARY KEY(document_id,group_name))",
            "CREATE TABLE IF NOT EXISTS configs (id TEXT PRIMARY KEY,payload TEXT,created DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY,value TEXT)",
            "CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY,user_id TEXT,config_id TEXT,kind TEXT,payload TEXT,created DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS evaluations (id TEXT PRIMARY KEY,config_id TEXT,payload TEXT,created DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY,actor TEXT,action TEXT,payload TEXT,created DOUBLE PRECISION)",
            "CREATE TABLE IF NOT EXISTS rollouts (id TEXT PRIMARY KEY,candidate TEXT,champion TEXT,status TEXT,mode TEXT,created DOUBLE PRECISION,decision TEXT)",
        ]
        for statement in statements:
            c.execute(statement)
        if PG:
            c.execute(
                "CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY,document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,page INTEGER,position INTEGER,text TEXT,embedding vector(384),model TEXT,hostile INTEGER,search tsvector GENERATED ALWAYS AS (to_tsvector('english',text)) STORED)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS chunks_search ON chunks USING gin(search)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS chunks_vector ON chunks USING hnsw(embedding vector_cosine_ops)"
            )
        else:
            c.execute(
                "CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY,document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,page INTEGER,position INTEGER,text TEXT,embedding TEXT,model TEXT,hostile INTEGER)"
            )
        c.execute("CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id)")
        if PG:
            c.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS sentences TEXT")
        elif "sentences" not in {r[1] for r in c.execute("PRAGMA table_info(chunks)")}:
            c.execute("ALTER TABLE chunks ADD COLUMN sentences TEXT")
        for key in ("champion", "active_rollout", "previous", "corpus_epoch"):
            sql(
                c,
                "INSERT INTO state VALUES (?,?) ON CONFLICT (key) DO NOTHING",
                (key, "0" if key == "corpus_epoch" else ""),
            )


def state(key):
    with db() as c:
        row = sql(c, "SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row[0] if row else ""


def set_state(key, value, c):
    sql(
        c,
        "INSERT INTO state VALUES (?,?) ON CONFLICT (key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def audit(actor, action, payload, c=None):
    values = (str(uuid.uuid4()), actor, action, json.dumps(payload), time.time())
    if c:
        sql(c, "INSERT INTO audit VALUES (?,?,?,?,?)", values)
    else:
        with db() as conn:
            sql(conn, "INSERT INTO audit VALUES (?,?,?,?,?)", values)


initialize()
