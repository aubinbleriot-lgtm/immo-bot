#!/usr/bin/env python3
"""
Immo Bot — Collecte, enrichissement et scoring autonome.
Lancé toutes les 30 min par GitHub Actions. PC éteint = bot actif.
"""

import argparse, logging, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from core.database import ImmoDB
from core.collectors import collecter_tout
from core.enricher import enrichir
from core.scorer import scorer_annonce
from core.alerts import envoyer_telegram


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        # PAS de FileHandler → les logs ne sont pas committés dans Git
        handlers=[logging.StreamHandler()],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--no-alert", action="store_true")
    parser.add_argument("--source",   type=str, help="lbc|bienici|seloger|pap|figaro")
    args = parser.parse_args()

    setup_logging()
    log = logging.getLogger("run_scrape")
    t0  = time.time()

    log.info("=" * 60)
    log.info(f"IMMO BOT — {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    if not settings.GEMINI_API_KEY and not args.dry_run:
        log.error("GEMINI_API_KEY manquante (GitHub Secret).")
        sys.exit(1)

    if args.source:
        for k in settings.SOURCES:
            settings.SOURCES[k] = (k == args.source)

    db = ImmoDB(settings.DB_PATH)
    nb_collectes = nb_nouvelles = nb_enrichies = nb_scorees = nb_alertes = 0

    # ── 1. Collecte ──────────────────────────────────────────────────────
    log.info("--- Phase 1 : Collecte multi-sources ---")
    annonces_brutes = collecter_tout(settings)
    nb_collectes = len(annonces_brutes)

    for a in annonces_brutes:
        if db.inserer(a):
            nb_nouvelles += 1

    log.info(f"Collectées={nb_collectes} | Nouvelles={nb_nouvelles}")

    if args.dry_run:
        db.log_run({"nb_collectes": nb_collectes, "nb_nouvelles": nb_nouvelles,
                    "duree_sec": round(time.time()-t0, 1)})
        db.close(); return

    # ── 2. Enrichissement géo + rentabilité ──────────────────────────────
    log.info("--- Phase 2 : Enrichissement géo + rentabilité ---")
    a_enrichir = db.a_enrichir(limite=settings.MAX_ANNONCES_SCORING)
    log.info(f"À enrichir : {len(a_enrichir)}")

    for annonce in a_enrichir:
        try:
            geo = enrichir(annonce)
            db.mettre_a_jour_geo(annonce["id"], geo)
            db.marquer_statut(annonce["id"], "enrichi")
            nb_enrichies += 1
            log.info(f"  enrichi : {annonce['titre'][:50]} | campus={geo.get('dist_campus_km')}km | rdt={geo.get('rendement_brut')}%")
        except Exception as e:
            log.error(f"Enrichissement {annonce['id']} : {e}")

    # ── 3. Scoring hybride en parallèle ───────────────────────────────────
    log.info("--- Phase 3 : Scoring hybride ---")
    a_scorer = db.a_scorer(limite=settings.MAX_ANNONCES_SCORING)
    log.info(f"À scorer : {len(a_scorer)} (workers={settings.SCORING_WORKERS})")

    def _scorer_une(annonce):
        scoring = scorer_annonce(settings, annonce)
        return annonce["id"], scoring

    completed = 0
    with ThreadPoolExecutor(max_workers=settings.SCORING_WORKERS) as executor:
        futures = {executor.submit(_scorer_une, a): a for a in a_scorer}
        for future in as_completed(futures):
            try:
                annonce_id, scoring = future.result()
                db.mettre_a_jour_score(annonce_id, scoring)
                nb_scorees += 1
                completed += 1
                log.info(
                    f"  [{completed}/{len(a_scorer)}] "
                    f"score={scoring.get('score_final','?'):>3} "
                    f"| {scoring.get('verdict','?'):<20} "
                    f"| {futures[future]['titre'][:45]}"
                )
            except Exception as e:
                log.error(f"Scoring : {e}")

    # ── 4. Alertes Telegram ───────────────────────────────────────────────
    if not args.no_alert and settings.TELEGRAM_TOKEN:
        log.info("--- Phase 4 : Alertes Telegram ---")
        a_alerter = db.a_alerter(seuil=settings.SCORE_ALERT_TELEGRAM)
        log.info(f"Pépites à alerter : {len(a_alerter)}")
        for annonce in a_alerter:
            if envoyer_telegram(settings.TELEGRAM_TOKEN, settings.TELEGRAM_CHAT_ID, annonce):
                db.marquer_alerte(annonce["id"])
                nb_alertes += 1

    duree = round(time.time() - t0, 1)
    log.info(f"Terminé en {duree}s | collectées={nb_collectes} nouvelles={nb_nouvelles} "
             f"enrichies={nb_enrichies} scorées={nb_scorees} alertes={nb_alertes}")
    log.info(f"BDD : {db.stats()} | Sources : {db.stats_sources()}")

    db.log_run({
        "source": args.source or "all",
        "nb_collectes": nb_collectes, "nb_nouvelles": nb_nouvelles,
        "nb_scorees": nb_scorees, "nb_alertes": nb_alertes,
        "duree_sec": duree,
    })
    db.close()


if __name__ == "__main__":
    main()
