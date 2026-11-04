"""Lecciones "How to…": expresar algo, situaciones de la vida y estructuras de inglés.
El contenido lo genera la IA según tu nivel y tu idioma de ayuda, y se guarda (lesson_cache) para no pagar dos veces."""
import os, json, random, hashlib, logging
from datetime import datetime, timezone
from . import db, llm, i18n, levels, engine as E

log = logging.getLogger("migo.lessons")
LESSON_DAILY = int(os.getenv("MIGO_LESSON_DAILY", "5"))     # lecciones propias que un usuario puede pedir por día (UTC)
TALK_TURNS = int(os.getenv("MIGO_TALK_TURNS", "4"))        # turnos del alumno en el juego de roles de la lección
HINT_DAILY = int(os.getenv("MIGO_HINT_DAILY", "30"))         # pistas 💡 por usuario y día
CACHE_V = "v2"          # súbelo para regenerar todas las lecciones guardadas (formato nuevo: juego de roles en todas)
def _key(lang): return f"{lang}|{CACHE_V}"

def _c(slug, kind, title, es, en, icon, kw): return dict(slug=slug, kind=kind, title=title, es=es, en=en, icon=icon, kw=kw)
CATALOG = [
 _c("express-happiness", "express", "How to express happiness", "Decir que estás feliz sin repetir «I'm happy»", "Say you're happy without repeating «I'm happy»", "😄", ["happy", "feliz", "excited", "celebr"]),
 _c("apologize", "express", "How to apologize", "Pedir disculpas bien, en casual y en formal", "Apologize well, casual and formal", "🙏", ["apolog", "sorry", "disculp", "perd"]),
 _c("agree-disagree", "express", "How to agree and disagree politely", "Estar de acuerdo o no, con buena educación", "Agree or disagree politely", "🤝", ["agree", "opinion", "meeting", "reunión", "negoti"]),
 _c("say-no", "express", "How to say no politely", "Rechazar sin sonar grosero", "Decline without sounding rude", "🙅", ["decline", "refuse", "invit", "boundar"]),
 _c("compliments", "express", "How to give and accept compliments", "Dar y recibir cumplidos", "Give and accept compliments", "🌟", ["compliment", "cumpl", "social", "friend", "amig"]),
 _c("funeral", "situation", "How to go to a funeral", "Qué decir y qué no en un funeral", "What to say (and not say) at a funeral", "🕊️", ["funeral", "condol", "grief", "death", "muert"]),
 _c("doctor", "situation", "How to talk to a doctor", "Explicar cómo te sientes en la consulta", "Explain how you feel at the doctor", "🩺", ["doctor", "medic", "health", "salud", "hospital"]),
 _c("job-interview", "situation", "How to do a job interview", "Presentarte y responder en una entrevista", "Introduce yourself and answer in an interview", "💼", ["interview", "entrevista", "job", "trabajo", "work", "career", "cv", "resume"]),
 _c("small-talk", "situation", "How to make small talk with strangers", "Conversar con desconocidos sin que sea incómodo", "Chat with strangers without awkwardness", "☕", ["small talk", "stranger", "social", "meet", "conocer", "party", "fiesta"]),
 _c("travel-problems", "situation", "How to handle problems when traveling", "Resolver problemas en aeropuerto y hotel", "Solve problems at the airport and hotel", "✈️", ["travel", "viaj", "airport", "hotel", "trip", "flight", "vuelo"]),
 _c("comparatives", "structure", "How to compare two things", "Comparar: bigger than, more expensive than, as… as", "Compare: bigger than, more expensive than, as… as", "⚖️", ["compar", "than", "superlat"]),
 _c("past", "structure", "How to talk about the past", "Contar lo que pasó (pasado simple)", "Tell what happened (past simple)", "⏪", ["past", "tense", "pasado", "verb", "ed ", "irregular"]),
 _c("plans", "structure", "How to talk about your plans", "Hablar de planes y del futuro", "Talk about plans and the future", "🗓️", ["future", "plan", "going to", "will", "futuro"]),
 _c("polite-questions", "structure", "How to ask polite questions", "Pedir cosas con «Could you…?»", "Ask for things with «Could you…?»", "🙋", ["polite", "modal", "could", "would", "can i", "question", "pregunt", "word order"]),
 _c("describe", "structure", "How to describe people and places", "Describir personas y lugares", "Describe people and places", "🖼️", ["describ", "adject", "appearance", "place", "lugar"]),
]
BY = {c["slug"]: c for c in CATALOG}
KINDS = ("express", "situation", "structure")

