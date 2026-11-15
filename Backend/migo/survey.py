"""Encuesta de mercado de Migo (plan de mercadotecnia, sección 4.7): 10 reactivos en 3 bloques.
Se guarda en la base de Migo. El panel de resultados (/survey/admin/*) es solo para ti: pide la clave MIGO_ADMIN_KEY."""
import os, re, io, csv, json, time, hmac, math, collections
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from . import db

router = APIRouter()
try:
    from zoneinfo import ZoneInfo
    MX = ZoneInfo("America/Mexico_City")
except Exception: MX = timezone.utc

# id, bloque, tipo, pregunta, opciones (en el orden del documento)
QUESTIONS = [
 ("q1", "Filtro", "single", "¿Actualmente resides en una zona urbana de México?", ["Sí", "No"]),
 ("q2", "Filtro", "single", "¿Te encuentras en el rango de edad de 18 a 29 años?", ["Sí", "No"]),
 ("q3", "Análisis", "single", "¿Cuál es tu nivel percibido de inglés actualmente?",
  ["Lo entiendo al leer/escuchar, pero me cuesta hablarlo", "Lo hablo con fluidez", "Tengo nivel básico sin comprensión", "Otro"]),
 ("q4", "Análisis", "single", "¿Cuál es la razón principal por la que te interesa o necesitarías dominar el inglés?",
  ["Mejorar empleos o ingresos", "Requisito de titulación escolar", "Viajes", "Desarrollo personal"]),
 ("q5", "Análisis", "multi", "¿Qué métodos o herramientas has utilizado para intentar aprender inglés?",
  ["Duolingo u otras apps", "Cursos o academias presenciales", "Videos de YouTube o podcasts", "Ninguno"]),
 ("q6", "Análisis", "single", "¿Cuál es la mayor dificultad o frustración que enfrentas al usar aplicaciones tradicionales de idiomas?",
  ["No te enseñan a hablar con soltura", "Tienen demasiados anuncios", "Son aburridas o repetitivas", "Falta de constancia o hábito"]),
 ("q7", "Análisis", "single", "¿Cuánto tiempo al día estarías dispuesto/a a dedicarle a una aplicación móvil para practicar inglés mediante lecciones breves y voz?",
  ["De 5 a 10 minutos", "De 15 a 30 minutos", "Más de 30 minutos"]),
 ("q8", "Análisis", "single", "¿Estarías dispuesto/a a pagar una suscripción mensual accesible (similar al rango de otras apps de entretenimiento o educación, ej. $149 - $199 MXN) si una aplicación te garantiza perder el miedo a hablar con la ayuda de un tutor virtual interactivo?",
  ["Sí", "Tal vez", "No"]),
 ("q9", "Socioeconómico", "single", "¿Cuál es tu ocupación principal actual?",
  ["Estudiante de bachillerato o universidad", "Empleado", "Emprendedor o profesionista independiente", "Desempleado u otro"]),
 ("q10", "Socioeconómico", "single", "¿Cuentas con un teléfono inteligente (smartphone) con acceso a internet móvil o Wi-Fi propio para uso diario?",
  ["Sí, de uso personal", "No"]),
]
QS = {q[0]: q for q in QUESTIONS}
CROSS = [("q9", "q8"), ("q3", "q8"), ("q7", "q8"), ("q4", "q8")]       # (agrupar por, contra)
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")

def public_spec(): return [{"id": i, "block": b, "type": t, "text": q, "options": o} for i, b, t, q, o in QUESTIONS]

