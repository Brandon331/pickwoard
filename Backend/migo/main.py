import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from . import db, engine as E, llm, auth, i18n, levels, lessons

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
    lv: int = -1
class VocabIn(BaseModel): items: List[VocabItem]
class DiagIn(BaseModel):
    responses: List[Resp]
    vocab: Optional[VocabIn] = None
class AnswerIn(BaseModel):
    answer: str
    replays: int = 0          # listening: veces que volvió a escuchar
    slow: bool = False        # usó el audio lento
    viewed: bool = False      # vio el texto de lo que escuchó (cuenta como ayuda)
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
def health():
    try: db.run("select 1 x", one=True); dbs = "ok"
    except Exception: dbs = "error"
    return {"ok": dbs == "ok", "db": dbs, "llm_enabled": llm.enabled(), "model": llm.MODEL, "llm_last_error": llm.LAST_ERROR, "tts_model": llm.TTS_MODEL, "voice": llm.TTS_VOICE, "stt_model": llm.STT_MODEL}

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
    return E.attempt(u, s, b.answer, {"replays": b.replays, "slow": b.slow, "viewed": b.viewed})

@app.post("/sessions/{sid}/recovery")
def recovery(sid: int, b: AnswerIn):
    s, u = S(sid)
    if s["status"] != "recovery": raise HTTPException(409, "recovery not available yet")
    return E.recover_and_close(u, s, b.answer, {"replays": b.replays, "slow": b.slow, "viewed": b.viewed})

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

class SetIn(BaseModel):
    help_lang: Optional[str] = None
    audio: Optional[bool] = None

@app.get("/users/{uid}/settings")
def get_settings(uid: int):
    U(uid); return {"help_lang": i18n.pref(uid), "effective": i18n.lang(uid), "audio": E.audio_on(uid)}

@app.post("/users/{uid}/settings")
def set_settings(uid: int, b: SetIn):
    U(uid)
    if b.help_lang is not None:
        if b.help_lang not in ("auto", "es", "mixed", "en"): raise HTTPException(422, "help_lang inválido")
        E.set_pref(uid, "help_lang", b.help_lang)
    if b.audio is not None: E.set_pref(uid, "audio", 1 if b.audio else 0)
    return {"help_lang": i18n.pref(uid), "effective": i18n.lang(uid), "audio": E.audio_on(uid)}

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

@app.get("/users/{uid}/vocab")
def get_vocab(uid: int):
    U(uid); return E.vocab_state(uid)

class UseItem(BaseModel):
    w: str
    lv: int = -1
    sentence: str
class UseIn(BaseModel): items: List[UseItem]
class RoleWord(BaseModel):
    w: str
    lv: int = -1
class RoleStartIn(BaseModel): words: List[RoleWord]
class RoleTurnIn(BaseModel): text: str

@app.get("/users/{uid}/vocab/due")
def vocab_due(uid: int): U(uid); return E.vocab_due(uid)

@app.post("/users/{uid}/vocab/use")
def vocab_use(uid: int, b: UseIn):
    u = U(uid)
    if not 1 <= len(b.items) <= 5: raise HTTPException(422, "entre 1 y 5 frases")
    return E.use_words(u, [{"w": x.w.strip()[:40], "lv": x.lv, "sentence": x.sentence.strip()[:300]} for x in b.items])

@app.post("/users/{uid}/roleplay")
def roleplay_start(uid: int, b: RoleStartIn):
    u = U(uid)
    if not 1 <= len(b.words) <= 5: raise HTTPException(422, "entre 1 y 5 palabras")
    return E.role_start(u, [{"w": x.w.strip()[:40], "lv": x.lv} for x in b.words])

def RP(rid):
    rp = db.run("select * from roleplays where id=?", (rid,), one=True)
    if not rp: raise HTTPException(404, "roleplay not found")
    return rp, U(rp["user_id"])

@app.post("/roleplay/{rid}/turn")
def roleplay_turn(rid: int, b: RoleTurnIn):
    rp, u = RP(rid)
    if rp["status"] != "active": raise HTTPException(409, "el rol ya terminó")
    if not b.text.strip(): raise HTTPException(422, "texto vacío")
    return E.role_turn(u, rp, b.text.strip()[:400])

@app.post("/roleplay/{rid}/finish")
def roleplay_finish(rid: int):
    rp, u = RP(rid)
    if rp["status"] == "done": return E.L(rp["summary_json"]) or {"evaluator": "none", "results": []}
    return E.role_finish(u, rp)


# ---------- lecciones "How to…" ----------
def _today(request: Request):
    """Fecha de hoy en la zona horaria del usuario (la app manda X-TZ); si no, UTC. Así «una lección por día» cambia a SU medianoche."""
    try: return datetime.now(ZoneInfo(request.headers.get("x-tz", "UTC"))).strftime("%Y-%m-%d")
    except Exception: return datetime.now(timezone.utc).strftime("%Y-%m-%d")

class CustomLessonIn(BaseModel): title: str
class TalkIn(BaseModel):
    text: str
    history: List[dict] = []
    score: int = 0
    role: Optional[dict] = None

class HintIn(BaseModel):
    history: List[dict] = []
    role: Optional[dict] = None

