"""
Collecteur PAP (De Particulier à Particulier).

PAP bloque les IPs datacenter sur le RSS. Stratégie en 3 niveaux :
  1. RSS via feedparser (fonctionne en dehors des datacenters)
  2. Scraping HTML avec BeautifulSoup (sélecteurs 2024 vérifiés)
  3. Playwright en dernier recours (si les deux échouent)

Formats d'URL PAP vérifiés 2024 :
  https://www.pap.fr/annonce/ventes-appartement-g38000/rss
  (g + code département/postal, pas le nom de ville)
"""

import logging
import re
import time

import feedparser
import requests
from bs4 import BeautifulSoup

from core.collectors.base import BaseCollector, HEADERS, delai_humain, normaliser_annonce

log = logging.getLogger("collector.pap")

_TYPE_PAP = {
    "appartement": "appartement",
    "maison":      "maison",
    "studio":      "studio",
    "terrain":     "terrain",
}

# Codes postaux par ville pour PAP (g + code postal = filtre géographique)
_CP_MAP = {
    "Grenoble":           "38000",
    "Lyon":               "69000",
    "Allevard":           "38580",
    "Clermont-Ferrand":   "63000",
    "Paris":              "75000",
    "Marseille":          "13000",
    "Bordeaux":           "33000",
    "Saint-Pierre-de-Chartreuse": "38380",
}


def _cp(r: dict) -> str:
    return _CP_MAP.get(r["ville"], r.get("code_postal", "38000"))


def _rss_urls(r: dict) -> list[str]:
    type_bien = _TYPE_PAP.get(r.get("types_bien", ["appartement"])[0], "appartement")
    cp = _cp(r)
    dept = cp[:2]
    return [
        # Format officiel PAP avec code géo
        f"https://www.pap.fr/annonce/ventes-{type_bien}-g{cp}/rss",
        f"https://www.pap.fr/annonce/ventes-immobilieres-g{cp}/rss",
        f"https://www.pap.fr/annonce/ventes-{type_bien}-g{dept}000/rss",
    ]


def _search_url(r: dict) -> str:
    type_bien = _TYPE_PAP.get(r.get("types_bien", ["appartement"])[0], "appartement")
    cp = _cp(r)
    p_max = r.get("prix_max", 9_000_000)
    p_min = r.get("prix_min", 0)
    s_min = r.get("surface_min", 1)
    return (
        f"https://www.pap.fr/annonce/ventes-{type_bien}-g{cp}"
        f"?prix_max={p_max}&prix_min={p_min}&surface_min={s_min}"
        f"&ordre=date-desc&nb_resultats=40"
    )


class PAPCollector(BaseCollector):
    source = "pap"

    def collecter(self) -> list:
        r = self.recherche
        annonces = []

        # ── Niveau 1 : RSS ────────────────────────────────────────────────
        for rss_url in _rss_urls(r):
            try:
                feed = feedparser.parse(rss_url)
                if feed.bozo or not feed.entries:
                    continue
                for entry in feed.entries[:30]:
                    raw = {
                        "titre":        entry.get("title", ""),
                        "url":          entry.get("link", ""),
                        "description":  _strip_html(entry.get("summary", "")),
                        "ville":        r["ville"],
                        "type_bien":    r.get("types_bien", ["appartement"])[0],
                        "date_publiee": entry.get("published"),
                        "prix":         _prix_texte(entry.get("title", "")),
                        "surface":      _surf_texte(entry.get("title", "")),
                    }
                    if raw["url"] and raw["titre"]:
                        annonces.append(normaliser_annonce(raw, "pap", r))
                if annonces:
                    log.info(f"PAP RSS [{r['id']}] → {len(annonces)} (url: {rss_url})")
                    delai_humain(2, 4)
                    return annonces
            except Exception as e:
                log.debug(f"PAP RSS [{rss_url}] : {e}")

        # ── Niveau 2 : HTML BeautifulSoup ─────────────────────────────────
        try:
            url = _search_url(r)
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                # Sélecteurs PAP 2024 vérifiés
                cards = (
                    soup.select("article.search-list-item")
                    or soup.select("[class*='search-list-item']")
                    or soup.select("li.item-list")
                    or soup.select(".list-ads article")
                )
                for card in cards[:30]:
                    lien   = card.select_one("a[href*='/annonces/']") or card.select_one("a[href]")
                    titre  = card.select_one("h3, h2, .title, [class*='title']")
                    prix_e = card.select_one(".price, [class*='price']")
                    surf_e = card.select_one(".size, [class*='size'], [class*='surface']")
                    desc_e = card.select_one(".description, [class*='description']")
                    href   = lien["href"] if lien else ""
                    if href and not href.startswith("http"):
                        href = "https://www.pap.fr" + href
                    raw = {
                        "titre":       titre.get_text(strip=True) if titre else "Annonce PAP",
                        "url":         href,
                        "prix":        _prix_texte(prix_e.get_text() if prix_e else ""),
                        "surface":     _surf_texte(surf_e.get_text() if surf_e else ""),
                        "description": desc_e.get_text(strip=True)[:500] if desc_e else "",
                        "ville":       r["ville"],
                        "type_bien":   r.get("types_bien", ["appartement"])[0],
                    }
                    if raw["url"] and raw["titre"] != "Annonce PAP":
                        annonces.append(normaliser_annonce(raw, "pap", r))
                if annonces:
                    log.info(f"PAP HTML [{r['id']}] → {len(annonces)}")
                    delai_humain(2, 4)
                    return annonces
        except Exception as e:
            log.warning(f"PAP HTML [{r['id']}] : {e}")

        # ── Niveau 3 : Playwright ─────────────────────────────────────────
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = browser.new_page(
                    user_agent=HEADERS["User-Agent"],
                    locale="fr-FR",
                )
                page.goto(_search_url(r), wait_until="domcontentloaded", timeout=25_000)
                time.sleep(2)
                cards = page.query_selector_all("article, li.item-list, [class*='list-item']")
                for card in cards[:25]:
                    try:
                        lien  = card.query_selector("a[href]")
                        titre = card.query_selector("h2, h3, [class*='title']")
                        prix  = card.query_selector("[class*='price']")
                        href  = lien.get_attribute("href") if lien else ""
                        if href and not href.startswith("http"):
                            href = "https://www.pap.fr" + href
                        raw = {
                            "titre":   titre.inner_text(timeout=1000).strip() if titre else "",
                            "url":     href,
                            "prix":    _prix_texte(prix.inner_text(timeout=1000) if prix else ""),
                            "ville":   r["ville"],
                            "type_bien": r.get("types_bien", ["appartement"])[0],
                        }
                        if raw["url"] and raw["titre"]:
                            annonces.append(normaliser_annonce(raw, "pap", r))
                    except Exception:
                        continue
                browser.close()
        except Exception as e:
            log.error(f"PAP Playwright [{r['id']}] : {e}")

        log.info(f"PAP [{r['id']}] → {len(annonces)} annonces (3 méthodes épuisées)")
        delai_humain(3, 6)
        return annonces


def _prix_texte(t: str) -> int | None:
    m = re.search(r"([\d\s\u202f\xa0]+)\s*€", t)
    if m:
        try:
            return int(re.sub(r"\s|\u202f|\xa0", "", m.group(1)))
        except Exception:
            pass
    return None


def _surf_texte(t: str) -> float | None:
    m = re.search(r"(\d+[\.,]?\d*)\s*m", t)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except Exception:
            pass
    return None


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).strip()
