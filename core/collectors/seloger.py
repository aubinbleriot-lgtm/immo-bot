"""
Collecteur SeLoger — Playwright headless + __NEXT_DATA__ JSON.

SeLoger est migré Next.js. L'ancienne URL list.htm ne fonctionne plus.
Format correct 2024-2025 : /annonces/achat/[type]/[ville]-[cp]/

Le JSON __NEXT_DATA__ contient les annonces sous :
  props.pageProps.initialData.ads  (structure vérifiée 2024)
  ou props.pageProps.ads

En cas d'échec total : fallback sur sélecteurs CSS data-testid.
"""

import json
import logging
import random
import re
import time

from core.collectors.base import BaseCollector, delai_humain, normaliser_annonce

log = logging.getLogger("collector.seloger")

_TYPE_MAP = {
    "appartement": "appartement",
    "maison":      "maison",
    "studio":      "appartement",
    "terrain":     "terrain",
}

# Codes département pour SeLoger (nécessaires pour le filtre prix)
_CP_DEPT = {
    "Grenoble": "38", "Lyon": "69", "Allevard": "38",
    "Saint-Pierre-de-Chartreuse": "38", "Clermont-Ferrand": "63",
    "Paris": "75", "Marseille": "13", "Bordeaux": "33",
}


def _build_url(r: dict) -> str:
    type_bien = _TYPE_MAP.get(r.get("types_bien", ["appartement"])[0], "appartement")
    ville = r["ville"].lower().replace(" ", "-").replace("'", "").replace("é","e").replace("è","e")
    dept  = _CP_DEPT.get(r["ville"], "")
    cp    = r.get("code_postal", "")
    slug  = f"{ville}-{cp}" if cp else f"{ville}-{dept}0000" if dept else ville
    prix_min = r.get("prix_min", 0)
    prix_max = r.get("prix_max", 9_000_000)
    surf_min = r.get("surface_min", 1)
    return (
        f"https://www.seloger.com/annonces/achat/{type_bien}/{slug}/"
        f"?prix_min={prix_min}&prix_max={prix_max}&surface_min={surf_min}"
        f"&tri=d_dt_crea"
    )


