# 🏠 Immo Bot — Bot immobilier autonome

Bot de surveillance immobilière qui tourne **24h/24 sur GitHub Actions** sans serveur ni abonnement.
Inspiré du pattern [job-bot](https://github.com/aubinbleriot-lgtm/job-bot-ca).

## Ce que ça fait

- **Collecte automatique** toutes les 30 min sur LeBonCoin, Bien'ici, SeLoger, PAP, Figaro Immobilier
- **Scoring IA double** via Google Gemini : Plan A (résidence principale) + Plan B (locatif étudiant)
- **Alerte Telegram immédiate** dès qu'une pépite (score ≥ 75) est détectée
- **Digest email quotidien** à 9h avec les meilleures annonces du jour
- **Base de données persistante** (SQLite committé dans le repo Git)
- **Zéro serveur, zéro VPS, zéro coût** — GitHub Actions gratuit

## Architecture

```
GitHub Actions (cron 30 min)
    └── run_scrape.py
            ├── Collecteurs (LBC · Bien'ici · SeLoger · PAP · Figaro)
            ├── Déduplication SHA256
            ├── Scoring Gemini 2.0 Flash
            ├── Alerte Telegram si score ≥ 75
            └── Commit annonces.db dans le repo

GitHub Actions (cron 9h quotidien)
    └── run_digest.py
            ├── Top annonces du jour
            ├── Email HTML via SendGrid
            └── Résumé Telegram
```

## Installation en 5 étapes

### 1. Fork ce repo

Fork sur GitHub → ton repo privé `immo-bot`.

### 2. Obtenir les clés API (toutes gratuites)

| Service | Où l'obtenir | Coût |
|---|---|---|
| **Gemini API** | [aistudio.google.com](https://aistudio.google.com/app/apikey) | Gratuit (1500 req/jour) |
| **Telegram Bot** | [@BotFather](https://t.me/BotFather) sur Telegram | Gratuit |
| **Telegram Chat ID** | [@userinfobot](https://t.me/userinfobot) sur Telegram | Gratuit |
| **SendGrid** | [sendgrid.com](https://sendgrid.com) (tier gratuit 100 emails/jour) | Gratuit |

### 3. Configurer les GitHub Secrets

Dans ton repo GitHub → **Settings → Secrets and variables → Actions** :

| Secret | Description |
|---|---|
| `GEMINI_API_KEY` | Clé Google Gemini |
| `TELEGRAM_TOKEN` | Token du bot Telegram |
| `TELEGRAM_CHAT_ID` | Ton Chat ID Telegram |
| `EMAIL_TO` | Email de destination du digest |
| `EMAIL_FROM` | Adresse expéditrice vérifiée dans SendGrid |
| `SENDGRID_API_KEY` | Clé SendGrid (optionnel, pour email) |

### 4. Adapter les critères de recherche

Édite `config/config.json` pour définir tes zones, budgets et types de biens :

```json
{
  "recherches": [
    {
      "id": "locatif_grenoble",
      "type": "locatif",
      "ville": "Grenoble",
      "lat": 45.1875602,
      "lng": 5.7357819,
      "rayon_km": 5,
      "prix_min": 50000,
      "prix_max": 150000,
      "surface_min": 15,
      "surface_max": 40,
      "types_bien": ["appartement"],
      "actif": true
    }
  ]
}
```

### 5. Activer et lancer

- Va dans **Actions** sur GitHub
- Active les workflows si nécessaire
- Clique **"Run workflow"** sur `scrape.yml` pour un premier test immédiat

Le bot tourne ensuite tout seul. Ton PC peut être éteint.

## Utilisation locale

```bash
git clone https://github.com/TON-USER/immo-bot
cd immo-bot
pip install -r requirements.txt
playwright install chromium

# Variables d'environnement
export GEMINI_API_KEY="ta-clé"
export TELEGRAM_TOKEN="ton-token"
export TELEGRAM_CHAT_ID="ton-chat-id"

# Lancer
python run_scrape.py              # collecte + scoring + alertes
python run_scrape.py --dry-run    # collecte uniquement
python run_scrape.py --no-alert   # scoring sans alertes
python run_scrape.py --source lbc # LeBonCoin uniquement
python run_digest.py              # digest quotidien
```

## Modifier les critères sans toucher au code

Édite `config/config.json` directement sur GitHub (bouton crayon) :
- Changer les seuils de score (`score_alert_telegram`, `score_alert_email`)
- Activer/désactiver des sources (`sources.seloger: false`)
- Ajouter une nouvelle ville (`recherches[...].actif: true`)

## Structure des fichiers

```
immo-bot/
├── .github/workflows/
│   ├── scrape.yml          ← cron toutes les 30 min
│   └── digest.yml          ← cron quotidien 9h
├── config/
│   ├── settings.py         ← configuration centrale
│   └── config.json         ← critères modifiables
├── core/
│   ├── collectors/
│   │   ├── leboncoin.py    ← API JSON native (lib lbc)
│   │   ├── bienici.py      ← API JSON native
│   │   ├── seloger.py      ← Playwright stealth
│   │   ├── pap.py          ← RSS + BeautifulSoup
│   │   └── figaro.py       ← Playwright stealth
│   ├── database.py         ← SQLite persisté dans Git
│   ├── scorer.py           ← Gemini scoring double A/B
│   └── alerts.py           ← Telegram + email
├── run_scrape.py           ← point d'entrée principal
├── run_digest.py           ← digest quotidien
├── requirements.txt
└── annonces.db             ← base de données (commitée automatiquement)
```

## Scores et verdicts

| Score | Verdict | Action |
|---|---|---|
| 85-100 | 🏆 PÉPITE | Alerte Telegram immédiate |
| 70-84 | 🌟 TRÈS INTÉRESSANT | Alerte Telegram immédiate |
| 60-69 | 👀 À SURVEILLER | Dans le digest email |
| 40-59 | ⚠️ MOYEN | Sauvegardé, pas alerté |
| < 40 | ❌ À ÉVITER | Ignoré |

## Limites importantes

- SeLoger et Figaro peuvent occasionnellement bloquer Playwright → le bot réessaie au prochain run
- Gemini gratuit = 1500 requêtes/jour → suffisant pour ~50 annonces/run × 30 runs/jour
- La base SQLite grossit dans le repo : prévoir un nettoyage mensuel des vieilles annonces
- Les prix et descriptions sont ceux affichés — toujours vérifier sur la fiche originale

## Licence

MIT
