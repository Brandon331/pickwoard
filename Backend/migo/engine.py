"""Núcleo del Companion: diagnóstico, memoria, motor de decisión, sesión adaptativa, conversación, progreso."""
import json, re, random
from . import db, llm, i18n, levels

COMPS = ["comprehension", "production", "vocabulary", "translation_independence"]
FORMATS = {"production": "situational_response", "comprehension": "listen_and_respond",
           "vocabulary": "rebuild_from_memory", "translation_independence": "timed_direct_response"}
VARIANTS = ["a routine case", "something goes wrong (a mistake or misunderstanding)",
            "you need to ask for clarification", "you change your mind midway",
            "the other person speaks fast and you must react"]
HELP_KIND = {1: "hint", 2: "guiding_question", 3: "example", 4: "full_explanation"}
WHY = {"comprehension": "si no entiendes lo que te dicen, no puedes responder en una situación real",
       "production": "hablar sin guion es lo que separa 'sé inglés' de 'puedo resolver mi situación'",
       "vocabulary": "sin las palabras clave de tu situación te quedas bloqueado a mitad de frase",
       "translation_independence": "traducir mentalmente vuelve lenta la conversación y rompe el ritmo"}
PASS = 0.7
J = json.dumps
def L(s): return json.loads(s) if s else None
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))

# ---------- memoria ----------
def comps(uid): return {r["name"]: r for r in db.run("select * from competencies where user_id=?", (uid,))}
def eff(c): return 0.6 * c["level"] + 0.4 * c["autonomy"]
def snapshot(uid):
    return {k: {"level": round(v["level"], 2), "autonomy": round(v["autonomy"], 2), "evidence": v["evidence_n"]}
            for k, v in comps(uid).items()}

def bump(uid, comp, level_x, auto_x):
    r = comps(uid)[comp]; n = r["evidence_n"]
    f = lambda old, x: x if n == 0 else old + 0.4 * (x - old)
    db.run("update competencies set level=?,autonomy=?,evidence_n=evidence_n+1,updated_at=? where user_id=? and name=?",
           (f(r["level"], level_x), f(r["autonomy"], auto_x), db.now(), uid, comp), write=True)

def record_errors(uid, comp, errs):
    for e in errs:
        p = e["pattern"]
        r = db.run("select id from errors where user_id=? and pattern=?", (uid, p), one=True)
        if r: db.run("update errors set count=count+1,resolved=0,example=?,last_seen=? where id=?",
                     (e.get("example", ""), db.now(), r["id"]), write=True)
        else: db.run("insert into errors(user_id,pattern,competency,example,last_seen) values(?,?,?,?,?)",
                     (uid, p, comp, e.get("example", ""), db.now()), write=True)

def record_strengths(uid, items):
    for s in items:
        db.run("insert into strengths(user_id,item) values(?,?) on conflict(user_id,item) do update set times_ok=strengths.times_ok+1",
               (uid, s), write=True)

def add_evidence(uid, sid, comp, score, help_level, kind, note=""):
    db.run("insert into evidence(user_id,session_id,competency,score,help_level,kind,note,created_at) values(?,?,?,?,?,?,?,?)",
           (uid, sid, comp, score, help_level, kind, note, db.now()), write=True)

def set_pref(uid, k, v):
    db.run("insert into preferences(user_id,key,value) values(?,?,?) on conflict(user_id,key) do update set value=excluded.value",
           (uid, k, str(v)), write=True)

def memory(uid):
    return {"competencies": snapshot(uid),
            "errors": db.run("select pattern,competency,count,resolved,example from errors where user_id=? order by count desc", (uid,)),
            "strengths": db.run("select item,times_ok from strengths where user_id=? order by times_ok desc", (uid,)),
            "preferences": {r["key"]: r["value"] for r in db.run("select * from preferences where user_id=?", (uid,))},
            "decision_history": [{"session_id": d["session_id"], "rule": d["rule"], "outcome": L(d["outcome_json"])}
                                 for d in db.run("select * from decisions where user_id=? order by id", (uid,))]}

