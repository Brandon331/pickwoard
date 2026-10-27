"""Base de datos: PostgreSQL (Supabase, etc.) si existe DATABASE_URL; si no, SQLite local (MIGO_DB, por defecto migo.db).
La interfaz es la misma en ambos casos: run(sql, args, one=False, write=False)."""
import os, re, time

DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("DATABASEURL") or "").strip().strip('"').strip("'")
PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
DB = os.getenv("MIGO_DB", "migo.db")
SCHEMA = """
create table if not exists users(id integer primary key autoincrement, name text, goal text, situation text, context text,
  minutes_per_day int, native_lang text, stage text default 'onboarding', diag_json text, profile_json text, plan_json text, created_at real);
create table if not exists competencies(user_id int, name text, level real default 0, autonomy real default 0,
  evidence_n int default 0, updated_at real, primary key(user_id,name));
create table if not exists errors(id integer primary key autoincrement, user_id int, pattern text, competency text,
  example text, count int default 1, resolved int default 0, last_seen real);
create table if not exists strengths(user_id int, item text, times_ok int default 1, primary key(user_id,item));
create table if not exists preferences(user_id int, key text, value text, primary key(user_id,key));
create table if not exists sessions(id integer primary key autoincrement, user_id int, plan_json text, activity_json text,
  status text, help_level int default 0, blocked int default 0, attempts_json text, summary_json text, created_at real, closed_at real);
create table if not exists decisions(id integer primary key autoincrement, user_id int, session_id int, rule text,
  decision_json text, outcome_json text, created_at real);
create table if not exists evidence(id integer primary key autoincrement, user_id int, session_id int, competency text,
  score real, help_level int, kind text, note text, created_at real);
create table if not exists messages(id integer primary key autoincrement, user_id int, role text, content text, created_at real);
"""
def now(): return time.time()

if PG:
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    # El "Transaction pooler" de Supabase (puerto 6543) no admite prepared statements -> prepare_threshold=None. Supabase exige SSL.
    _url = DATABASE_URL if "sslmode=" in DATABASE_URL else DATABASE_URL + ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"
    _pool = ConnectionPool(_url, min_size=1, max_size=int(os.getenv("DB_POOL", "5")), open=True, timeout=30,
                           kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
                           check=ConnectionPool.check_connection)
    _ID = {"users", "errors", "sessions", "decisions", "evidence", "messages", "accounts"}   # tablas con columna id

    def _pg(sql):   # el código escribe SQL estilo SQLite; aquí se traduce
        sql = re.sub(r"integer primary key autoincrement", "serial primary key", sql, flags=re.I)
        sql = re.sub(r"\breal\b", "double precision", sql, flags=re.I)   # real = float4 perdería precisión en timestamps
        return sql.replace("?", "%s")

    def run(sql, args=(), one=False, write=False):
        q = _pg(sql); m = re.match(r"\s*insert\s+into\s+(\w+)", q, re.I)
        ret = bool(write and m and m.group(1).lower() in _ID and "on conflict" not in q.lower())
        if ret: q += " returning id"
        with _pool.connection() as c:
            cur = c.execute(q, args)
            if ret: return cur.fetchone()["id"]
            if write: return None
            rows = cur.fetchall()
            return (rows[0] if rows else None) if one else rows

    def init():
        with _pool.connection() as c:
            for st in SCHEMA.split(";"):
                if st.strip(): c.execute(_pg(st))
else:
    import sqlite3

    def run(sql, args=(), one=False, write=False):
        c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
        try:
            cur = c.execute(sql, args)
            if write: c.commit(); return cur.lastrowid
            rows = [dict(r) for r in cur.fetchall()]
            return (rows[0] if rows else None) if one else rows
        finally: c.close()

    def init():
        c = sqlite3.connect(DB); c.executescript(SCHEMA); c.commit(); c.close()
