"""Recomendaciones para escuchar y ver (podcasts, canales, series, películas) según el NIVEL del usuario.
Cada título tiene un rango de niveles (lo..hi). Se recomiendan los que caben en tu nivel (y son un poco más fáciles, para disfrutar)
y unos pocos del siguiente nivel (para retarte). Cuando tu nivel sube, las recomendaciones cambian solas."""
import time
from . import db, i18n, levels

LV = levels.LV            # A1..C2
# slug, tipo, título, fuente, nivel mínimo, nivel máximo, ritmo, vocabulario, duración, intereses
P, C, S, F, K = "podcast", "canal", "serie", "película", "caricatura"
CATALOG = [
 ("voa", P, "VOA Learning English", "Voice of America", 0, 2, "slow", "news", "", "study"),
 ("peppa", K, "Peppa Pig", "serie infantil", 0, 0, "slow", "kids", "", "family"),
 ("bluey", K, "Bluey", "serie infantil (acento australiano)", 0, 1, "slow", "kids", "~7 min", "family"),
 ("sesame", K, "Sesame Street", "serie infantil", 0, 1, "slow", "kids", "", "family"),
 ("easyeng", C, "Easy English", "YouTube, con subtítulos en inglés", 1, 3, "normal", "daily", "", "travel"),
 ("bbcyt", C, "BBC Learning English", "YouTube", 1, 3, "slow", "daily", "", "study"),
 ("phineas", K, "Phineas and Ferb", "serie animada", 1, 2, "normal", "story", "", "fun"),
 ("avatar", K, "Avatar: The Last Airbender", "serie animada", 1, 2, "normal", "story", "", "fun"),
 ("toy", F, "Toy Story", "película", 1, 2, "normal", "story", "", "family"),
 ("bbc6", P, "6 Minute English", "BBC Learning English", 2, 3, "normal", "topics", "6 min", "study"),
 ("bbcew", P, "The English We Speak", "BBC Learning English", 2, 3, "normal", "idioms", "3 min", "fun"),
 ("allears", P, "All Ears English", "podcast de conversación en inglés americano", 2, 3, "normal", "daily", "", "work"),
 ("lucy", C, "English with Lucy", "YouTube", 2, 4, "normal", "idioms", "", "study"),
 ("friends", S, "Friends", "serie de comedia", 2, 3, "normal", "daily", "~22 min", "fun"),
 ("modern", S, "Modern Family", "serie de comedia", 2, 3, "normal", "daily", "~22 min", "family"),
 ("heart", S, "Heartstopper", "serie (acento británico)", 2, 3, "normal", "daily", "", "fun"),
 ("lukes", P, "Luke's English Podcast", "podcast en inglés británico", 3, 4, "normal", "idioms", "episodios largos", "fun"),
 ("ted", P, "TED Talks Daily", "TED", 3, 4, "normal", "adv", "episodios cortos", "work"),
 ("sysk", P, "Stuff You Should Know", "podcast de curiosidades", 3, 5, "fast", "sci", "", "study"),
 ("office", S, "The Office (US)", "serie de comedia", 3, 4, "normal", "work", "~22 min", "work"),
 ("b99", S, "Brooklyn Nine-Nine", "serie de comedia", 3, 4, "fast", "humor", "~22 min", "work"),
 ("goodplace", S, "The Good Place", "serie de comedia", 3, 4, "normal", "humor", "", "fun"),
 ("lasso", S, "Ted Lasso", "serie de comedia", 3, 4, "normal", "work", "", "work"),
 ("abbott", S, "Abbott Elementary", "serie de comedia", 3, 4, "normal", "work", "~22 min", "study"),
 ("tal", P, "This American Life", "podcast de historias reales", 4, 5, "normal", "story", "", "fun"),
 ("crown", S, "The Crown", "serie (inglés británico formal)", 4, 5, "normal", "adv", "", "study"),
 ("sherlock", S, "Sherlock", "serie de la BBC", 4, 5, "fast", "adv", "", "fun"),
 ("downton", S, "Downton Abbey", "serie de época (inglés británico)", 4, 5, "normal", "adv", "", "study"),
]
BYS = {c[0]: c for c in CATALOG}
KIND_ES = {P: "Podcast", C: "Canal de YouTube", S: "Serie", F: "Película", K: "Serie animada"}
KIND_EN = {P: "Podcast", C: "YouTube channel", S: "Series", F: "Movie", K: "Cartoon"}
AUDIO = {P, C}
SPEED = {"slow": ("va despacio y se entiende bien", "it goes slowly and is easy to follow"), "normal": ("tiene un ritmo natural", "it has a natural pace"), "fast": ("va rápido", "it moves fast")}
VOC = {"kids": ("usa frases cortas y vocabulario básico que se repite", "uses short phrases and basic, repeated vocabulary"),
       "news": ("usa vocabulario sencillo de noticias y temas de actualidad", "uses simple news and current-affairs vocabulary"),
       "topics": ("usa vocabulario variado de ciencia, salud y cultura", "uses varied vocabulary on science, health and culture"),
       "idioms": ("usa expresiones y modismos reales del día a día", "uses real everyday expressions and idioms"),
       "daily": ("usa vocabulario de la vida diaria: casa, comida, trabajo y amigos", "uses everyday vocabulary: home, food, work and friends"),
       "story": ("usa vocabulario de aventuras y de contar historias", "uses adventure and storytelling vocabulary"),
       "work": ("usa vocabulario de oficina y trabajo", "uses office and work vocabulary"),
       "adv": ("usa vocabulario amplio y expresiones de nativos", "uses wide vocabulary and native expressions"),
       "sci": ("usa vocabulario de ciencia, historia y curiosidades", "uses science, history and trivia vocabulary"),
       "humor": ("usa humor, ironía y jerga natural", "uses humor, irony and natural slang")}
