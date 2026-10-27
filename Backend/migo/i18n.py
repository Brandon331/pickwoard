"""Idioma de ayuda. Los EJERCICIOS siempre son en inglés; esto controla instrucciones/explicaciones/feedback.
es = español (A1-A2) · mixed = inglés simple + glosa en español (B1) · en = solo inglés (B2+). 'auto' lo deduce del nivel demostrado."""
from . import db, levels

def pref(uid):
    r = db.run("select value from preferences where user_id=? and key='help_lang'", (uid,), one=True)
    return r["value"] if r else "auto"

def lang(uid):
    p = pref(uid)
    if p in ("es", "mixed", "en"): return p
    k = levels.estimate(uid)["k"]          # A1-A2 es · B1 mixed · B2+ en
    return "es" if k <= 1 else "mixed" if k == 2 else "en"

def tk(l): return "en" if l == "en" else "es"      # textos de respaldo (sin LLM): mixed usa español
def llm_lang(uid): return {"es": "Spanish", "mixed": "simple English first, then a one-line Spanish gloss", "en": "simple English only"}[lang(uid)]
def cn(l, c): return CN[l][c]
def t(l, k, **kw): return T[l][k].format(**kw)

CN = {"es": {"comprehension": "comprensión", "production": "expresión", "vocabulary": "vocabulario", "translation_independence": "pensar en inglés sin traducir"},
      "en": {"comprehension": "comprehension", "production": "speaking and writing", "vocabulary": "vocabulary", "translation_independence": "thinking in English without translating"}}
WHY = {"es": {"comprehension": "si no entiendes lo que te dicen, no puedes responder en una situación real",
              "production": "hablar sin guion es lo que separa 'sé inglés' de 'puedo resolver mi situación'",
              "vocabulary": "sin las palabras clave de tu situación te quedas bloqueado a mitad de frase",
              "translation_independence": "es responder directo en inglés sin pasar por el español; sin eso la conversación se vuelve lenta"},
       "en": {"comprehension": "if you can't understand what people say, you can't answer in a real situation",
              "production": "speaking without a script is what separates 'I know English' from 'I can handle my situation'",
              "vocabulary": "without the key words for your situation you freeze mid-sentence",
              "translation_independence": "answering directly in English without passing through Spanish; without it conversation gets slow"}}
