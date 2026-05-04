"""
Client LLM multi-provider avec fallback automatique.

Ordre de priorité :
  1. Groq         (Llama 3.3 70B — 14 400 req/jour gratuits, 315 tok/s)
  2. OpenRouter   (DeepSeek R1 / Llama — 11+ modèles gratuits)
  3. Gemini       (2.0 Flash — 1 500 req/jour, garder en dernier recours)

Tous les providers exposent une API compatible OpenAI → même code.
Configuration via GitHub Secrets (ajouter GROQ_API_KEY, OPENROUTER_API_KEY).
"""

import json
import logging
import re
import time

log = logging.getLogger("llm")

# ── Configuration des providers ────────────────────────────────────────────

PROVIDERS = [
    {
        "name":     "groq",
        "env_key":  "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model":    "llama-3.3-70b-versatile",
        "max_tokens": 600,
        "rpm_limit":  25,   # 30 RPM officiel — scoring séquentiel évite le dépassement
    },
    {
        "name":     "openrouter",
        "env_key":  "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "model":    "meta-llama/llama-3.3-70b-instruct:free",
        "max_tokens": 600,
        "rpm_limit":  18,
    },
    {
        "name":     "gemini",
        "env_key":  "GEMINI_API_KEY",  # dernier recours — quota gratuit épuisable rapidement
        "base_url": None,   # SDK natif
        "model":    "gemini-2.0-flash",
        "max_tokens": 600,
        "rpm_limit":  14,
    },
]


def _get_providers(settings) -> list:
    """Retourne les providers disponibles (clé API configurée), dans l'ordre."""
    disponibles = []
    for p in PROVIDERS:
        key = getattr(settings, p["env_key"], "") or ""
        if key.strip():
            disponibles.append({**p, "api_key": key.strip()})
    if not disponibles:
        log.warning("Aucun provider LLM configuré — scoring IA désactivé")
    return disponibles


def appel_llm(settings, system: str, prompt: str) -> str:
    """
    Appelle le premier provider disponible.
    Bascule automatiquement sur le suivant en cas d'erreur ou quota dépassé.
    Retourne la réponse texte brute.
    """
    providers = _get_providers(settings)
    last_err = None

    for provider in providers:
        try:
            log.debug(f"LLM via {provider['name']} ({provider['model']})")
            if provider["name"] == "gemini":
                result = _call_gemini(provider, system, prompt)
            else:
                result = _call_openai_compat(provider, system, prompt)
            log.debug(f"LLM {provider['name']} OK")
            # Délai minimal pour respecter le RPM (60s / rpm_limit)
            time.sleep(60 / provider.get("rpm_limit", 20))
            return result
        except Exception as e:
            last_err = e
            err_str = str(e)
            # Quota dépassé → passer au suivant immédiatement
            if any(x in err_str.lower() for x in ["rate_limit", "429", "quota", "exceeded"]):
                log.warning(f"LLM {provider['name']} quota dépassé → fallback")
                continue
            # Autre erreur → retry une fois puis fallback
            log.warning(f"LLM {provider['name']} erreur : {e} → retry")
            time.sleep(3)
            try:
                if provider["name"] == "gemini":
                    return _call_gemini(provider, system, prompt)
                return _call_openai_compat(provider, system, prompt)
            except Exception as e2:
                log.warning(f"LLM {provider['name']} retry échoué : {e2} → fallback")
                last_err = e2
                continue

    log.error(f"Tous les providers LLM ont échoué. Dernière erreur : {last_err}")
    raise RuntimeError(f"LLM indisponible : {last_err}")


def _call_openai_compat(provider: dict, system: str, prompt: str) -> str:
    """Appel via API compatible OpenAI (Groq, OpenRouter, Mistral…)."""
    import requests
    headers = {
        "Authorization": f"Bearer {provider['api_key']}",
        "Content-Type": "application/json",
    }
    # OpenRouter nécessite ces headers pour identifier l'app
    if provider["name"] == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/aubinbleriot-lgtm/immo-bot"
        headers["X-Title"] = "immo-bot"

    payload = {
        "model": provider["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens":  provider["max_tokens"],
        "temperature": 0.1,
    }
    resp = requests.post(
        f"{provider['base_url']}/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError(f"rate_limit 429 {provider['name']}")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_gemini(provider: dict, system: str, prompt: str) -> str:
    """Appel via le SDK natif Google Gemini."""
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
