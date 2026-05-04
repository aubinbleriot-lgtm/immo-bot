"""
Collecteur LeBonCoin via la lib 'lbc' (pip install lbc).
Appelle l'API interne LBC — stable, pas de scraping HTML.

Champs réels du modèle lbc.Ad (inspectés sur la source) :
  ad.subject       → titre
  ad.body          → description
  ad.url           → URL complète (déjà absolue)
  ad.price         → float (price_cents/100), PAS une liste
  ad.location.lat/lng/city/zipcode/city_label
  ad.first_publication_date → str ISO (pas datetime)
  ad.attributes    → list[Attribute] avec .key et .value (strings)
    keys immobilier : 'square', 'rooms', 'real_estate_type',
                      'energy_rate', 'ges', 'nb_rooms'
kwargs search :
  price=[min_int, max_int]   → filters.ranges.price
  square=[min_int, max_int]  → filters.ranges.square
  real_estate_type=["1","2"] → filters.enums.real_estate_type
"""

import logging
import time
import random

from core.collectors.base import BaseCollector, delai_humain

log = logging.getLogger("collector.leboncoin")

# Codes LBC : 1=appartement, 2=maison, 3=parking, 4=terrain, 5=boutique
_TYPE_MAP = {
    "appartement": ["1"],
    "maison":      ["2"],
    "studio":      ["1"],
    "terrain":     ["4"],
    "parking":     ["3"],
}


class LeBonCoinCollector(BaseCollector):
    source = "leboncoin"

    def collecter(self) -> list:
        try:
            import lbc
        except ImportError:
            log.error("lib lbc non installée : pip install lbc")
            return []

        r = self.recherche
        annonces = []

        # Construire les types de biens (liste de strings)
        re_types: list[str] = []
        for t in r.get("types_bien", ["appartement"]):
            re_types.extend(_TYPE_MAP.get(t.lower(), ["1"]))
        re_types = list(set(re_types))

        try:
            client = lbc.Client()
            location = lbc.City(
                lat=float(r["lat"]),
                lng=float(r["lng"]),
                radius=int(r["rayon_km"] * 1000),
                city=r["ville"],
            )

            result = client.search(
                locations=[location],
                page=1,
                limit=min(r.get("max_par_source", 35), 35),
                sort=lbc.Sort.NEWEST,
                ad_type=lbc.AdType.OFFER,
                category=lbc.Category.IMMOBILIER_VENTES_IMMOBILIERES,
                # kwargs → ranges pour int[], enums pour str[]
                price=[int(r.get("prix_min", 0)), int(r.get("prix_max", 9_000_000))],
                square=[int(r.get("surface_min", 1)), int(r.get("surface_max", 9_999))],
                real_estate_type=re_types,
            )

            for ad in result.ads:
                raw = {
                    "titre":        ad.subject or "",
                    # ad.price est déjà un float (price_cents/100), pas une liste
                    "prix":         int(ad.price) if ad.price else None,
                    "surface":      _attr_float(ad, "square"),
                    "ville":        ad.location.city if ad.location else r["ville"],
                    "code_postal":  ad.location.zipcode if ad.location else None,
                    "adresse":      None,
                    "lat":          ad.location.lat if ad.location else None,
                    "lng":          ad.location.lng if ad.location else None,
                    # ad.url est déjà l'URL complète absolue
                    "url":          ad.url,
                    "description":  ad.body or "",
                    "nb_pieces":    _attr_int(ad, "rooms"),
                    "nb_chambres":  _attr_int(ad, "bedrooms"),
                    "type_bien":    r.get("types_bien", ["appartement"])[0],
                    "dpe":          _attr_str(ad, "energy_rate"),
                    "ges":          _attr_str(ad, "ges"),
                    # first_publication_date est une str ISO, pas un datetime
                    "date_publiee": ad.first_publication_date,
                }
                if raw["url"]:
                    annonces.append(self._norm(raw))

            log.info(f"LBC [{r['id']}] → {len(annonces)} annonces")
            delai_humain(15, 30)  # Datadome : délai long obligatoire entre recherches LBC

        except Exception as e:
            log.error(f"LBC erreur [{r['id']}] : {e}")

        return annonces


def _attr_str(ad, key: str) -> str | None:
    for attr in (ad.attributes or []):
        if attr.key == key:
            return str(attr.value_label or attr.value)
    return None


def _attr_float(ad, key: str) -> float | None:
    for attr in (ad.attributes or []):
        if attr.key == key:
            try:
                return float(attr.value)
            except Exception:
                pass
    return None


def _attr_int(ad, key: str) -> int | None:
    for attr in (ad.attributes or []):
        if attr.key == key:
            try:
                return int(attr.value)
            except Exception:
                pass
    return None
