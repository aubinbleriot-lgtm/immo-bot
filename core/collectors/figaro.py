"""
Collecteur Figaro Immobilier — Playwright + API JSON interne.

Figaro Immobilier (immobilier.lefigaro.fr) utilise une API JSON interne
appelée lors du chargement de la page de résultats.
On l'intercepte via playwright network interception.
"""

import json
import logging
import random
import re
import time

from core.collectors.base import BaseCollector, delai_humain, normaliser_annonce, _to_int, _to_float

log = logging.getLogger("collector.figaro")

_TYPE_MAP = {
    "appartement": "appartement",
    "maison":      "maison",
    "studio":      "studio",
    "terrain":     "terrain",
}


def _build_url(r: dict) -> str:
    type_bien = _TYPE_MAP.get(r.get("types_bien", ["appartement"])[0], "appartement")
    ville = (
        r["ville"].lower()
        .replace(" ", "-")
        .replace("'", "")
        .replace("é", "e").replace("è", "e").replace("ê", "e")
    )
    p_min = r.get("prix_min", 0)
    p_max = r.get("prix_max", 9_000_000)
    s_min = r.get("surface_min", 1)
    return (
        f"https://immobilier.lefigaro.fr/annonces/"
        f"immobilier-vente,{type_bien},{ville}-38000.html"
        f"?prixmax={p_max}&prixmin={p_min}&surfacemin={s_min}&tri=date_desc"
    )


class FigaroCollector(BaseCollector):
    source = "figaro"

    def collecter(self) -> list:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Playwright non installé")
            return []

        r = self.recherche
        annonces = []
        json_ads = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                ctx = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="fr-FR",
                )
                page = ctx.new_page()

                # Intercepter les réponses JSON de l'API interne Figaro
                def on_response(response):
                    url = response.url
                    if "api" in url and ("annonce" in url or "search" in url or "listing" in url):
                        try:
                            data = response.json()
                            if isinstance(data, dict) and (
                                data.get("ads") or data.get("results") or data.get("items")
                            ):
                                ads = data.get("ads") or data.get("results") or data.get("items") or []
                                json_ads.extend(ads)
                                log.debug(f"Figaro API JSON interceptée : {len(ads)} annonces")
                        except Exception:
                            pass

                page.on("response", on_response)

                page.goto(_build_url(r), wait_until="domcontentloaded", timeout=25_000)
                time.sleep(random.uniform(2, 4))

                # Refus cookies
                for sel in ["#didomi-notice-disagree-button", "[data-testid='cookie-reject']",
                            "button[id*='refuse']", ".gdpr-refuse"]:
                    try:
                        page.click(sel, timeout=2000)
                        time.sleep(0.5)
                        break
                    except Exception:
                        pass

                time.sleep(2)  # Laisser le temps aux requêtes API de se charger

                # Traiter les annonces interceptées via API
                if json_ads:
                    for ad in json_ads[:30]:
                        raw = _parse_figaro_ad(ad, r)
                        if raw:
                            annonces.append(normaliser_annonce(raw, "figaro", r))
                else:
                    # Fallback DOM
                    annonces = _parse_dom(page, r)

                browser.close()

            log.info(f"Figaro [{r['id']}] → {len(annonces)} annonces")
            delai_humain(8, 15)

        except Exception as e:
            log.error(f"Figaro erreur [{r['id']}] : {e}")

        return annonces


def _parse_figaro_ad(ad: dict, r: dict) -> dict | None:
    url = ad.get("url") or ad.get("link") or ad.get("href") or ""
    if not url:
        return None
    if not url.startswith("http"):
        url = "https://immobilier.lefigaro.fr" + url
    return {
        "titre":        ad.get("title") or ad.get("name") or "Bien Figaro",
        "prix":         ad.get("price") or ad.get("prix"),
        "surface":      ad.get("surface") or ad.get("area"),
        "ville":        ad.get("city") or ad.get("ville") or r["ville"],
        "code_postal":  ad.get("postalCode") or ad.get("codePostal"),
        "adresse":      ad.get("address"),
        "lat":          ad.get("lat") or ad.get("latitude"),
        "lng":          ad.get("lng") or ad.get("longitude"),
        "url":          url,
        "description":  ad.get("description", ""),
        "nb_pieces":    ad.get("rooms") or ad.get("pieces"),
        "nb_chambres":  ad.get("bedrooms") or ad.get("chambres"),
        "type_bien":    r.get("types_bien", ["appartement"])[0],
        "dpe":          ad.get("dpe") or ad.get("energyRate"),
        "ges":          ad.get("ges"),
        "date_publiee": ad.get("publicationDate") or ad.get("datePublication"),
    }


def _parse_dom(page, r: dict) -> list:
    annonces = []
    selectors = [
        ".fig-profil-card", "article[data-id]",
        ".property-card", "[class*='annonce-card']",
        ".classified-card",
    ]
    cards = []
    for sel in selectors:
        cards = page.query_selector_all(sel)
        if cards:
            break

    for card in cards[:25]:
        try:
            lien  = card.query_selector("a[href]")
            titre = card.query_selector("h2, h3, [class*='title']")
            prix  = card.query_selector("[class*='price'], .price")
            surf  = card.query_selector("[class*='surface'], [class*='size']")

            href = lien.get_attribute("href") if lien else ""
            if href and not href.startswith("http"):
                href = "https://immobilier.lefigaro.fr" + href

            raw = {
                "titre":   titre.inner_text(timeout=1000).strip() if titre else "",
                "url":     href,
                "prix":    _to_int(prix.inner_text(timeout=1000) if prix else ""),
                "surface": _to_float(surf.inner_text(timeout=1000) if surf else ""),
                "ville":   r["ville"],
                "type_bien": r.get("types_bien", ["appartement"])[0],
            }
            if raw["url"] and raw["titre"]:
                annonces.append(normaliser_annonce(raw, "figaro", r))
        except Exception:
            continue

    return annonces