def _day(): return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def quota(uid, key, limit, msg):
    """Cuenta un uso del día (reutiliza voice_usage con day='<key>:<fecha>'); 429 si ya pasó el límite."""
    from fastapi import HTTPException
    d = f"{key}:{_day()}"
    r = db.run("insert into voice_usage(user_id,day,n) values(?,?,1) on conflict(user_id,day) do update set n=voice_usage.n+1 returning n", (uid, d), one=True)
    if (r["n"] if r else 1) > limit:
        db.run("update voice_usage set n=n-1 where user_id=? and day=?", (uid, d), write=True)
        raise HTTPException(429, msg)

def _ctx(user):
    uid = user["id"]; k = levels.estimate(uid)["k"]
    return uid, levels.LV[k], i18n.lang(uid), i18n.llm_lang(uid)

def _cached(slug, lvl, lang):
    r = db.run("select title,kind,content_json from lesson_cache where slug=? and lvl=? and lang=?", (slug, lvl, lang), one=True)
    return (r["title"], r["kind"], json.loads(r["content_json"])) if r else None

# ---------------- generación ----------------
def _prompt(title, kind, lvl, lang_name):
    ktxt = f'The lesson type is "{kind}".' if kind else 'Decide the lesson type yourself: "express" (saying a feeling/function), "situation" (a real-life situation with its vocabulary) or "structure" (an English grammar pattern).'
    return (f'You write ONE short English lesson for a Spanish-speaking adult learner (CEFR {lvl}) for Migo, a friendly English companion. Lesson title: "{title}". {ktxt} '
            f'Write explanations, translations, tips and the hook in {lang_name}; all English examples natural, clear and at about {lvl} level. '
            'If the title is NOT about learning to communicate in English, or asks for something harmful, return only {"reject":"short reason in ' + lang_name + '"}. Otherwise return ONLY this JSON: '
            '{"kind":"express|situation|structure","hook":one friendly sentence Migo says to open the lesson, starting in lowercase so it can follow "Name, " and without any name,'
            '"items":[4 or 5 {"en":expression or phrase or pattern,"es":its meaning/use,"tone":"casual|neutral|formal","example":natural English sentence using it,"note":optional short tip}],'
            '"rule":for type structure 2-3 short simple sentences explaining the rule, else "",'
            '"mistake":for type structure {"wrong":typical Spanish-speaker mistake,"right":correct version,"why":short reason} else null,'
            '"avoid":for type situation 2-3 short things NOT to say or do, else [],'
            '"dialogue":for type situation 4 lines [{"who":"You"|"Them","en":line}] of a realistic exchange, else [],'
            '"culture":for type situation ONE short cultural tip, else "",'
            '"check":[3 {"q":short situation or gap-fill sentence in English using ___,"options":[3 short English options],"answer":index of the right option,"why":one short sentence}],'
            '"speak":{"role":{"migo_role":who Migo plays,"user_role":who the learner plays,"setting":one short sentence describing a REALISTIC everyday scene where the learner would naturally need several of the items (e.g. a friend calls with big news, a shop assistant, a coworker, a neighbour at the funeral reception)},'
            '"ask":Migo\'s first line IN ROLE, max 20 words, simple English, ending with a question that makes the learner react,"targets":[3 or 4 of the items\' "en" the learner should try to use naturally in the scene]}} '
            'Be respectful and practical with sensitive topics (funerals, health): never graphic, never medical advice.')

def _valid(r):
    try:
        if not isinstance(r, dict) or r.get("kind") not in KINDS: return False
        it, ck, sp = r["items"], r["check"], r["speak"]
        if not (isinstance(it, list) and len(it) >= 3 and all(isinstance(x, dict) and x.get("en") and x.get("example") for x in it)): return False
        if not (isinstance(ck, list) and len(ck) >= 2 and all(isinstance(q.get("options"), list) and len(q["options"]) >= 2 and isinstance(q.get("answer"), int) and 0 <= q["answer"] < len(q["options"]) and q.get("q") for q in ck)): return False
        return bool(sp.get("ask")) and isinstance(sp.get("targets"), list) and len(sp["targets"]) >= 1 and bool(r.get("hook"))
    except Exception: return False