def create_user(d):
    uid = db.run("insert into users(name,goal,situation,context,minutes_per_day,native_lang,created_at) values(?,?,?,?,?,?,?)",
                 (d["name"], d["goal"], d["situation"], d["context"], d["minutes_per_day"], d["native_lang"], db.now()), write=True)
    for c in COMPS: db.run("insert into competencies(user_id,name,updated_at) values(?,?,?)", (uid, c, db.now()), write=True)
    set_pref(uid, "minutes_per_day", d["minutes_per_day"])
    return uid

# ---------- evaluación (LLM con fallback heurístico) ----------
ES = set("yo quiero el la los las para que un una con por pero como está estoy tengo necesito hola gracias favor puedo es mi".split())
RX = [(r"\bI am agree\b", "am_agree"), (r"\bI have \d+ years\b", "age_with_have"), (r"^\s*(want|need)\b", "dropped_subject"),
      (r"\bI am (go|come|want|need|live)\b", "am_plus_base_verb"), (r"\b(informations|peoples|advices)\b", "uncountable_plural")]

def heuristic(task, answer, lang="es"):
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ']+", answer); n = len(words)
    ratio = sum(w.lower() in ES for w in words) / max(n, 1)
    errs = [{"pattern": p, "example": answer[:80]} for rx, p in RX if re.search(rx, answer, re.I | re.M)]
    kw = task.get("keywords") or []
    if task["competency"] == "comprehension" and kw:
        hits = sum(k.lower() in answer.lower() for k in kw); score = clamp(hits / max(2, len(kw) // 2))
    else:
        if ratio > 0.2: errs.append({"pattern": "falls_back_to_spanish", "example": answer[:80]})
        score = clamp(n / 20 - 0.15 * len(errs) - ratio)
    fb = i18n.t(i18n.tk(lang), "fb_err", e=", ".join(i18n.errn(i18n.tk(lang), x["pattern"]) for x in errs)) if errs else i18n.t(i18n.tk(lang), "fb_ok")
    return {"score": round(score, 2), "errors": errs, "strengths": [], "translated": ratio > 0.2,
            "feedback": fb, "evaluator": "heuristic"}

def evaluate(user, task, answer, secs=None):
    known = [e["pattern"] for e in db.run("select pattern from errors where user_id=?", (user["id"],))]
    r = llm.ask_json(
        "You are a strict but kind English assessor for a Spanish speaker. Judge ONLY observable evidence in the answer. "
        "Return {\"score\":0-1,\"errors\":[{\"pattern\":snake_case_label,\"example\":str}],\"strengths\":[str],"
        "\"translated\":bool (answer shows mental translation from Spanish),\"feedback\":\"1-2 sentences, language: " + i18n.llm_lang(user["id"]) + "\"}. "
        "If competency is translation_independence, judge how direct and natural the reply is (literal calques, L1 interference); seconds_taken is only context. Reuse these known error labels when they apply: " + J(known),
        J({"situation": user["situation"], "task": task["prompt"], "competency": task["competency"], "answer": answer, "seconds_taken": secs}))
    if r and isinstance(r.get("score"), (int, float)):
        r.update(score=clamp(float(r["score"])), evaluator="llm")
        r.setdefault("errors", []); r.setdefault("strengths", []); r.setdefault("feedback", ""); r.setdefault("translated", False)
    else: r = heuristic(task, answer, i18n.lang(user["id"]))
    if task["competency"] == "translation_independence" and r["translated"]: r["score"] = round(r["score"] * 0.6, 2)
    return r

# ---------- vocabulario con imágenes ----------
def record_vocab(user, items, kind="vocab"):
    """first = acertó a la primera; peek = vio la imagen. nivel = aciertos a la primera; autonomía = a la primera SIN ver la imagen."""
    uid = user["id"]; n = len(items)
    if not n: return None
    first = sum(1 for x in items if x["first"]); good = [x["w"] for x in items if x["first"] and not x["peek"]]
    bump(uid, "vocabulary", first / n, len(good) / n)
    for x in items:
        db.run("insert into vocab_words(user_id,word,lv,seen,first_ok,unaided,last_seen) values(?,?,?,1,?,?,?) on conflict(user_id,word) do update set "
               "seen=vocab_words.seen+1, first_ok=vocab_words.first_ok+excluded.first_ok, unaided=vocab_words.unaided+excluded.unaided, "
               "lv=case when excluded.lv>=0 then excluded.lv else vocab_words.lv end, last_seen=excluded.last_seen",
               (uid, x["w"], x.get("lv", -1), int(bool(x["first"])), int(bool(x["first"] and not x["peek"])), db.now()), write=True)
    note = i18n.t(i18n.tk(i18n.lang(uid)), "v_note", a=first, n=n, b=len(good))
    add_evidence(uid, None, "vocabulary", len(good) / n, 0, kind, note)
    return {"first_try": first, "unaided": len(good), "n": n, "note": note, "words_mastered": words_mastered(uid)}

def vocab_state(uid):
    rows = db.run("select word as w, lv, seen, first_ok, unaided, last_seen from vocab_words where user_id=? order by last_seen desc", (uid,))
    for r in rows: r["status"] = "mastered" if r["unaided"] >= 2 else "seen"
    return {"path": levels.path(uid), "words": rows, "progress": levels.progress(uid)}

def words_mastered(uid):
    return db.run("select count(*) n from vocab_words where user_id=? and unaided>=2", (uid,), one=True)["n"]   # dominada = 2 aciertos sin ver la imagen

# ---------- diagnóstico ----------
def diagnostic_tasks(user):
    if user["diag_json"]: return L(user["diag_json"])
    s = user["situation"]; k = levels.estimate(user["id"])["k"]; tasks = None
    r = llm.ask_json("Design 3 short English diagnostic tasks for a Spanish speaker, in this order: "
                     "1) comprehension: a short message or email (length and difficulty by estimated_cefr_level) plus ONE question about its content; the learner may answer in Spanish or English. "
                     "2) production: a writing prompt tied to the learner's situation, 2-5 sentences, difficulty by level. "
                     "3) translation_independence: a short chat message that needs a QUICK natural reply (60 seconds). "
                     "Never ask the learner to list words, spell, listen, record or look at images (vocabulary is tested elsewhere). All tasks are text-only and answered by typing. "
                     "Return {\"tasks\":[{\"id\":\"d1\",\"competency\":...,\"prompt\":...,\"keywords\":[]}]}; keywords only for comprehension (words a correct answer contains, in English and Spanish).",
                     J({"goal": user["goal"], "situation": s, "estimated_cefr_level": levels.LV[k]}))
    ok = {"comprehension", "production", "translation_independence"}
    if r and isinstance(r.get("tasks"), list) and len(r["tasks"]) >= 3 and all(t.get("competency") in ok for t in r["tasks"][:3]): tasks = r["tasks"][:3]
    if not tasks:   # respaldo sin LLM: 3 niveles de dificultad
        b = 0 if k <= 1 else 1 if k == 2 else 2
        C = [("Message from your host: 'Hi! The class starts at 9:30 tomorrow. Please bring your passport and a pen. The room is on the second floor.' What time is the class, and what do you need to bring?", ["9:30", "nine thirty", "nueve y media", "passport", "pasaporte", "pen", "pluma", "bolígrafo", "lápiz"]),
             ("Email: 'Thanks for your application. Unfortunately the position has been filled, but we would like to keep your CV and contact you if something similar opens up in the next six months.' Did they offer you the job? What will they do with your CV?", ["filled", "ocupad", "no ", "cv", "six months", "seis meses", "contact"]),
             ("'Although the new policy was meant to reduce commuting costs, many employees say it made their days longer, since the shuttle only runs twice in the morning. Management insists the data show a net saving.' What is the disagreement about, and why do employees complain?", ["shuttle", "twice", "longer", "saving", "management", "employees", "dos veces", "más largo", "ahorro"])]
        P = [f"Situation: {s}. Write 2 simple sentences: say who you are and one thing you want.",
             f"Situation: {s}. Introduce yourself and say what you need, in 2-3 sentences.",
             f"Situation: {s}. Something went wrong yesterday. Write 3-4 sentences: what happened and what you did about it.",
             f"Situation: {s}. Give your opinion: is it better to prepare a lot or to improvise? Write 4-5 sentences with a reason and an example."]
        R = ["A friend texts you: 'Hey! Are you free this weekend? Let's do something!' Reply right now, as if live.",
             "Your manager writes in chat: 'Can you send me the report by 5 pm, or is that a problem?' Reply naturally.",
             "A colleague says: 'Honestly, I think the deadline is unrealistic. What's your take?' Reply with your opinion."]
        tasks = [{"id": "d1", "competency": "comprehension", "prompt": C[b][0], "keywords": C[b][1]},
                 {"id": "d2", "competency": "production", "prompt": P[min(k, 3)]},
                 {"id": "d3", "competency": "translation_independence", "prompt": R[b]}]
    for i, t in enumerate(tasks): t["id"] = t.get("id") or f"d{i+1}"
    db.run("update users set diag_json=? where id=?", (J(tasks), user["id"]), write=True)
    return tasks

def run_diagnostic(user, responses, vocab=None):
    uid = user["id"]; tasks = {t["id"]: t for t in diagnostic_tasks(user)}; results = []
    for r in responses:
        t = tasks.get(r["task_id"])
        if not t: continue
        ev = evaluate(user, t, r["answer"], r.get("seconds")); score = ev["score"]
        if t["competency"] == "translation_independence" and r.get("translated_first"): score = round(score * 0.6, 2)
        bump(uid, t["competency"], score, score)  # sin ayuda: nivel = autonomía
        record_errors(uid, t["competency"], ev["errors"]); record_strengths(uid, ev["strengths"])
        add_evidence(uid, None, t["competency"], score, 0, "diagnostic", ev["feedback"])
        claimed = (r["self_rating"] - 1) / 2 if r.get("self_rating") else None
        results.append({"task_id": t["id"], "competency": t["competency"], "claimed": claimed, "demonstrated": score,
                        "overclaimed": claimed is not None and claimed - score >= 0.4, "feedback": ev["feedback"], "evaluator": ev["evaluator"]})
    if vocab:
        v = record_vocab(user, vocab, "diagnostic")
        if v: results.append({"task_id": "vocab", "competency": "vocabulary", "claimed": None, "demonstrated": v["unaided"] / v["n"], "overclaimed": False, "feedback": v["note"], "evaluator": "auto"})
    profile = build_profile(user, results); plan = make_plan(user, profile)
    db.run("update users set stage='diagnosed',profile_json=?,plan_json=? where id=?", (J(profile), J(plan), uid), write=True)
    return {"profile": profile, "plan": plan}

def build_profile(user, results=None):
    uid = user["id"]; C = comps(uid); E = {k: eff(v) for k, v in C.items()}; lg = i18n.tk(i18n.lang(uid))
    order = sorted(E, key=E.get)
    bottlenecks = ([c for c in order if E[c] < 0.7] or order[:1])[:3]
    errs = db.run("select pattern,count,example from errors where user_id=? order by count desc limit 3", (uid,))
    for x in errs: x["label"] = i18n.errn(lg, x["pattern"]); x["hint"] = i18n.errh(lg, x["pattern"])
    over = [r["competency"] for r in (results or []) if r["overclaimed"]]
    obs = i18n.t(lg, "p_obs", g=user["goal"], c=i18n.cn(lg, bottlenecks[0]), w=i18n.WHY[lg][bottlenecks[0]])
    if errs: obs += i18n.t(lg, "p_err", p=i18n.errn(lg, errs[0]["pattern"]), e=errs[0]["example"])
    if over: obs += i18n.t(lg, "p_over", c=", ".join(i18n.cn(lg, o) for o in over))
    evd = {r["competency"]: r["note"] for r in db.run("select competency,note from evidence where user_id=? and kind='diagnostic' order by id", (uid,))}
    return {"competencies": snapshot(uid), "bottlenecks": bottlenecks, "top_errors": errs, "overclaimed": over,
            "why_it_matters": {c: i18n.WHY[lg][c] for c in bottlenecks}, "summary": obs, "evidence": {c: evd.get(c) for c in bottlenecks}}

def make_plan(user, profile):
    s = user["situation"]
    lg = i18n.tk(i18n.lang(user["id"]))
    steps = [i18n.t(lg, "s_prac", c=i18n.cn(lg, c), s=s) for c in profile["bottlenecks"][:2]]
    if profile["top_errors"]: steps.append(i18n.t(lg, "s_fix", p=i18n.errn(lg, profile["top_errors"][0]["pattern"])))
    pth = levels.path(user["id"])
    if pth["next"]: steps.append(i18n.t(lg, "s_lvl", a=pth["level"], b=pth["next"], m=pth["minutes_per_day"], t=pth["eta_" + lg]))
    steps.append(i18n.t(lg, "s_new"))
    return {"steps": steps[:5]}

# ---------- motor de decisión ----------
def decide(user, consume=False):
    uid = user["id"]; C = comps(uid); E = {k: eff(v) for k, v in C.items()}; lg = i18n.tk(i18n.lang(uid))
    decs = db.run("select * from decisions where user_id=? order by id", (uid,))
    used = [L(d["decision_json"]).get("scenario") for d in decs]
    last = next((d for d in reversed(decs) if d["outcome_json"]), None)
    lastout = L(last["outcome_json"]) if last else {}; lastplan = L(last["decision_json"]) if last else {}
    frustrated = db.run("select 1 x from preferences where user_id=? and key='frustrated'", (uid,), one=True)
    weakest = min(E, key=E.get)
    err = db.run("select * from errors where user_id=? and resolved=0 and count>=2 order by count desc limit 1", (uid,), one=True)
    gaps = {k: v["level"] - v["autonomy"] for k, v in C.items() if E[k] < 0.8}
    comp, help_max, focus, fmt = weakest, 3, None, None
    if lastout.get("blocked"):
        rule, comp = "change_strategy", lastplan["competency"]
        fmt = random.choice([f for f in FORMATS.values() if f != lastplan["activity_format"]])
        why = i18n.t(lg, "w_block")
    elif err:
        rule, comp, focus, help_max = "recurring_error", err["competency"] or weakest, err["pattern"], 2
        why = i18n.t(lg, "w_rec", focus=i18n.errn(lg, focus), n=err["count"])
    elif gaps and max(gaps.values()) >= 0.2:
        comp = max(gaps, key=gaps.get); rule, help_max = "reduce_hints", 1
        why = i18n.t(lg, "w_gap", c=i18n.cn(lg, comp))
    elif E[weakest] >= 0.8:
        rule, why = "advance", i18n.t(lg, "w_adv")
    else:
        rule = "bottleneck"; why = i18n.t(lg, "w_bn", c=i18n.cn(lg, comp), g=user["goal"])
    fmt = fmt or FORMATS[comp]
    diff = int(clamp(1 + int(C[comp]["level"] * 4) + (rule == "advance") - bool(frustrated), 1, 5))
    if frustrated: why += " " + i18n.t(lg, "w_frus")
    fresh = [v for v in VARIANTS if v not in used] or VARIANTS
    m = db.run("select max(closed_at) m from sessions where user_id=?", (uid,), one=True)["m"]
    days = (db.now() - m) / 86400 if m else 0
    st = db.run("select item from strengths where user_id=? order by times_ok desc limit 1", (uid,), one=True)
    reentry = i18n.t(lg, "reentry", d=int(days), s=(i18n.t(lg, "re_st", i=st["item"]) if st else i18n.t(lg, "re_calm"))) if days >= 3 else None
    if consume and frustrated: db.run("delete from preferences where user_id=? and key='frustrated'", (uid,), write=True)
    return {"rule": rule, "why": why, "competency": comp, "activity_format": fmt, "difficulty": diff, "help_allowed": help_max,
            "focus_error": focus, "focus_label": i18n.errn(lg, focus) if focus else None, "focus_hint": i18n.errh(lg, focus) if focus else None, "scenario": fresh[0], "reentry_note": reentry,
            "objective": i18n.t(lg, "obj", c=i18n.cn(lg, comp), s=user["situation"]) + (i18n.t(lg, "obj_err", f=i18n.errn(lg, focus)) if focus else ""),
            "success_criterion": i18n.t(lg, "succ", h=help_max),
            "memory_to_update": [f"competencies.{comp}", "errors", "strengths", "decision_history"]}

# ---------- sesión ----------
def make_activity(user, plan):
    r = llm.ask_json("Design ONE micro-activity for an English learner (Spanish speaker). Follow the plan exactly (format, difficulty 1-5, scenario). Text-only: no audio, images or microphone; the learner types the answer in English. "
                     "Return {\"prompt\":English task,\"key_phrases\":[...],\"help\":{\"1\":hint,\"2\":guiding question,\"3\":example,\"4\":full explanation with model answer (help language: " + i18n.llm_lang(user["id"]) + ")},"
                     "\"recovery_prompt\":same skill, DIFFERENT scenario, no help}",
                     J({"situation": user["situation"], "goal": user["goal"], "plan": plan}))
    if r and r.get("prompt") and isinstance(r.get("help"), dict) and r.get("recovery_prompt"): return r
    s, sc, d = user["situation"], plan["scenario"], plan["difficulty"]
    extra = f" Use at least {min(d, 4)} full sentence(s) with a connector (because/but/so)." if d >= 2 else ""
    P = {"situational_response": "Write what you would say in English (2-4 sentences).",
         "listen_and_respond": "The other person says: 'Sorry, could you tell me exactly what you need?' Reply in English.",
         "rebuild_from_memory": "Without looking anything up, write 3 phrases you'd use and put each in a sentence.",
         "timed_direct_response": "Answer immediately, first thing that comes to mind, in English: 'Sorry, I didn't catch that. Could you say it again?'"}[plan["activity_format"]]
    rec = f"Situation: {s}. New twist: {VARIANTS[-1] if sc != VARIANTS[-1] else VARIANTS[0]}. {P}"
    return {"prompt": f"Situation: {s}. Twist: {sc}. {P}{extra}",
            "key_phrases": ["Could I...?", "I'd like to...", "I need to...", "Sorry, could you repeat that?"],
            "help": {str(k): i18n.t(i18n.tk(i18n.lang(user["id"])), f"h{k}") for k in (1, 2, 3, 4)},
            "recovery_prompt": rec}

def create_session(user):
    plan = decide(user, consume=True); act = make_activity(user, plan)
    sid = db.run("insert into sessions(user_id,plan_json,activity_json,status,attempts_json,created_at) values(?,?,?,?,?,?)",
                 (user["id"], J(plan), J(act), "active", "[]", db.now()), write=True)
    db.run("insert into decisions(user_id,session_id,rule,decision_json,created_at) values(?,?,?,?,?)",
           (user["id"], sid, plan["rule"], J(plan), db.now()), write=True)
    return {"session_id": sid, "decision": plan, "activity": {"prompt": act["prompt"], "format": plan["activity_format"]}}

def give_help(sess, blocked=False):
    plan, act = L(sess["plan_json"]), L(sess["activity_json"])
    if blocked: db.run("update sessions set blocked=1 where id=?", (sess["id"],), write=True)
    lvl = sess["help_level"] + 1
    if lvl > (4 if blocked else plan["help_allowed"]):
        return {"granted": False, "message": "Esta sesión trabaja con menos ayuda. Intenta otra vez; si estás bloqueado, avísalo (blocked=true) y cambio la estrategia."}
    db.run("update sessions set help_level=? where id=?", (lvl, sess["id"]), write=True)
    return {"granted": True, "level": lvl, "kind": HELP_KIND[lvl], "content": act["help"].get(str(lvl), "")}

def attempt(user, sess, answer):
    plan, act, att = L(sess["plan_json"]), L(sess["activity_json"]), L(sess["attempts_json"])
    ev = evaluate(user, {"prompt": act["prompt"], "competency": plan["competency"], "keywords": act.get("keywords", [])}, answer)
    att.append({"answer": answer, "score": ev["score"], "help_level": sess["help_level"], "errors": ev["errors"],
                "strengths": ev["strengths"], "feedback": ev["feedback"]})
    add_evidence(user["id"], sess["id"], plan["competency"], ev["score"], sess["help_level"], "attempt", ev["feedback"])
    passed = ev["score"] >= PASS; done = passed or len(att) >= 3
    db.run("update sessions set attempts_json=?,status=? where id=?", (J(att), "recovery" if done else "active", sess["id"]), write=True)
    out = {"passed": passed, "score": ev["score"], "feedback": ev["feedback"], "errors": ev["errors"],
           "help_level_used": sess["help_level"], "evaluator": ev["evaluator"]}
    out.update({"recovery_task": act["recovery_prompt"]} if done else {"next": "Intenta de nuevo o pide una ayuda."})
    return out

def recover_and_close(user, sess, answer):
    uid, plan, act, att = user["id"], L(sess["plan_json"]), L(sess["activity_json"]), L(sess["attempts_json"])
    comp = plan["competency"]
    ev = evaluate(user, {"prompt": act["recovery_prompt"], "competency": comp}, answer)
    add_evidence(uid, sess["id"], comp, ev["score"], 0, "recovery", ev["feedback"])
    before = snapshot(uid)
    best = max(a["score"] for a in att)
    bump(uid, comp, max(best, ev["score"]), ev["score"])  # autonomía = desempeño sin ayuda en contexto nuevo
    for a in att + [ev]: record_errors(uid, comp, a["errors"]); record_strengths(uid, a["strengths"])
    resolved = None
    if plan.get("focus_error") and ev["score"] >= PASS and plan["focus_error"] not in {e["pattern"] for e in ev["errors"]}:
        db.run("update errors set resolved=1 where user_id=? and pattern=?", (uid, plan["focus_error"]), write=True); resolved = plan["focus_error"]
    max_help = max(a["help_level"] for a in att)
    outcome = {"success": ev["score"] >= PASS, "recovery_score": ev["score"], "max_help": max_help,
               "blocked": bool(sess["blocked"]) or max_help >= 4 or best < PASS}
    after = snapshot(uid); n = after[comp]["evidence"]
    improved = after[comp]["autonomy"] - before[comp]["autonomy"]
    summary = {"competency": comp, "before": before[comp], "after": after[comp], "autonomy_change": round(improved, 2),
               "recovery_score": ev["score"], "recovery_feedback": ev["feedback"], "error_resolved": resolved,
               "honest_note": i18n.t(i18n.tk(i18n.lang(uid)), "hn_low" if n < 3 else "hn_ok")}
    db.run("update sessions set status='closed',summary_json=?,closed_at=? where id=?", (J(summary), db.now(), sess["id"]), write=True)
    db.run("update decisions set outcome_json=? where session_id=?", (J(outcome), sess["id"]), write=True)
    summary["next_step"] = decide(user)
    return summary

def abandon(user, sess):
    plan = L(sess["plan_json"])
    db.run("update sessions set status='abandoned',closed_at=? where id=?", (db.now(), sess["id"]), write=True)
    db.run("update decisions set outcome_json=? where session_id=?", (J({"success": False, "abandoned": True, "blocked": False}), sess["id"]), write=True)
    return {"status": "abandoned", "note": i18n.t(i18n.tk(i18n.lang(user["id"])), "abandon")}

# ---------- conversación libre conectada al plan ----------
def heur_chat(user, msg):
    m = msg.lower(); sig = {"intent": "other", "new_situation": None, "preference": None}
    g = re.search(r"quiero (?:ahora )?(?:practicar|aprender|prepararme para|enfocarme en) (.+)", m)
    mins = re.search(r"(\d+)\s*min", m)
    if re.search(r"frustr|no puedo|difícil|dificil|me rindo|no entiendo|harto|cansad", m): sig["intent"] = "frustration"; reply = "Te leo. Eso que sientes es información útil: mañana ajusto la dificultad. Pero ojo, trabarse en esto es normal cuando algo está en el límite de tu nivel, no significa que no avances."
    elif g: sig.update(intent="goal_change", new_situation=g.group(1).strip(" .")); reply = f"Se puede: cambiamos a '{sig['new_situation']}'. Te aviso el costo: lo que veníamos trabajando para '{user['goal']}' queda en pausa y tu evidencia previa aplica solo parcialmente."
    elif mins: sig.update(intent="preference", preference={"key": "minutes_per_day", "value": mins.group(1)}); reply = f"Anotado: {mins.group(1)} min por sesión. Ajusto el tamaño de las actividades."
    else: reply = "Cuéntame más. Si es una duda de inglés te la respondo y la conecto con tu plan; si es otra cosa, dime y vemos cuánto te acerca o aleja de tu objetivo."
    lg = i18n.tk(i18n.lang(user["id"]))
    reply = i18n.t(lg, {"frustration": "c_frus", "goal_change": "c_goal", "preference": "c_pref"}.get(sig["intent"], "c_other"), s=sig["new_situation"], g=user["goal"], m=(sig["preference"] or {}).get("value"))
    return {"reply": reply, "signals": sig}

def chat(user, msg):
    uid = user["id"]
    db.run("insert into messages(user_id,role,content,created_at) values(?,?,?,?)", (uid, "user", msg, db.now()), write=True)
    prof = L(user["profile_json"]) or {}
    r = llm.ask_json("You are Migo, a close but demanding English companion for a Spanish speaker. Reply in " + i18n.llm_lang(uid) + ", short, warm but honest; never invent progress. "
                     "If the user wants something off-plan, allow it but state the cost vs their goal. "
                     "Return {\"reply\":str,\"signals\":{\"intent\":\"question|frustration|goal_change|off_topic|preference|other\",\"new_situation\":str|null,\"preference\":{\"key\":str,\"value\":str}|null}}",
                     J({"goal": user["goal"], "situation": user["situation"], "profile": prof.get("summary"), "memory": memory(uid)["errors"][:3], "message": msg}))
    if not (r and r.get("reply")): r = heur_chat(user, msg)
    sig = r.get("signals") or {}; applied = []
    if sig.get("intent") == "frustration": set_pref(uid, "frustrated", 1); applied.append(i18n.t(i18n.tk(i18n.lang(uid)), "m_frus"))
    if sig.get("intent") == "goal_change" and sig.get("new_situation"):
        db.run("update users set situation=? where id=?", (sig["new_situation"], uid), write=True); applied.append(f"situation={sig['new_situation']}")
    if sig.get("preference"): set_pref(uid, sig["preference"]["key"], sig["preference"]["value"]); applied.append(f"pref {sig['preference']}")
    db.run("insert into messages(user_id,role,content,created_at) values(?,?,?,?)", (uid, "migo", r["reply"], db.now()), write=True)
    return {"reply": r["reply"], "intent": sig.get("intent", "other"), "memory_updates": applied}

# ---------- progreso basado en evidencia ----------
def progress(user):
    uid = user["id"]; snap = snapshot(uid); out = {}
    for c, v in snap.items():
        base = db.run("select score from evidence where user_id=? and competency=? and kind='diagnostic' order by id limit 1", (uid, c), one=True)
        b = base["score"] if base else None
        out[c] = {"baseline_unaided": b, "current_autonomy": v["autonomy"], "delta": None if b is None else round(v["autonomy"] - b, 2),
                  "observations": v["evidence"], "confidence": "low" if v["evidence"] < 3 else "medium"}
    ind = db.run("select count(*) n from evidence where user_id=? and kind='recovery' and score>=? and help_level=0", (uid, PASS), one=True)["n"]
    return {"by_competency": out, "independent_successes_in_new_contexts": ind, "words_mastered": words_mastered(uid),
            "sessions_closed": db.run("select count(*) n from sessions where user_id=? and status='closed'", (uid,), one=True)["n"],
            "recent_evidence": db.run("select competency,score,help_level,kind,note from evidence where user_id=? order by id desc limit 10", (uid,)),
            "note": i18n.t(i18n.tk(i18n.lang(uid)), "pnote")}