T = {"es": {
 "w_block": "La sesión anterior te bloqueó. No repito la explicación: cambio el formato del ejercicio.",
 "w_rec": "El error «{focus}» apareció {n} veces. Lo practico en un contexto nuevo, con poca ayuda.",
 "w_gap": "En «{c}» sabes más de lo que haces solo. Menos pistas, más recuperación.",
 "w_adv": "Todo está sólido: subo la dificultad.",
 "w_bn": "«{c}» es tu punto débil para «{g}».",
 "w_frus": "Te noté frustrado en el chat: bajo un punto la dificultad.",
 "reentry": "Han pasado {d} días, sin drama. Retomamos{s}", "re_st": " desde algo que ya dominas ({i}).", "re_calm": " con calma.",
 "obj": "Mejorar «{c}» en: {s}", "obj_err": " (error: «{f}»)",
 "succ": "Resolverlo con ayuda ≤ {h} y luego repetirlo sin ayuda en un contexto nuevo.",
 "fb_err": "Detecté: {e}.", "fb_ok": "Respuesta razonable (lectura aproximada: sin evaluador LLM).",
 "h1": "Empieza con una de estas: 'Could I...?', 'I'd like to...'.",
 "h2": "¿Qué quieres lograr y cuál es la forma cortés de pedirlo?",
 "h3": "Estructura: 'Hi, I'm [name]. I'd like to [need]. Could you [request]?'",
 "h4": "Saluda, di quién eres, pide lo que necesitas con 'I'd like to...' y cierra con 'Could you...?'. (Sin LLM la explicación es genérica.)",
 "hn_low": "Evidencia aún limitada (<3 observaciones): tómalo como tendencia, no como veredicto.",
 "hn_ok": "Ya hay varias observaciones: la tendencia es más confiable.",
 "abandon": "Sin culpa. La próxima sesión retoma desde donde estabas.",
 "c_frus": "Te leo. Eso que sientes es información útil: en la próxima sesión ajusto la dificultad. Trabarse es normal cuando algo está en tu límite; no significa que no avances.",
 "c_goal": "Se puede: cambiamos a '{s}'. Costo: lo que veníamos trabajando para '{g}' queda en pausa.",
 "c_pref": "Anotado: {m} min por sesión. Ajusto el tamaño de las actividades.",
 "c_other": "Cuéntame más. Si es una duda de inglés te la respondo y la conecto con tu plan; si es otra cosa, vemos cuánto te acerca o aleja de tu objetivo.",
 "p_obs": "Para tu objetivo ({g}), lo que más conviene practicar hoy es «{c}»: {w}.", "p_err": " Error que más se repite: «{p}».",
 "p_over": " Ojo: en «{c}» creías poder más de lo que demostraste.",
 "s_prac": "Practicar «{c}» en situaciones reales de: {s}", "s_fix": "Corregir «{p}» en un contexto nuevo",
 "s_new": "Repetir lo practicado en una situación distinta, con menos ayuda",
 "v_note": "Palabras con imagen: {a} de {n} a la primera, {b} sin ver la imagen.",
 "s_lvl": "Meta «{a}» → «{b}»: {m} min al día durante ~{t}",
 "pnote": "El progreso se mide con tareas sin ayuda en contextos nuevos, no con puntos o rachas.",
 "m_frus": "frustrado=1 (baja la dificultad en la próxima sesión)"},
"en": {
 "w_block": "Last session got you stuck. I won't repeat the explanation: I'm changing the exercise format.",
 "w_rec": "The error «{focus}» showed up {n} times. You'll practice it in a new context, with little help.",
 "w_gap": "In «{c}» you know more than you can do alone. Fewer hints, more recall.",
 "w_adv": "Everything looks solid: I'm raising the difficulty.",
 "w_bn": "«{c}» is your weak spot for «{g}».",
 "w_frus": "You seemed frustrated in the chat: I'm lowering the difficulty by one.",
 "reentry": "It's been {d} days, no drama. Let's pick up{s}", "re_st": " from something you already know ({i}).", "re_calm": " gently.",
 "obj": "Improve «{c}» in: {s}", "obj_err": " (error: «{f}»)",
 "succ": "Solve it with help ≤ {h}, then repeat it with no help in a new context.",
 "fb_err": "I spotted: {e}.", "fb_ok": "Reasonable answer (rough reading: no LLM evaluator).",
 "h1": "Start with one of these: 'Could I...?', 'I'd like to...'.",
 "h2": "What do you want to achieve, and what is the polite way to ask for it?",
 "h3": "Structure: 'Hi, I'm [name]. I'd like to [need]. Could you [request]?'",
 "h4": "Greet, say who you are, ask for what you need with 'I'd like to...' and close with 'Could you...?'. (Without an LLM this explanation is generic.)",
 "hn_low": "Limited evidence so far (<3 observations): treat it as a trend, not a verdict.",
 "hn_ok": "There are several observations now: the trend is more reliable.",
 "abandon": "No guilt. Next session picks up where you were.",
 "c_frus": "I hear you. That feeling is useful information: next session I'll adjust the difficulty. Getting stuck is normal when something is at your limit; it doesn't mean you're not improving.",
 "c_goal": "We can do that: switching to '{s}'. Cost: what we were building for '{g}' goes on hold.",
 "c_pref": "Noted: {m} min per session. I'll resize the activities.",
 "c_other": "Tell me more. If it's an English question I'll answer it and tie it to your plan; if it's something else, we'll see how much it moves you toward or away from your goal.",
 "p_obs": "For your goal ({g}), the best thing to practice today is «{c}»: {w}.", "p_err": " Most repeated error: «{p}».",
 "p_over": " Heads up: in «{c}» you thought you could do more than you showed.",
 "s_prac": "Practice «{c}» in real situations: {s}", "s_fix": "Fix «{p}» in a new context",
 "s_new": "Repeat what you practiced in a different situation, with less help",
 "v_note": "Words with pictures: {a} of {n} on the first try, {b} without peeking at the picture.",
 "s_lvl": "Goal «{a}» → «{b}»: {m} min a day for ~{t}",
 "pnote": "Progress is measured with unaided tasks in new contexts, not points or streaks.",
 "m_frus": "frustrated=1 (lower difficulty next session)"}}