def _shuffle(r):
    for q in r["check"]:
        right = q["options"][q["answer"]]; random.shuffle(q["options"]); q["answer"] = q["options"].index(right)
    return r

def _fix_role(r):
    sp = r["speak"]; ro = sp.get("role")
    if not (isinstance(ro, dict) and ro.get("migo_role") and ro.get("user_role") and ro.get("setting")):
        sp["role"] = {"migo_role": "a friendly person", "user_role": "yourself", "setting": r.get("title") or "an everyday conversation"}
    return r

def generate(title, kind, lvl, lang_name):
    """Devuelve el contenido, {"reject":..} o None si la IA no respondió bien."""
    r = llm.ask_json(_prompt(title, kind, lvl, lang_name), json.dumps({"title": title}), max_tokens=2600)
    if isinstance(r, dict) and r.get("reject"): return {"reject": str(r["reject"])[:200]}
    if kind and isinstance(r, dict): r["kind"] = kind
    return _fix_role(_shuffle(r)) if _valid(r) else None

def _get_or_make(user, slug, title, kind):
    uid, lvl, lang, lang_name = _ctx(user)
    c = _cached(slug, lvl, _key(lang))
    if c: return c
    from fastapi import HTTPException
    if not llm.enabled(): raise HTTPException(503, "Las lecciones necesitan la IA y ahora no está disponible.")
    r = generate(title, kind, lvl, lang_name)
    if r is None: raise HTTPException(503, "No pude preparar la lección ahora. Inténtalo en un momento.")
    if "reject" in r: raise HTTPException(422, r["reject"])
    db.run("insert into lesson_cache(slug,lvl,lang,title,kind,content_json,created_at) values(?,?,?,?,?,?,?) on conflict(slug,lvl,lang) do nothing",
           (slug, lvl, _key(lang), title, r["kind"], json.dumps(r, ensure_ascii=False), db.now()), write=True)
    return title, r["kind"], r

# ---------------- progreso ----------------
def _prog(uid): return {p["slug"]: p for p in db.run("select slug,title,kind,status,score from lesson_progress where user_id=?", (uid,))}

def _set(uid, slug, title, kind, status, score=None, result=None):
    db.run("insert into lesson_progress(user_id,slug,title,kind,status,score,result_json,updated_at) values(?,?,?,?,?,?,?,?) "
           "on conflict(user_id,slug) do update set status=case when lesson_progress.status='done' and excluded.status!='done' then 'done' else excluded.status end, "
           "score=coalesce(excluded.score,lesson_progress.score), result_json=coalesce(excluded.result_json,lesson_progress.result_json), updated_at=excluded.updated_at",
           (uid, slug, title, kind, status, score, result, db.now()), write=True)

def _recommend(user, prog, es):
    uid = user["id"]
    errs = " ".join((e["pattern"] or "").lower().replace("_", " ") for e in db.run("select pattern from errors where user_id=? and resolved=0 order by count desc limit 3", (uid,)))
    ctx = f'{user["goal"] or ""} {user["situation"] or ""}'.lower(); best = None
    for c in CATALOG:
        if (prog.get(c["slug"]) or {}).get("status") == "done": continue
        e = any(k in errs for k in c["kw"]); g = any(k in ctx for k in c["kw"]); sc = (3 if e else 0) + (1 if g else 0)
        if best is None or sc > best[0]: best = (sc, c, e, g)
    if not best: return None
    _, c, e, g = best
    why = (("Te ayuda con un error que se te repite" if es else "It helps with a mistake you keep making") if e else
           ("Va con lo que quieres lograr" if es else "It fits what you want to achieve") if g else
           ("Buen siguiente paso" if es else "A good next step"))
    return {"slug": c["slug"], "title": c["title"], "icon": c["icon"], "reason": why}

