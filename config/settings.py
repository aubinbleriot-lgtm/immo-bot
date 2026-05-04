"""
Configuration centrale du bot immobilier.
Variables d'environnement → GitHub Actions Secrets.
Valeurs dynamiques (critères, seuils) → config.json.
"""

import json
import os
from pathlib import Path

# ── Chemins ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DB_PATH    = BASE_DIR / "annonces.db"
LOG_DIR    = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE   = LOG_DIR / "immo-bot.log"

# ── Secrets (GitHub Actions Secrets) ─────────────────────────────────────────
# ── LLM providers (par ordre de priorité) ────────────────────────────────────
# Ajouter au moins un dans GitHub Secrets. Le bot utilise le premier disponible
# et bascule automatiquement sur le suivant en cas de quota dépassé.

GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")        # groq.com — gratuit, rapide
OPENROUTER_API_KEY= os.getenv("OPENROUTER_API_KEY", "")  # openrouter.ai — 11+ modèles gratuits
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")       # aistudio.google.com — fallback

TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "")
SENDGRID_API_KEY  = os.getenv("SENDGRID_API_KEY", "")
EMAIL_TO          = os.getenv("EMAIL_TO", "")
EMAIL_FROM        = os.getenv("EMAIL_FROM", "immo-bot@noreply.com")

# ── Config dynamique (config.json) ───────────────────────────────────────────
def _load_config() -> dict:
    path = CONFIG_DIR / "config.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_cfg = _load_config()

# Seuils de scoring
SCORE_ALERT_TELEGRAM = _cfg.get("score_alert_telegram", 75)  # alerte immédiate
SCORE_ALERT_EMAIL    = _cfg.get("score_alert_email", 60)      # dans le digest
SCORE_MIN_SAVE       = _cfg.get("score_min_save", 30)         # sauvegarder en DB

MAX_ANNONCES_PAR_RUN = _cfg.get("max_annonces_par_run", 50)
MAX_ANNONCES_SCORING = _cfg.get("max_annonces_scoring", 30)
SCORING_WORKERS      = _cfg.get("scoring_workers", 3)

# ── Critères de recherche ─────────────────────────────────────────────────────
RECHERCHES = _cfg.get("recherches", [
    {
        "id": "locatif_grenoble",
        "label": "Locatif étudiant — Grenoble",
        "type": "locatif",           # Plan B
        "ville": "Grenoble",
        "lat": 45.1875602,
        "lng": 5.7357819,
        "rayon_km": 5,
        "prix_min": 50000,
        "prix_max": 150000,
        "surface_min": 15,
        "surface_max": 40,
        "types_bien": ["appartement"],
        "actif": True,
    },
    {
        "id": "locatif_lyon",
        "label": "Locatif étudiant — Lyon",
        "type": "locatif",
        "ville": "Lyon",
        "lat": 45.7640385,
        "lng": 4.8356938,
        "rayon_km": 5,
        "prix_min": 60000,
        "prix_max": 180000,
        "surface_min": 15,
        "surface_max": 40,
        "types_bien": ["appartement"],
        "actif": True,
    },
    {
        "id": "residence_isere",
        "label": "Résidence principale — Isère",
        "type": "residence",         # Plan A
        "ville": "Allevard",
        "lat": 45.3941,
        "lng": 6.0034,
        "rayon_km": 30,
        "prix_min": 150000,
        "prix_max": 400000,
        "surface_min": 80,
        "surface_max": 250,
        "types_bien": ["maison"],
        "actif": True,
    },
])

# ── Sources actives ───────────────────────────────────────────────────────────
SOURCES = _cfg.get("sources", {
    "leboncoin":  True,
    "bienici":    True,
    "seloger":    True,
    "pap":        True,
    "figaro":     True,
})

# ── Campus Grenoble (pour scoring proximité) ──────────────────────────────────
CAMPUS_GRENOBLE = [
    {"nom": "UGA Domaine Universitaire", "lat": 45.1933, "lng": 5.7687},
    {"nom": "Grenoble INP", "lat": 45.1956, "lng": 5.7698},
    {"nom": "Sciences Po Grenoble", "lat": 45.1880, "lng": 5.7262},
    {"nom": "ENSAG", "lat": 45.1960, "lng": 5.7710},
]

CAMPUS_LYON = [
    {"nom": "Campus La Doua", "lat": 45.7824, "lng": 4.8692},
    {"nom": "Lyon 2 Berges du Rhône", "lat": 45.7490, "lng": 4.8334},
    {"nom": "EM Lyon", "lat": 45.7414, "lng": 4.8757},
]

LOG_LEVEL = "INFO"