# patrón de error -> (nombre es, pista es, name en, hint en). Si el LLM inventa otro patrón se muestra "limpio".
ERR = {
 "capitalization": ("mayúsculas", "Escribe con mayúscula «I», el inicio de cada oración y los nombres propios.", "capital letters", "Capitalize «I», the start of each sentence and proper names."),
 "am_agree": ("«I am agree» en vez de «I agree»", "En inglés «agree» ya es verbo: se dice «I agree», sin «am».", "«I am agree» instead of «I agree»", "«Agree» is already a verb: say «I agree», no «am»."),
 "age_with_have": ("edad con «have»", "Se dice «I am 25 years old», no «I have 25 years».", "age with «have»", "Say «I am 25 years old», not «I have 25 years»."),
 "dropped_subject": ("falta el sujeto", "Toda oración necesita sujeto: «I want a job», no «Want job».", "missing subject", "Every sentence needs a subject: «I want a job», not «Want job»."),
 "am_plus_base_verb": ("«am» + otro verbo", "No juntes «am» con un verbo: «I want», no «I am want».", "«am» + another verb", "Don't join «am» with a verb: «I want», not «I am want»."),
 "uncountable_plural": ("plural incorrecto", "«information» y «advice» no llevan «s»; «people» ya es plural.", "wrong plural", "«information» and «advice» take no «s»; «people» is already plural."),
 "falls_back_to_spanish": ("cambias al español", "Intenta decirlo con palabras simples en inglés en vez de pasarte al español.", "switching to Spanish", "Try saying it with simple English words instead of switching to Spanish."),
 "subject_verb_agreement": ("concordancia sujeto-verbo", "«He works», «they work»: el verbo cambia con el sujeto.", "subject-verb agreement", "«He works», «they work»: the verb changes with the subject."),
 "verb_tense": ("tiempo verbal", "Revisa si hablas del pasado, presente o futuro y conjuga igual.", "verb tense", "Check whether you mean past, present or future and conjugate to match."),
 "article_usage": ("artículos (a / an / the)", "Casi siempre necesitas «a», «an» o «the» antes de un sustantivo singular.", "articles (a / an / the)", "You almost always need «a», «an» or «the» before a singular noun."),
 "word_order": ("orden de las palabras", "En inglés va sujeto + verbo + resto: «I like coffee».", "word order", "English goes subject + verb + rest: «I like coffee»."),
 "preposition_usage": ("preposiciones (in / on / at)", "Cada verbo o lugar pide su preposición; apréndelas en frases completas.", "prepositions (in / on / at)", "Each verb or place takes its own preposition; learn them in full phrases."),
 "missing_verb": ("falta un verbo", "Cada oración necesita un verbo: «I am happy», no «I happy».", "missing verb", "Every sentence needs a verb: «I am happy», not «I happy»."),
 "spelling": ("ortografía", "Revisa cómo se escribe la palabra; léela en voz alta y escríbela otra vez.", "spelling", "Check how the word is spelled; read it aloud and write it again."),
 "punctuation": ("puntuación", "Cierra las oraciones con punto o signo de pregunta.", "punctuation", "End sentences with a period or question mark."),
}
def errn(l, p):
    e = ERR.get(p); n = (e[0] if l == "es" else e[2]) if e else p.replace("_", " ")
    return n.replace("«", "'").replace("»", "'")
def errh(l, p): e = ERR.get(p); return (e[1] if l == "es" else e[3]) if e else ""