TIP = {"audio": ("Escúchalo una vez sin pausas y otra con la transcripción si la tiene. Anota 5 palabras nuevas.", "Listen once without pausing, then again with the transcript if it has one. Write down 5 new words."),
       "video": ("Míralo con subtítulos en inglés (no en español) y repite en voz alta una frase que te guste.", "Watch it with English subtitles (not Spanish) and repeat one line you like out loud.")}
INTEREST = {"work": ["work", "job", "trabaj", "interview", "entrevista", "office", "oficina", "business", "negoci", "career"], "travel": ["travel", "viaj", "trip", "hotel", "airport", "aeropuerto"],
            "study": ["study", "estudi", "exam", "universit", "school", "escuela", "certif"], "family": ["famil", "kids", "niñ", "hij", "child"]}

def _pref(uid, key):
    r = db.run("select value from preferences where user_id=? and key=?", (uid, key), one=True)
    return r["value"] if r else None

def _interests(user):
    t = f'{user["goal"] or ""} {user["situation"] or ""}'.lower()
    return {tag for tag, kws in INTEREST.items() if any(k in t for k in kws)}

def _item(c, k, es, stretch):
    slug, kind, title, src, lo, hi, sp, voc, ln, tag = c
    s, v = SPEED[sp][0 if es else 1], VOC[voc][0 if es else 1]
    cap = lambda x: x[:1].upper() + x[1:]
    if stretch: why = (f"Está pensado para {LV[lo]}, el siguiente nivel. {cap(s)} y {v}. Tendrás que esforzarte un poco, y por eso aprenderás más." if es
                       else f"It is made for {LV[lo]}, your next level. {cap(s)} and {v}. You will have to try harder, which is how you learn more.")
    else: why = (f"Tu nivel es {LV[k]}: {s} y {v}." + (" Es un poco más fácil que tu nivel, ideal para disfrutarlo y ganar fluidez." if lo < k else " Está justo a tu nivel.") if es
                 else f"Your level is {LV[k]}: {s} and {v}." + (" It is a bit easier than your level, ideal to enjoy it and build fluency." if lo < k else " It is right at your level."))
    grp = "audio" if kind in AUDIO else "video"
    return {"slug": slug, "kind": kind, "kind_label": (KIND_ES if es else KIND_EN)[kind], "group": grp, "title": title, "source": src,
            "levels": LV[lo] if lo == hi else f"{LV[lo]}-{LV[hi]}", "len": ln, "why": why, "tip": TIP[grp][0 if es else 1]}