@app.get("/users/{uid}/lessons")
def lessons_list(uid: int, request: Request): return lessons.list_lessons(U(uid), _today(request))

@app.post("/users/{uid}/lessons/custom")
def lessons_custom(uid: int, b: CustomLessonIn, request: Request): return lessons.create_custom(U(uid), b.title, _today(request))

@app.post("/users/{uid}/lessons/{slug}/start")
def lessons_start(uid: int, slug: str, request: Request): return lessons.start(U(uid), slug, _today(request))

@app.post("/users/{uid}/lessons/{slug}/talk")
def lessons_talk(uid: int, slug: str, b: TalkIn, request: Request): return lessons.talk(U(uid), slug, b.history, b.text, b.score, _today(request), b.role)

@app.post("/users/{uid}/lessons/{slug}/scene")
def lessons_scene(uid: int, slug: str): return lessons.scene(U(uid), slug)

@app.post("/users/{uid}/lessons/{slug}/hint")
def lessons_hint(uid: int, slug: str, b: HintIn): return lessons.hint(U(uid), slug, b.history, b.role)

class AudioIn(BaseModel): text: str

@app.post("/users/{uid}/lessons/{slug}/audio")
def lessons_audio(uid: int, slug: str, b: AudioIn):
    a = lessons.audio(U(uid), slug, b.text)
    return Response(content=a, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=604800"})

@app.get("/users/{uid}/lessons/{slug}/result")
def lessons_result(uid: int, slug: str): return lessons.result(U(uid), slug)

# ---------- voz (speaking): Migo habla (TTS) y el usuario responde hablando (STT) ----------
VOICE_DAILY = int(os.getenv("MIGO_VOICE_DAILY", "120"))   # llamadas de voz (Migo habla + tú hablas) por usuario y día UTC; un rol completo gasta ~14

def _day(): return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def voice_take(uid):
    """Cuenta una llamada de voz; 429 si ya pasó el límite del día. Devuelve cuántas le quedan."""
    r = db.run("insert into voice_usage(user_id,day,n) values(?,?,1) on conflict(user_id,day) do update set n=voice_usage.n+1 returning n", (uid, _day()), one=True)
    n = r["n"] if r else 1
    if n > VOICE_DAILY:
        db.run("update voice_usage set n=n-1 where user_id=? and day=?", (uid, _day()), write=True)
        raise HTTPException(429, "Llegaste al límite de voz de hoy 🎤 Escribe tu respuesta y mañana vuelves a hablar.")
    return VOICE_DAILY - n

def voice_refund(uid): db.run("update voice_usage set n=n-1 where user_id=? and day=? and n>0", (uid, _day()), write=True)

class TtsIn(BaseModel):
    text: str
    lang: str = "en"

@app.post("/users/{uid}/speech/tts")
def speech_tts(uid: int, b: TtsIn):
    U(uid)
    t = b.text.strip()
    if not t: raise HTTPException(422, "texto vacío")
    left = voice_take(uid)
    a = llm.tts(t[:500], "es" if b.lang == "es" else "en")
    if not a: voice_refund(uid); raise HTTPException(503, "voz no disponible")
    return Response(content=a, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400", "X-Voice-Left": str(left)})

_EXT = {"webm": "webm", "mp4": "mp4", "m4a": "m4a", "mpeg": "mp3", "mp3": "mp3", "ogg": "ogg", "wav": "wav", "x-m4a": "m4a"}

@app.post("/users/{uid}/speech/stt")
async def speech_stt(uid: int, request: Request, hint: str = ""):
    U(uid)
    data = await request.body()
    if len(data) < 1000: raise HTTPException(422, "audio vacío o muy corto")
    if len(data) > 6_000_000: raise HTTPException(413, "audio muy largo (máx. ~1 min)")
    voice_take(uid)
    mime = (request.headers.get("content-type") or "audio/webm").split(";")[0].strip()
    ext = _EXT.get(mime.split("/")[-1], "webm")
    t = llm.stt(data, "audio." + ext, mime, hint)
    if t is None: voice_refund(uid); raise HTTPException(503, "no pude transcribir el audio")
    return {"text": t}


# ---------- keep-alive: el servidor se llama a sí mismo cada 14 min para que el plan gratis no se duerma ----------
import threading, time, urllib.request, logging

_log = logging.getLogger("migo.keepalive")
KEEPALIVE_URL = (os.getenv("MIGO_SELF_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")   # Render pone RENDER_EXTERNAL_URL solo
KEEPALIVE_MIN = float(os.getenv("MIGO_KEEPALIVE_MIN", "14"))

def _keepalive():
    time.sleep(60)                               # deja arrancar primero
    while True:
        try:
            with urllib.request.urlopen(KEEPALIVE_URL + "/health", timeout=30) as r: _log.info("keepalive %s", r.status)
        except Exception as e: _log.warning("keepalive falló: %s", type(e).__name__)
        time.sleep(KEEPALIVE_MIN * 60)

if KEEPALIVE_URL and KEEPALIVE_MIN > 0:
    threading.Thread(target=_keepalive, daemon=True, name="keepalive").start()
