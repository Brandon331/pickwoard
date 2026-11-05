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
        "If a transcript is given, the learner HEARD it as audio without seeing the text: for comprehension judge whether the answer shows they understood it (the learner may answer in Spanish or English; judge understanding, not the language). If competency is translation_independence, judge how direct and natural the reply is (literal calques, L1 interference); seconds_taken is only context. Reuse these known error labels when they apply: " + J(known),
        J({"situation": user["situation"], "task": task["prompt"], "competency": task["competency"], "answer": answer, "seconds_taken": secs, "transcript": task.get("transcript")}))
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
    for x in items: _touch(uid, x["w"], x.get("lv", -1), bool(x["first"] and not x["peek"]), rec=x)
    note = i18n.t(i18n.tk(i18n.lang(uid)), "v_note", a=first, n=n, b=len(good))
    add_evidence(uid, None, "vocabulary", len(good) / n, 0, kind, note)
    return {"first_try": first, "unaided": len(good), "n": n, "note": note, "words_mastered": words_mastered(uid)}

INTERVALS = [1, 1, 3, 7, 14]    # días hasta el próximo repaso según la caja (0 = fallaste o pediste ayuda)
MAX_TURNS = 6                   # turnos del alumno en un rol con Migo
FOLLOW = ["Tell me more about that.", "Why is that important to you?", "What happened next?", "Can you give me an example?", "How do you feel about it?", "Anything else you want to add?"]

def _stem_rx(w): return re.compile(r"\b" + r"\s+".join(re.escape(t) + r"\w*" for t in w.split(" ")), re.I)

def _touch(uid, w, lv, good, rec=None, use=False):
    """Actualiza una palabra. rec = ronda de reconocimiento (frase con hueco); use = el alumno la USÓ en una frase o conversación.
    Caja de repaso: acierto sube una caja (próximo repaso más lejano); fallo en reconocimiento vuelve a 0; fallo al usarla baja una."""
    r = db.run("select box from vocab_words where user_id=? and word=?", (uid, w), one=True)
    box = (r["box"] or 0) if r else 0
    box = min(4, box + 1) if good else (max(0, box - 1) if use else 0)
    now = db.now()
    db.run("insert into vocab_words(user_id,word,lv,seen,first_ok,unaided,used_n,used_ok,box,due,last_seen) values(?,?,?,?,?,?,?,?,?,?,?) on conflict(user_id,word) do update set "
           "seen=vocab_words.seen+excluded.seen, first_ok=vocab_words.first_ok+excluded.first_ok, unaided=vocab_words.unaided+excluded.unaided, "
           "used_n=vocab_words.used_n+excluded.used_n, used_ok=vocab_words.used_ok+excluded.used_ok, box=excluded.box, due=excluded.due, "
           "lv=case when excluded.lv>=0 then excluded.lv else vocab_words.lv end, last_seen=excluded.last_seen",
           (uid, w, lv, 1 if rec is not None else 0, int(bool(rec and rec["first"])), int(bool(rec and rec["first"] and not rec["peek"])),
            1 if use else 0, int(bool(use and good)), box, now + INTERVALS[box] * 86400, now), write=True)

def vocab_due(uid):
    now = db.now()
    rows = db.run("select word as w, lv, box, coalesce(due, last_seen + 86400) as due from vocab_words where user_id=? and coalesce(due, last_seen + 86400) <= ? order by 4", (uid, now))
    nx = db.run("select min(coalesce(due, last_seen + 86400)) t from vocab_words where user_id=? and coalesce(due, last_seen + 86400) > ?", (uid, now), one=True)
    return {"due": rows, "count": len(rows), "next_due": nx["t"] if nx else None}