def _pick(items, mine, want_audio, want_video):
    ranked = sorted(items, key=lambda c: -(2 * (c[9] in mine)))        # estable: respeta el orden del catálogo en empates
    out = [c for c in ranked if c[1] in AUDIO][:want_audio] + [c for c in ranked if c[1] not in AUDIO][:want_video]
    return out

def recommend(user, ack=False):
    uid = user["id"]; es = i18n.lang(uid) != "en"; k = levels.estimate(uid)["k"]
    seen = {r["slug"] for r in db.run("select slug from media_seen where user_id=?", (uid,))}
    mine = _interests(user)
    fit = [c for c in CATALOG if c[4] <= k <= c[5] and c[0] not in seen]
    fit.sort(key=lambda c: (c[4] >= k, -(2 * (c[9] in mine))))       # primero lo un poco más fácil que tu nivel (se disfruta más)
    stretch = [c for c in CATALOG if c[4] == k + 1 and c[0] not in seen]
    sections = [{"id": "fit", "title": "Para disfrutar ahora" if es else "To enjoy now", "items": [_item(c, k, es, False) for c in _pick(fit, mine, 2, 2)]}]
    if k < len(LV) - 1 and stretch:
        sections.append({"id": "stretch", "title": (f"Para retarte (nivel {LV[k + 1]})" if es else f"To challenge you ({LV[k + 1]} level)"), "items": [_item(c, k, es, True) for c in _pick(stretch, mine, 1, 1)]})
    prev = _pref(uid, "media_level"); up = None
    if prev is not None and prev.isdigit() and int(prev) < k:
        up = {"from": LV[int(prev)], "to": LV[k], "text": ("Ya tienes recomendaciones nuevas, un poco más retadoras y con vocabulario más amplio." if es else "You have new recommendations, a bit more challenging with wider vocabulary.")}
    if ack or prev is None:                                        # al abrir la pantalla completa se da por visto el cambio de nivel
        db.run("insert into preferences(user_id,key,value) values(?,?,?) on conflict(user_id,key) do update set value=excluded.value", (uid, "media_level", str(k)), write=True)
    note = ("Lo ideal para disfrutar es contenido de tu nivel o un poco más fácil: entiendes la mayor parte, no te frustras y sigues aprendiendo palabras nuevas. Cuando tu nivel suba, esta lista cambia sola." if es
            else "The best content to enjoy is at your level or a bit easier: you understand most of it, don't get frustrated and keep picking up new words. When your level goes up, this list changes by itself.")
    find = ("Búscalo por su nombre en Spotify, YouTube, tu app de podcasts o tu plataforma de series. Lo que hay disponible cambia según el país." if es
            else "Search for it by name on Spotify, YouTube, your podcast app or streaming service. What is available changes by country.")
    return {"level": LV[k], "k": k, "next": LV[k + 1] if k < len(LV) - 1 else None, "level_up": up, "note": note, "find": find, "sections": sections}

def mark_seen(user, slug):
    from fastapi import HTTPException
    if slug not in BYS: raise HTTPException(404, "título no encontrado")
    db.run("insert into media_seen(user_id,slug,at) values(?,?,?) on conflict(user_id,slug) do nothing", (user["id"], slug, time.time()), write=True)
    return {"ok": True}