class SeLogerCollector(BaseCollector):
    source = "seloger"

    def collecter(self) -> list:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Playwright non installé")
            return []

        r = self.recherche
        annonces = []
        url = _build_url(r)
        log.debug(f"SeLoger URL: {url}")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                ctx = browser.new_context(
                    viewport={"width": 1366, "height": 768},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="fr-FR",
                    timezone_id="Europe/Paris",
                    extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"},
                )
                page = ctx.new_page()

                # Masquer l'automatisation
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = {runtime: {}};
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
                """)

                resp = page.goto(url, wait_until="domcontentloaded", timeout=35_000)
                time.sleep(random.uniform(2, 4))

                # Refus cookies (plusieurs sélecteurs possibles)
                for sel in ["#didomi-notice-disagree-button", "button[id*='refuse']",
                            "button[id*='deny']", "#onetrust-reject-all-handler"]:
                    try:
                        page.click(sel, timeout=2000)
                        time.sleep(0.5)
                        break
                    except Exception:
                        pass

                # Extraire __NEXT_DATA__
                raw_json = page.evaluate("""
                    () => {
                        const el = document.getElementById('__NEXT_DATA__');
                        return el ? el.textContent : null;
                    }
                """)

                if raw_json:
                    try:
                        data = json.loads(raw_json)
                        annonces = _parse_next_data(data, r)
                    except Exception as e:
                        log.warning(f"SeLoger parse __NEXT_DATA__ : {e}")

                # Fallback CSS si JSON vide
                if not annonces:
                    annonces = _parse_html(page, r)

                browser.close()

            log.info(f"SeLoger [{r['id']}] → {len(annonces)} annonces")
            delai_humain(6, 12)  # SeLoger = Datadome, délai long obligatoire

        except Exception as e:
            log.error(f"SeLoger erreur [{r['id']}] : {e}")

        return annonces


def _parse_next_data(data: dict, r: dict) -> list:
    """
    Cherche les annonces dans __NEXT_DATA__ — structure Next.js SeLoger.
    Plusieurs chemins possibles selon la version du site.
    """
    annonces = []
    pp = data.get("props", {}).get("pageProps", {})

    # Chemins connus (SeLoger change régulièrement sa structure)
    candidates = (
        pp.get("initialData", {}).get("ads")
        or pp.get("ads")
        or pp.get("listings")
        or pp.get("searchResult", {}).get("ads")
        or pp.get("data", {}).get("ads")
        or []
    )

    for ad in candidates:
        # SeLoger peut imbriquer les prix différemment
        prix = (ad.get("pricing", {}) or {}).get("price") or ad.get("price") or ad.get("priceRaw")

        # Coordonnées
        coord = ad.get("coordinate") or ad.get("coordinates") or {}
        lat = coord.get("lat") or coord.get("latitude")
        lng = coord.get("lon") or coord.get("lng") or coord.get("longitude")

        # DPE
        dpe_info = ad.get("energyConsumption") or ad.get("dpe") or {}
        dpe = dpe_info.get("letter") or dpe_info if isinstance(dpe_info, str) else None
        ges_info = ad.get("gasEmission") or ad.get("ges") or {}
        ges = ges_info.get("letter") or ges_info if isinstance(ges_info, str) else None

        # URL
        slug = ad.get("slug") or ad.get("id") or ""
        url = ad.get("url") or (
            f"https://www.seloger.com/annonces/achat/{slug}" if not str(slug).startswith("http") else slug
        )

        raw = {
            "titre":        ad.get("title") or ad.get("subject") or "Bien SeLoger",
            "prix":         prix,
            "surface":      ad.get("surface") or ad.get("area") or ad.get("surfaceArea"),
            "ville":        ad.get("city") or r["ville"],
            "code_postal":  ad.get("zipCode") or ad.get("postalCode"),
            "adresse":      ad.get("address"),
            "lat":          lat,
            "lng":          lng,
            "url":          url,
            "description":  ad.get("description", ""),
            "nb_pieces":    ad.get("rooms") or ad.get("roomsNumber"),
            "nb_chambres":  ad.get("bedRooms") or ad.get("bedroomsNumber"),
            "type_bien":    r.get("types_bien", ["appartement"])[0],
            "dpe":          dpe,
            "ges":          ges,
            "date_publiee": ad.get("publicationDate") or ad.get("firstPublicationDate"),
        }
        if raw["url"] and raw["url"] != "https://www.seloger.com/annonces/achat/":
            annonces.append(normaliser_annonce(raw, "seloger", r))

    return annonces


def _parse_html(page, r: dict) -> list:
    """Fallback scraping HTML — sélecteurs SeLoger 2024."""
    annonces = []
    selectors = [
        "article[data-testid='sl.card']",
        "article[data-testid='card']",
        "[data-testid='card-product']",
        "article.classified",
    ]
    cards = []
    for sel in selectors:
        cards = page.query_selector_all(sel)
        if cards:
            break

    for card in cards[:20]:
        try:
            lien = card.query_selector("a[href*='/annonces/']") or card.query_selector("a[href]")
            titre_el = card.query_selector("h2, h3, [data-testid='title']")
            prix_el  = card.query_selector("[data-testid='price'], .price")

            href = lien.get_attribute("href") if lien else ""
            if href and not href.startswith("http"):
                href = "https://www.seloger.com" + href

            from core.collectors.base import _to_int
            raw = {
                "titre":    titre_el.inner_text(timeout=1000).strip() if titre_el else "Bien SeLoger",
                "url":      href,
                "prix":     _to_int(prix_el.inner_text(timeout=1000) if prix_el else ""),
                "ville":    r["ville"],
                "type_bien": r.get("types_bien", ["appartement"])[0],
            }
            if raw["url"]:
                annonces.append(normaliser_annonce(raw, "seloger", r))
        except Exception:
            continue

    return annonces