def list_lessons(user):
    uid = user["id"]; es = i18n.lang(uid) != "en"; prog = _prog(uid)
    st = lambda s: (prog.get(s) or {}).get("status", "new")
    groups = [{"kind": k, "lessons": [{"slug": c["slug"], "title": c["title"], "icon": c["icon"], "desc": c["es"] if es else c["en"], "status": st(c["slug"])}
                                      for c in CATALOG if c["kind"] == k]} for k in KINDS]
    mine = [{"slug": s, "title": p["title"], "icon": "✨", "desc": "", "status": p["status"]} for s, p in prog.items() if s.startswith("c-")]
    return {"recommended": _recommend(user, prog, es), "groups": groups, "custom": mine, "custom_left": max(0, LESSON_DAILY - _used(uid, "gen"))}

def _used(uid, key):
    r = db.run("select n from voice_usage where user_id=? and day=?", (uid, f"{key}:{_day()}"), one=True)
    return r["n"] if r else 0

def _find(uid, slug):
    if slug in BY: return BY[slug]["title"], BY[slug]["kind"]
    p = _prog(uid).get(slug)
    if p: return p["title"], None
    return None, None

def start(user, slug):
    from fastapi import HTTPException
    uid = user["id"]; title, kind = _find(uid, slug)
    if not title: raise HTTPException(404, "lección no encontrada")
    title, kind, c = _get_or_make(user, slug, title, kind)
    _set(uid, slug, title, kind, "doing")
    n = E.first_name(user); hook = c["hook"].strip()
    intro = (f"{n}, {hook}" if n else hook[:1].upper() + hook[1:])
    return {"slug": slug, "title": title, "kind": kind, "turns": TALK_TURNS, "intro": intro, "voice_lang": E.voice_lang(uid), "content": {k: v for k, v in c.items() if k != "hook"}}

def create_custom(user, title):
    from fastapi import HTTPException
    uid = user["id"]; title = " ".join(title.split())[:80]
    if len(title) < 6: raise HTTPException(422, "Cuéntame qué quieres aprender, por ejemplo: How to order food at a restaurant")
    slug = "c-" + hashlib.sha1(title.lower().encode()).hexdigest()[:10]
    if not _prog(uid).get(slug): quota(uid, "gen", LESSON_DAILY, f"Hoy ya pediste {LESSON_DAILY} lecciones propias. Mañana puedes pedir más 🙂")
    t, k, c = _get_or_make(user, slug, title, None)
    _set(uid, slug, t, k, "new")
    return start(user, slug)

# ---------------- hablar (3 turnos) ----------------
def _role(r, fb):
    if isinstance(r, dict):
        o = {k: str(r.get(k, "")).strip()[:160] for k in ("migo_role", "user_role", "setting")}
        if all(o.values()): return o
    return fb

