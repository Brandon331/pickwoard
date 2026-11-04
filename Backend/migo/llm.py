"""Capa LLM: solo OpenAI (ChatGPT). Toda llamada devuelve None si no hay clave o falla -> el llamador usa su respaldo."""
import os, json, re, logging

log = logging.getLogger("migo.llm")
MODEL = os.getenv("MIGO_MODEL", "gpt-4.1-mini")
TTS_MODEL = os.getenv("MIGO_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("MIGO_VOICE", "marin")
STT_MODEL = os.getenv("MIGO_STT_MODEL", "gpt-4o-mini-transcribe")
TTS_STYLE = "Speak like a warm, friendly English conversation partner. Natural pace, clear pronunciation, relaxed and encouraging, not robotic."
LAST_ERROR = None          # solo el tipo de error (sin mensaje: podría incluir parte de la clave); el detalle va a los logs
_client = None

def enabled(): return bool(os.getenv("OPENAI_API_KEY"))

def _cli():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(timeout=45)
    return _client

TTS_STYLE_ES = "Habla en español natural y cercano, como un amigo: cálido, ritmo relajado, pronunciación clara, nada robótico."

def tts(text, lang="en"):
    """Texto -> bytes mp3 con voz natural. None si no hay clave o falla."""
    global LAST_ERROR
    if not enabled() or not text: return None
    try:
        r = _cli().audio.speech.create(model=TTS_MODEL, voice=TTS_VOICE, input=text[:500], instructions=(TTS_STYLE_ES if lang == "es" else TTS_STYLE), response_format="mp3")
        LAST_ERROR = None
        return r.content
    except Exception as e:
        LAST_ERROR = type(e).__name__; log.error("TTS error (%s): %s", LAST_ERROR, e); return None

def stt(data, filename="audio.webm", mime="audio/webm", hint=""):
    """Audio -> texto en inglés. None si falla. `hint` = palabras objetivo (ayuda a reconocerlas)."""
    global LAST_ERROR
    if not enabled() or not data: return None
    try:
        kw = {"prompt": hint[:200]} if hint else {}
        r = _cli().audio.transcriptions.create(model=STT_MODEL, file=(filename, data, mime), language="en", **kw)
        LAST_ERROR = None
        return (r.text or "").strip()
    except Exception as e:
        LAST_ERROR = type(e).__name__; log.error("STT error (%s): %s", LAST_ERROR, e); return None

def ask(system, prompt, max_tokens=1200, json_mode=False):
    global _client, LAST_ERROR
    if not enabled(): return None
    try:
        if _client is None:
            from openai import OpenAI
            _client = OpenAI(timeout=45)
        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        r = _client.chat.completions.create(
            model=MODEL, max_completion_tokens=max_tokens, **kw,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}])
        LAST_ERROR = None
        return r.choices[0].message.content
    except Exception as e:
        LAST_ERROR = type(e).__name__
        log.error("LLM error (%s): %s", LAST_ERROR, e)
        return None

def ask_json(system, prompt, max_tokens=1200):
    t = ask(system + "\nRespond ONLY with valid JSON, no markdown.", prompt, max_tokens, json_mode=True)
    if not t: return None
    try: return json.loads(re.search(r"\{.*\}", t, re.S).group(0))
    except Exception:
        global LAST_ERROR
        LAST_ERROR = "InvalidJSON"; log.error("LLM devolvió JSON inválido"); return None