def vocab_state(uid):
    now = db.now()
    rows = db.run("select word as w, lv, seen, first_ok, unaided, used_n, used_ok, box, coalesce(due, last_seen + 86400) as due, last_seen from vocab_words where user_id=? order by last_seen desc", (uid,))
    for r in rows: r["status"] = "mastered" if r["used_ok"] >= 2 and r["unaided"] >= 2 else "used" if r["used_ok"] >= 1 else "seen"
    return {"path": levels.path(uid), "words": rows, "progress": levels.progress(uid), "due_count": sum(1 for r in rows if r["due"] <= now)}

def use_words(user, items):
    """'Usa la palabra': el alumno escribe SU frase con cada palabra y un evaluador ESTRICTO decide si la usó bien. Sin LLM no se evalúa ni se cambia nada."""
    uid = user["id"]
    known = [e["pattern"] for e in db.run("select pattern from errors where user_id=?", (uid,))]
    r = llm.ask_json("You are a STRICT but kind English teacher evaluating SENTENCES that a Spanish-speaking learner wrote to practice target words. For each item decide used_correctly: "
                     "true ONLY if the target word (any inflection) appears AND is used with the right meaning and part of speech in a grammatical, natural sentence the learner wrote themselves. "
                     "False if the sentence is under 4 words, copies or barely edits the example, is ungrammatical, or uses the word with a wrong meaning. "
                     "Return {\"results\":[{\"w\":word,\"used_correctly\":bool,\"feedback\":ONE short sentence (language: " + i18n.llm_lang(uid) + ") on what is good or wrong,"
                     "\"better\":a more natural English version of THEIR sentence keeping their idea,\"errors\":[{\"pattern\":snake_case_label,\"example\":str}]}]}. Reuse these error labels when they apply: " + J(known),
                     J({"estimated_cefr_level": levels.LV[levels.estimate(uid)["k"]], "items": [{"w": i["w"], "example": _example(i["w"]), "sentence": i["sentence"]} for i in items]}), max_tokens=1400)
    if not (r and isinstance(r.get("results"), list)): return {"evaluator": "none", "results": [], "ok": 0, "n": len(items)}
    by = {x.get("w"): x for x in r["results"] if isinstance(x, dict)}; out = []; ok_n = 0
    for it in items:
        x = by.get(it["w"]) or {}
        good = bool(x.get("used_correctly")) and len(it["sentence"].split()) >= 4 and bool(_stem_rx(it["w"]).search(it["sentence"]))
        _touch(uid, it["w"], it.get("lv", -1), good, use=True); ok_n += good
        out.append({"w": it["w"], "ok": good, "feedback": str(x.get("feedback", ""))[:240], "better": str(x.get("better", ""))[:240]})
        errs = [{"pattern": e["pattern"], "example": str(e.get("example", ""))[:80]} for e in (x.get("errors") or []) if isinstance(e, dict) and e.get("pattern")][:2]
        if errs: record_errors(uid, "production", errs)
    bump(uid, "vocabulary", ok_n / len(items), ok_n / len(items))
    add_evidence(uid, None, "vocabulary", ok_n / len(items), 0, "vocab_use", f"{ok_n}/{len(items)}")
    return {"evaluator": "llm", "results": out, "ok": ok_n, "n": len(items), "words_mastered": words_mastered(uid)}

def _example(w): return ""   # el ejemplo lo conoce el cliente; el evaluador no lo necesita para juzgar el uso

def _nz(t): return " ".join(re.sub(r"[^\w' ]+", " ", str(t).lower()).split())

def clean_fixes(raw, learner_texts, limit=4):
    """Correcciones verificadas: solo las que citan TAL CUAL lo que dijo el alumno (así siempre se ve la frase equivocada). Añade `said`, la frase completa."""
    out, seen = [], set()
    for f in raw or []:
        if not isinstance(f, dict): continue
        w, r = str(f.get("wrong", "")).strip(), str(f.get("right", "")).strip(); nw = _nz(w)
        if not nw or not r or nw == _nz(r) or nw in seen: continue
        said = next((t for t in learner_texts if nw in _nz(t)), None)
        if not said: continue
        seen.add(nw); out.append({"wrong": w[:160], "right": r[:160], "why": str(f.get("why", ""))[:200], "said": said[:300]})
        if len(out) >= limit: break
    return out

