from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from . import db, engine as E, llm, auth, i18n, levels

db.init()
app = FastAPI(title="Migo English Companion (prototype backend)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)

class UserIn(BaseModel):
    name: str
    goal: str                       # ej. "Mantener una conversación funcional en una entrevista de trabajo"
    situation: str                  # situación concreta que define "progreso"
    context: str = ""
    minutes_per_day: int = 15
    native_lang: str = "es"

class Resp(BaseModel):
    task_id: str
    answer: str
    self_rating: Optional[int] = None      # 1-3: "¿podría hacerlo sin ayuda?" (declarado vs demostrado)
    translated_first: Optional[bool] = None
    seconds: Optional[float] = None

class VocabItem(BaseModel):
    w: str
    first: bool
    peek: bool = False
class VocabIn(BaseModel): items: List[VocabItem]
class DiagIn(BaseModel):
    responses: List[Resp]
    vocab: Optional[VocabIn] = None
class AnswerIn(BaseModel): answer: str
class HelpIn(BaseModel): blocked: bool = False
class ChatIn(BaseModel): message: str

def U(uid):
    u = db.run("select * from users where id=?", (uid,), one=True)
    if not u: raise HTTPException(404, "user not found")
    return u
def S(sid):
    s = db.run("select * from sessions where id=?", (sid,), one=True)
    if not s: raise HTTPException(404, "session not found")
    return s, U(s["user_id"])

@app.get("/health")
def health(): return {"ok": True, "llm_enabled": llm.enabled(), "model": llm.MODEL, "db": "postgres" if db.PG else "sqlite"}

@app.post("/users")
def create_user(b: UserIn): return {"user_id": E.create_user(b.model_dump()), "next": "GET /users/{id}/diagnostic"}

@app.get("/users/{uid}/diagnostic")
def get_diag(uid: int): return {"tasks": E.diagnostic_tasks(U(uid))}

@app.post("/users/{uid}/diagnostic")
def post_diag(uid: int, b: DiagIn):
    u = U(uid)
    if not u["diag_json"]: raise HTTPException(409, "request the diagnostic first")
    return E.run_diagnostic(u, [r.model_dump() for r in b.responses], [x.model_dump() for x in b.vocab.items] if b.vocab else None)

@app.get("/users/{uid}/profile")
def profile(uid: int):
    u = U(uid)
    return {"stage": u["stage"], "goal": u["goal"], "situation": u["situation"], "profile": E.L(u["profile_json"]), "plan": E.L(u["plan_json"]), "lang": i18n.lang(uid), "path": levels.path(uid)}

@app.post("/users/{uid}/sessions")
def new_session(uid: int):
    u = U(uid)
    if u["stage"] != "diagnosed": raise HTTPException(409, "complete the diagnostic first")
    return E.create_session(u)

@app.post("/sessions/{sid}/help")
def help_(sid: int, b: HelpIn):
    s, _ = S(sid)
    if s["status"] != "active": raise HTTPException(409, f"session is {s['status']}")
    return E.give_help(s, b.blocked)

@app.post("/sessions/{sid}/attempt")
def attempt(sid: int, b: AnswerIn):
    s, u = S(sid)
    if s["status"] != "active": raise HTTPException(409, f"session is {s['status']}")
    return E.attempt(u, s, b.answer)

@app.post("/sessions/{sid}/recovery")
def recovery(sid: int, b: AnswerIn):
    s, u = S(sid)
    if s["status"] != "recovery": raise HTTPException(409, "recovery not available yet")
    return E.recover_and_close(u, s, b.answer)

@app.post("/sessions/{sid}/abandon")
def abandon(sid: int):
    s, u = S(sid); return E.abandon(u, s)

@app.post("/users/{uid}/chat")
def chat(uid: int, b: ChatIn): return E.chat(U(uid), b.message)

@app.get("/users/{uid}/progress")
def progress(uid: int): return E.progress(U(uid))

@app.get("/users/{uid}/memory")
def memory(uid: int): U(uid); return E.memory(uid)

@app.get("/users/{uid}/next")
def next_decision(uid: int): return E.decide(U(uid))   # preview: "¿qué haría Migo contigo ahora?"

class SetIn(BaseModel): help_lang: str

@app.get("/users/{uid}/settings")
def get_settings(uid: int):
    U(uid); return {"help_lang": i18n.pref(uid), "effective": i18n.lang(uid)}

@app.post("/users/{uid}/settings")
def set_settings(uid: int, b: SetIn):
    U(uid)
    if b.help_lang not in ("auto", "es", "mixed", "en"): raise HTTPException(422, "help_lang inválido")
    E.set_pref(uid, "help_lang", b.help_lang); return {"help_lang": b.help_lang, "effective": i18n.lang(uid)}

class PlIn(BaseModel):
    level: str
    score: int = 0
    counts: List[int] = []
    n: int = 10
    conf: str = ""
    lo: str = ""
    hi: str = ""

@app.post("/users/{uid}/placement")
def set_placement(uid: int, b: PlIn):
    U(uid)
    if b.level not in levels.LV[:5]: raise HTTPException(422, "nivel inválido")
    E.set_pref(uid, "placement", E.J({"k": levels.LV.index(b.level), "level": b.level, "score": b.score, "counts": b.counts, "n": b.n, "conf": b.conf if b.conf in ("alta", "media", "baja") else "", "lo": b.lo if b.lo in levels.LV else "", "hi": b.hi if b.hi in levels.LV else ""}))
    return levels.path(uid)

@app.get("/users/{uid}/path")
def get_path(uid: int): U(uid); return levels.path(uid)

@app.post("/users/{uid}/vocab")
def post_vocab(uid: int, b: VocabIn):
    u = U(uid)
    if not b.items: raise HTTPException(422, "sin palabras")
    return E.record_vocab(u, [x.model_dump() for x in b.items], "vocab")
