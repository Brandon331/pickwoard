"""Recorre el flujo completo del prototipo (sesión 1 -> chat -> sesión 2) y comprueba que la sesión 2 cambia."""
import os, json
if not os.environ.get("TEST_DATABASE_URL"): raise SystemExit("Define TEST_DATABASE_URL con una base de PRUEBA (no la de producción).")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
from fastapi.testclient import TestClient
from migo.main import app
c = TestClient(app)
p = lambda t, d: print(f"\n== {t}\n{json.dumps(d, ensure_ascii=False, indent=1)[:900]}")

uid = c.post("/users", json={"name": "Ana", "goal": "Conversar en una entrevista de trabajo", "situation": "job interview for a marketing role"}).json()["user_id"]
tasks = c.get(f"/users/{uid}/diagnostic").json()["tasks"]
answers = ["They are late, twenty minutes, and ask if I want to reschedule.", "Want job. I am agree with the salary. I have 25 years.",
           "meeting, salary, experience, schedule, team. I want the job because I have experience.", "Yes, spell it: A-N-A. Sorry, yo traduje primero."]
r = c.post(f"/users/{uid}/diagnostic", json={"responses": [{"task_id": t["id"], "answer": a, "self_rating": 3, "translated_first": i == 3} for i, (t, a) in enumerate(zip(tasks, answers))]}).json()
p("PERFIL", r["profile"]["summary"]); p("PLAN", r["plan"])

def session(label, bad_first=True):
    s = c.post(f"/users/{uid}/sessions").json(); p(f"{label}: DECISIÓN", s["decision"]); sid = s["session_id"]
    p("ayuda", c.post(f"/sessions/{sid}/help", json={}).json())
    a = c.post(f"/sessions/{sid}/attempt", json={"answer": "I am agree. Want to work in your company because I have experience in marketing and I like teams."}).json()
    while "recovery_task" not in a: a = c.post(f"/sessions/{sid}/attempt", json={"answer": "I would like to join the team because I have strong experience in marketing."}).json()
    done = c.post(f"/sessions/{sid}/recovery", json={"answer": "I'd like to explain why I changed my mind, because the schedule is better for me."}).json()
    p("CIERRE", {k: done[k] for k in ("competency", "before", "after", "autonomy_change", "error_resolved", "honest_note")}); return s["decision"], done

d1, _ = session("SESIÓN 1")
p("CHAT", c.post(f"/users/{uid}/chat", json={"message": "uf, esto es muy difícil, me frustra"}).json())
d2, _ = session("SESIÓN 2")
p("PROGRESO", c.get(f"/users/{uid}/progress").json()); p("MEMORIA(errores)", c.get(f"/users/{uid}/memory").json()["errors"])
assert d1["scenario"] != d2["scenario"], "sesión 2 debe usar contexto nuevo"
print("\nOK — la sesión 2 cambió según lo ocurrido:", d1["rule"], "->", d2["rule"], "|", d1["scenario"], "->", d2["scenario"])
