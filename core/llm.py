"""
Client LLM multi-provider avec fallback automatique.

Ordre de priorité :
  1. Groq         (Llama 3.3 70B — 14 400 req/jour, 30 RPM)
  2. OpenRouter   (Llama 3.3 70B free — 20 RPM)
  3. Gemini       (2.0 Flash — dernier recours, quota gratuit limité)

Gestion des quotas :
  - RPM dépassé (429 temporaire) → fallback immédiat sur suivant
  - Quota journalier épuisé (limit: 0) → skip définitif pour ce run
  - Pas de retry inter-provider : on avance, on ne tourne pas en rond
"""

import logging
import time

log = logging.getLogger("llm")

PROVIDERS = [
    {
        "name":      "groq",
        "env_key":   "GROQ_API_KEY",
        "base_url":  "https://api.groq.com/openai/v1",
        "model":     "llama-3.3-70b-versatile",
        "max_tokens": 600,
        "min_delay":  2.5,   # 60s / 25 req = 2.4s entre appels
    },
    {
        "name":      "openrouter",
        "env_key":   "OPENROUTER_API_KEY",
        "base_url":  "https://openrouter.ai/api/v1",
        "model":     "meta-llama/llama-3.3-70b-instruct:free",
        "max_tokens": 600,
        "min_delay":  3.5,   # 60s / 18 req = 3.3s
    },
    {
        "name":      "gemini",
        "env_key":   "GEMINI_API_KEY",
        "base_url":  None,
        "model":     "gemini-2.0-flash",
        "max_tokens": 600,
        "min_delay":  5.0,
    },
]

# Providers dont le quota journalier est épuisé pour ce run
_quota_epuise: set[str] = set()


def _get_providers(settings) -> list:
    disponibles = []
    for p in PROVIDERS:
        if p["name"] in _quota_epuise:
            continue
        key = getattr(settings, p["env_key"], "") or ""
        if key.strip():
            disponibles.append({**p, "api_key": key.strip()})
    return disponibles


def appel_llm(settings, system: str, prompt: str) -> str:
    """
    Un seul appel LLM. Cascade Groq → OpenRouter → Gemini.
    Pas de retry : si un provider échoue, on passe au suivant immédiatement.
    Le retry est géré au niveau appelant (scorer._with_retry).
    """
    providers = _get_providers(settings)

    if not providers:
        raise RuntimeError("Aucun provider LLM disponible (quotas épuisés ou clés manquantes)")

    last_err = None
    for provider in providers:
        try:
            result = _call(provider, system, prompt)
            # Délai post-appel pour respecter le RPM
            time.sleep(provider.get("min_delay", 3))
            return result
        except Exception as e:
            err_str = str(e)
            last_err = e

            # Quota journalier épuisé (limit: 0) → ne plus essayer ce provider aujourd'hui
            if "limit: 0" in err_str or "GenerateRequestsPerDayPerProjectPerModel" in err_str:
                log.warning(f"LLM {provider['name']} quota journalier épuisé → retiré pour ce run")
                _quota_epuise.add(provider["name"])
                continue

            # RPM ou quota temporaire → fallback immédiat
            if any(x in err_str.lower() for x in ["rate_limit", "429", "quota", "exceeded", "too many"]):
                log.warning(f"LLM {provider['name']} limite RPM → fallback")
                continue

            # Autre erreur réseau/format → log et fallback
            log.warning(f"LLM {provider['name']} erreur : {str(e)[:100]} → fallback")
            continue

    raise RuntimeError(f"Tous les providers LLM ont échoué : {last_err}")


def _call(provider: dict, system: str, prompt: str) -> str:
    if provider["name"] == "gemini":
        return _call_gemini(provider, system, prompt)
    return _call_openai_compat(provider, system, prompt)


def _call_openai_compat(provider: dict, system: str, prompt: str) -> str:
    import requests
    headers = {
        "Authorization": f"Bearer {provider['api_key']}",
        "Content-Type": "application/json",
    }
    if provider["name"] == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/aubinbleriot-lgtm/immo-bot"
        headers["X-Title"] = "immo-bot"

    resp = requests.post(
        f"{provider['base_url']}/chat/completions",
        headers=headers,
        json={
            "model": provider["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            "max_tokens":  provider["max_tokens"],
            "temperature": 0.1,
        },
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError(f"rate_limit 429")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_gemini(provider: dict, system: str, prompt: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=provider["api_key"])
    resp = client.models.generate_content(
        model=provider["model"],
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.1,
            max_output_tokens=provider["max_tokens"],
        ),
        contents=prompt,
    )
    return resp.text.strip()
