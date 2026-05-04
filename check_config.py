#!/usr/bin/env python3
"""
Script de vérification de la configuration.
Lance avant le premier run : python check_config.py

Vérifie :
  ✓ Clés API LLM (Groq, OpenRouter, Gemini)
  ✓ Connexion effective au provider LLM
  ✓ Telegram (si configuré)
  ✓ Base de données SQLite
  ✓ Import de tous les collecteurs
"""

import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

OK    = "✅"
WARN  = "⚠️ "
FAIL  = "❌"
INFO  = "ℹ️ "

def titre(t): print(f"\n{'─'*50}\n{t}\n{'─'*50}")
def ok(msg):   print(f"  {OK}  {msg}")
def warn(msg): print(f"  {WARN} {msg}")
def fail(msg): print(f"  {FAIL}  {msg}")
def info(msg): print(f"  {INFO}  {msg}")


def check_llm(settings):
    titre("LLM providers")
    from core.llm import PROVIDERS, _get_providers

    providers = _get_providers(settings)
    if not providers:
        fail("Aucune clé API LLM configurée — ajouter GROQ_API_KEY dans GitHub Secrets")
        return False

    for p in PROVIDERS:
        key = getattr(settings, p["env_key"], "")
        if key:
            ok(f"{p['name'].upper()} configuré ({p['model']})")
        else:
            info(f"{p['name'].upper()} non configuré (optionnel)")

    # Test d'un vrai appel LLM
    print()
    print("  Test d'appel LLM réel...")
    try:
        from core.llm import appel_llm
        reponse = appel_llm(
            settings,
            system="Tu es un assistant concis. Réponds en JSON uniquement.",
            prompt='Retourne exactement : {"ok": true, "provider": "test"}',
        )
        import json, re
        clean = re.sub(r"```json\s*|```\s*", "", reponse).strip()
        data = json.loads(clean)
        ok(f"Appel LLM réussi → {reponse[:80]}")
        return True
    except Exception as e:
        fail(f"Appel LLM échoué : {e}")
        return False


def check_telegram(settings):
    titre("Telegram")
    if not settings.TELEGRAM_TOKEN:
        warn("TELEGRAM_TOKEN non configuré — pas d'alertes immédiates")
        return
    if not settings.TELEGRAM_CHAT_ID:
        warn("TELEGRAM_CHAT_ID non configuré")
        return

    try:
        import requests
        resp = requests.get(
            f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/getMe",
            timeout=8,
        )
        if resp.status_code == 200:
            nom = resp.json().get("result", {}).get("username", "?")
            ok(f"Bot Telegram connecté : @{nom}")
        else:
            fail(f"Telegram erreur HTTP {resp.status_code}")
    except Exception as e:
        fail(f"Telegram connexion échouée : {e}")


def check_db(settings):
    titre("Base de données")
    try:
        from core.database import ImmoDB
        db = ImmoDB(settings.DB_PATH)
        stats = db.stats()
        total = sum(stats.values())
        ok(f"SQLite OK — {total} annonces en base")
        if stats:
            for statut, n in stats.items():
                info(f"  {statut}: {n}")
        db.close()
    except Exception as e:
        fail(f"DB erreur : {e}")


def check_collectors():
    titre("Collecteurs")
    collectors = [
        ("core.collectors.leboncoin", "LeBonCoinCollector"),
        ("core.collectors.bienici",   "BienIciCollector"),
        ("core.collectors.seloger",   "SeLogerCollector"),
        ("core.collectors.pap",       "PAPCollector"),
        ("core.collectors.figaro",    "FigaroCollector"),
    ]
    for module, cls in collectors:
        try:
            import importlib
            mod = importlib.import_module(module)
            getattr(mod, cls)
            ok(f"{cls} importé")
        except Exception as e:
            fail(f"{cls} erreur : {e}")


def check_config(settings):
    titre("Configuration recherches")
    actives = [r for r in settings.RECHERCHES if r.get("actif", True)]
    sources = [k for k, v in settings.SOURCES.items() if v]
    ok(f"{len(actives)} recherche(s) active(s) : {[r['id'] for r in actives]}")
    ok(f"{len(sources)} source(s) active(s) : {sources}")
    info(f"Seuil alerte Telegram : {settings.SCORE_ALERT_TELEGRAM}/100")
    info(f"Seuil digest email    : {settings.SCORE_ALERT_EMAIL}/100")


def main():
    print("\n🏠 IMMO BOT — Vérification de la configuration\n")

    from config import settings

    check_config(settings)
    check_collectors()
    check_db(settings)
    llm_ok = check_llm(settings)
    check_telegram(settings)

    titre("Résumé")
    if llm_ok:
        ok("Configuration valide — le bot peut tourner")
        print(f"\n  Prochain run automatique : demain 9h Paris (GitHub Actions)")
        print(f"  Dashboard local         : python dashboard/app.py")
        print(f"  Run manuel maintenant   : python run_scrape.py --dry-run\n")
    else:
        fail("Corriger les erreurs ci-dessus avant le premier run")
        sys.exit(1)


if __name__ == "__main__":
    main()