def talk(user, slug, history, text, score, role=None):
    from fastapi import HTTPException
    uid, lvl, lang, lang_name = _ctx(user)
    c = _cached(slug, lvl, _key(lang))
    if not c: raise HTTPException(404, "abre la lección otra vez")
    title, kind, d = c
    text = (text or "").strip()[:600]
    if not text: raise HTTPException(422, "no te escuché")
    hist = [{"who": "migo" if h.get("who") == "migo" else "learner", "text": str(h.get("text", ""))[:600]} for h in (history or [])][-12:]
    turn = sum(1 for h in hist if h["who"] == "learner") + 1; last = turn >= TALK_TURNS
    sp = _fix_role(d)["speak"]; role = _role(role, sp["role"])
    sysmsg = (f'You are Migo, playing a character in a REAL-LIFE role-play with {E.first_name(user) or "the learner"} (they play themselves). You are {role["migo_role"]}; the learner is {role["user_role"]}. Scene: {role["setting"]}. '
              'Stay in character; never mention lessons, targets or teaching. '
              f'Talk like a real person at CEFR {lvl}: short natural sentences, contractions (I\'m, don\'t, that\'s) and an occasional natural filler (oh, well, you know) when it fits. '
              f'Expressions the learner may use: {json.dumps(sp["targets"], ensure_ascii=False)}. Do NOT steer the conversation toward them and never quiz; just keep the scene going so they can come up naturally (you may use one yourself, casually, at most once). '
              f'This is learner turn {turn} of {TALK_TURNS}. First react genuinely to what they said (show you understood; if it was unclear, say what you understood and check). '
              + ('This is the LAST turn: wrap the scene up naturally in character (for example saying you have to go, or wishing them luck), with NO question, max 25 words. ' if last else
                 'Then vary: about half of the time ask ONE natural question, otherwise add something about yourself or the situation in one short line, so they have something to answer. Max 30 words. ')
              + 'Sensitive scenes (a funeral, illness): be gentle and respectful, no jokes, never give medical advice. Do NOT correct mistakes inside "reply". '
              + 'Return JSON {"reply":..,"used":[expressions the learner used correctly in THIS message]'
              + (f',"used_all":[expressions used correctly in the whole conversation],"friend":Migo speaking as HIMSELF, out of character, in {lang_name}, 2 short sentences using the learner\'s first name: react to something specific they said, say one thing that went well and one thing to watch next time (no scores),'
                 '"fixes":[up to 2 {"wrong":learner\'s mistake,"right":corrected,"pattern":short snake_case error label}]' if last else '') + '}')
    r = llm.ask_json(sysmsg, json.dumps({"conversation": hist, "learner_says": text, "friend_context": E.friend_ctx(user)}, ensure_ascii=False), max_tokens=800)
    if not isinstance(r, dict) or not r.get("reply"): raise HTTPException(503, "Migo no pudo responder ahora. Inténtalo otra vez.")
    out = {"reply": str(r["reply"])[:300], "used": [u for u in (r.get("used") or []) if isinstance(u, str)][:6], "done": last}
    if last:
        fixes = [{"wrong": str(f.get("wrong", ""))[:160], "right": str(f.get("right", ""))[:160]} for f in (r.get("fixes") or []) if isinstance(f, dict) and f.get("wrong") and f.get("right")][:2]
        pats = [{"pattern": str(f.get("pattern") or "lesson_mistake")[:60], "example": str(f.get("wrong", ""))[:160]} for f in (r.get("fixes") or []) if isinstance(f, dict) and f.get("wrong")][:2]
        if pats: E.record_errors(uid, "production", pats)       # lo que te costó pasa a tu memoria y a las recomendaciones
        used_all = [u for u in (r.get("used_all") or []) if isinstance(u, str)][:6]
        out.update({"friend": str(r.get("friend") or "")[:420], "fixes": fixes, "used_all": used_all, "targets": sp["targets"], "voice_lang": E.voice_lang(uid)})
        sc = max(0, min(len(d["check"]), int(score or 0)))
        conv = [{"who": h["who"] if h["who"] == "migo" else "me", "text": h["text"]} for h in hist] + [{"who": "me", "text": text}, {"who": "migo", "text": out["reply"]}]
        out.update({"conversation": conv, "score": sc, "n": len(d["check"])})
        _set(uid, slug, title, kind, "done", sc, json.dumps({**out, "role": role}, ensure_ascii=False))   # tu conversación y tu feedback quedan guardados
    return out


# ---------------- audios compartidos de las frases de la lección ----------------
def _norm(t): return " ".join(str(t).split())

def _phrases(d):
    ph = set()
    for x in d.get("items", []): ph |= {_norm(x.get("en", "")), _norm(x.get("example", ""))}
    for x in d.get("dialogue", []) or []: ph.add(_norm(x.get("en", "")))
    ph.discard(""); return ph

def audio(user, slug, text):
    """mp3 de una frase de la lección: se genera UNA vez y se comparte entre todos los usuarios (no cuenta en el límite de voz)."""
    from fastapi import HTTPException
    uid, lvl, lang, _ = _ctx(user); c = _cached(slug, lvl, _key(lang))
    if not c: raise HTTPException(404, "abre la lección otra vez")
    t = _norm(text)
    if t not in _phrases(c[2]): raise HTTPException(422, "esa frase no es de la lección")
    h = hashlib.sha1(f"{llm.TTS_MODEL}|{llm.TTS_VOICE}|en|{t}".encode()).hexdigest()
    r = db.run("select audio from tts_cache where h=?", (h,), one=True)
    if r and r["audio"]: return bytes(r["audio"])
    a = llm.tts(t, "en")
    if not a: raise HTTPException(503, "voz no disponible")
    db.run("insert into tts_cache(h,audio,created_at) values(?,?,?) on conflict(h) do nothing", (h, a, db.now()), write=True)
    return a