def first_name(user): return ((user["name"] or "").strip().split() or [""])[0][:20]

def friend_ctx(user, exclude_rid=None):
    """Lo que Migo sabe de ti como amigo: tu nombre, el error que más se repite y cómo te fue en el último rol."""
    uid = user["id"]
    e = db.run("select pattern,example from errors where user_id=? and resolved=0 order by count desc, last_seen desc limit 1", (uid,), one=True)
    q, a = "select id,scenario_json,summary_json from roleplays where user_id=? and status='done'", [uid]
    if exclude_rid: q += " and id!=?"; a.append(exclude_rid)
    r = db.run(q + " order by id desc limit 1", tuple(a), one=True); last = None
    if r:
        sc, sm = L(r["scenario_json"]) or {}, L(r["summary_json"]) or {}
        last = {"scene": sc.get("title"), "main_fix": (lambda f: (f if isinstance(f, str) or f is None else f"{f.get('wrong')} -> {f.get('right')}"))((sm.get("fixes") or [None])[0]), "words_used_ok": sm.get("ok"), "words_used": sm.get("used")}
    return {"name": first_name(user), "recurring_mistake": ({"pattern": e["pattern"], "example": e["example"]} if e else None), "last_roleplay": last}

def voice_lang(uid): return "es" if i18n.lang(uid) == "es" else "en"   # idioma en que Migo habla como él mismo (TTS)

def _intro_fb(user, sc):
    n, es = first_name(user), i18n.lang(user["id"]) == "es"
    if sc["migo_role"] == "a friendly partner": body = "charlemos un rato en inglés sobre tu situación. ¡Cuando quieras!" if es else "let's chat for a bit about your situation. Whenever you're ready!"
    else: body = (f"practiquemos una escena. Yo: {sc['migo_role']}. Tú: {sc['user_role']}. ¡Cuando quieras!" if es
                  else f"let's practice a scene. Me: {sc['migo_role']}. You: {sc['user_role']}. Whenever you're ready!")
    t = f"{n}, {body}" if n else body
    return t[0].upper() + t[1:]

def role_start(user, words):
    uid = user["id"]; k = levels.estimate(uid)["k"]; keys = ("title", "setting", "migo_role", "user_role", "line")
    r = llm.ask_json("Design a short ROLE-PLAY for an English learner (Spanish speaker). Migo plays a role in a realistic scene tied to the learner's situation; the learner plays themselves. "
                     "Choose a scene where the TARGET WORDS can come up naturally. Return {\"title\":scene title,\"setting\":one sentence,\"migo_role\":who Migo plays,\"user_role\":who the learner plays,"
                     "\"line\":Migo's first line IN ROLE, max 20 words, simple English for the learner's level, ending with a question,"
                     "\"intro\":what Migo says as HIMSELF, a close friend and not the character, just before the scene starts: ONE or TWO short sentences in this language: " + i18n.llm_lang(user["id"]) + ". "
                     "Use the learner's first name, say who you will be today and invite them to start. If friend_context has a recurring_mistake or a last_roleplay main_fix, "
                     "gently say to watch it this time, like a friend (never a lecture, never invent anything that is not in friend_context)}. "
                     "Scene values (title, setting, migo_role, user_role, line) in English, no stage directions.",
                     J({"situation": user["situation"], "goal": user["goal"], "estimated_cefr_level": levels.LV[k], "target_words": [w["w"] for w in words], "friend_context": friend_ctx(user)}))
    sc = {x: r[x].strip()[:200] for x in keys} if isinstance(r, dict) and all(isinstance(r.get(x), str) and r[x].strip() for x in keys) else None
    if not sc: sc = {"title": user["situation"][:60], "setting": "A practice conversation about: " + user["situation"], "migo_role": "a friendly partner", "user_role": "yourself",
                     "line": "Hi! Let's practice. Tell me a little about your situation and what you need."}
    intro = str(r.get("intro") or "").strip()[:260] if isinstance(r, dict) else ""
    if not intro: intro = _intro_fb(user, sc)
    rid = db.run("insert into roleplays(user_id,scenario_json,words_json,turns_json,created_at) values(?,?,?,?,?)", (uid, J(sc), J(words), J([{"who": "migo", "text": sc["line"]}]), db.now()), write=True)
    return {"id": rid, "scenario": sc, "line": sc["line"], "intro": intro, "voice_lang": voice_lang(uid), "words": [w["w"] for w in words], "max_turns": MAX_TURNS}

