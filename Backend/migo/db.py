"""PostgreSQL (Supabase u otro). Requiere la variable de entorno DATABASE_URL.
Interfaz: run(sql, args, one=False, write=False). El SQL usa ? como marcador (se convierte a %s para psycopg)."""
import os, re, time
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip().strip('"').strip("'")
if not DATABASE_URL.startswith(("postgres://", "postgresql://")):
    raise RuntimeError("Falta la variable de entorno DATABASE_URL (postgresql://usuario:contraseña@host:puerto/base)")

# El "Transaction pooler" de Supabase (puerto 6543) no admite prepared statements -> prepare_threshold=None. Supabase exige SSL.
_url = DATABASE_URL if "sslmode=" in DATABASE_URL else DATABASE_URL + ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"
_pool = ConnectionPool(_url, min_size=1, max_size=int(os.getenv("DB_POOL", "5")), open=True, timeout=30,
                       kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
                       check=ConnectionPool.check_connection)
_ID = {"users", "errors", "sessions", "decisions", "evidence", "messages", "accounts"}   # tablas con columna id

SCHEMA = """
create table if not exists users(id serial primary key, name text, goal text, situation text, context text,
  minutes_per_day int, native_lang text, stage text default 'onboarding', diag_json text, profile_json text, plan_json text, created_at double precision);
create table if not exists competencies(user_id int, name text, level double precision default 0, autonomy double precision default 0,
  evidence_n int default 0, updated_at double precision, primary key(user_id,name));
create table if not exists errors(id serial primary key, user_id int, pattern text, competency text,
  example text, count int default 1, resolved int default 0, last_seen double precision);
create table if not exists strengths(user_id int, item text, times_ok int default 1, primary key(user_id,item));
create table if not exists preferences(user_id int, key text, value text, primary key(user_id,key));
create table if not exists sessions(id serial primary key, user_id int, plan_json text, activity_json text,
  status text, help_level int default 0, blocked int default 0, attempts_json text, summary_json text, created_at double precision, closed_at double precision);
create table if not exists decisions(id serial primary key, user_id int, session_id int, rule text,
  decision_json text, outcome_json text, created_at double precision);
create table if not exists evidence(id serial primary key, user_id int, session_id int, competency text,
  score double precision, help_level int, kind text, note text, created_at double precision);
create table if not exists messages(id serial primary key, user_id int, role text, content text, created_at double precision);
create table if not exists vocab_words(user_id int, word text, lv int default -1, seen int default 0, first_ok int default 0, unaided int default 0, last_seen double precision, primary key(user_id,word));
create index if not exists ix_errors_user on errors(user_id);
create index if not exists ix_sessions_user on sessions(user_id);
create index if not exists ix_decisions_user on decisions(user_id);
create index if not exists ix_evidence_user on evidence(user_id);
create index if not exists ix_messages_user on messages(user_id);
"""

def now(): return time.time()

def run(sql, args=(), one=False, write=False):
    q = sql.replace("?", "%s"); m = re.match(r"\s*insert\s+into\s+(\w+)", q, re.I)
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
            if st.strip(): c.execute(st)
