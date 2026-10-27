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
        elif f > (.9 if conf == "alta" else .85) and k < 4: k += 1
    return {"k": k, "source": src, "note": "up" if k > p["k"] else "down" if k < p["k"] else None}

def eta(h, m, lg="es"):
    days = h / (m / 60); mo = days / 30.4
    if mo < 1.5:
        n = max(1, round(days / 7)); return f"{n} semanas" if lg == "es" else f"{n} weeks"
    n = round(mo); return f"{n} meses" if lg == "es" else f"{n} months"

def path(uid):
    e = estimate(uid); k = e["k"]
    try: m = max(5, int(_pref(uid, "minutes_per_day") or 15))
    except ValueError: m = 15
    out = {"level": LV[k], "next": LV[k + 1] if k < 5 else None, "source": e["source"], "note": e["note"],
           "minutes_per_day": m, "test": (placement(uid) or {}).get("score"),
           "n": (placement(uid) or {}).get("n"), "conf": (placement(uid) or {}).get("conf") or None,
           "lo": (placement(uid) or {}).get("lo") or None, "hi": (placement(uid) or {}).get("hi") or None}
    if out["next"]:
        h = HRS[k]
        out.update(hours=h, eta_es=eta(h, m, "es"), eta_en=eta(h, m, "en"),
                   scenarios=[{"min": x, "t_es": eta(h, x, "es"), "t_en": eta(h, x, "en")} for x in (15, 30, 60, 120)])
    return out