def role_turn(user, rp, text):
    sc, words, turns = L(rp["scenario_json"]), L(rp["words_json"]), L(rp["turns_json"])
    turns.append({"who": "me", "text": text}); n = sum(1 for t in turns if t["who"] == "me")
    mine = [t["text"] for t in turns if t["who"] == "me"]
    used = [w["w"] for w in words if any(_stem_rx(w["w"]).search(t) for t in mine)]
    done = n >= MAX_TURNS
    if done: reply = "Great talk! Let's see how you did."
    else:
        pending = [w["w"] for w in words if w["w"] not in used]
        hist = "\n".join(("Migo: " if t["who"] == "migo" else "Learner: ") + t["text"] for t in turns[-8:])
        reply = llm.ask("You are Migo, playing " + sc["migo_role"] + " in this scene: " + sc["setting"] + " The learner plays: " + sc["user_role"] + ". Stay in role. First react naturally and warmly to what the learner just said, like a friend would (show you really understood it, e.g. a quick 'Ha, nice!' or 'Oh really?'; "
                        "if it was unclear, say what you understood and check). Then ask ONE question. Total: ONE or TWO short sentences (max 25 words) in simple English for CEFR level " + levels.LV[levels.estimate(user["id"])["k"]] + ". "
                        "No teacher voice. Do NOT correct mistakes now. The question must give the learner a natural reason "
                        "to use one of these words WITHOUT saying the words yourself: " + (", ".join(pending) or "(none left: just keep the conversation natural)") + ".", hist, max_tokens=120)
        reply = (reply or "").strip().replace("\n", " ")[:300] or FOLLOW[(n - 1) % len(FOLLOW)]
    turns.append({"who": "migo", "text": reply})
    db.run("update roleplays set turns_json=? where id=?", (J(turns), rp["id"]), write=True)
    return {"reply": reply, "used_now": used, "turn": n, "done": done}

