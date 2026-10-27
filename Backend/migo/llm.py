"""Capa LLM opcional. Toda llamada devuelve None si no hay key o falla -> el llamador usa su fallback."""
import os, json, re
MODEL = os.getenv("MIGO_MODEL", "claude-sonnet-5-5")
_client = None

def enabled(): return bool(os.getenv("ANTHROPIC_API_KEY"))

def ask(system, prompt, max_tokens=1200):
    global _client
    if not enabled(): return None
    try:
        if _client is None:
            import anthropic; _client = anthropic.Anthropic()
        r = _client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                    messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if b.type == "text")
    except Exception:
        return None

def ask_json(system, prompt, max_tokens=1200):
    t = ask(system + "\nRespond ONLY with valid JSON, no markdown.", prompt, max_tokens)
    if not t: return None
    try: return json.loads(re.search(r"\{.*\}", t, re.S).group(0))
    except Exception: return None
