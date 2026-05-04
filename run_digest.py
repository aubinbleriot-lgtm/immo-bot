#!/usr/bin/env python3
"""
Immo Bot — Digest quotidien.
Lancé chaque matin à 9h (heure Paris) par GitHub Actions.
Envoie un résumé email + récap Telegram des meilleures annonces du jour.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from core.database import ImmoDB
from core.alerts import envoyer_digest, envoyer_telegram


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(settings.LOG_FILE),
            logging.StreamHandler(),
        ],
    )


def main():
    setup_logging()
    log = logging.getLogger("run_digest")
    log.info("=" * 60)
    log.info(f"DIGEST QUOTIDIEN — {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    db = ImmoDB(settings.DB_PATH)

    top = db.top_du_jour(seuil=settings.SCORE_ALERT_EMAIL, limite=20)
    log.info(f"Top du jour ({settings.SCORE_ALERT_EMAIL}+) : {len(top)} annonces")

    if not top:
        log.info("Aucune annonce qualifiée aujourd'hui.")

        # Envoyer quand même un message Telegram de status
        if settings.TELEGRAM_TOKEN:
            stats = db.stats()
            total = sum(stats.values())
            msg = (
                f"📊 *Immo Bot — Bilan {datetime.now().strftime('%d/%m')}*\n"
                f"Aucune pépite aujourd'hui.\n"
                f"Total base : {total} annonces · {stats.get('score', 0)} analysées"
            )
            import requests
            requests.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
        db.close()
        return

    # Email digest
    envoyer_digest(settings, top)

    # Résumé Telegram du digest
    if settings.TELEGRAM_TOKEN:
        stats = db.stats()
        sources = db.stats_sources()
        sources_txt = " · ".join(f"{s}: {n}" for s, n in sources.items())
        meilleure = top[0]
        msg = (
            f"☀️ *Digest du {datetime.now().strftime('%d/%m/%Y')}*\n"
            f"{len(top)} opportunités · meilleure score : {meilleure.get('score_final')}/100\n\n"
            f"🏆 *{meilleure.get('titre', '')[:60]}*\n"
            f"📍 {meilleure.get('ville')} · {meilleure.get('source','').upper()}\n"
            f"💰 {meilleure.get('prix', 0):,}€ · {meilleure.get('surface')}m²\n\n"
            f"📦 Sources : {sources_txt}\n"
            f"📊 BDD : {sum(stats.values())} annonces total\n\n"
            f"📧 Digest email envoyé à {settings.EMAIL_TO}"
        )
        import requests
        requests.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )

    for a in top:
        db.marquer_statut(a["id"], "rapporte")

    log.info(f"Digest terminé : {len(top)} annonces envoyées")
    db.close()


if __name__ == "__main__":
    main()