# ---------------- límites sencillos en memoria (por proceso) ----------------
_hits = collections.defaultdict(collections.deque)
def _ip(request: Request): return (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?"))
def _limit(key, n, window, msg):
    now = time.time(); d = _hits[key]
    while d and now - d[0] > window: d.popleft()
    if len(d) >= n: raise HTTPException(429, msg)
    d.append(now)

# ---------------- envío público ----------------
class SurveyIn(BaseModel):
    answers: Dict[str, Any] = {}
    email: Optional[str] = None
    consent: bool = False
    src: str = ""
    website: str = ""        # trampa para bots: las personas lo dejan vacío
    screened: int = 0        # 0 = completa; 1 o 2 = quedó fuera del filtro en esa pregunta

def _clean(answers):
    out = {}
    for qid, _, typ, _, opts in QUESTIONS:
        v = answers.get(qid)
        if qid in ("q1", "q2"):
            if v != "Sí": raise HTTPException(422, "esta encuesta es para quien cumple el filtro")
            out[qid] = v; continue
        if typ == "multi":
            if not isinstance(v, list) or not v or any(x not in opts for x in v): raise HTTPException(422, f"falta responder {qid}")
            v = list(dict.fromkeys(v))
            if "Ninguno" in v and len(v) > 1: raise HTTPException(422, "«Ninguno» no se combina con otras opciones")
            out[qid] = v
        else:
            if v not in opts: raise HTTPException(422, f"falta responder {qid}")
            out[qid] = v
    other = str(answers.get("q3_other") or "").strip()[:80]
    if out["q3"] == "Otro" and other: out["q3_other"] = other
    return out

@router.post("/survey/submit")
def submit(b: SurveyIn, request: Request):
    if b.website: return {"ok": True}                                            # bot: se ignora sin avisar
    _limit("sub:" + _ip(request), 60, 3600, "Demasiados envíos desde esta conexión. Inténtalo más tarde.")
    src = re.sub(r"[^\w.\- ]", "", b.src or "")[:40]
    if b.screened in (1, 2):
        if (b.answers or {}).get(f"q{b.screened}") != "No": raise HTTPException(422, "respuesta de filtro inválida")
        ans = {f"q{i}": b.answers.get(f"q{i}") for i in range(1, b.screened + 1) if b.answers.get(f"q{i}") in ("Sí", "No")}
        db.run("insert into survey_responses(created_at,status,screen_q,email,consent,answers_json,src) values(?,?,?,?,?,?,?)",
               (db.now(), "screened_out", b.screened, None, 0, json.dumps(ans, ensure_ascii=False), src), write=True)
        return {"ok": True}
    ans = _clean(b.answers or {})
    email = (b.email or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email): raise HTTPException(422, "escribe un correo válido")
    if not b.consent: raise HTTPException(422, "necesitamos tu autorización para guardar tu correo")
    if db.run("select 1 x from survey_responses where status='complete' and lower(email)=?", (email,), one=True):
        return {"ok": True, "duplicate": True}                                    # misma respuesta que éxito: no revela qué correos existen
    try:
        db.run("insert into survey_responses(created_at,status,screen_q,email,consent,answers_json,src) values(?,?,?,?,?,?,?)",
               (db.now(), "complete", None, email, 1, json.dumps(ans, ensure_ascii=False), src), write=True)
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower(): return {"ok": True, "duplicate": True}
        raise
    return {"ok": True, "duplicate": False}

# ---------------- panel (solo tú) ----------------
def _admin(request: Request):
    key = os.getenv("MIGO_ADMIN_KEY", "")
    if not key: raise HTTPException(503, "Panel desactivado: define MIGO_ADMIN_KEY en el servidor.")
    ip = "adm:" + _ip(request)
    if len([t for t in _hits[ip] if time.time() - t < 600]) >= 10: raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")
    if not hmac.compare_digest(request.headers.get("x-admin-key", "").encode(), key.encode()):
        _hits[ip].append(time.time()); raise HTTPException(401, "Clave incorrecta")

def _rows():
    out = []
    for r in db.run("select id,created_at,status,screen_q,email,answers_json,src from survey_responses order by created_at"):
        try: a = json.loads(r["answers_json"] or "{}")
        except Exception: a = {}
        out.append({**r, "a": a})
    return out

def _day(ts): return datetime.fromtimestamp(ts, MX).strftime("%Y-%m-%d")

@router.get("/survey/admin/summary")
def summary(request: Request):
    _admin(request)
    rows = _rows(); comp = [r for r in rows if r["status"] == "complete"]; scr = [r for r in rows if r["status"] == "screened_out"]
    n = len(comp); questions = []
    for qid, blk, typ, text, opts in QUESTIONS:
        pool = rows if qid in ("q1", "q2") else comp
        c = collections.Counter()
        for r in pool:
            v = r["a"].get(qid)
            if isinstance(v, list): c.update(v)
            elif v: c[v] += 1
        answered = sum(1 for r in pool if r["a"].get(qid))
        questions.append({"id": qid, "block": blk, "type": typ, "text": text, "options": opts, "counts": {o: c.get(o, 0) for o in opts}, "n": answered})
    cross = {}
    for g, v in CROSS:
        gm, vm = QS[g], QS[v]; data = {o: {x: 0 for x in vm[4]} for o in gm[4]}
        for r in comp:
            a, b = r["a"].get(g), r["a"].get(v)
            if a in data and b in data[a]: data[a][b] += 1
        cross[f"{v}_by_{g}"] = {"group": g, "value": v, "rows": gm[4], "cols": vm[4], "data": data}
    days = collections.Counter(_day(r["created_at"]) for r in comp)
    pay = {o: sum(1 for r in comp if r["a"].get("q8") == o) for o in QS["q8"][4]}
    pct = lambda x: round(100 * x / n, 1) if n else 0
    return {"questions": questions, "cross": cross,
            "days": [{"day": d, "n": days[d]} for d in sorted(days)],
            "src": dict(collections.Counter((r["src"] or "directo") for r in rows)),
            "screen": {"total": len(scr), "q1": sum(1 for r in scr if r["screen_q"] == 1), "q2": sum(1 for r in scr if r["screen_q"] == 2)},
            "kpis": {"complete": n, "screened": len(scr), "qualify_rate": round(100 * n / (n + len(scr)), 1) if (n + len(scr)) else 0,
                     "pay_yes": pct(pay["Sí"]), "pay_maybe": pct(pay["Tal vez"]), "pay_no": pct(pay["No"]),
                     "margin": round(98 / math.sqrt(n), 1) if n >= 2 else None}}      # ±% al 95 % con p=.5 (solo si la muestra fuera aleatoria)

@router.get("/survey/admin/responses")
def responses(request: Request, limit: int = 100, offset: int = 0):
    _admin(request)
    comp = [r for r in _rows() if r["status"] == "complete"][::-1]
    return {"total": len(comp), "items": [{"id": r["id"], "at": _day(r["created_at"]) + " " + datetime.fromtimestamp(r["created_at"], MX).strftime("%H:%M"), "email": r["email"], "src": r["src"] or "directo", "a": r["a"]}
                                          for r in comp[max(0, offset):max(0, offset) + max(1, min(limit, 500))]]}

def _csv_safe(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v

@router.get("/survey/admin/export.csv")
def export(request: Request):
    _admin(request)
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["id", "fecha_mx", "estado", "descartado_en", "correo", "origen"] + [f"{q[0]}: {q[3]}" for q in QUESTIONS] + ["q3_otro"])
    for r in _rows():
        a = r["a"]; w.writerow([_csv_safe(x) for x in [r["id"], datetime.fromtimestamp(r["created_at"], MX).strftime("%Y-%m-%d %H:%M"),
                                                       "completa" if r["status"] == "complete" else "descartado", r["screen_q"] or "", r["email"] or "", r["src"] or "directo"]
                                                      + [" | ".join(a[q[0]]) if isinstance(a.get(q[0]), list) else a.get(q[0], "") for q in QUESTIONS] + [a.get("q3_other", "")]])
    return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="migo-encuesta.csv"'})