def role_finish(user, rp):
    uid = user["id"]; words, turns = L(rp["words_json"]), L(rp["turns_json"])
    mine = [t["text"] for t in turns if t["who"] == "me"]
    used = [w for w in words if any(_stem_rx(w["w"]).search(t) for t in mine)]
    r = llm.ask_json("You are a STRICT but kind English teacher doing a ROLE-PLAY review for a Spanish-speaking learner. For each target word the learner used, decide used_correctly: true ONLY if it was used with the right meaning "
                     "and part of speech in a grammatical, natural sentence. Return {\"results\":[{\"w\":word,\"used_correctly\":bool,\"feedback\":ONE short sentence (language: " + i18n.llm_lang(uid) + "),"
                     "\"better\":a more natural version of the learner's sentence}],\"overall\":{\"praise\":one short encouraging sentence (language: " + i18n.llm_lang(uid) + "),"
                     "\"fixes\":[up to 4 objects {\"wrong\":the learner's EXACT words copied verbatim from the transcript,\"right\":the corrected version,\"why\":short reason in the same language as praise}, one per different mistake, never invent words the learner did not say]},"
                     "\"friend\":what Migo says as HIMSELF, a close friend and not a grader, right after the scene: 2 short sentences (language: " + i18n.llm_lang(uid) + ") using the learner's first name; "
                     "react to something specific the learner actually said, and mention ONE concrete thing that went well or ONE thing to watch next time (use friend_context only if truly relevant); if you mention a mistake it MUST be one of the items in overall.fixes. Warm and honest, no scores, never invent progress}.",
                     J({"transcript": "\n".join(("Migo: " if t["who"] == "migo" else "Learner: ") + t["text"] for t in turns), "target_words_used": [w["w"] for w in used], "friend_context": friend_ctx(user, rp["id"])}), max_tokens=1600)
    db.run("update roleplays set status='done', ended_at=? where id=?", (db.now(), rp["id"]), write=True)
    if not (r and isinstance(r.get("results"), list)) or not mine:
        return {"evaluator": "none", "results": [{"w": w["w"], "used": w in used, "ok": False, "feedback": "", "better": ""} for w in words], "ok": 0, "used": len(used), "n": len(words)}
    by = {x.get("w"): x for x in r["results"] if isinstance(x, dict)}; out = []; ok_n = 0
    for w in words:
        if w not in used: out.append({"w": w["w"], "used": False, "ok": False, "feedback": "", "better": ""}); continue
        x = by.get(w["w"]) or {}; good = bool(x.get("used_correctly")); ok_n += good
        _touch(uid, w["w"], w.get("lv", -1), good, use=True)
        out.append({"w": w["w"], "used": True, "ok": good, "feedback": str(x.get("feedback", ""))[:240], "better": str(x.get("better", ""))[:240]})
    if used:
        bump(uid, "vocabulary", ok_n / len(used), ok_n / len(used)); add_evidence(uid, None, "vocabulary", ok_n / len(used), 0, "vocab_use", f"rol: {ok_n}/{len(used)}")
    ov = r.get("overall") if isinstance(r.get("overall"), dict) else {}
    summary = {"evaluator": "llm", "results": out, "praise": str(ov.get("praise", ""))[:240], "fixes": clean_fixes(ov.get("fixes"), mine, 4), "friend": str(r.get("friend") or "").strip()[:420], "voice_lang": voice_lang(uid),
               "ok": ok_n, "used": len(used), "n": len(words), "words_mastered": words_mastered(uid)}
    db.run("update roleplays set summary_json=? where id=?", (J(summary), rp["id"]), write=True)
    return summary


def words_mastered(uid):
    return db.run("select count(*) n from vocab_words where user_id=? and used_ok>=2 and unaided>=2", (uid,), one=True)["n"]   # dominada = reconocida sin ayuda 2 veces Y usada bien 2 veces

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
    modality = "read"          # comprensión: alterna escuchar (audio, sin texto) y leer
    if fmt == "listen_and_respond" and audio_on(uid):
        prev = [L(d["decision_json"]).get("modality") for d in decs if L(d["decision_json"]).get("activity_format") == "listen_and_respond"]
        modality = "read" if prev and prev[-1] == "listen" else "listen"
    diff = int(clamp(1 + int(C[comp]["level"] * 4) + (rule == "advance") - bool(frustrated), 1, 5))
    if frustrated: why += " " + i18n.t(lg, "w_frus")
    fresh = [v for v in VARIANTS if v not in used] or VARIANTS
    m = db.run("select max(closed_at) m from sessions where user_id=?", (uid,), one=True)["m"]
    days = (db.now() - m) / 86400 if m else 0
    st = db.run("select item from strengths where user_id=? order by times_ok desc limit 1", (uid,), one=True)
    reentry = i18n.t(lg, "reentry", d=int(days), s=(i18n.t(lg, "re_st", i=st["item"]) if st else i18n.t(lg, "re_calm"))) if days >= 3 else None
    if consume and frustrated: db.run("delete from preferences where user_id=? and key='frustrated'", (uid,), write=True)
    return {"rule": rule, "why": why, "modality": modality, "competency": comp, "activity_format": fmt, "difficulty": diff, "help_allowed": help_max,
            "focus_error": focus, "focus_label": i18n.errn(lg, focus) if focus else None, "focus_hint": i18n.errh(lg, focus) if focus else None, "scenario": fresh[0], "reentry_note": reentry,
            "objective": i18n.t(lg, "obj", c=i18n.cn(lg, comp), s=user["situation"]) + (i18n.t(lg, "obj_err", f=i18n.errn(lg, focus)) if focus else ""),
            "success_criterion": i18n.t(lg, "succ", h=help_max),
            "memory_to_update": [f"competencies.{comp}", "errors", "strengths", "decision_history"]}

