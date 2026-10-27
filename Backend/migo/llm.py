
import os
import json
import re
import traceback

PROVIDER = os.getenv("MIGO_PROVIDER", "openai")
MODEL = os.getenv("MIGO_MODEL", "gpt-4.1-mini")
_client = None


def enabled():
    return bool(
        os.getenv(
            "OPENAI_API_KEY" if PROVIDER == "openai"
            else "ANTHROPIC_API_KEY"
        )
    )


def ask(system, prompt, max_tokens=1200, json_mode=False):
    global _client

    if not enabled():
        print(
            f"[LLM ERROR] No se encontró la API key para "
            f"el proveedor: {PROVIDER}"
        )
        return None

    try:
        if PROVIDER == "openai":
            if _client is None:
                from openai import OpenAI
                _client = OpenAI()

            kw = (
                {"response_format": {"type": "json_object"}}
                if json_mode else {}
            )

            r = _client.chat.completions.create(
                model=MODEL,
                max_completion_tokens=max_tokens,
                **kw,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )

            return r.choices[0].message.content

        elif PROVIDER == "anthropic":
            if _client is None:
                import anthropic
                _client = anthropic.Anthropic()

            r = _client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )

            return "".join(
                b.text for b in r.content if b.type == "text"
            )

        else:
            print(f"[LLM ERROR] Proveedor no válido: {PROVIDER}")
            return None

    except Exception as e:
        print(f"\n[LLM ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        return None


def ask_json(system, prompt, max_tokens=1200):
    t = ask(
        system + "\nRespond ONLY with valid JSON, no markdown.",
        prompt,
        max_tokens=max_tokens,
        json_mode=True,
    )

    if not t:
        return None

    try:
        match = re.search(r"\{.*\}", t, re.S)
        if not match:
            raise ValueError("La respuesta no contiene un objeto JSON.")

        return json.loads(match.group(0))

    except Exception as e:
        print(f"\n[LLM JSON ERROR] {type(e).__name__}: {e}")
        print(f"[LLM JSON RESPONSE] {t}")
        traceback.print_exc()
        return None
