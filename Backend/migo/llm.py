import os, json, re
PROVIDER = os.getenv("MIGO_PROVIDER", "openai")        # "openai" o "anthropic"
MODEL = os.getenv("MIGO_MODEL", "gpt-4.1-mini")      # pon el modelo GPT al que tengas acceso
_client = None

def enabled():
    return bool(os.getenv("OPENAI_API_KEY" if PROVIDER == "openai" else "ANTHROPIC_API_KEY"))

def ask(system, prompt, max_tokens=1200, json_mode=False):
    global _client
    if not enabled(): return None
    try:
        if PROVIDER == "openai":
            if _client is None:
                from openai import OpenAI; _client = OpenAI()
            kw = {"response_format": {"type": "json_object"}} if json_mode else {}
            r = _client.chat.completions.create(
                model=MODEL, max_completion_tokens=max_tokens, **kw,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}])
            return r.choices[0].message.content
        if _client is None:
            import anthropic; _client = anthropic.Anthropic()
        r = _client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                    messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if b.type == "text")
    except Exception:
        return None

def ask_json(system, prompt, max_tokens=1200):
    t = ask(system + "\nRespond ONLY with valid JSON, no markdown.", prompt, max_tokens, json_mode=True)
    if not t: return None
    try: return json.loads(re.search(r"\{.*\}", t, re.S).group(0))
    except Exception: return None