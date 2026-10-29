"""Capa LLM: solo OpenAI (ChatGPT). Toda llamada devuelve None si no hay clave o falla -> el llamador usa su respaldo."""
import os, json, re, logging

log = logging.getLogger("migo.llm")
MODEL = os.getenv("MIGO_MODEL", "gpt-4.1-mini")
LAST_ERROR = None          # solo el tipo de error (sin mensaje: podría incluir parte de la clave); el detalle va a los logs
_client = None

def enabled(): return bool(os.getenv("OPENAI_API_KEY"))

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