# ---------- sesión ----------
DIALOGUES = [  # respaldo sin LLM. tier 0 = A1-A2 · 1 = B1 · 2 = B2+
 {"tier": 0, "sp": {"A": {"name": "Ana", "g": "f"}, "B": {"name": "Leo", "g": "m"}},
  "s": [("A", "Hi Leo! Are you free on Saturday?"), ("B", "Hi Ana! Yes, I am. Why?"), ("A", "I want to go to the cinema. The film starts at six."), ("B", "Great! Let's meet at the station at five thirty."), ("A", "Perfect. See you on Saturday!")],
  "q": "What are they going to do, and what time do they meet?", "kw": ["cinema", "cine", "film", "película", "five thirty", "5:30", "cinco y media", "station", "estación"]},
 {"tier": 0, "sp": {"A": {"name": "Tom", "g": "m"}, "B": {"name": "Sara", "g": "f"}},
  "s": [("A", "Good morning. What would you like?"), ("B", "A coffee and a sandwich, please."), ("A", "Sorry, we have no sandwiches today. We have cake."), ("B", "OK, a coffee and a piece of cake, please."), ("A", "That is six dollars, please.")],
  "q": "What does the customer order, and how much does it cost?", "kw": ["coffee", "café", "cake", "pastel", "six", "seis", "6"]},
 {"tier": 1, "sp": {"A": {"name": "Marta", "g": "f"}, "B": {"name": "Pablo", "g": "m"}},
  "s": [("A", "Did you finish the report? The boss wants it by Friday."), ("B", "Almost. I still need the sales numbers from Carlos, but he is on holiday until Thursday."), ("A", "Then ask Julia. She has the same numbers and she is in the office today."), ("B", "Good idea. If she sends them this afternoon, I can finish tomorrow.")],
  "q": "What is the problem, and what solution do they find?", "kw": ["numbers", "números", "carlos", "holiday", "vacaciones", "julia", "ask", "pedir", "report", "informe"]},
 {"tier": 2, "sp": {"A": {"name": "Dan", "g": "m"}, "B": {"name": "Eva", "g": "f"}},
  "s": [("A", "I used to love working from home, but lately I feel isolated."), ("B", "Really? I find it more productive. No commute, fewer interruptions."), ("A", "True, but I miss the casual chats by the coffee machine. That's where the best ideas came from."), ("B", "Maybe a hybrid schedule would suit you better: two days at the office, three at home.")],
  "q": "What is each person's opinion about working from home?", "kw": ["isolated", "aislado", "productive", "productivo", "hybrid", "híbrido", "office", "oficina"]}]

def _tx(sc): return " / ".join(f'{t["who"]}: {t["text"]}' for t in sc) if sc else None

def _valid_script(sc):
    return isinstance(sc, list) and 2 <= len(sc) <= 12 and all(isinstance(t, dict) and t.get("who") in ("A", "B") and isinstance(t.get("text"), str) and t["text"].strip() for t in sc)

