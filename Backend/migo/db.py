import sqlite3, os, time
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
