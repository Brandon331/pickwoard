from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from . import db, engine as E, llm, auth

db.init()
app = FastAPI(title="Migo English Companion (prototype backend)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)

class UserIn(BaseModel):
    name: str
    goal: str
    situation: str
    context: str = ""
    minutes_per_day: int = 15
    native_lang: str = "es"

class Resp(BaseModel):
    task_id: str
    answer: str
    self_rating: Optional[int] = None
    translated_first: Optional[bool] = None

class DiagIn(BaseModel): responses: List[Resp]
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
def health(): return {"ok": True, "llm_enabled": llm.enabled(), "model": llm.MODEL}

@app.post("/users")
def create_user(b: UserIn): return {"user_id": E.create_user(b.model_dump()), "next": "GET /users/{id}/diagnostic"}

@app.get("/users/{uid}/diagnostic")
def get_diag(uid: int): return {"tasks": E.diagnostic_tasks(U(uid))}

@app.post("/users/{uid}/diagnostic")
def post_diag(uid: int, b: DiagIn):
    u = U(uid)
    if not u["diag_json"]: raise HTTPException(409, "request the diagnostic first")
    return E.run_diagnostic(u, [r.model_dump() for r in b.responses])

@app.get("/users/{uid}/profile")
def profile(uid: int):
    u = U(uid)
    return {"stage": u["stage"], "goal": u["goal"], "situation": u["situation"], "profile": E.L(u["profile_json"]), "plan": E.L(u["plan_json"])}

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
def next_decision(uid: int): return E.decide(U(uid))