def _spk(d, a, b):
    d = d if isinstance(d, dict) else {}; out = {}
    for who, nm, g in (("A", a, "f"), ("B", b, "m")):
        x = d.get(who) if isinstance(d.get(who), dict) else {}
        out[who] = {"name": str(x.get("name") or nm)[:20], "g": x.get("g") if x.get("g") in ("f", "m") else g}
    return out

def audio_on(uid):
    r = db.run("select value from preferences where user_id=? and key='audio'", (uid,), one=True)
    return not r or r["value"] != "0"

def make_dialogue(user, plan):
    """Actividad de comprensión: conversación entre 2 personas + una pregunta. Se escucha (sin texto) o se lee, según plan['modality']."""
    r = llm.ask_json("Design ONE comprehension activity for an English learner (Spanish speaker): a short natural conversation between TWO people (speakers A and B) "
                     "about the learner's situation or a related everyday scenario, plus ONE question about its gist or key details. Follow the plan (difficulty 1-5 = CEFR A1..C1, scenario twist). "
                     "4-8 turns, each at most 18 words, natural for that level. The learner will usually HEAR it as audio (no text) and may answer in Spanish or English. "
                     "Return {\"script\":[{\"who\":\"A\",\"text\":...}],\"speakers\":{\"A\":{\"name\":...,\"g\":\"f|m\"},\"B\":{\"name\":...,\"g\":\"f|m\"}},\"prompt\":the question in English,"
                     "\"keywords\":[ideas a correct answer contains, in English and Spanish],\"help\":{\"1\":hint,\"2\":guiding question,\"3\":where to pay attention,\"4\":full explanation of what the conversation says (help language: " + i18n.llm_lang(user["id"]) + ")},"
                     "\"recovery_script\":[...],\"recovery_speakers\":{...},\"recovery_prompt\":question about a DIFFERENT conversation in a different scenario,\"recovery_keywords\":[...]}. "
                     "Plain spoken lines only: no stage directions, no sound effects, no audio instructions.",
                     J({"situation": user["situation"], "goal": user["goal"], "plan": plan}), max_tokens=1800)
    if r and _valid_script(r.get("script")) and _valid_script(r.get("recovery_script")) and r.get("prompt") and r.get("recovery_prompt") and isinstance(r.get("help"), dict):
        r["speakers"] = _spk(r.get("speakers"), "Ana", "Leo"); r["recovery_speakers"] = _spk(r.get("recovery_speakers"), "Eva", "Tom")
        r.setdefault("keywords", []); r.setdefault("recovery_keywords", []); return r
    k = levels.estimate(user["id"])["k"]; tier = 0 if k <= 1 else 1 if k == 2 else 2
    main = random.choice([d for d in DIALOGUES if d["tier"] == tier])
    rec = random.choice([d for d in DIALOGUES if d is not main and abs(d["tier"] - tier) <= 1])
    lg = i18n.tk(i18n.lang(user["id"])); sc = lambda d: [{"who": w, "text": t} for w, t in d["s"]]
    return {"script": sc(main), "speakers": main["sp"], "prompt": main["q"], "keywords": main["kw"],
            "help": {str(i): i18n.t(lg, f"dh{i}") for i in (1, 2, 3, 4)},
            "recovery_script": sc(rec), "recovery_speakers": rec["sp"], "recovery_prompt": rec["q"], "recovery_keywords": rec["kw"]}

def make_activity(user, plan):
    if plan["activity_format"] == "listen_and_respond": return make_dialogue(user, plan)
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
    return {"session_id": sid, "decision": plan, "activity": {"prompt": act["prompt"], "format": plan["activity_format"], "script": act.get("script"), "speakers": act.get("speakers"), "modality": plan.get("modality", "read")}}

