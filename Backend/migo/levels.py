"""Nivel estimado (A1-C2) y tiempo hasta el siguiente. Combina el test de la landing (prior) con el desempeño práctico del diagnóstico."""
import json
from . import db

LV = ["A1", "A2", "B1", "B2", "C1", "C2"]
HRS = [100, 185, 175, 200, 350]   # horas aprox. de A1->A2, A2->B1, B1->B2, B2->C1, C1->C2 (guía tipo Cambridge, mismas cifras de la landing)

def _pref(uid, key):
    r = db.run("select value from preferences where user_id=? and key=?", (uid, key), one=True)
    return r["value"] if r else None

def placement(uid):
    try: return json.loads(_pref(uid, "placement") or "null")
    except Exception: return None

def perf(uid):
    rows = db.run("select level,autonomy,evidence_n from competencies where user_id=?", (uid,))
    if not rows or not sum(r["evidence_n"] for r in rows): return None
    return sum(.6 * r["level"] + .4 * r["autonomy"] for r in rows) / len(rows)

def estimate(uid):
    p, f = placement(uid), perf(uid)
    if not p:
        if f is None: return {"k": 0, "source": "default", "note": None}
        return {"k": 0 if f < .25 else 1 if f < .45 else 2 if f < .65 else 3 if f < .85 else 4, "source": "practice", "note": None}
    k, conf, src = int(p["k"]), p.get("conf", ""), "test"
    if f is not None:
        src = "test+practice"
        kp = 0 if f < .25 else 1 if f < .45 else 2 if f < .65 else 3 if f < .85 else 4     # nivel según la práctica sola
        if conf == "baja": k = int((k + kp) / 2 + .5)                                     # test poco fiable: práctica y test pesan igual
        elif f < (.2 if conf == "alta" else .3) and k > 0: k -= 1                         # con confianza alta se exige más para corregir
        elif f > .92 and k < 4: k += 1                                              # subir exige evidencia muy fuerte (evita inflar el nivel)
    return {"k": k, "source": src, "note": "up" if k > p["k"] else "down" if k < p["k"] else None}

def eta(h, m, lg="es"):
    days = max(0.0, h) / (m / 60); mo = days / 30.4
    if mo < 1.5:
        n = max(1, round(days / 7)); return (f"{n} semana" + ("s" if n > 1 else "")) if lg == "es" else f"{n} week" + ("s" if n > 1 else "")
    n = round(mo); return (f"{n} mes" + ("es" if n > 1 else "")) if lg == "es" else f"{n} month" + ("s" if n > 1 else "")

KEYW = [136, 106, 108, 107, 102]      # palabras clave por nivel (mismas listas que la app)

def _declared(uid):
    try: return max(5, int(_pref(uid, "minutes_per_day") or 15))
    except ValueError: return 15

def activity(uid):
    """Eventos de estudio (timestamp, minutos) estimados con marcas de tiempo reales: sesiones (tope 25 min), rondas de palabras (4 min),
    diagnóstico (10 min, una vez) y mensajes de chat (1 min)."""
    ev = []
    for s in db.run("select created_at, closed_at, status from sessions where user_id=?", (uid,)):
        if s["closed_at"] and s["created_at"]:
            cap = 10 if s["status"] == "abandoned" else 25
            ev.append((s["created_at"], max(1.0, min(cap, (s["closed_at"] - s["created_at"]) / 60))))
    for r in db.run("select created_at from evidence where user_id=? and kind='vocab'", (uid,)): ev.append((r["created_at"], 4.0))
    d = db.run("select min(created_at) t from evidence where user_id=? and kind='diagnostic'", (uid,), one=True)
    if d and d["t"]: ev.append((d["t"], 10.0))
    for m in db.run("select created_at from messages where user_id=? and role='user'", (uid,)): ev.append((m["created_at"], 1.0))
    return [(t, m) for t, m in ev if t]

def progress(uid, k=None):
    """Tiempo que falta para el siguiente nivel según la actividad real: horas necesarias (HRS) menos horas estudiadas, donde cada hora
    vale hasta x1.5 según cuánto dominas las palabras clave y tus habilidades. Ritmo = minutos reales por día (últimos 14 días)."""
    k = estimate(uid)["k"] if k is None else k
    if k >= 5: return None
    ev, now, H = activity(uid), db.now(), HRS[k]
    total_min, declared = sum(m for _, m in ev), _declared(uid)
    first = min((t for t, _ in ev), default=None)
    span = max(1.0, (now - first) / 86400) if first else 0.0
    recent = sum(m for t, m in ev if t >= now - 14 * 86400)
    pace, src = (max(5.0, recent / min(14.0, span)), "actual") if span >= 3 else (float(declared), "declared")
    mastered = db.run("select count(*) n from vocab_words where user_id=? and lv=? and unaided>=2", (uid, k), one=True)["n"]
    vf = min(1.0, mastered / KEYW[k])
    rows = db.run("select autonomy from competencies where user_id=?", (uid,))
    skill = sum(r["autonomy"] for r in rows) / len(rows) if rows else 0.0
    boost = 1 + .5 * (vf + skill) / 2
    hours = total_min / 60; credited = min(float(H), hours * boost); rem = H - credited
    return {"k": k, "level": LV[k], "next": LV[k + 1], "needed_h": H, "hours_done": round(hours, 1), "credited_h": round(credited, 1),
            "remaining_h": round(rem, 1), "pct": round(100 * credited / H, 1), "pace_min": round(pace), "pace_source": src,
            "declared_min": declared, "boost": round(boost, 2), "key_mastered": mastered, "key_total": KEYW[k],
            "vocab_frac": round(vf, 2), "skill": round(skill, 2), "eta_es": eta(rem, pace, "es"), "eta_en": eta(rem, pace, "en")}

def path(uid):
    e = estimate(uid); k = e["k"]
    try: m = max(5, int(_pref(uid, "minutes_per_day") or 15))
    except ValueError: m = 15
    out = {"level": LV[k], "next": LV[k + 1] if k < 5 else None, "source": e["source"], "note": e["note"],
           "minutes_per_day": m, "test": (placement(uid) or {}).get("score"),
           "n": (placement(uid) or {}).get("n"), "conf": (placement(uid) or {}).get("conf") or None,
           "lo": (placement(uid) or {}).get("lo") or None, "hi": (placement(uid) or {}).get("hi") or None}
    pr = progress(uid, k) if out["next"] else None
    if pr:
        h = max(pr["remaining_h"], 0.1)
        out.update(hours=pr["needed_h"], remaining_hours=pr["remaining_h"], credited_hours=pr["credited_h"], pct=pr["pct"], pace_source=pr["pace_source"],
                   declared_minutes=m, minutes_per_day=pr["pace_min"], eta_es=pr["eta_es"], eta_en=pr["eta_en"],
                   scenarios=[{"min": x, "t_es": eta(h, x, "es"), "t_en": eta(h, x, "en")} for x in (15, 30, 60, 120)])
    return out