def result(user, slug):
    from fastapi import HTTPException
    r = db.run("select title,kind,result_json from lesson_progress where user_id=? and slug=?", (user["id"], slug), one=True)
    if not r or not r["result_json"]: raise HTTPException(404, "todavía no terminaste esta lección")
    return {"title": r["title"], "kind": r["kind"], "result": json.loads(r["result_json"])}


# ---------------- escena personalizada y pistas ----------------
def scene(user, slug):
    """Escena de juego de roles hecha para ti (tu nombre, tu meta) y distinta cada vez que repites. Si la IA falla, usa la escena guardada de la lección."""
    from fastapi import HTTPException
    uid, lvl, lang, _ = _ctx(user); c = _cached(slug, lvl, _key(lang))
    if not c: raise HTTPException(404, "abre la lección otra vez")
    title, kind, d = c; sp = _fix_role(d)["speak"]
    pr = db.run("select result_json from lesson_progress where user_id=? and slug=?", (uid, slug), one=True); prev = None
    if pr and pr["result_json"]:
        try: prev = ((json.loads(pr["result_json"]).get("role") or {}).get("setting"))
        except Exception: prev = None
    sysm = ("Design ONE short, realistic role-play scene for an English learner to practice the lesson. Believable everyday situation (not a quiz or interview-style drill) where the target expressions would come up naturally. "
            "The learner plays themselves; Migo plays the other person (a friend, colleague, shop assistant, neighbour...). Use the learner's goal/situation if it fits the lesson. "
            "If the topic is sensitive (funeral, illness) be gentle and respectful. Make it different from avoid_setting. "
            'Return JSON {"role":{"migo_role":..,"user_role":..,"setting":one short sentence},"ask":Migo\'s first line in character, natural, with contractions, max 20 words, simple English for CEFR ' + lvl + "}.")
    r = llm.ask_json(sysm, json.dumps({"lesson": title, "targets": sp["targets"], "learner": {"first_name": E.first_name(user), "goal": user["goal"], "situation": user["situation"]}, "avoid_setting": prev}, ensure_ascii=False), max_tokens=450)
    role = _role(r.get("role") if isinstance(r, dict) else None, None); ask = str((r or {}).get("ask") or "").strip()[:200] if isinstance(r, dict) else ""
    if not role or not ask: return {"role": sp["role"], "ask": sp["ask"]}
    return {"role": role, "ask": ask}

def hint(user, slug, history, role):
    """💡 Pista: dos formas naturales de contestar, con su significado."""
    from fastapi import HTTPException
    uid, lvl, lang, lang_name = _ctx(user); c = _cached(slug, lvl, _key(lang))
    if not c: raise HTTPException(404, "abre la lección otra vez")
    quota(uid, "hint", HINT_DAILY, "Hoy ya usaste muchas pistas 🙂 Inténtalo tú, ¡puedes!")
    sp = _fix_role(c[2])["speak"]; role = _role(role, sp["role"])
    hist = [{"who": "migo" if h.get("who") == "migo" else "learner", "text": str(h.get("text", ""))[:400]} for h in (history or [])][-8:]
    r = llm.ask_json("The learner is stuck in an English role-play and needs help answering. Suggest TWO different natural things they could say next, in simple English for CEFR " + lvl +
                     " (contractions OK), each short (max 14 words) and fitting the scene; naturally use one of the target expressions in the first one if it fits. "
                     'Return JSON {"suggestions":[{"en":..,"es":its meaning in ' + lang_name + "}]}.",
                     json.dumps({"scene": role, "targets": sp["targets"], "conversation": hist}, ensure_ascii=False), max_tokens=350)
    sug = [{"en": str(x.get("en", ""))[:140], "es": str(x.get("es", ""))[:160]} for x in ((r or {}).get("suggestions") or []) if isinstance(x, dict) and x.get("en")][:2] if isinstance(r, dict) else []
    if not sug: raise HTTPException(503, "No se me ocurrió una pista ahora. Inténtalo tú 🙂")
    return {"suggestions": sug}