def give_help(sess, blocked=False):
    plan, act = L(sess["plan_json"]), L(sess["activity_json"])
    if blocked: db.run("update sessions set blocked=1 where id=?", (sess["id"],), write=True)
    lvl = sess["help_level"] + 1
    if lvl > (4 if blocked else plan["help_allowed"]):
        return {"granted": False, "message": "Esta sesión trabaja con menos ayuda. Intenta otra vez; si estás bloqueado, avísalo (blocked=true) y cambio la estrategia."}
    db.run("update sessions set help_level=? where id=?", (lvl, sess["id"]), write=True)
    return {"granted": True, "level": lvl, "kind": HELP_KIND[lvl], "content": act["help"].get(str(lvl), "")}

def attempt(user, sess, answer, meta=None):
    plan, act, att = L(sess["plan_json"]), L(sess["activity_json"]), L(sess["attempts_json"])
    hl = sess["help_level"]; meta = meta or {}
    if meta.get("viewed"): hl = max(hl, 3)                                      # vio el texto = ayuda
    elif meta.get("slow") or meta.get("replays", 0) > 2: hl = max(hl, 1)        # más de 3 escuchas o audio lento = ayuda leve
    ev = evaluate(user, {"prompt": act["prompt"], "competency": plan["competency"], "keywords": act.get("keywords", []), "transcript": _tx(act.get("script"))}, answer)
    att.append({"answer": answer, "score": ev["score"], "help_level": hl, "errors": ev["errors"],
                "strengths": ev["strengths"], "feedback": ev["feedback"]})
    add_evidence(user["id"], sess["id"], plan["competency"], ev["score"], hl, "attempt", (f'[{plan.get("modality", "read")}] ' if act.get("script") else "") + ev["feedback"])
    passed = ev["score"] >= PASS; done = passed or len(att) >= 3
    db.run("update sessions set attempts_json=?,status=? where id=?", (J(att), "recovery" if done else "active", sess["id"]), write=True)
    out = {"passed": passed, "score": ev["score"], "feedback": ev["feedback"], "errors": ev["errors"],
           "help_level_used": hl, "evaluator": ev["evaluator"]}
    if done: out.update({"recovery_task": act["recovery_prompt"], "recovery_script": act.get("recovery_script"), "recovery_speakers": act.get("recovery_speakers")})
    else: out["next"] = "Intenta de nuevo o pide una ayuda."
    return out

def recover_and_close(user, sess, answer, meta=None):
    uid, plan, act, att = user["id"], L(sess["plan_json"]), L(sess["activity_json"]), L(sess["attempts_json"])
    comp = plan["competency"]
    ev = evaluate(user, {"prompt": act["recovery_prompt"], "competency": comp, "keywords": act.get("recovery_keywords", []), "transcript": _tx(act.get("recovery_script"))}, answer)
    viewed = bool((meta or {}).get("viewed"))
    add_evidence(uid, sess["id"], comp, ev["score"], 3 if viewed else 0, "recovery", ev["feedback"])
    before = snapshot(uid)
    best = max(a["score"] for a in att)
    bump(uid, comp, max(best, ev["score"]), ev["score"] * (0.5 if viewed else 1))  # autonomía = desempeño sin ayuda en contexto nuevo
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
    r = llm.ask_json("You are Migo, a close but demanding English companion for a Spanish speaker. Reply in " + i18n.llm_lang(uid) + ", short, warm but honest; never invent progress. Talk like a close friend: use the user's first name now and then (not in every message) and, only when relevant, mention their last role-play or recurring mistake from friend_context (never invent facts). "
                     "If the user wants something off-plan, allow it but state the cost vs their goal. "
                     "Return {\"reply\":str,\"signals\":{\"intent\":\"question|frustration|goal_change|off_topic|preference|other\",\"new_situation\":str|null,\"preference\":{\"key\":str,\"value\":str}|null}}",
                     J({"goal": user["goal"], "situation": user["situation"], "profile": prof.get("summary"), "memory": memory(uid)["errors"][:3], "friend_context": friend_ctx(user), "message": msg}))
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
